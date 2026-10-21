"""Checklist di qualità, versionate, su tre livelli: generica della tipologia di atto, del
modello di atto (`modello`), della specificità (`modulo`, modulo di regole). La verifica di
un atto le applica tutte (routers.verifiche.schede_applicabili).

Modificare una checklist crea una nuova versione: le verifiche già eseguite restano
legate alla versione usata.
"""

from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel
from sqlalchemy import select

from deps import audit, autenticato, db, solo_admin, utente
from schemas import Schema
from web import ErroreApi, corpo, nessun_contenuto, out, parametri
from common.configurazione import ChecklistIn, ChecklistNuovaIn, controlla_checklist
from common.pacchetti import MANTIENI_BASE, salva_checklist
from common.models import Checklist, TipologiaAtto

bp = Blueprint("checklists", __name__, url_prefix="/api/v1/checklists")


class ElementoOut(Schema):
    id: str
    ordine: int
    titolo: str
    regola: str
    riferimenti_json: list[str] | None
    obbligatorio: bool


class ChecklistOut(Schema):
    id: str
    codice: str
    versione: int
    titolo: str
    tipologia_atto: str
    modello: str | None
    modulo: str | None
    descrizione: str | None
    attiva: bool
    pacchetto: str | None  # pacchetto standard da cui deriva
    impronta: str | None
    impronta_base: str | None
    elementi: list[ElementoOut]


class FiltroChecklist(BaseModel):
    tipologia: str | None = None
    tutte: bool = False


async def _verifica_tipologia(sessione, codice: str) -> None:
    if await sessione.get(TipologiaAtto, codice) is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")


@bp.get("")
@autenticato()
async def elenco():
    """Checklist attive (o tutte le versioni con `tutte=true`)."""
    filtro = parametri(FiltroChecklist)
    query = select(Checklist).order_by(Checklist.codice, Checklist.versione.desc())
    if not filtro.tutte:
        query = query.where(Checklist.attiva.is_(True))
    if filtro.tipologia:
        query = query.where(Checklist.tipologia_atto == filtro.tipologia)
    return out(ChecklistOut, (await db().scalars(query)).all())


@bp.get("/<checklist_id>")
@autenticato()
async def dettaglio(checklist_id: str):
    cl = await db().get(Checklist, checklist_id)
    if cl is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    return out(ChecklistOut, cl)


@bp.post("")
@solo_admin
async def crea():
    dati = corpo(ChecklistNuovaIn)
    sessione = db()
    await _verifica_tipologia(sessione, dati.tipologia_atto)
    if await sessione.scalar(select(Checklist.id).where(Checklist.codice == dati.codice).limit(1)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Codice checklist già esistente")
    cl = await _salva(sessione, dati)
    return out(ChecklistOut, cl), HTTPStatus.CREATED


@bp.put("/codice/<codice>")
@solo_admin
async def nuova_versione(codice: str):
    """Crea una nuova versione della checklist e disattiva le precedenti. Se la checklist
    deriva da un pacchetto standard, resta il riferimento allo standard: un aggiornamento
    successivo la riconosce come modificata dall'ente."""
    dati = corpo(ChecklistIn)
    sessione = db()
    await _verifica_tipologia(sessione, dati.tipologia_atto)
    esistente = await sessione.scalar(
        select(Checklist.id).where(Checklist.codice == codice).limit(1)
    )
    if esistente is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    cl = await _salva(sessione, ChecklistNuovaIn(codice=codice, **dati.model_dump()))
    return out(ChecklistOut, cl)


async def _salva(sessione, dati: ChecklistNuovaIn) -> Checklist:
    try:
        controlla_checklist(dati)
        cl = await salva_checklist(sessione, dati, MANTIENI_BASE, utente().id)
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    await sessione.commit()
    await sessione.refresh(cl)
    return cl


@bp.delete("/codice/<codice>")
@solo_admin
async def disattiva(codice: str):
    sessione = db()
    versioni = (await sessione.scalars(select(Checklist).where(Checklist.codice == codice))).all()
    if not versioni:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    for cl in versioni:
        cl.attiva = False
    audit(sessione, utente(), "checklist", codice, "DISATTIVATA")
    await sessione.commit()
    return nessun_contenuto()
