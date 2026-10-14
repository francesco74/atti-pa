"""Libreria normativa: atti, testo degli articoli per data, riferimenti pronti all'uso."""

import re
from datetime import date, datetime
from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel, model_validator
from sqlalchemy import or_, select

from deps import audit, autenticato, db, impostazioni, risorse, solo_admin, utente
from schemas import Schema
from web import ErroreApi, corpo, nessun_contenuto, out, parametri
from common.libreria import articolo_alla_data, assicura_atto, scarica_testo, trova_partizione
from common.models import NormaArticoloVersione, NormaAtto, NormattivaSync, Riferimento, Ruolo, TipologiaAtto
from common.normattiva import (
    ATTRIBUZIONE,
    AttoNonTrovato,
    NormattivaError,
    RisultatoAmbiguo,
    Urn,
)
from common.normattiva.citazioni import citazione_riferimento
from common.normattiva.urn import e_manuale

bp = Blueprint("norme", __name__, url_prefix="/api/v1")


def _errore_normattiva(e: Exception) -> ErroreApi:
    if isinstance(e, AttoNonTrovato):
        return ErroreApi(HTTPStatus.NOT_FOUND, "Norma non trovata su Normattiva")
    if isinstance(e, RisultatoAmbiguo):
        return ErroreApi(
            HTTPStatus.CONFLICT,
            {
                "messaggio": "La URN corrisponde a più testi su Normattiva",
                "candidati": [c.sottotitolo for c in e.candidati],
            },
        )
    return ErroreApi(HTTPStatus.BAD_GATEWAY, f"Normattiva non disponibile: {e}")


def _urn(valore: str) -> Urn:
    try:
        return Urn.parse(valore)
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e


# --- Tipologie -----------------------------------------------------------------------


class TipologiaOut(Schema):
    codice: str
    descrizione: str


@bp.get("/tipologie")
@autenticato()
async def tipologie():
    righe = (await db().scalars(select(TipologiaAtto).order_by(TipologiaAtto.ordine))).all()
    return out(TipologiaOut, righe)


# --- Atti normativi ------------------------------------------------------------------


class NormaOut(Schema):
    urn: str
    fonte: str
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
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e


class FiltroTesto(BaseModel):
    q: str | None = None


@bp.get("/norme")
@autenticato()
async def elenco_norme():
    q = parametri(FiltroTesto).q
    query = select(NormaAtto).order_by(NormaAtto.data_provvedimento.desc())
    if q:
        filtro = f"%{q}%"
        query = query.where(or_(NormaAtto.citazione.like(filtro), NormaAtto.titolo.like(filtro)))
    return out(NormaOut, (await db().scalars(query)).all())


@bp.post("/norme")
@autenticato()
async def aggiungi_norma():
    """Aggiunge un atto alla libreria verificandone l'esistenza su Normattiva."""
    urn = corpo(NormaIn).a_urn()
    if e_manuale(urn.atto):
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Le norme non presenti su Normattiva si inseriscono caricandone il testo",
        )
    sessione = db()
    esistente = await sessione.get(NormaAtto, urn.atto)
    if esistente:
        return out(NormaOut, esistente), HTTPStatus.CREATED
    try:
        # l'articolo 1 serve a verificare l'atto e a leggerne titolo e metadati
        testo = await scarica_testo(
            risorse().normattiva, Urn.parse(urn.atto).con_articolo("1"), date.today()
        )
    except NormattivaError as e:
        raise _errore_normattiva(e) from e
    atto = await assicura_atto(sessione, urn.atto, testo)
    audit(sessione, utente(), "norma", urn.atto, "AGGIUNTA")
    await sessione.commit()
    return out(NormaOut, atto), HTTPStatus.CREATED


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


class ArticoloQuery(BaseModel):
    urn: str  # es. urn:nir:stato:decreto.legislativo:2023-03-31;36~art50
    data: date | None = None  # data di vigenza (default: oggi)


class UrnAtto(BaseModel):
    urn: str


class ArticoloInLibreria(BaseModel):
    articolo: str
    rubrica: str | None


def _ordine_articolo(numero: str) -> tuple:
    """Ordine naturale: 2 < 10, 6 < 6-bis < 6-ter."""
    m = re.match(r"^(\d+)(?:-(\w+))?", numero)
    if not m:
        return (10**9, 0, numero)
    return (int(m[1]), _ORDINE_SUFFISSI.get(m[2] or "", 99), numero)


_ORDINE_SUFFISSI = {
    s: i
    for i, s in enumerate(
        ["", "bis", "ter", "quater", "quinquies", "sexies", "septies", "octies", "novies", "decies"]
    )
}


@bp.get("/norme/articoli")
@autenticato()
async def articoli_in_libreria():
    """Articoli dell'atto già presenti in libreria (scaricati da Normattiva o caricati)."""
    u = _urn(parametri(UrnAtto).urn)
    righe = await db().execute(
        select(NormaArticoloVersione.articolo, NormaArticoloVersione.rubrica)
        .where(NormaArticoloVersione.urn_atto == u.atto)
        .order_by(NormaArticoloVersione.vigenza_inizio.desc())
    )
    articoli: dict[str, str | None] = {}
    for articolo, rubrica in righe.all():
        articoli.setdefault(articolo, rubrica)  # rubrica della versione più recente
    return [
        ArticoloInLibreria(articolo=a, rubrica=r).model_dump()
        for a, r in sorted(articoli.items(), key=lambda x: _ordine_articolo(x[0]))
    ]


@bp.get("/norme/articolo")
@autenticato()
async def testo_articolo():
    """Testo di un articolo vigente alla data, scomposto in commi e lettere."""
    q = parametri(ArticoloQuery)
    u = _urn(q.urn)
    if not u.articolo:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indicare l'articolo (~artN)")
    giorno = q.data or datetime.now(impostazioni().tz).date()
    sessione = db()
    try:
        versione = await articolo_alla_data(
            sessione, risorse().normattiva, u.atto, u.articolo, giorno
        )
    except AttoNonTrovato as e:
        if e_manuale(u.atto):
            raise ErroreApi(
                HTTPStatus.NOT_FOUND,
                f"Articolo {u.articolo} non presente nel testo della norma vigente al "
                f"{giorno:%d/%m/%Y}",
            ) from e
        raise _errore_normattiva(e) from e
    except NormattivaError as e:
        raise _errore_normattiva(e) from e
    atto = await sessione.get(NormaAtto, u.atto)
    return ArticoloOut(
        urn_atto=u.atto,
        articolo=u.articolo,
        citazione_atto=atto.citazione,
        rubrica=versione.rubrica,
        vigenza_inizio=versione.vigenza_inizio,
        vigenza_fine=versione.vigenza_fine,
        data_richiesta=giorno,
        struttura=versione.struttura_json,
    ).model_dump(mode="json")


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


class FiltroRiferimenti(BaseModel):
    tipologia: str | None = None
    q: str | None = None


@bp.get("/riferimenti")
@autenticato()
async def elenco_riferimenti():
    """Riferimenti condivisi più quelli personali dell'utente."""
    filtro = parametri(FiltroRiferimenti)
    query = (
        select(Riferimento)
        .where(or_(Riferimento.owner_id.is_(None), Riferimento.owner_id == utente().id))
        .order_by(Riferimento.urn_atto, Riferimento.articolo)
    )
    if filtro.q:
        query = query.where(Riferimento.citazione.like(f"%{filtro.q}%"))
    risultati = (await db().scalars(query)).unique().all()
    if filtro.tipologia:
        risultati = [
            r for r in risultati if not r.tipologie_atto or filtro.tipologia in r.tipologie_atto
        ]
    return out(RiferimentoOut, risultati)


@bp.post("/riferimenti")
@autenticato()
async def crea_riferimento():
    dati = corpo(RiferimentoIn)
    user = utente()
    if dati.condiviso and not user.ha_ruolo(Ruolo.ADMIN):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Solo un ADMIN può condividere riferimenti")
    urn = _urn(dati.urn_atto)
    oggi = datetime.now(impostazioni().tz).date()
    sessione = db()
    try:
        versione = await articolo_alla_data(
            sessione, risorse().normattiva, urn.atto, dati.articolo, oggi
        )
    except NormattivaError as e:
        if e_manuale(urn.atto):
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
        raise _errore_normattiva(e) from e
    trovato, _ = trova_partizione(versione.struttura_json, dati.comma, dati.lettera)
    if not trovato:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Comma o lettera non presenti nel testo vigente dell'articolo",
        )
    rif = Riferimento(
        urn_atto=urn.atto,
        articolo=dati.articolo,
        comma=dati.comma,
        lettera=dati.lettera,
        citazione=dati.citazione
        or citazione_riferimento(
            urn.atto,
            dati.articolo,
            dati.comma,
            dati.lettera,
            atto=atto.citazione if (atto := await sessione.get(NormaAtto, urn.atto)) else None,
        ),
        tipologie_atto=dati.tipologie_atto or None,
        note=dati.note,
        owner_id=None if dati.condiviso else user.id,
    )
    sessione.add(rif)
    await sessione.flush()
    audit(sessione, user, "riferimento", rif.id, "CREATO")
    await sessione.commit()
    return out(RiferimentoOut, rif), HTTPStatus.CREATED


@bp.delete("/riferimenti/<rif_id>")
@autenticato()
async def elimina_riferimento(rif_id: str):
    sessione = db()
    user = utente()
    rif = await sessione.get(Riferimento, rif_id)
    if rif is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    proprio = rif.owner_id == user.id
    if not proprio and not user.ha_ruolo(Ruolo.ADMIN):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Riferimento non modificabile")
    await sessione.delete(rif)
    audit(sessione, user, "riferimento", rif_id, "ELIMINATO")
    await sessione.commit()
    return nessun_contenuto()


# --- Stato aggiornamenti -------------------------------------------------------------


class SyncOut(Schema):
    intervallo_da: datetime
    intervallo_a: datetime
    atti_modificati: int
    articoli_aggiornati: int
    esito: str
    dettaglio: str | None
    eseguito_il: datetime


class FiltroAggiornamenti(BaseModel):
    limite: int = 30


@bp.get("/norme/aggiornamenti")
@solo_admin
async def aggiornamenti():
    """Ultime esecuzioni del job di aggiornamento delle normative."""
    limite = min(parametri(FiltroAggiornamenti).limite, 200)
    query = select(NormattivaSync).order_by(NormattivaSync.id.desc()).limit(limite)
    return out(SyncOut, (await db().scalars(query)).all())
