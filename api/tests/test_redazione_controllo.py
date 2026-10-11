import httpx
import pytest
import respx
from sqlalchemy import select

from atti_common.llm import LlmClient
from atti_common.models import StatoVerifica, Verifica
from atti_common.testing import FakeNormattiva, crea_odt, html_articolo

URN_TUEL = "urn:nir:stato:decreto.legislativo:2000-08-18;267"


@pytest.fixture(autouse=True)
def normattiva(app):
    fake = FakeNormattiva()
    fake.aggiungi(f"{URN_TUEL}~art107", html_articolo("107", {
        "1": "Spetta ai dirigenti la direzione degli uffici.",
        "3": ("Sono attribuiti ai dirigenti:", {"d": "gli atti di gestione finanziaria;"}),
    }))  # fmt: skip
    app.state.normattiva = fake
    return fake


async def _template(client, admin):
    odt = crea_odt([
        "OGGETTO: {{oggetto}}",
        "{{riferimenti_normativi}}",
        "Premesso che {{premesse}}",
        "CIG {{cig}} - Beneficiario {{beneficiario}}",
    ])  # fmt: skip
    r = await client.post(
        "/api/v1/templates",
        data={"nome": "Base", "tipologia_atto": "AFFIDAMENTO_DIRETTO"},
        files={"file": ("base.odt", odt, "application/vnd.oasis.opendocument.text")},
        headers=admin,
    )
    return r.json()["id"]


def _bozza(template_id, **extra):
    return {
        "oggetto": "Affidamento servizio di pulizia",
        "tipologia_atto": "AFFIDAMENTO_DIRETTO",
        "template_id": template_id,
        "data_adozione_prevista": "2026-10-20",
        "dati": {"premesse": "occorre garantire la pulizia", "cig": "",
                 "beneficiario": "Mario Rossi, C.F. RSSMRA80A01H501U"},
        "riferimenti": [{"urn_atto": URN_TUEL, "articolo": "107", "comma": "3", "lettera": "d"}],
        **extra,
    }  # fmt: skip


async def test_flusso_redazione(client, login):
    admin, rossi = await login("admin"), await login("mrossi")
    template_id = await _template(client, admin)

    r = await client.post("/api/v1/bozze", json=_bozza(template_id), headers=rossi)
    assert r.status_code == 201, r.text
    bozza = r.json()
    assert (
        "Visto l'art. 107, comma 3, lett. d), del D.Lgs. 18 agosto 2000, n. 267;"
        in (bozza["contenuto_testo"])
    )
    assert "CIG [[cig]]" in bozza["contenuto_testo"]

    r = await client.get(f"/api/v1/bozze/{bozza['id']}/controllo-rapido", headers=rossi)
    controllo = r.json()
    assert controllo["campi_obbligatori_mancanti"] == ["Cig"]
    assert controllo["segnaposto"] == ["cig"]
    assert controllo["riferimenti"][0]["esito"] == "VIGENTE"
    assert controllo["dati_personali"][0]["categoria"] == "CODICE_FISCALE"

    r = await client.get(f"/api/v1/bozze/{bozza['id']}/documento", headers=rossi)
    assert r.headers["content-type"] == "application/vnd.oasis.opendocument.text"
    r = await client.get(
        f"/api/v1/bozze/{bozza['id']}/documento", params={"formato": "pdfa", "omissis": True},
        headers=rossi,
    )  # fmt: skip
    assert r.content.startswith(b"%PDF")
    assert "determina-omissis.pdf" in r.headers["content-disposition"]


async def test_omissis_nel_documento(client, login, app):
    admin, rossi = await login("admin"), await login("mrossi")
    template_id = await _template(client, admin)
    bozza = (await client.post("/api/v1/bozze", json=_bozza(template_id), headers=rossi)).json()
    r = await client.get(
        f"/api/v1/bozze/{bozza['id']}/documento", params={"omissis": True}, headers=rossi
    )
    from atti_common.odt import estrai_testo

    testo = estrai_testo(r.content)
    assert "RSSMRA80A01H501U" not in testo
    assert "[OMISSIS]" in testo


async def test_isolamento_bozze(client, login):
    rossi, admin = await login("mrossi"), await login("admin")
    bozza = (await client.post("/api/v1/bozze", json=_bozza(None), headers=rossi)).json()
    # nemmeno l'amministratore vede le bozze altrui
    assert (await client.get(f"/api/v1/bozze/{bozza['id']}", headers=admin)).status_code == 404
    assert (await client.get("/api/v1/bozze", headers=admin)).json() == []
    assert len((await client.get("/api/v1/bozze", headers=rossi)).json()) == 1
    # il controllore non ha accesso al modulo redazione
    bianchi = await login("lbianchi")
    assert (await client.get("/api/v1/bozze", headers=bianchi)).status_code == 403


async def test_template_di_altra_tipologia(client, login):
    admin, rossi = await login("admin"), await login("mrossi")
    template_id = await _template(client, admin)
    r = await client.post(
        "/api/v1/bozze", json=_bozza(template_id, tipologia_atto="IMPEGNO_SPESA"), headers=rossi
    )
    assert r.status_code == 422


async def test_verifica_bozza_in_coda(client, login, engine):
    admin, rossi = await login("admin"), await login("mrossi")
    await client.post(
        "/api/v1/checklists",
        json={"codice": "AFF", "titolo": "Affidamento", "tipologia_atto": "AFFIDAMENTO_DIRETTO",
              "elementi": [{"titolo": "CIG", "regola": "CIG presente"}]},
        headers=admin,
    )  # fmt: skip
    bozza = (await client.post("/api/v1/bozze", json=_bozza(None), headers=rossi)).json()
    r = await client.post("/api/v1/verifiche", json={"bozza_id": bozza["id"]}, headers=rossi)
    assert r.status_code == 202
    verifica = r.json()
    assert verifica["stato"] == "IN_CODA"
    assert verifica["data_riferimento"] == "2026-10-20"
    assert verifica["checklist_id"] is not None

    # un altro utente non vede la verifica della bozza
    bianchi = await login("lbianchi")
    assert (
        await client.get(f"/api/v1/verifiche/{verifica['id']}", headers=bianchi)
    ).status_code == 404


@respx.mock
async def test_espansione_appunti(client, login, app):
    app.state.llm = LlmClient("http://llm.test/v1", "m")
    respx.post("http://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "Considerato che occorre..."}}]}
        )
    )
    r = await client.post(
        "/api/v1/bozze/espandi",
        json={"sezione": "premesse", "appunti": "serve pulizia uffici", "oggetto": "Pulizia"},
        headers=await login("mrossi"),
    )
    assert r.json() == {"testo": "Considerato che occorre..."}


async def test_espansione_senza_llm(client, login):
    r = await client.post(
        "/api/v1/bozze/espandi", json={"sezione": "x", "appunti": "abc"},
        headers=await login("mrossi"),
    )  # fmt: skip
    assert r.status_code == 503


# --- Modulo controllo ----------------------------------------------------------------


async def test_flusso_controllo(client, login, app):
    bianchi = await login("lbianchi")
    s = await client.post(
        "/api/v1/controllo/sessioni",
        json={"titolo": "1° semestre 2026", "periodo_da": "2026-01-01", "periodo_a": "2026-06-30"},
        headers=bianchi,
    )
    assert s.status_code == 201
    sid = s.json()["id"]

    r = await client.post(
        f"/api/v1/controllo/sessioni/{sid}/sorteggio",
        json={"elenco": [f"DD-{i}" for i in range(1, 41)], "percentuale": 10, "seme": 42},
        headers=bianchi,
    )
    estratti = r.json()["estratti"]
    assert len(estratti) == 4
    # stesso seme, stessa estrazione: il sorteggio è verificabile
    import random

    atteso = sorted(random.Random(42).sample(sorted(f"DD-{i}" for i in range(1, 41)), 4))
    assert estratti == atteso

    docx = b"PK\x03\x04 finto docx"
    r = await client.post(
        f"/api/v1/controllo/sessioni/{sid}/atti",
        data={"data_adozione": "2026-03-15", "numero_registro": estratti[0],
              "settore": "Lavori pubblici", "tipologia_atto": "AFFIDAMENTO_DIRETTO"},
        files={"file": ("atto.docx", docx)},
        headers=bianchi,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    atto = r.json()
    assert atto["stato"] == "IN_ANALISI"
    assert app.state.documenti.chiamate == [("atto.docx", "odt")]

    testo = (await client.get(f"/api/v1/controllo/atti/{atto['id']}/testo", headers=bianchi)).json()
    assert "art. 107 del TUEL" in testo["testo"]

    # il worker completa la verifica (simulato)
    async with app.state.sessionmaker() as db:
        v = await db.scalar(select(Verifica).where(Verifica.atto_controllato_id == atto["id"]))
        v.stato = StatoVerifica.COMPLETATA
        v.esito_riferimenti = {"riferimenti": [{"esito": "VIGENTE"}]}
        v.esito_automatico = [{"elemento_id": "x", "titolo": "CIG", "esito": "NON_CONFORME"}]
        await db.commit()
        vid = v.id

    assert (
        await client.post(f"/api/v1/controllo/sessioni/{sid}/chiudi", headers=bianchi)
    ).status_code == 409

    r = await client.put(
        f"/api/v1/verifiche/{vid}/revisione",
        json={"esiti": [{"elemento_id": "x", "titolo": "CIG", "esito": "CONFORME",
                         "nota": "CIG presente in allegato"}],
              "motivazione": "Proposta automatica corretta dal controllore", "conclusa": True},
        headers=bianchi,
    )  # fmt: skip
    assert r.status_code == 200, r.text

    report = (await client.get(f"/api/v1/controllo/sessioni/{sid}/report", headers=bianchi)).json()
    assert report["atti_totali"] == 1
    assert report["atti_revisionati"] == 1
    assert report["per_criterio"] == {"CIG": {"CONFORME": 1}}
    assert report["per_settore"]["Lavori pubblici"] == {"atti": 1, "con_rilievi": 0}

    csv = await client.get(f"/api/v1/controllo/sessioni/{sid}/report.csv", headers=bianchi)
    assert "Lavori pubblici" in csv.text

    r = await client.post(f"/api/v1/controllo/sessioni/{sid}/chiudi", headers=bianchi)
    assert r.json()["stato"] == "CHIUSA"


async def test_pdf_scansione_rifiutato(client, login):
    bianchi = await login("lbianchi")
    sid = (await client.post(
        "/api/v1/controllo/sessioni",
        json={"titolo": "Prova", "periodo_da": "2026-01-01", "periodo_a": "2026-06-30"},
        headers=bianchi,
    )).json()["id"]  # fmt: skip
    r = await client.post(
        f"/api/v1/controllo/sessioni/{sid}/atti",
        data={"data_adozione": "2026-03-15"},
        files={"file": ("scan.pdf", b"%PDF-1.4 non valido")},
        headers=bianchi,
    )
    assert r.status_code == 422


async def test_controllo_vietato_ai_redattori(client, login):
    r = await client.get("/api/v1/controllo/sessioni", headers=await login("mrossi"))
    assert r.status_code == 403
