"""Libreria normativa: atti, testo degli articoli per data, riferimenti pronti all'uso."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator
from sqlalchemy import or_, select

from atti_api.deps import AdminDep, DbDep, SettingsDep, UtenteDep, audit, get_normattiva
from atti_api.schemas import Schema
from atti_common.libreria import articolo_alla_data, assicura_atto, scarica_testo, trova_partizione
from atti_common.models import NormaAtto, NormattivaSync, Riferimento, Ruolo, TipologiaAtto
from atti_common.normattiva import (
    ATTRIBUZIONE,
    AttoNonTrovato,
    NormattivaClient,
    NormattivaError,
    RisultatoAmbiguo,
    Urn,
)
from atti_common.normattiva.citazioni import citazione_riferimento

router = APIRouter(prefix="/api/v1", tags=["libreria normativa"])

NormattivaDep = Annotated[NormattivaClient, Depends(get_normattiva)]


def _errore_normattiva(e: Exception) -> HTTPException:
    if isinstance(e, AttoNonTrovato):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Norma non trovata su Normattiva")
    if isinstance(e, RisultatoAmbiguo):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "messaggio": "La URN corrisponde a più testi su Normattiva",
                "candidati": [c.sottotitolo for c in e.candidati],
            },
        )
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"Normattiva non disponibile: {e}")


def _urn(valore: str) -> Urn:
    try:
        return Urn.parse(valore)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e


# --- Tipologie -----------------------------------------------------------------------


class TipologiaOut(Schema):
    codice: str
    descrizione: str


@router.get("/tipologie", response_model=list[TipologiaOut])
async def tipologie(db: DbDep, _: UtenteDep):
    return (await db.scalars(select(TipologiaAtto).order_by(TipologiaAtto.ordine))).all()


# --- Atti normativi ------------------------------------------------------------------


class NormaOut(Schema):
    urn: str
    denominazione: str
    data_provvedimento: date
    numero: str
    titolo: str | None
    citazione: str


class NormaIn(BaseModel):
    urn: str | None = None
    tipo: str | None = None  # "legge", "d.lgs.", "dpr", ...
    data: date | None = None
    numero: str | None = None

    @model_validator(mode="after")
    def _controlla(self):
        if not self.urn and not (self.tipo and self.data and self.numero):
            raise ValueError("Indicare la URN oppure tipo, data e numero")
        return self

    def a_urn(self) -> Urn:
        if self.urn:
            return _urn(self.urn)
        try:
            return Urn.per_tipo(self.tipo, self.data, self.numero)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e


@router.get("/norme", response_model=list[NormaOut])
async def elenco_norme(db: DbDep, _: UtenteDep, q: str | None = None):
    query = select(NormaAtto).order_by(NormaAtto.data_provvedimento.desc())
    if q:
        filtro = f"%{q}%"
        query = query.where(or_(NormaAtto.citazione.like(filtro), NormaAtto.titolo.like(filtro)))
    return (await db.scalars(query)).all()


@router.post("/norme", response_model=NormaOut, status_code=status.HTTP_201_CREATED)
async def aggiungi_norma(dati: NormaIn, db: DbDep, user: UtenteDep, normattiva: NormattivaDep):
    """Aggiunge un atto alla libreria verificandone l'esistenza su Normattiva."""
    urn = dati.a_urn()
    esistente = await db.get(NormaAtto, urn.atto)
    if esistente:
        return esistente
    try:
        # l'articolo 1 serve a verificare l'atto e a leggerne titolo e metadati
        testo = await scarica_testo(normattiva, Urn.parse(urn.atto).con_articolo("1"), date.today())
    except NormattivaError as e:
        raise _errore_normattiva(e) from e
    atto = await assicura_atto(db, urn.atto, testo)
    audit(db, user, "norma", urn.atto, "AGGIUNTA")
    await db.commit()
    return atto


class ArticoloOut(BaseModel):
    urn_atto: str
    articolo: str
    citazione_atto: str
    rubrica: str | None
    vigenza_inizio: date | None
    vigenza_fine: date | None
    data_richiesta: date
    struttura: dict
    fonte: str = ATTRIBUZIONE


@router.get("/norme/articolo", response_model=ArticoloOut)
async def testo_articolo(
    db: DbDep,
    _: UtenteDep,
    normattiva: NormattivaDep,
    settings: SettingsDep,
    urn: Annotated[str, Query(examples=["urn:nir:stato:decreto.legislativo:2023-03-31;36~art50"])],
    data: Annotated[date | None, Query(description="Data di vigenza (default: oggi)")] = None,
):
    """Testo di un articolo vigente alla data, scomposto in commi e lettere."""
    u = _urn(urn)
    if not u.articolo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indicare l'articolo (~artN)")
    giorno = data or datetime.now(settings.tz).date()
    try:
        versione = await articolo_alla_data(db, normattiva, u.atto, u.articolo, giorno)
    except NormattivaError as e:
        raise _errore_normattiva(e) from e
    atto = await db.get(NormaAtto, u.atto)
    return ArticoloOut(
        urn_atto=u.atto,
        articolo=u.articolo,
        citazione_atto=atto.citazione,
        rubrica=versione.rubrica,
        vigenza_inizio=versione.vigenza_inizio,
        vigenza_fine=versione.vigenza_fine,
        data_richiesta=giorno,
        struttura=versione.struttura_json,
    )


# --- Riferimenti ---------------------------------------------------------------------


class RiferimentoIn(BaseModel):
    urn_atto: str
    articolo: str
    comma: str | None = None
    lettera: str | None = None
    citazione: str | None = None  # se assente viene generata
    tipologie_atto: list[str] = []
    note: str | None = None
    condiviso: bool = False  # visibile a tutti (solo ADMIN)


class RiferimentoOut(Schema):
    id: str
    urn_atto: str
    articolo: str
    comma: str | None
    lettera: str | None
    citazione: str
    tipologie_atto: list[str] | None
    note: str | None
    owner_id: str | None


@router.get("/riferimenti", response_model=list[RiferimentoOut])
async def elenco_riferimenti(
    db: DbDep, user: UtenteDep, tipologia: str | None = None, q: str | None = None
):
    """Riferimenti condivisi più quelli personali dell'utente."""
    query = (
        select(Riferimento)
        .where(or_(Riferimento.owner_id.is_(None), Riferimento.owner_id == user.id))
        .order_by(Riferimento.urn_atto, Riferimento.articolo)
    )
    if q:
        query = query.where(Riferimento.citazione.like(f"%{q}%"))
    risultati = (await db.scalars(query)).unique().all()
    if tipologia:
        risultati = [r for r in risultati if not r.tipologie_atto or tipologia in r.tipologie_atto]
    return risultati


@router.post("/riferimenti", response_model=RiferimentoOut, status_code=status.HTTP_201_CREATED)
async def crea_riferimento(
    dati: RiferimentoIn,
    db: DbDep,
    user: UtenteDep,
    normattiva: NormattivaDep,
    settings: SettingsDep,
):
    if dati.condiviso and not user.ha_ruolo(Ruolo.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un ADMIN può condividere riferimenti")
    urn = _urn(dati.urn_atto)
    oggi = datetime.now(settings.tz).date()
    try:
        versione = await articolo_alla_data(db, normattiva, urn.atto, dati.articolo, oggi)
    except NormattivaError as e:
        raise _errore_normattiva(e) from e
    trovato, _ = trova_partizione(versione.struttura_json, dati.comma, dati.lettera)
    if not trovato:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Comma o lettera non presenti nel testo vigente dell'articolo",
        )
    rif = Riferimento(
        urn_atto=urn.atto,
        articolo=dati.articolo,
        comma=dati.comma,
        lettera=dati.lettera,
        citazione=dati.citazione
        or citazione_riferimento(urn.atto, dati.articolo, dati.comma, dati.lettera),
        tipologie_atto=dati.tipologie_atto or None,
        note=dati.note,
        owner_id=None if dati.condiviso else user.id,
    )
    db.add(rif)
    await db.flush()
    audit(db, user, "riferimento", rif.id, "CREATO")
    await db.commit()
    return rif


@router.delete("/riferimenti/{rif_id}", status_code=status.HTTP_204_NO_CONTENT)
async def elimina_riferimento(rif_id: str, db: DbDep, user: UtenteDep) -> None:
    rif = await db.get(Riferimento, rif_id)
    if rif is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    proprio = rif.owner_id == user.id
    if not proprio and not user.ha_ruolo(Ruolo.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Riferimento non modificabile")
    await db.delete(rif)
    audit(db, user, "riferimento", rif_id, "ELIMINATO")
    await db.commit()


# --- Stato aggiornamenti -------------------------------------------------------------


class SyncOut(Schema):
    intervallo_da: datetime
    intervallo_a: datetime
    atti_modificati: int
    articoli_aggiornati: int
    esito: str
    dettaglio: str | None
    eseguito_il: datetime


@router.get("/norme/aggiornamenti", response_model=list[SyncOut])
async def aggiornamenti(db: DbDep, _: AdminDep, limite: int = 30):
    """Ultime esecuzioni del job di aggiornamento delle normative."""
    query = select(NormattivaSync).order_by(NormattivaSync.id.desc()).limit(min(limite, 200))
    return (await db.scalars(query)).all()
