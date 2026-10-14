"""Checklist di qualità per tipologia di atto, versionate.

Modificare una checklist crea una nuova versione: le verifiche già eseguite restano
legate alla versione usata.
"""

import re
from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from deps import audit, autenticato, db, solo_admin, utente
from schemas import Schema
from web import ErroreApi, corpo, nessun_contenuto, out, parametri
from common.models import Checklist, ChecklistElemento, TipologiaAtto

bp = Blueprint("checklists", __name__, url_prefix="/api/v1/checklists")


class ElementoIn(BaseModel):
    titolo: str = Field(min_length=1, max_length=255)
    regola: str = Field(min_length=1)
    riferimenti: list[str] = []  # URN di articoli da passare all'LLM come contesto
    obbligatorio: bool = True


class ChecklistIn(BaseModel):
    titolo: str = Field(min_length=1, max_length=255)
    tipologia_atto: str
    descrizione: str | None = None
    elementi: list[ElementoIn] = Field(min_length=1)


class ChecklistNuovaIn(ChecklistIn):
    codice: str = Field(min_length=2, max_length=100)

    @field_validator("codice")
    @classmethod
    def _codice(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]+", v):
            raise ValueError("Il codice può contenere solo lettere, numeri, '_' e '-'")
        return v


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
    descrizione: str | None
    attiva: bool
    elementi: list[ElementoOut]


class FiltroChecklist(BaseModel):
    tipologia: str | None = None
    tutte: bool = False


def _elementi(dati: list[ElementoIn]) -> list[ChecklistElemento]:
    return [
        ChecklistElemento(
            ordine=i,
            titolo=e.titolo,
            regola=e.regola,
            riferimenti_json=e.riferimenti or None,
            obbligatorio=e.obbligatorio,
        )
        for i, e in enumerate(dati)
    ]


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
    cl = Checklist(
        codice=dati.codice,
        versione=1,
        titolo=dati.titolo,
        tipologia_atto=dati.tipologia_atto,
        descrizione=dati.descrizione,
        attiva=True,
        elementi=_elementi(dati.elementi),
    )
    sessione.add(cl)
    await sessione.flush()
    audit(sessione, utente(), "checklist", cl.id, "CREATA", {"codice": cl.codice, "versione": 1})
    await sessione.commit()
    await sessione.refresh(cl)
    return out(ChecklistOut, cl), HTTPStatus.CREATED


@bp.put("/codice/<codice>")
@solo_admin
async def nuova_versione(codice: str):
    """Crea una nuova versione della checklist e disattiva le precedenti."""
    dati = corpo(ChecklistIn)
    sessione = db()
    await _verifica_tipologia(sessione, dati.tipologia_atto)
    ultima = await sessione.scalar(
        select(func.max(Checklist.versione)).where(Checklist.codice == codice)
    )
    if ultima is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    for vecchia in (
        await sessione.scalars(select(Checklist).where(Checklist.codice == codice))
    ).all():
        vecchia.attiva = False
    cl = Checklist(
        codice=codice,
        versione=ultima + 1,
        titolo=dati.titolo,
        tipologia_atto=dati.tipologia_atto,
        descrizione=dati.descrizione,
        attiva=True,
        elementi=_elementi(dati.elementi),
    )
    sessione.add(cl)
    await sessione.flush()
    audit(
        sessione,
        utente(),
        "checklist",
        cl.id,
        "NUOVA_VERSIONE",
        {"codice": codice, "versione": cl.versione},
    )
    await sessione.commit()
    await sessione.refresh(cl)
    return out(ChecklistOut, cl)


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
