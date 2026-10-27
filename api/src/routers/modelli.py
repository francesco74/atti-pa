"""Modelli di atto e dati dell'ente.

I modelli arrivano con i pacchetti (routers/pacchetti.py) e si modificano nell'app; qui si
consultano. I "Dati
dell'ente" sono i campi con fonte "ente" dei modelli attivi (delibere di programmazione,
luogo, sezione del TAR...): li compila l'amministratore e valgono per tutti gli atti.
La carta intestata è l'ODT con i segnaposto {{intestazione}}, {{preambolo}},
{{dispositivo}} e {{chiusura}}.
"""

from datetime import datetime
from http import HTTPStatus
from typing import Any

from flask import Blueprint
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import undefer

from composizione import SEGNAPOSTO_CARTA, impostazioni_ente, modello_compilato
from deps import amministratore_ente, audit, autenticato, db, ente_id, impostazioni, solo_admin, utente
from schemas import Schema
from web import ErroreApi, allegato, corpo, file_caricato, nessun_contenuto, out
from common.models import Ente, ModelloAtto, TipologiaAtto
from common.modelli import campi_ente
from common.odt import OdtNonValido, estrai_segnaposto

bp = Blueprint("modelli", __name__, url_prefix="/api/v1")

MIME_ODT = "application/vnd.oasis.opendocument.text"


class ModelloOut(Schema):
    id: str
    codice: str
    versione: int
    titolo: str
    provvedimento: str
    tipologia_atto: str
    descrizione: str | None
    attivo: bool
    pacchetto: str | None  # pacchetto standard da cui deriva
    impronta: str | None
    impronta_base: str | None
    created_at: datetime | None


async def _attivi(sessione) -> list[ModelloAtto]:
    return list(
        (
            await sessione.scalars(
                select(ModelloAtto)
                .where(ModelloAtto.ente_id == ente_id(), ModelloAtto.attivo.is_(True))
                .order_by(ModelloAtto.provvedimento, ModelloAtto.titolo)
            )
        ).all()
    )


@bp.get("/modelli")
@autenticato()
async def elenco():
    """Modelli attivi, per la scelta "Che atto vuoi redigere?"."""
    sessione = db()
    tipologie = {
        t.codice: t.descrizione for t in (await sessione.scalars(select(TipologiaAtto))).all()
    }
    return [
        {
            **ModelloOut.model_validate(m).model_dump(mode="json"),
            "tipologia_descrizione": tipologie.get(m.tipologia_atto),
            # specificità componibili nel modello (moduli di regole): servono anche nel
            # controllo per scegliere le schede da applicare a un atto
            "specificita": (m.definizione_json or {}).get("regole", []),
        }
        for m in await _attivi(sessione)
    ]


@bp.get("/modelli/tutti")
@solo_admin
async def tutti():
    righe = await db().scalars(
        select(ModelloAtto)
        .where(ModelloAtto.ente_id == ente_id())
        .order_by(ModelloAtto.codice, ModelloAtto.versione.desc())
    )
    return out(ModelloOut, righe.all())


@bp.get("/modelli/<modello_id>/sorgente")
@solo_admin
async def sorgente(modello_id: str):
    m = await db().scalar(
        select(ModelloAtto)
        .where(ModelloAtto.id == modello_id, ModelloAtto.ente_id == ente_id())
        .options(undefer(ModelloAtto.sorgente))
    )
    if m is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Modello non trovato")
    return allegato(m.sorgente.encode(), "application/yaml", f"{m.codice}_v{m.versione}.yaml")


# --- Dati dell'ente --------------------------------------------------------------------


class DatiEnteIn(BaseModel):
    valori: dict[str, Any]


async def _stato_ente(sessione) -> dict:
    ente = await impostazioni_ente(sessione, ente_id())
    campi = campi_ente([modello_compilato(m) for m in await _attivi(sessione)])
    return {
        "campi": list(campi.values()),
        "valori": ente.dati_json or {},
        "carta_intestata": ente.carta_intestata_nome,
        "segnaposto_carta": list(SEGNAPOSTO_CARTA),
    }


@bp.get("/ente")
@autenticato()
async def dati_ente():
    return await _stato_ente(db())


@bp.put("/ente")
@amministratore_ente
async def aggiorna_dati_ente():
    dati = corpo(DatiEnteIn)
    sessione = db()
    ente = await impostazioni_ente(sessione, ente_id())
    ente.dati_json = {
        k: (v.strip() if isinstance(v, str) else v)
        for k, v in dati.valori.items()
        if v not in (None, "")
    }
    audit(sessione, utente(), "ente", ente.id, "DATI_AGGIORNATI", {"campi": sorted(ente.dati_json)})
    await sessione.commit()
    return await _stato_ente(sessione)


@bp.post("/ente/carta-intestata")
@amministratore_ente
async def carica_carta():
    """Carta intestata (.odt) con i segnaposto delle quattro parti dell'atto."""
    file = file_caricato()
    limite = impostazioni().upload_max_mb * 1024 * 1024
    contenuto = file.read(limite + 1)
    if len(contenuto) > limite:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
    try:
        presenti = set(estrai_segnaposto(contenuto))
    except OdtNonValido as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    mancanti = [s for s in SEGNAPOSTO_CARTA if s not in presenti]
    if mancanti:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Nella carta intestata mancano i segnaposto: "
            + ", ".join(f"{{{{{s}}}}}" for s in mancanti),
        )
    sessione = db()
    ente = await impostazioni_ente(sessione, ente_id())
    ente.carta_intestata = contenuto
    ente.carta_intestata_nome = file.filename or "carta_intestata.odt"
    audit(sessione, utente(), "ente", ente.id, "CARTA_INTESTATA", {"file": ente.carta_intestata_nome})
    await sessione.commit()
    return await _stato_ente(sessione), HTTPStatus.CREATED


@bp.get("/ente/carta-intestata")
@autenticato()
async def scarica_carta():
    ente = await db().scalar(
        select(Ente).where(Ente.id == ente_id()).options(undefer(Ente.carta_intestata))
    )
    if ente is None or not ente.carta_intestata:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Carta intestata non caricata")
    return allegato(ente.carta_intestata, MIME_ODT, ente.carta_intestata_nome or "carta.odt")


@bp.delete("/ente/carta-intestata")
@amministratore_ente
async def elimina_carta():
    sessione = db()
    ente = await impostazioni_ente(sessione, ente_id())
    ente.carta_intestata = None
    ente.carta_intestata_nome = None
    audit(sessione, utente(), "ente", ente.id, "CARTA_INTESTATA_RIMOSSA")
    await sessione.commit()
    return nessun_contenuto()
