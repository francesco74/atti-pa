"""Test di integrazione su MySQL/MariaDB con schema già migrato (TEST_DATABASE_URL)."""

import os
import uuid
from dataclasses import replace
from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from normattiva_sync.repository import ArticoloMonitorato, MySqlRepository

URL_TEST = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL_TEST, reason="TEST_DATABASE_URL non impostato")

URN = "urn:nir:stato:legge:1990-08-07;241"


@pytest.fixture
async def repo():
    engine = create_async_engine(URL_TEST)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM riferimenti WHERE urn_atto = :u"), {"u": URN})
        await conn.execute(text("DELETE FROM norme_atti WHERE urn = :u"), {"u": URN})
        await conn.execute(text("DELETE FROM normattiva_sync"))
        await conn.execute(
            text(
                "INSERT INTO norme_atti (urn, denominazione, data_provvedimento, numero, citazione) "
                "VALUES (:u, 'LEGGE', '1990-08-07', '241', 'L. 7 agosto 1990, n. 241')"
            ),
            {"u": URN},
        )
        await conn.execute(
            text(
                "INSERT INTO riferimenti (id, urn_atto, articolo, citazione) "
                "VALUES (:id, :u, '3', 'art. 3 della L. 241/1990')"
            ),
            {"id": str(uuid.uuid4()), "u": URN},
        )
    yield MySqlRepository(engine)
    await engine.dispose()


async def test_ciclo_versioni(repo, crea_testo):
    art = ArticoloMonitorato(URN, "3")
    assert await repo.articoli_senza_versione() == [art]

    v1 = crea_testo(URN, "Ogni provvedimento deve essere motivato.", inizio=date(1990, 9, 2))
    await repo.salva_versione(art, v1)
    assert await repo.articoli_senza_versione() == []
    corrente = await repo.versione_corrente(art)
    assert corrente.hash_testo == v1.articolo.hash()

    v2 = crea_testo(URN, "Testo modificato.", inizio=date(2026, 1, 1))
    await repo.salva_versione(art, v2)
    corrente = await repo.versione_corrente(art)
    assert corrente.vigenza_inizio == date(2026, 1, 1)

    async with repo._engine.connect() as conn:
        righe = (
            await conn.execute(
                text(
                    "SELECT vigenza_inizio, vigenza_fine FROM norme_articoli_versioni "
                    "WHERE urn_atto = :u ORDER BY vigenza_inizio"
                ),
                {"u": URN},
            )
        ).all()
    assert righe == [(date(1990, 9, 2), date(2025, 12, 31)), (date(2026, 1, 1), None)]

    # stesso intervallo riscaricato: aggiornamento in place, nessuna riga in più
    await repo.salva_versione(art, replace(v2))
    assert art in await repo.articoli_monitorati()


async def test_ultima_sincronizzazione(repo):
    assert await repo.ultima_sincronizzazione_ok() is None
    await repo.registra_esecuzione(datetime(2026, 10, 1), datetime(2026, 10, 2), 3, 1, "OK", None)
    await repo.registra_esecuzione(
        datetime(2026, 10, 2), datetime(2026, 10, 3), 0, 0, "PARZIALE", "errore"
    )
    assert await repo.ultima_sincronizzazione_ok() == datetime(2026, 10, 2)
