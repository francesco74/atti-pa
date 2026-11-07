"""Pagine pubbliche, senza accesso: la mappatura dei processi dell'anticorruzione, che i
cittadini consultano su /pubblico/mappatura, e i procedimenti con i dati dell'art. 35 d.lgs.
33/2013 (allegato 11 alla delibera ANAC 495/2024) su /pubblico/procedimenti, da collegare nella
sezione Amministrazione trasparente (Attività e procedimenti > Tipologie di procedimento).
Ciascuna ha il suo interruttore (Ente.mappatura_pubblica, Ente.procedimenti_pubblici).

L'ente si riconosce dal dominio della richiesta. Le API rispondono solo se l'ente ha il modulo
anticorruzione e il RPCT ha acceso la pubblicazione (Ente.mappatura_pubblica); altrimenti 404,
come se la pagina non esistesse. Si mostrano solo i dati da pubblicare: per i rischi evento,
fattore abilitante e livello, non i valori degli indicatori né le correzioni motivate.
"""

from http import HTTPStatus

from flask import Blueprint, g, request
from sqlalchemy import select
from sqlalchemy.orm import undefer

import ricerca as servizio_ricerca
from deps import db, ente_richiesta, impostazioni
from routers.anticorruzione import (
    FiltriProcessi, RicercaIn, albero_processo, documenti_ricerca, elenco_processi, metodologia_ente,
    processo_dell_ente,
)  # fmt: skip
from common.anticorruzione import art35 as dati_art35
from common.anticorruzione.metodologia import chiave_naturale
from web import ErroreApi, allegato, corpo, parametri
from common.anticorruzione.metodologia import chiave_area
from common import registro_ricerche as reg
from common.models import AcArea, AcProcesso, Ente, Modulo, Struttura
from routers.ricerche import FeedbackIn, RicercaIn as RicercaConclusaIn, registra_feedback, registra_ricerca

bp = Blueprint("pubblico", __name__, url_prefix="/api/v1/pubblico")

# campi pubblicati di ogni elemento della mappatura
_PROCESSO = (
    "id", "codice", "tipo", "area_id", "denominazione", "descrizione", "tempi", "attori_esterni",
    "termine_conclusione", "norma_riferimento", "struttura_id",
)  # fmt: skip
_CONTEGGI = ("attivita", "rischi", "misure", "livello_massimo")
_ATTIVITA = ("id", "codice", "descrizione", "strutture_coinvolte")
_RISCHIO = ("id", "codice", "evento", "fattore_abilitante", "livello")
_MISURA = (
    "id", "codice", "descrizione", "tipo", "categoria", "obbligo_trasparenza", "fasi", "tempi",
    "struttura_id", "indicatore", "target",
)  # fmt: skip


# ricerche per significato per indirizzo IP (RICERCA_LIMITE_PUBBLICO al minuto); creato alla
# prima ricerca, con il limite della configurazione
_limite: servizio_ricerca.LimiteRichieste | None = None


async def _cerca(e: Ente, tipo: str | None) -> dict:
    """Ricerca dei cittadini: oltre il limite di richieste solo per parole, senza modello."""
    global _limite
    if _limite is None:
        _limite = servizio_ricerca.LimiteRichieste(impostazioni().ricerca_limite_pubblico)
    f = parametri(RicercaIn)
    semantica = _limite.consenti(request.remote_addr or "")
    return await servizio_ricerca.cerca(f.testo, await documenti_ricerca(db(), tipo), ente_id=e.id, semantica=semantica)


def _ente(e: Ente) -> dict:
    """Intestazione delle pagine pubbliche: nome, logo e dichiarazione di accessibilità."""
    return {"nome": e.nome, "logo": bool(e.logo_mime), "dichiarazione_accessibilita": e.dichiarazione_accessibilita}


def _solo(dati: dict, campi: tuple[str, ...]) -> dict:
    return {k: dati.get(k) for k in campi}


async def _ente_con_mappatura() -> Ente:
    """Ente del dominio con la mappatura pubblicata; imposta g.ente per le funzioni di lettura
    del modulo anticorruzione."""
    e = await ente_richiesta()
    if e is None or not e.modulo_attivo(Modulo.ANTICORRUZIONE) or not e.mappatura_pubblica:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Mappatura non pubblicata")
    g.ente = e
    return e


@bp.get("/mappatura")
async def mappatura():
    """Dati della pagina: ente, livelli di rischio (dal più basso), aree e strutture."""
    e = await _ente_con_mappatura()
    sessione = db()
    m = await metodologia_ente()
    aree = await sessione.scalars(select(AcArea).where(AcArea.ente_id == e.id))
    strutture = await sessione.scalars(
        select(Struttura).where(Struttura.ente_id == e.id).order_by(Struttura.ordine, Struttura.codice)
    )
    return {
        "ente": _ente(e),
        "livelli": m.livelli,
        "aree": [
            {"id": a.id, "codice": a.codice, "descrizione": a.descrizione, "descrizione_breve": a.descrizione_breve}
            for a in sorted(aree, key=chiave_area)
        ],
        "strutture": [{"id": s.id, "codice": s.codice, "descrizione": s.descrizione} for s in strutture],
    }


@bp.get("/mappatura/processi")
async def processi():
    """Processi e procedimenti con i conteggi e il livello più alto (stessi filtri dell'app)."""
    await _ente_con_mappatura()
    elenco = await elenco_processi(db(), parametri(FiltriProcessi))
    return [_solo(p, _PROCESSO + _CONTEGGI) for p in elenco]


@bp.get("/mappatura/processi/<processo_id>")
async def processo(processo_id: str):
    """Processo con le attività, i rischi (con il solo livello) e le misure."""
    await _ente_con_mappatura()
    sessione = db()
    albero = await albero_processo(sessione, await processo_dell_ente(sessione, processo_id))
    return {
        **_solo(albero, _PROCESSO),
        "attivita": [
            {**_solo(a, _ATTIVITA), "rischi": [
                {**_solo(r, _RISCHIO), "misure": [_solo(x, _MISURA) for x in r["misure"]]}
                for r in a["rischi"]
            ]}
            for a in albero["attivita"]
        ],
    }  # fmt: skip


@bp.get("/mappatura/ricerca")
async def ricerca_mappatura():
    """Ricerca in linguaggio naturale nei processi e procedimenti pubblicati."""
    return await _cerca(await _ente_con_mappatura(), None)


async def _ente_con_procedimenti() -> Ente:
    """Ente del dominio con i procedimenti pubblicati (dati della mappatura dell'anticorruzione)."""
    e = await ente_richiesta()
    if e is None or not e.modulo_attivo(Modulo.ANTICORRUZIONE) or not e.procedimenti_pubblici:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Procedimenti non pubblicati")
    g.ente = e
    return e


async def _strutture(e: Ente) -> dict[str, Struttura]:
    righe = await db().scalars(select(Struttura).where(Struttura.ente_id == e.id).order_by(Struttura.ordine, Struttura.codice))
    return {s.id: s for s in righe}


@bp.get("/procedimenti")
async def procedimenti():
    """Tipologie di procedimento (art. 35 d.lgs. 33/2013) con la struttura responsabile, per la
    pagina pubblica: ente, strutture che hanno procedimenti, elenco."""
    e = await _ente_con_procedimenti()
    strutture = await _strutture(e)
    righe = await db().scalars(select(AcProcesso).where(AcProcesso.ente_id == e.id, AcProcesso.tipo == "PROCEDIMENTO"))
    elenco = [
        {"id": p.id, "codice": p.codice, "denominazione": p.denominazione,
         "tipologia": (p.art35 or {}).get("tipologia"), "struttura_id": p.struttura_id}
        for p in sorted(righe, key=lambda p: chiave_naturale(p.codice))
    ]  # fmt: skip
    usate = {p["struttura_id"] for p in elenco}
    return {
        "ente": _ente(e),
        "strutture": [{"id": s.id, "codice": s.codice, "descrizione": s.descrizione}
                      for s in strutture.values() if s.id in usate],  # fmt: skip
        "procedimenti": elenco,
    }


@bp.get("/procedimenti/ricerca")
async def ricerca_procedimenti():
    """Ricerca in linguaggio naturale nei procedimenti (es. "come chiedo il contributo per
    l'affitto?")."""
    return await _cerca(await _ente_con_procedimenti(), "PROCEDIMENTO")


@bp.get("/procedimenti/<procedimento_id>")
async def procedimento(procedimento_id: str):
    """Tutti i dati dell'allegato 11 (schema ART_35) del procedimento, con i recapiti degli uffici."""
    e = await _ente_con_procedimenti()
    p = await db().get(AcProcesso, procedimento_id)
    if p is None or p.ente_id != e.id or p.tipo != "PROCEDIMENTO":
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Procedimento non trovato")
    return {"id": p.id, "codice": p.codice, "struttura_id": p.struttura_id,
            "scheda": dati_art35.scheda(p, await _strutture(e))}  # fmt: skip


# --- registro delle ricerche e feedback dei cittadini ---------------------------------------

# registrazioni per indirizzo IP (RICERCHE_LIMITE_REGISTRO al minuto)
_limite_registro: servizio_ricerca.LimiteRichieste | None = None


async def _ambiti_pubblici() -> tuple[Ente, dict]:
    """Ente del dominio e ambiti con la pagina pubblica attiva; senza nessuno: 404."""
    global _limite_registro
    if _limite_registro is None:
        _limite_registro = servizio_ricerca.LimiteRichieste(impostazioni().ricerche_limite_registro)
    e = await ente_richiesta()
    if e is None or not e.modulo_attivo(Modulo.ANTICORRUZIONE):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Pagine pubbliche non attive")
    attivi = {"MAPPATURA": e.mappatura_pubblica, "PROCEDIMENTI": e.procedimenti_pubblici}
    ambiti = {k: d for k, d in reg.ambiti_disponibili(e).items() if attivi.get(k)}
    if not ambiti:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Pagine pubbliche non attive")
    if not _limite_registro.consenti(request.remote_addr or ""):
        raise ErroreApi(HTTPStatus.TOO_MANY_REQUESTS, "Troppe richieste, riprova tra poco")
    g.ente = e
    return e, ambiti


@bp.post("/ricerche/registro")
async def registro_ricerca():
    """Ricerca conclusa di un cittadino (senza IP né altri dati di chi cerca)."""
    e, ambiti = await _ambiti_pubblici()
    return await registra_ricerca(e.id, ambiti, True, corpo(RicercaConclusaIn)), 201


@bp.post("/ricerche/feedback")
async def feedback_ricerca():
    """Feedback facoltativo di un cittadino sui risultati di una ricerca o su una scheda."""
    e, ambiti = await _ambiti_pubblici()
    return await registra_feedback(e.id, ambiti, True, corpo(FeedbackIn)), 201


@bp.get("/logo")
async def logo():
    """Logo dell'ente, per l'intestazione delle pagine pubbliche."""
    e = await ente_richiesta()
    if e is None or not e.modulo_attivo(Modulo.ANTICORRUZIONE) or not (e.mappatura_pubblica or e.procedimenti_pubblici):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Pagine pubbliche non attive")
    e = await db().scalar(select(Ente).where(Ente.id == e.id).options(undefer(Ente.logo)))
    if not e.logo:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Logo non caricato")
    estensione = "png" if e.logo_mime == "image/png" else "jpg"
    return allegato(e.logo, e.logo_mime, f"logo.{estensione}", in_linea=True)
