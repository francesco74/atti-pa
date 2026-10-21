"""Pacchetti di modelli, specificità e checklist (common/pacchetti.py): il database comanda.

L'amministratore carica un pacchetto zip: l'API lo controlla e analizza, per ogni oggetto,
cosa cambia rispetto all'ente (confronto a tre vie con lo standard di riferimento). Poi lo
importa con le decisioni prese (applica, mantieni, disattiva). L'esportazione produce un
pacchetto con tutto ciò che è attivo nell'ente.
"""

from datetime import datetime
from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from deps import audit, db, impostazioni, solo_admin, utente
from schemas import Schema
from web import ErroreApi, allegato, corpo, file_caricato, nessun_contenuto, out
from common.models import PacchettoImportato
from common.pacchetti import (
    PacchettoNonValido,
    analizza,
    da_zip,
    esporta,
    importa,
    in_zip,
    leggi_pacchetto,
)

bp = Blueprint("pacchetti", __name__, url_prefix="/api/v1/pacchetti")


class PacchettoOut(Schema):
    id: str
    nome: str
    versione: str
    descrizione: str | None
    stato: str
    analisi_json: list | None
    resoconto_json: dict | None
    created_at: datetime | None
    importato_il: datetime | None


class DecisioniIn(BaseModel):
    decisioni: dict[str, str] = {}  # {"modello:CODICE": "applica" | "mantieni" | "disattiva"}


@bp.get("")
@solo_admin
async def elenco():
    righe = await db().scalars(
        select(PacchettoImportato).order_by(PacchettoImportato.created_at.desc())
    )
    return out(PacchettoOut, righe.all())


@bp.post("")
@solo_admin
async def carica():
    """Carica e analizza un pacchetto: non cambia ancora nulla."""
    file = file_caricato()
    limite = impostazioni().upload_max_mb * 1024 * 1024
    contenuto = file.read(limite + 1)
    if len(contenuto) > limite:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
    try:
        pacchetto = leggi_pacchetto(da_zip(contenuto))
    except PacchettoNonValido as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    sessione = db()
    voci = await analizza(sessione, pacchetto)
    riga = PacchettoImportato(
        nome=pacchetto.manifesto.nome,
        versione=pacchetto.manifesto.versione,
        descrizione=pacchetto.manifesto.descrizione,
        stato="ANALIZZATO",
        contenuto=contenuto,
        analisi_json=[v.come_dict() for v in voci],
        caricato_da=utente().id,
    )
    sessione.add(riga)
    await sessione.flush()
    audit(sessione, utente(), "pacchetto", riga.id, "ANALIZZATO", {"pacchetto": riga.nome})
    await sessione.commit()
    await sessione.refresh(riga)
    return out(PacchettoOut, riga), HTTPStatus.CREATED


@bp.post("/<pacchetto_id>/importa")
@solo_admin
async def importa_pacchetto(pacchetto_id: str):
    """Importa il pacchetto analizzato con le decisioni dell'amministratore. L'analisi si
    ripete al momento dell'importazione: vale lo stato attuale del database."""
    dati = corpo(DecisioniIn)
    sessione = db()
    riga = await sessione.scalar(
        select(PacchettoImportato)
        .where(PacchettoImportato.id == pacchetto_id)
        .options(undefer(PacchettoImportato.contenuto))
    )
    if riga is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Pacchetto non trovato")
    if riga.stato != "ANALIZZATO":
        raise ErroreApi(HTTPStatus.CONFLICT, "Il pacchetto è già stato importato o annullato")
    try:
        pacchetto = leggi_pacchetto(da_zip(riga.contenuto))
    except PacchettoNonValido as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    resoconto = await importa(sessione, pacchetto, dati.decisioni, utente().id)
    riga.stato = "IMPORTATO"
    riga.resoconto_json = resoconto.come_dict()
    riga.importato_il = func.now()
    riga.contenuto = None  # il contenuto resta negli oggetti importati
    audit(
        sessione, utente(), "pacchetto", riga.id, "IMPORTATO",
        {"pacchetto": f"{riga.nome} {riga.versione}", "applicati": resoconto.applicati},
    )  # fmt: skip
    await sessione.commit()
    await sessione.refresh(riga)
    return out(PacchettoOut, riga)


@bp.delete("/<pacchetto_id>")
@solo_admin
async def annulla(pacchetto_id: str):
    sessione = db()
    riga = await sessione.get(PacchettoImportato, pacchetto_id)
    if riga is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Pacchetto non trovato")
    if riga.stato == "ANALIZZATO":
        riga.stato = "ANNULLATO"
        riga.contenuto = None
        await sessione.commit()
    return nessun_contenuto()


@bp.get("/esporta")
@solo_admin
async def esporta_configurazione():
    """Tutti i modelli, le specificità e le checklist attivi, come pacchetto zip."""
    oggi = datetime.now(impostazioni().tz)
    file = await esporta(db(), "Configurazione dell'ente", oggi.strftime("%Y-%m-%d.%H%M"))
    nome = f"atti-pa-configurazione-{oggi:%Y%m%d-%H%M}.zip"
    return allegato(in_zip(file), "application/zip", nome)
