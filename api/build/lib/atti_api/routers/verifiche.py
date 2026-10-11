"""Verifiche asincrone di bozze e atti controllati (eseguite dal verifica-worker)."""

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import undefer

from atti_api.composizione import aggiorna_testo, data_riferimento
from atti_api.deps import ControlloreDep, DbDep, SettingsDep, UtenteDep, audit
from atti_api.schemas import Schema
from atti_common.models import (
    AttoControllato,
    Bozza,
    Checklist,
    Ruolo,
    StatoVerifica,
    Template,
    User,
    Verifica,
)

router = APIRouter(prefix="/api/v1/verifiche", tags=["verifiche"])


class VerificaIn(BaseModel):
    bozza_id: str | None = None
    atto_controllato_id: str | None = None
    checklist_id: str | None = None  # default: checklist attiva della tipologia

    @model_validator(mode="after")
    def _uno_solo(self):
        if bool(self.bozza_id) == bool(self.atto_controllato_id):
            raise ValueError("Indicare bozza_id oppure atto_controllato_id")
        return self


class VerificaOut(Schema):
    id: str
    bozza_id: str | None
    atto_controllato_id: str | None
    checklist_id: str | None
    data_riferimento: date
    stato: str
    errore: str | None
    tentativi: int
    esito_riferimenti: dict | None
    esito_automatico: list | None
    esito_finale: list | None
    motivazione: str | None
    revisore_id: str | None
    modello_llm: str | None
    created_at: datetime | None
    completata_il: datetime | None


async def checklist_per_tipologia(db, tipologia: str | None) -> str | None:
    if not tipologia:
        return None
    return await db.scalar(
        select(Checklist.id)
        .where(Checklist.tipologia_atto == tipologia, Checklist.attiva.is_(True))
        .order_by(Checklist.versione.desc())
        .limit(1)
    )


async def _autorizza(db, verifica: Verifica, user: User) -> None:
    if verifica.bozza_id:
        bozza = await db.get(Bozza, verifica.bozza_id)
        if bozza is None or bozza.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Verifica non trovata")
    elif not user.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verifica non trovata")


async def accoda(
    db, user: User, giorno: date, checklist_id: str | None, **destinazione
) -> Verifica:
    if checklist_id and await db.get(Checklist, checklist_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Checklist inesistente")
    verifica = Verifica(
        data_riferimento=giorno,
        checklist_id=checklist_id,
        stato=StatoVerifica.IN_CODA,
        richiesta_da=user.id,
        **destinazione,
    )
    db.add(verifica)
    await db.flush()
    audit(db, user, "verifica", verifica.id, "RICHIESTA", destinazione)
    return verifica


@router.post("", response_model=VerificaOut, status_code=status.HTTP_202_ACCEPTED)
async def richiedi(dati: VerificaIn, db: DbDep, user: UtenteDep, settings: SettingsDep):
    oggi = datetime.now(settings.tz).date()
    if dati.bozza_id:
        bozza = await db.get(Bozza, dati.bozza_id)
        if bozza is None or bozza.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bozza non trovata")
        if bozza.template_id:
            template = await db.scalar(
                select(Template)
                .where(Template.id == bozza.template_id)
                .options(undefer(Template.file_contenuto))
            )
            aggiorna_testo(bozza, template)
        checklist_id = dati.checklist_id or await checklist_per_tipologia(db, bozza.tipologia_atto)
        verifica = await accoda(
            db, user, data_riferimento(bozza, oggi), checklist_id, bozza_id=bozza.id
        )
    else:
        if not user.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Operazione non consentita")
        atto = await db.get(AttoControllato, dati.atto_controllato_id)
        if atto is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Atto non trovato")
        checklist_id = dati.checklist_id or await checklist_per_tipologia(db, atto.tipologia_atto)
        verifica = await accoda(
            db, user, atto.data_adozione, checklist_id, atto_controllato_id=atto.id
        )
        atto.stato = "IN_ANALISI"
    await db.commit()
    await db.refresh(verifica)
    return verifica


@router.get("", response_model=list[VerificaOut])
async def elenco(
    db: DbDep,
    user: UtenteDep,
    bozza_id: str | None = None,
    atto_controllato_id: str | None = None,
):
    if bool(bozza_id) == bool(atto_controllato_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Indicare bozza_id oppure atto_controllato_id"
        )
    query = select(Verifica).order_by(Verifica.created_at.desc())
    if bozza_id:
        bozza = await db.get(Bozza, bozza_id)
        if bozza is None or bozza.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bozza non trovata")
        query = query.where(Verifica.bozza_id == bozza_id)
    else:
        if not user.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Operazione non consentita")
        query = query.where(Verifica.atto_controllato_id == atto_controllato_id)
    return (await db.scalars(query)).all()


@router.get("/{verifica_id}", response_model=VerificaOut)
async def dettaglio(verifica_id: str, db: DbDep, user: UtenteDep):
    verifica = await db.get(Verifica, verifica_id)
    if verifica is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verifica non trovata")
    await _autorizza(db, verifica, user)
    return verifica


class EsitoRevisione(BaseModel):
    elemento_id: str | None = None  # None per osservazioni generali
    titolo: str
    esito: str = Field(pattern="^(CONFORME|NON_CONFORME|NON_APPLICABILE|DUBBIO)$")
    nota: str | None = None


class RevisioneIn(BaseModel):
    esiti: list[EsitoRevisione]
    motivazione: str = Field(min_length=1)
    conclusa: bool = False


@router.put("/{verifica_id}/revisione", response_model=VerificaOut)
async def revisione(verifica_id: str, dati: RevisioneIn, db: DbDep, user: ControlloreDep):
    """Esito finale del controllore: conferma o modifica la proposta automatica."""
    verifica = await db.get(Verifica, verifica_id)
    if verifica is None or not verifica.atto_controllato_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verifica non trovata")
    if verifica.stato != StatoVerifica.COMPLETATA:
        raise HTTPException(status.HTTP_409_CONFLICT, "La verifica automatica non è conclusa")
    atto = await db.get(AttoControllato, verifica.atto_controllato_id)
    if atto.stato == "CHIUSO":
        raise HTTPException(status.HTTP_409_CONFLICT, "Il controllo dell'atto è già chiuso")
    verifica.esito_finale = [e.model_dump() for e in dati.esiti]
    verifica.motivazione = dati.motivazione
    verifica.revisore_id = user.id
    atto.stato = "CHIUSO" if dati.conclusa else "IN_REVISIONE"
    audit(db, user, "verifica", verifica.id, "REVISIONE", {"conclusa": dati.conclusa})
    await db.commit()
    await db.refresh(verifica)
    return verifica
