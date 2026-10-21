"""Verifiche asincrone di bozze e atti controllati (eseguite dal verifica-worker)."""

from datetime import date, datetime
from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from composizione import aggiorna_bozza, data_riferimento, valuta
from common import coda
from deps import audit, autenticato, controllore, db, impostazioni, notifica, utente
from schemas import Schema
from web import ErroreApi, corpo, out, parametri
from common.models import (
    AttoControllato,
    Bozza,
    Checklist,
    Ruolo,
    StatoVerifica,
    User,
    Verifica,
)

bp = Blueprint("verifiche", __name__, url_prefix="/api/v1/verifiche")


class VerificaIn(BaseModel):
    bozza_id: str | None = None
    atto_controllato_id: str | None = None

    @model_validator(mode="after")
    def _uno_solo(self):
        if bool(self.bozza_id) == bool(self.atto_controllato_id):
            raise ValueError("Indicare bozza_id oppure atto_controllato_id")
        return self


class VerificaOut(Schema):
    id: str
    bozza_id: str | None
    atto_controllato_id: str | None
    checklist_ids: list[str] | None
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


class FiltroVerifiche(BaseModel):
    bozza_id: str | None = None
    atto_controllato_id: str | None = None


async def schede_applicabili(
    sessione, tipologia: str | None, modello: str | None = None, moduli: list[str] | None = None
) -> list[str]:
    """Checklist attive da applicare a un atto, nell'ordine: la generica della tipologia,
    quella del modello di atto, quelle delle specificità scelte."""
    if not tipologia:
        return []
    schede = (
        await sessione.scalars(
            select(Checklist)
            .where(Checklist.tipologia_atto == tipologia, Checklist.attiva.is_(True))
            .order_by(Checklist.codice)
        )
    ).all()
    generiche = [c.id for c in schede if not c.modello and not c.modulo]
    del_modello = [c.id for c in schede if modello and c.modello == modello]
    delle_specificita = [
        c.id for codice in moduli or [] for c in schede if c.modulo == codice
    ]
    return generiche + del_modello + delle_specificita


async def _autorizza(sessione, verifica: Verifica, user: User) -> None:
    if verifica.bozza_id:
        bozza = await sessione.get(Bozza, verifica.bozza_id)
        if bozza is None or bozza.owner_id != user.id:
            raise ErroreApi(HTTPStatus.NOT_FOUND, "Verifica non trovata")
    elif not user.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Verifica non trovata")


async def accoda(
    sessione, user: User, giorno: date, checklist_ids: list[str], **destinazione
) -> Verifica:
    verifica = Verifica(
        data_riferimento=giorno,
        checklist_ids=checklist_ids or None,
        stato=StatoVerifica.IN_CODA,
        richiesta_da=user.id,
        **destinazione,
    )
    sessione.add(verifica)
    await sessione.flush()
    audit(sessione, user, "verifica", verifica.id, "RICHIESTA", destinazione)
    return verifica


@bp.post("")
@autenticato()
async def richiedi():
    dati = corpo(VerificaIn)
    sessione = db()
    user = utente()
    oggi = datetime.now(impostazioni().tz).date()
    if dati.bozza_id:
        bozza = await sessione.get(Bozza, dati.bozza_id)
        if bozza is None or bozza.owner_id != user.id:
            raise ErroreApi(HTTPStatus.NOT_FOUND, "Bozza non trovata")
        # il testo verificato è quello composto dal modello con i dati attuali; si applicano
        # la scheda della tipologia, quella del modello e quelle delle specificità scelte
        valutazione = await valuta(sessione, bozza, user)
        aggiorna_bozza(bozza, valutazione)
        schede = await schede_applicabili(
            sessione, bozza.tipologia_atto, bozza.modello.codice, valutazione.moduli_attivi()
        )
        verifica = await accoda(
            sessione, user, data_riferimento(bozza, oggi), schede, bozza_id=bozza.id
        )
    else:
        if not user.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN):
            raise ErroreApi(HTTPStatus.FORBIDDEN, "Operazione non consentita")
        atto = await sessione.get(AttoControllato, dati.atto_controllato_id)
        if atto is None:
            raise ErroreApi(HTTPStatus.NOT_FOUND, "Atto non trovato")
        schede = await schede_applicabili(
            sessione, atto.tipologia_atto, atto.modello, atto.moduli_json
        )
        verifica = await accoda(
            sessione, user, atto.data_adozione, schede, atto_controllato_id=atto.id
        )
        # senza testo (conversione fallita o non ancora fatta) si riparte dalla conversione
        da_convertire = atto.stato in ("IN_CONVERSIONE", "ERRORE_CONVERSIONE")
        atto.stato = "IN_CONVERSIONE" if da_convertire else "IN_ANALISI"
    await sessione.commit()
    await sessione.refresh(verifica)
    if dati.atto_controllato_id and da_convertire:
        await notifica(
            coda.CONVERSIONE,
            {
                "atto_id": atto.id,
                "verifica_id": verifica.id,
                "percorso": atto.file_percorso,
                "nome_file": atto.file_nome,
            },
        )
    else:
        await notifica(coda.VERIFICA, {"verifica_id": verifica.id})
    return out(VerificaOut, verifica), HTTPStatus.ACCEPTED


@bp.get("")
@autenticato()
async def elenco():
    filtro = parametri(FiltroVerifiche)
    if bool(filtro.bozza_id) == bool(filtro.atto_controllato_id):
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Indicare bozza_id oppure atto_controllato_id"
        )
    sessione = db()
    user = utente()
    query = select(Verifica).order_by(Verifica.created_at.desc())
    if filtro.bozza_id:
        bozza = await sessione.get(Bozza, filtro.bozza_id)
        if bozza is None or bozza.owner_id != user.id:
            raise ErroreApi(HTTPStatus.NOT_FOUND, "Bozza non trovata")
        query = query.where(Verifica.bozza_id == filtro.bozza_id)
    else:
        if not user.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN):
            raise ErroreApi(HTTPStatus.FORBIDDEN, "Operazione non consentita")
        query = query.where(Verifica.atto_controllato_id == filtro.atto_controllato_id)
    return out(VerificaOut, (await sessione.scalars(query)).all())


@bp.get("/<verifica_id>")
@autenticato()
async def dettaglio(verifica_id: str):
    sessione = db()
    verifica = await sessione.get(Verifica, verifica_id)
    if verifica is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Verifica non trovata")
    await _autorizza(sessione, verifica, utente())
    return out(VerificaOut, verifica)


class EsitoRevisione(BaseModel):
    elemento_id: str | None = None  # None per osservazioni generali
    titolo: str
    esito: str = Field(pattern="^(CONFORME|NON_CONFORME|NON_APPLICABILE|DUBBIO)$")
    nota: str | None = None


class RevisioneIn(BaseModel):
    esiti: list[EsitoRevisione]
    motivazione: str = Field(min_length=1)
    conclusa: bool = False


@bp.put("/<verifica_id>/revisione")
@controllore
async def revisione(verifica_id: str):
    """Esito finale del controllore: conferma o modifica la proposta automatica."""
    dati = corpo(RevisioneIn)
    sessione = db()
    verifica = await sessione.get(Verifica, verifica_id)
    if verifica is None or not verifica.atto_controllato_id:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Verifica non trovata")
    if verifica.stato != StatoVerifica.COMPLETATA:
        raise ErroreApi(HTTPStatus.CONFLICT, "La verifica automatica non è conclusa")
    atto = await sessione.get(AttoControllato, verifica.atto_controllato_id)
    if atto.stato == "CHIUSO":
        raise ErroreApi(HTTPStatus.CONFLICT, "Il controllo dell'atto è già chiuso")
    verifica.esito_finale = [e.model_dump() for e in dati.esiti]
    verifica.motivazione = dati.motivazione
    verifica.revisore_id = utente().id
    atto.stato = "CHIUSO" if dati.conclusa else "IN_REVISIONE"
    audit(sessione, utente(), "verifica", verifica.id, "REVISIONE", {"conclusa": dati.conclusa})
    await sessione.commit()
    await sessione.refresh(verifica)
    return out(VerificaOut, verifica)
