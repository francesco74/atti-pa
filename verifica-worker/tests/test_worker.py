import os
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from atti_common.config import Settings
from atti_common.db import crea_sessionmaker
from atti_common.models import (
    AttoControllato,
    Base,
    Bozza,
    SessioneControllo,
    StatoVerifica,
    TipologiaAtto,
    User,
    Verifica,
)
from atti_common.testing import FakeNormattiva, html_articolo
from verifica_worker.worker import Worker

URL_TEST = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def sessionmaker():
    if URL_TEST:
        engine = create_async_engine(URL_TEST)
        async with engine.begin() as conn:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for t in reversed(Base.metadata.sorted_tables):
                if t.name != "tipologie_atto":
                    await conn.execute(delete(t))
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with crea_sessionmaker(engine)() as s:
            s.add(TipologiaAtto(codice="ALTRO", descrizione="Altro"))
            await s.commit()
    yield crea_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def utente(sessionmaker):
    async with sessionmaker() as s:
        u = User(username="mrossi", ruoli=["REDATTORE"])
        s.add(u)
        await s.commit()
        return u.id


def worker(sessionmaker, **opzioni):
    n = FakeNormattiva()
    n.aggiungi(
        "urn:nir:stato:decreto.legislativo:2000-08-18;267~art107",
        html_articolo("107", {"1": "Spetta ai dirigenti la direzione degli uffici."}),
    )
    settings = Settings(worker_max_tentativi=2, worker_timeout_minuti=30, **opzioni)
    return Worker(sessionmaker, n, None, settings)


async def _bozza(sessionmaker, utente, testo):
    async with sessionmaker() as s:
        b = Bozza(owner_id=utente, oggetto="Prova", tipologia_atto="ALTRO", contenuto_testo=testo)
        s.add(b)
        await s.flush()
        v = Verifica(bozza_id=b.id, data_riferimento=date(2026, 10, 1), richiesta_da=utente)
        s.add(v)
        await s.commit()
        return v.id


async def test_elabora_verifica_bozza(sessionmaker, utente):
    vid = await _bozza(sessionmaker, utente, "Visto l'art. 107 del TUEL; CIG {{cig}}")
    w = worker(sessionmaker)

    assert await w.esegui_una() is True
    assert await w.esegui_una() is False  # coda vuota

    async with sessionmaker() as s:
        v = await s.get(Verifica, vid)
    assert v.stato == StatoVerifica.COMPLETATA
    assert v.tentativi == 1
    assert v.esito_riferimenti["riferimenti"][0]["esito"] == "VIGENTE"
    assert v.esito_riferimenti["segnaposto"] == ["cig"]


async def test_testo_vuoto_va_in_errore_dopo_i_tentativi(sessionmaker, utente):
    vid = await _bozza(sessionmaker, utente, "   ")
    w = worker(sessionmaker)

    await w.esegui_una()
    async with sessionmaker() as s:
        assert (await s.get(Verifica, vid)).stato == StatoVerifica.IN_CODA
    await w.esegui_una()
    async with sessionmaker() as s:
        v = await s.get(Verifica, vid)
    assert v.stato == StatoVerifica.ERRORE
    assert "testo" in v.errore


async def test_recupero_verifiche_bloccate(sessionmaker, utente):
    vid = await _bozza(sessionmaker, utente, "testo")
    async with sessionmaker() as s:
        v = await s.get(Verifica, vid)
        v.stato = StatoVerifica.IN_CORSO
        v.avviata_il = datetime.now() - timedelta(hours=2)
        v.tentativi = 1
        await s.commit()

    assert await worker(sessionmaker).recupera_bloccate() == 1
    async with sessionmaker() as s:
        assert (await s.get(Verifica, vid)).stato == StatoVerifica.IN_CODA


async def test_atto_controllato_passa_ad_analizzato(sessionmaker, utente):
    async with sessionmaker() as s:
        sess = SessioneControllo(
            titolo="1° semestre", periodo_da=date(2026, 1, 1), periodo_a=date(2026, 6, 30),
            creata_da=utente,
        )  # fmt: skip
        s.add(sess)
        await s.flush()
        atto = AttoControllato(
            sessione_id=sess.id, data_adozione=date(2026, 3, 1), file_nome="a.pdf",
            file_mime="application/pdf", file_contenuto=b"%PDF", contenuto_testo="art. 107 del TUEL",
        )  # fmt: skip
        s.add(atto)
        await s.flush()
        s.add(
            Verifica(
                atto_controllato_id=atto.id, data_riferimento=date(2026, 3, 1), richiesta_da=utente
            )
        )
        await s.commit()
        atto_id = atto.id

    await worker(sessionmaker).esegui_una()
    async with sessionmaker() as s:
        stato = await s.scalar(select(AttoControllato.stato).where(AttoControllato.id == atto_id))
    assert stato == "ANALIZZATO"


@pytest.mark.skipif(not URL_TEST, reason="SKIP LOCKED richiede MySQL/MariaDB")
async def test_worker_concorrenti_non_prendono_la_stessa_verifica(sessionmaker, utente):
    import asyncio

    for i in range(6):
        await _bozza(sessionmaker, utente, f"testo {i}")
    w1, w2 = worker(sessionmaker), worker(sessionmaker)
    presi = await asyncio.gather(*[w.prendi_in_carico() for w in (w1, w2, w1, w2, w1, w2)])
    assert None not in presi
    assert len(set(presi)) == 6
