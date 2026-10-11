"""Checklist di qualità per tipologia di atto, versionate.

Modificare una checklist crea una nuova versione: le verifiche già eseguite restano
legate alla versione usata.
"""

import re

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from atti_api.deps import AdminDep, DbDep, UtenteDep, audit
from atti_api.schemas import Schema
from atti_common.models import Checklist, ChecklistElemento, TipologiaAtto

router = APIRouter(prefix="/api/v1/checklists", tags=["checklist"])


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


async def _verifica_tipologia(db, codice: str) -> None:
    if await db.get(TipologiaAtto, codice) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")


@router.get("", response_model=list[ChecklistOut])
async def elenco(db: DbDep, _: UtenteDep, tipologia: str | None = None, tutte: bool = False):
    """Checklist attive (o tutte le versioni con `tutte=true`)."""
    query = select(Checklist).order_by(Checklist.codice, Checklist.versione.desc())
    if not tutte:
        query = query.where(Checklist.attiva.is_(True))
    if tipologia:
        query = query.where(Checklist.tipologia_atto == tipologia)
    return (await db.scalars(query)).all()


@router.get("/{checklist_id}", response_model=ChecklistOut)
async def dettaglio(checklist_id: str, db: DbDep, _: UtenteDep):
    cl = await db.get(Checklist, checklist_id)
    if cl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return cl


@router.post("", response_model=ChecklistOut, status_code=status.HTTP_201_CREATED)
async def crea(dati: ChecklistNuovaIn, db: DbDep, user: AdminDep):
    await _verifica_tipologia(db, dati.tipologia_atto)
    if await db.scalar(select(Checklist.id).where(Checklist.codice == dati.codice).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Codice checklist già esistente")
    cl = Checklist(
        codice=dati.codice,
        versione=1,
        titolo=dati.titolo,
        tipologia_atto=dati.tipologia_atto,
        descrizione=dati.descrizione,
        attiva=True,
        elementi=_elementi(dati.elementi),
    )
    db.add(cl)
    await db.flush()
    audit(db, user, "checklist", cl.id, "CREATA", {"codice": cl.codice, "versione": 1})
    await db.commit()
    await db.refresh(cl)
    return cl


@router.put("/codice/{codice}", response_model=ChecklistOut)
async def nuova_versione(codice: str, dati: ChecklistIn, db: DbDep, user: AdminDep):
    """Crea una nuova versione della checklist e disattiva le precedenti."""
    await _verifica_tipologia(db, dati.tipologia_atto)
    ultima = await db.scalar(select(func.max(Checklist.versione)).where(Checklist.codice == codice))
    if ultima is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for vecchia in (await db.scalars(select(Checklist).where(Checklist.codice == codice))).all():
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
    db.add(cl)
    await db.flush()
    audit(
        db, user, "checklist", cl.id, "NUOVA_VERSIONE", {"codice": codice, "versione": cl.versione}
    )
    await db.commit()
    await db.refresh(cl)
    return cl


@router.delete("/codice/{codice}", status_code=status.HTTP_204_NO_CONTENT)
async def disattiva(codice: str, db: DbDep, user: AdminDep) -> None:
    versioni = (await db.scalars(select(Checklist).where(Checklist.codice == codice))).all()
    if not versioni:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for cl in versioni:
        cl.attiva = False
    audit(db, user, "checklist", codice, "DISATTIVATA")
    await db.commit()
