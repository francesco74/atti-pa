from datetime import date, datetime

import pytest

from atti_common.normattiva import (
    AttoNonTrovato,
    NormattivaError,
    RisultatoAmbiguo,
    TestoArticolo,
    parse_articolo,
)
from normattiva_sync.job import SyncJob, finestre
from normattiva_sync.repository import ArticoloMonitorato, VersioneSalvata

URN_CODICE = "urn:nir:stato:decreto.legislativo:2023-03-31;36"
URN_241 = "urn:nir:stato:legge:1990-08-07;241"

ORA = datetime(2026, 10, 12, 1, 30)


def crea_testo(urn: str, contenuto: str, sottotitolo: str | None = None) -> TestoArticolo:
    html = f'<div class="art-comma-div-akn"><span class="comma-num-akn">1. </span>{contenuto}</div>'
    return TestoArticolo(
        urn=urn,
        titolo_atto="",
        sottotitolo=sottotitolo,
        denominazione="",
        data_provvedimento=None,
        numero="",
        data_gu=None,
        vigenza_inizio=date(2026, 1, 1),
        vigenza_fine=None,
        html=html,
        articolo=parse_articolo(html),
    )


class FakeRepo:
    def __init__(self, monitorati, senza_versione=(), versioni=None, ultima=None):
        self.monitorati = list(monitorati)
        self.senza_versione = list(senza_versione)
        self.versioni = versioni or {}
        self.ultima = ultima
        self.salvati: list[ArticoloMonitorato] = []
        self.esecuzioni: list[dict] = []

    async def ultima_sincronizzazione_ok(self):
        return self.ultima

    async def articoli_monitorati(self):
        return self.monitorati

    async def articoli_senza_versione(self):
        return self.senza_versione

    async def versione_corrente(self, art):
        return self.versioni.get(art)

    async def salva_versione(self, art, t):
        self.salvati.append(art)

    async def registra_esecuzione(self, da, a, atti_modificati, articoli_aggiornati, esito, det):
        self.esecuzioni.append(
            {"da": da, "a": a, "modificati": atti_modificati, "esito": esito, "det": det}
        )


class FakeClient:
    def __init__(self, aggiornati, testi, errore_aggiornati=False):
        self.aggiornati = aggiornati
        self.testi = testi  # urn articolo -> TestoArticolo | Exception
        self.errore_aggiornati = errore_aggiornati
        self.finestre: list[tuple[datetime, datetime]] = []
        self.richiesti: list[str] = []

    async def atti_aggiornati(self, da, a):
        if self.errore_aggiornati:
            raise NormattivaError("HTTP 500")
        self.finestre.append((da, a))
        return self.aggiornati

    async def articolo(self, urn, vigenza=None):
        chiave = str(urn)
        self.richiesti.append(chiave)
        r = self.testi[chiave]
        if isinstance(r, Exception):
            raise r
        return r


def atto_modificato(denominazione, anno, mese, giorno, numero):
    return {
        "denominazioneAtto": denominazione,
        "annoProvvedimento": str(anno),
        "meseProvvedimento": str(mese),
        "giornoProvvedimento": str(giorno),
        "numeroProvvedimento": str(numero),
    }


def job(repo, client):
    return SyncJob(repo, client, oggi=date(2026, 10, 12), ora=ORA, giorni_iniziali=7)


def test_finestre():
    f = finestre(datetime(2026, 1, 1), datetime(2026, 1, 20), 7)
    assert [(a.day, b.day) for a, b in f] == [(1, 8), (8, 15), (15, 20)]


async def test_aggiorna_solo_articoli_di_atti_modificati():
    art50 = ArticoloMonitorato(URN_CODICE, "50")
    art3 = ArticoloMonitorato(URN_241, "3")
    repo = FakeRepo([art50, art3], versioni={art50: VersioneSalvata(date(2025, 1, 1), "vecchio")})
    client = FakeClient(
        aggiornati=[atto_modificato("DECRETO LEGISLATIVO", 2023, 3, 31, 36)],
        testi={f"{URN_CODICE}~art50": crea_testo(URN_CODICE, "Testo modificato.")},
    )

    esito = await job(repo, client).esegui()

    assert client.richiesti == [f"{URN_CODICE}~art50"]  # l'atto 241/1990 non è stato modificato
    assert repo.salvati == [art50]
    assert esito.atti_modificati == 1
    assert repo.esecuzioni[-1]["esito"] == "OK"


async def test_testo_invariato_non_crea_versione():
    art50 = ArticoloMonitorato(URN_CODICE, "50")
    t = crea_testo(URN_CODICE, "Testo uguale.")
    repo = FakeRepo([art50], versioni={art50: VersioneSalvata(date(2025, 1, 1), t.articolo.hash())})
    client = FakeClient(
        aggiornati=[atto_modificato("DECRETO LEGISLATIVO", 2023, 3, 31, 36)],
        testi={f"{URN_CODICE}~art50": t},
    )

    esito = await job(repo, client).esegui()

    assert repo.salvati == []
    assert esito.articoli_controllati == 1
    assert esito.articoli_aggiornati == 0


async def test_scarica_articoli_mai_scaricati():
    nuovo = ArticoloMonitorato(URN_241, "3")
    repo = FakeRepo([nuovo], senza_versione=[nuovo])
    client = FakeClient(
        aggiornati=[], testi={f"{URN_241}~art3": crea_testo(URN_241, "Motivazione.")}
    )

    await job(repo, client).esegui()

    assert repo.salvati == [nuovo]


async def test_prima_esecuzione_usa_finestra_iniziale():
    repo = FakeRepo([])
    client = FakeClient(aggiornati=[], testi={})
    await job(repo, client).esegui()
    assert client.finestre == [(datetime(2026, 10, 5, 1, 30), ORA)]


async def test_riparte_dall_ultima_esecuzione_ok():
    repo = FakeRepo([], ultima=datetime(2026, 10, 11, 1, 30))
    client = FakeClient(aggiornati=[], testi={})
    await job(repo, client).esegui()
    assert client.finestre == [(datetime(2026, 10, 11, 1, 30), ORA)]


async def test_errori_su_singoli_articoli_danno_esito_parziale():
    a, b = ArticoloMonitorato(URN_241, "3"), ArticoloMonitorato(URN_241, "4")
    repo = FakeRepo([a, b], senza_versione=[a, b])
    client = FakeClient(
        aggiornati=[],
        testi={
            f"{URN_241}~art3": AttoNonTrovato("x"),
            f"{URN_241}~art4": crea_testo(URN_241, "Ok."),
        },
    )

    esito = await job(repo, client).esegui()

    assert repo.salvati == [b]
    assert esito.stato == "PARZIALE"
    assert repo.esecuzioni[-1]["esito"] == "PARZIALE"
    assert "non trovato" in repo.esecuzioni[-1]["det"]


async def test_risultato_ambiguo_sceglie_testo_principale():
    art = ArticoloMonitorato(URN_241, "3")
    principale = crea_testo(URN_241, "Principale.")
    ripubblicato = crea_testo(URN_241, "Ripubblicato.", sottotitolo="Ripubblicazione del testo...")
    repo = FakeRepo([art], senza_versione=[art])
    client = FakeClient(
        aggiornati=[],
        testi={f"{URN_241}~art3": RisultatoAmbiguo("u", [ripubblicato, principale])},
    )

    esito = await job(repo, client).esegui()

    assert repo.salvati == [art]
    assert esito.stato == "OK"


async def test_errore_bloccante_registrato_e_rilanciato():
    repo = FakeRepo([])
    client = FakeClient(aggiornati=[], testi={}, errore_aggiornati=True)

    with pytest.raises(NormattivaError):
        await job(repo, client).esegui()
    assert repo.esecuzioni[-1]["esito"] == "ERRORE"
