from datetime import date

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from atti_common.dati_personali import applica_omissis, trova_dati_personali
from atti_common.db import crea_sessionmaker
from atti_common.llm import LlmClient
from atti_common.models import Base, Checklist, ChecklistElemento, TipologiaAtto
from atti_common.testing import FakeNormattiva, html_articolo
from atti_common.verifica import analizza

URN_CODICE = "urn:nir:stato:decreto.legislativo:2023-03-31;36"
URN_TUEL = "urn:nir:stato:decreto.legislativo:2000-08-18;267"
LLM_URL = "http://llm.test/v1"

ATTO = """DETERMINAZIONE DIRIGENZIALE
Visto l'art. 107 del TUEL;
Visto l'art. 50, comma 1, lett. b), del D.Lgs. 31 marzo 2023, n. 36;
Visto l'art. 50, comma 1, lett. z), del D.Lgs. n. 36/2023;
Vista la L. 241/1990;
Il beneficiario Mario Rossi, codice fiscale RSSMRA80A01H501U, nato a Roma il 1/1/1980,
IBAN IT60 X054 2811 1010 0000 0123 456.
CIG: {{cig}}
DETERMINA di affidare il servizio.
"""


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with crea_sessionmaker(engine)() as session:
        session.add(TipologiaAtto(codice="AFFIDAMENTO_DIRETTO", descrizione="Affidamento"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def normattiva():
    n = FakeNormattiva()
    n.aggiungi(f"{URN_TUEL}~art107", html_articolo("107", {"1": "Spetta ai dirigenti..."}))
    n.aggiungi(
        f"{URN_CODICE}~art50",
        html_articolo("50", {"1": ("Le stazioni appaltanti procedono:", {
            "a": "lavori sotto 150.000 euro;", "b": "servizi sotto 140.000 euro;"
        })}),
        inizio=date(2026, 3, 1),
    )  # fmt: skip
    n.aggiungi("urn:nir:stato:legge:1990-08-07;241~art1", html_articolo("1", {"1": "Principi."}))
    return n


def test_dati_personali_e_omissis():
    dati = trova_dati_personali(ATTO)
    categorie = [d.categoria for d in dati]
    assert categorie == ["CODICE_FISCALE", "DATA_DI_NASCITA", "IBAN"]
    assert "RSSMRA80A01H501U" not in applica_omissis(ATTO, dati)


async def test_analisi_senza_llm(db, normattiva):
    r = await analizza(db, normattiva, None, ATTO, date(2026, 10, 1))
    esiti = {(x["articolo"], x["lettera"]): x for x in r.riferimenti}

    assert esiti[("107", None)]["esito"] == "VIGENTE"
    assert esiti[("50", "b")]["esito"] == "VIGENTE"
    assert any("modificato di recente" in a for a in esiti[("50", "b")]["avvisi"])
    assert esiti[("50", "z")]["esito"] == "PARTIZIONE_INESISTENTE"
    # "D.Lgs. n. 36/2023" senza data risolto con l'atto già in libreria
    assert esiti[("50", "z")]["urn_atto"] == URN_CODICE
    # L. 241/1990 senza articolo: risolta su Normattiva, segnalata come citazione generica
    assert esiti[(None, None)]["esito"] == "ATTO_SENZA_ARTICOLO"
    assert esiti[(None, None)]["urn_atto"] == "urn:nir:stato:legge:1990-08-07;241"

    assert r.segnaposto == ["cig"]
    assert r.esito_riferimenti()["riepilogo"]["dati_personali"] == 3


async def test_riferimento_non_vigente_alla_data(db, normattiva):
    # alla data dell'atto l'art. 50 nella versione in archivio non era ancora vigente
    r = await analizza(
        db, normattiva, None, "art. 50 del D.Lgs. 31 marzo 2023, n. 36", date(2025, 1, 1)
    )
    assert r.riferimenti[0]["esito"] == "NON_TROVATO"


@respx.mock
async def test_checklist_con_llm(db, normattiva):
    risposte = [
        '{"esito": "NON_CONFORME", "motivazione": "Manca il CIG", "evidenza": "CIG: {{cig}}", '
        '"suggerimento": "Indicare il CIG"}',
        "risposta non json",
        '```json\n{"esito": "CONFORME", "motivazione": "Importo entro soglia"}\n```',
    ]
    chiamate = []

    def rispondi(request):
        chiamate.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": risposte.pop(0)}}]})

    respx.post(f"{LLM_URL}/chat/completions").mock(side_effect=rispondi)

    checklist = Checklist(
        codice="AFF", titolo="Affidamento", tipologia_atto="AFFIDAMENTO_DIRETTO",
        elementi=[
            ChecklistElemento(ordine=0, titolo="CIG", regola="L'atto riporta il CIG."),
            ChecklistElemento(ordine=1, titolo="Soglia", regola="Importo entro soglia.",
                              riferimenti_json=[f"{URN_CODICE}~art50"]),
        ],
    )  # fmt: skip
    db.add(checklist)
    await db.commit()

    llm = LlmClient(LLM_URL, "modello-test")
    r = await analizza(db, normattiva, llm, ATTO, date(2026, 10, 1), checklist)
    await llm.close()

    assert [e["esito"] for e in r.checklist] == ["NON_CONFORME", "CONFORME"]
    assert r.checklist[1]["norme_usate"] == ["art. 50, del D.Lgs. 31 marzo 2023, n. 36"]
    assert r.modello_llm == "modello-test"
    # il testo vigente della norma è passato al modello
    prompt_soglia = chiamate[1].read().decode()
    assert "servizi sotto 140.000 euro" in prompt_soglia
    assert len(chiamate) == 3  # una risposta non valida ha causato un nuovo tentativo


@respx.mock
async def test_errore_llm_non_blocca_analisi(db, normattiva):
    respx.post(f"{LLM_URL}/chat/completions").mock(return_value=httpx.Response(503))
    checklist = Checklist(
        codice="X", titolo="X", tipologia_atto="AFFIDAMENTO_DIRETTO",
        elementi=[ChecklistElemento(ordine=0, titolo="CIG", regola="CIG presente")],
    )  # fmt: skip
    db.add(checklist)
    await db.commit()
    llm = LlmClient(LLM_URL, "m")
    r = await analizza(db, normattiva, llm, ATTO, date(2026, 10, 1), checklist)
    await llm.close()
    assert r.checklist[0]["esito"] == "ERRORE"
    assert r.riferimenti  # le analisi deterministiche sono comunque presenti
