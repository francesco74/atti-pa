"""Modulo Controllo: un controllo è un atto con il suo audit.

Ogni controllo ha un titolo e contiene un solo atto, verificato con le norme vigenti alla
sua data di adozione. La scelta degli atti da controllare (sorteggio) avviene fuori dal
programma. L'audit è la verifica automatica (riferimenti, coerenza, checklist) più la
revisione del controllore (`PUT /api/v1/verifiche/<id>/revisione`).

Nel database un controllo è una riga di `controlli_sessioni` con un solo atto collegato.
"""

from datetime import date, datetime
from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import undefer

import asyncio
import logging

from deps import archivia_caricato, audit, controllore, impostazioni, notifica, risorse, utente
from documenti import DocumentiError
from deps import db as sessione_db
from routers.verifiche import accoda, checklist_per_tipologia
from schemas import Schema
from web import ErroreApi, allegato, file_caricato, modulo, nessun_contenuto
from common import archivio, coda
from common.models import AttoControllato, SessioneControllo, TipologiaAtto, Verifica

log = logging.getLogger("atti_api.controllo")

bp = Blueprint("controllo", __name__, url_prefix="/api/v1/controllo")


class AttoOut(Schema):
    id: str
    sessione_id: str
    numero_registro: str | None
    data_adozione: date
    tipologia_atto: str | None
    oggetto: str | None
    file_nome: str
    file_sha256: str | None
    file_dimensione: int | None
    stato: str
    created_at: datetime | None


class ControlloOut(BaseModel):
    id: str
    titolo: str
    created_at: datetime | None
    atto: AttoOut | None


class ControlloIn(BaseModel):
    titolo: str = Field(min_length=3, max_length=255)
    data_adozione: date  # le norme sono verificate al testo vigente in questa data
    tipologia_atto: str | None = None  # sceglie la checklist
    numero_registro: str | None = None
    oggetto: str | None = None


async def _atto_del_controllo(db, controllo_id: str) -> AttoControllato | None:
    return await db.scalar(
        select(AttoControllato).where(AttoControllato.sessione_id == controllo_id).limit(1)
    )


def _out(controllo: SessioneControllo, atto: AttoControllato | None) -> dict:
    return ControlloOut(
        id=controllo.id,
        titolo=controllo.titolo,
        created_at=controllo.created_at,
        atto=AttoOut.model_validate(atto) if atto else None,
    ).model_dump(mode="json")


@bp.get("/controlli")
@controllore
async def elenco_controlli():
    db = sessione_db()
    righe = await db.execute(
        select(SessioneControllo, AttoControllato)
        .outerjoin(AttoControllato, AttoControllato.sessione_id == SessioneControllo.id)
        .order_by(SessioneControllo.created_at.desc())
    )
    return [_out(controllo, atto) for controllo, atto in righe.all()]


@bp.post("/controlli")
@controllore
async def crea_controllo():
    """Nuovo controllo: titolo e atto (PDF, ODT, DOCX o DOC).

    Il file va nell'archivio e il converter lo trasforma in Markdown (coda "conversione");
    poi il worker esegue la verifica. La risposta non attende né l'una né l'altra.
    """
    dati = modulo(ControlloIn)
    file = file_caricato()
    db, user, settings = sessione_db(), utente(), impostazioni()
    if dati.tipologia_atto and await db.get(TipologiaAtto, dati.tipologia_atto) is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")
    nome, mime, archiviato = await archivia_caricato(file)

    try:
        controllo = SessioneControllo(titolo=dati.titolo, creata_da=user.id)
        db.add(controllo)
        await db.flush()
        atto = AttoControllato(
            sessione_id=controllo.id,
            numero_registro=dati.numero_registro,
            data_adozione=dati.data_adozione,
            tipologia_atto=dati.tipologia_atto,
            oggetto=dati.oggetto,
            file_nome=nome,
            file_mime=mime,
            file_percorso=archiviato.percorso,
            file_sha256=archiviato.sha256,
            file_dimensione=archiviato.dimensione,
            stato="IN_CONVERSIONE",
        )
        db.add(atto)
        await db.flush()
        audit(
            db, user, "controllo", controllo.id, "CREATO",
            {"atto": atto.id, "file": nome, "sha256": archiviato.sha256},
        )  # fmt: skip
        checklist_id = await checklist_per_tipologia(db, dati.tipologia_atto)
        verifica = await accoda(
            db, user, dati.data_adozione, checklist_id, atto_controllato_id=atto.id
        )
        await db.commit()
    except Exception:
        archivio.elimina(settings.archivio_dir, archiviato.percorso)  # niente file orfani
        raise
    await db.refresh(controllo)
    await db.refresh(atto)
    await notifica(
        coda.CONVERSIONE,
        {
            "atto_id": atto.id,
            "verifica_id": verifica.id,
            "percorso": atto.file_percorso,
            "nome_file": nome,
        },
    )
    return _out(controllo, atto), HTTPStatus.CREATED


@bp.get("/controlli/<controllo_id>")
@controllore
async def dettaglio_controllo(controllo_id: str):
    db = sessione_db()
    controllo = await db.get(SessioneControllo, controllo_id)
    if controllo is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Controllo non trovato")
    return _out(controllo, await _atto_del_controllo(db, controllo_id))


@bp.delete("/controlli/<controllo_id>")
@controllore
async def elimina_controllo(controllo_id: str):
    db, user = sessione_db(), utente()
    controllo = await db.get(SessioneControllo, controllo_id)
    if controllo is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Controllo non trovato")
    atto = await _atto_del_controllo(db, controllo_id)
    if atto is not None:
        if atto.stato == "CHIUSO":
            raise ErroreApi(HTTPStatus.CONFLICT, "Un controllo concluso non si elimina")
        await db.execute(delete(Verifica).where(Verifica.atto_controllato_id == atto.id))
        await db.delete(atto)
    await db.delete(controllo)
    audit(db, user, "controllo", controllo_id, "ELIMINATO")
    await db.commit()
    if atto is not None and atto.file_percorso:
        archivio.elimina(impostazioni().archivio_dir, atto.file_percorso)
        archivio.elimina(impostazioni().archivio_dir, archivio.percorso_anteprima(atto.id))
    return nessun_contenuto()


# --- Atto del controllo ------------------------------------------------------------------


async def _atto(db, atto_id: str) -> AttoControllato:
    atto = await db.get(AttoControllato, atto_id)
    if atto is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Atto non trovato")
    return atto


@bp.get("/atti/<atto_id>")
@controllore
async def dettaglio_atto(atto_id: str):
    return AttoOut.model_validate(await _atto(sessione_db(), atto_id)).model_dump(mode="json")


@bp.get("/atti/<atto_id>/testo")
@controllore
async def testo_atto(atto_id: str):
    atto = await sessione_db().scalar(
        select(AttoControllato)
        .where(AttoControllato.id == atto_id)
        .options(undefer(AttoControllato.contenuto_testo))
    )
    if atto is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Atto non trovato")
    return {"testo": atto.contenuto_testo or ""}


@bp.get("/atti/<atto_id>/file")
@controllore
async def file_atto(atto_id: str):
    atto = await _atto(sessione_db(), atto_id)
    if not atto.file_percorso:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "File originale non disponibile")
    try:
        contenuto = await asyncio.to_thread(
            archivio.leggi, impostazioni().archivio_dir, atto.file_percorso
        )
    except archivio.FileNonInArchivio as e:
        log.warning("Atto %s: %s", atto.id, e)
        raise ErroreApi(HTTPStatus.NOT_FOUND, "File originale non presente nell'archivio") from e
    return allegato(contenuto, atto.file_mime, atto.file_nome)


@bp.get("/atti/<atto_id>/anteprima")
@controllore
async def anteprima_atto(atto_id: str):
    """L'atto originale in PDF, da mostrare nel browser.

    Un PDF è restituito così com'è; ODT, DOC e DOCX sono convertiti da LibreOffice (servizio
    converter) alla prima richiesta e la copia PDF resta nell'archivio.
    """
    atto = await _atto(sessione_db(), atto_id)
    cartella = impostazioni().archivio_dir
    nome_pdf = f"{atto.file_nome.rsplit('.', 1)[0]}.pdf"
    if not atto.file_percorso:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "File originale non disponibile")
    try:
        if atto.file_mime == "application/pdf":
            pdf = await asyncio.to_thread(archivio.leggi, cartella, atto.file_percorso)
            return allegato(pdf, "application/pdf", atto.file_nome, in_linea=True)
        percorso = archivio.percorso_anteprima(atto.id)
        try:
            pdf = await asyncio.to_thread(archivio.leggi, cartella, percorso)
        except archivio.FileNonInArchivio:
            originale = await asyncio.to_thread(archivio.leggi, cartella, atto.file_percorso)
            pdf = await risorse().documenti.converti(originale, atto.file_nome, "pdf")
            await asyncio.to_thread(archivio.scrivi, cartella, percorso, pdf)
    except archivio.FileNonInArchivio as e:
        log.warning("Atto %s: %s", atto.id, e)
        raise ErroreApi(HTTPStatus.NOT_FOUND, "File originale non presente nell'archivio") from e
    except DocumentiError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, f"Anteprima non disponibile: {e}") from e
    return allegato(pdf, "application/pdf", nome_pdf, in_linea=True)
