"""Pagine pubbliche, senza accesso: la mappatura dei processi dell'anticorruzione, che i
cittadini consultano su /pubblico/mappatura (il link si mette nel sito dell'ente).

L'ente si riconosce dal dominio della richiesta. Le API rispondono solo se l'ente ha il modulo
anticorruzione e il RPCT ha acceso la pubblicazione (Ente.mappatura_pubblica); altrimenti 404,
come se la pagina non esistesse. Si mostrano solo i dati da pubblicare: per i rischi evento,
fattore abilitante e livello, non i valori degli indicatori né le correzioni motivate.
"""

from http import HTTPStatus

from flask import Blueprint, g
from sqlalchemy import select
from sqlalchemy.orm import undefer

from deps import db, ente_richiesta
from routers.anticorruzione import (
    FiltriProcessi, albero_processo, elenco_processi, metodologia_ente, processo_dell_ente,
)  # fmt: skip
from web import ErroreApi, allegato, parametri
from common.anticorruzione.metodologia import chiave_area
from common.models import AcArea, Ente, Modulo, Struttura

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
        "ente": {"nome": e.nome, "logo": bool(e.logo_mime)},
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


@bp.get("/logo")
async def logo():
    """Logo dell'ente, per l'intestazione della pagina pubblica."""
    e = await _ente_con_mappatura()
    e = await db().scalar(select(Ente).where(Ente.id == e.id).options(undefer(Ente.logo)))
    if not e.logo:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Logo non caricato")
    estensione = "png" if e.logo_mime == "image/png" else "jpg"
    return allegato(e.logo, e.logo_mime, f"logo.{estensione}", in_linea=True)
