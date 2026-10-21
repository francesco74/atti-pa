"""Modulo Redazione: bozze personali di atti, compilate secondo un modello a 4 fasi.

Ogni utente vede solo le proprie bozze. La bozza conserva le risposte alle domande, i
valori dei campi e le personalizzazioni (capoversi facoltativi tolti o aggiunti, testi
riscritti); il testo dell'atto è composto dal modello a ogni salvataggio.
"""

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, func, select

from composizione import (
    aggiorna_bozza,
    carta_intestata,
    data_riferimento,
    documento_odt,
    documento_odt_con_omissis,
    valuta,
)
from deps import audit, db, impostazioni, redattore, risorse, utente
from documenti import DocumentiError
from web import ErroreApi, allegato, corpo, nessun_contenuto, parametri
from common.dati_personali import DatiPersonaliNonDisponibili, StatoDatiPersonali
from common.llm import LlmError, espandi_appunti
from common.models import AuditLog, Bozza, ModelloAtto
from common.normattiva import Urn
from common.normattiva.citazioni import citazione_riferimento
from common.odt import segnaposto_non_compilati
from common.verifica import verifica_riferimenti

bp = Blueprint("bozze", __name__, url_prefix="/api/v1/bozze")


class RiferimentoBozza(BaseModel):
    urn_atto: str
    articolo: str
    comma: str | None = None
    lettera: str | None = None
    citazione: str | None = None


class Personalizzazioni(BaseModel):
    esclusi: list[str] = []
    inclusi: list[str] = []
    testi: dict[str, str] = {}


class BozzaNuova(BaseModel):
    modello_id: str


class BozzaModifica(BaseModel):
    """Le chiavi presenti sostituiscono per intero quelle salvate."""

    risposte: dict[str, Any] | None = None
    valori: dict[str, Any] | None = None
    personalizzazioni: Personalizzazioni | None = None
    riferimenti: list[RiferimentoBozza] | None = None


class FiltroBozze(BaseModel):
    q: str | None = None


def _sintesi(b: Bozza) -> dict:
    return {
        "id": b.id,
        "oggetto": b.oggetto,
        "modello": b.modello.titolo,
        "provvedimento": b.modello.provvedimento,
        "tipologia_atto": b.tipologia_atto,
        "fasi_complete": b.fasi_complete,
        "fasi_totali": len(b.modello.definizione_json.get("fasi", [])),
        "data_adozione_prevista": b.data_adozione_prevista and b.data_adozione_prevista.isoformat(),
        "updated_at": b.updated_at and b.updated_at.isoformat(),
    }


async def _bozza_propria(sessione, bozza_id: str) -> Bozza:
    bozza = await sessione.get(Bozza, bozza_id)
    if bozza is None or bozza.owner_id != utente().id:
        # stessa risposta per inesistente e altrui: non si rivela l'esistenza di atti di altri
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Bozza non trovata")
    return bozza


async def _dettaglio(sessione, bozza: Bozza) -> dict:
    valutazione = await valuta(sessione, bozza, utente())
    m = bozza.modello
    return {
        **_sintesi(bozza),
        "modello": {
            "id": m.id,
            "codice": m.codice,
            "versione": m.versione,
            "titolo": m.titolo,
            "provvedimento": m.provvedimento,
            "formula_dispositivo": valutazione.m.d.formula_dispositivo,
        },
        "risposte": bozza.risposte_json or {},
        "valori": bozza.valori_json or {},
        "personalizzazioni": bozza.personalizzazioni_json or {},
        "riferimenti": bozza.riferimenti_json or [],
        "stato": valutazione.riepilogo(),
    }


def _riferimenti(dati: list[RiferimentoBozza]) -> list[dict]:
    risultato = []
    for r in dati:
        try:
            urn = Urn.parse(r.urn_atto).atto
        except ValueError as e:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
        risultato.append(
            {
                "urn_atto": urn,
                "articolo": r.articolo,
                "comma": r.comma,
                "lettera": r.lettera,
                "citazione": r.citazione
                or citazione_riferimento(urn, r.articolo, r.comma, r.lettera),
            }
        )
    return risultato


@bp.get("")
@redattore
async def elenco():
    q = parametri(FiltroBozze).q
    query = select(Bozza).where(Bozza.owner_id == utente().id).order_by(Bozza.updated_at.desc())
    if q:
        query = query.where(Bozza.oggetto.like(f"%{q}%"))
    return [_sintesi(b) for b in (await db().scalars(query)).unique().all()]


@bp.post("")
@redattore
async def crea():
    dati = corpo(BozzaNuova)
    sessione = db()
    modello = await sessione.get(ModelloAtto, dati.modello_id)
    if modello is None or not modello.attivo:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Modello di atto inesistente o non attivo")
    bozza = Bozza(
        owner_id=utente().id,
        modello_id=modello.id,
        modello=modello,
        tipologia_atto=modello.tipologia_atto,
        risposte_json={},
        valori_json={},
        personalizzazioni_json={},
        riferimenti_json=[],
    )
    aggiorna_bozza(bozza, await valuta(sessione, bozza, utente()))
    sessione.add(bozza)
    await sessione.flush()
    audit(sessione, utente(), "bozza", bozza.id, "CREATA", {"modello": modello.codice})
    await sessione.commit()
    await sessione.refresh(bozza)  # date scritte dal database
    return await _dettaglio(sessione, bozza), HTTPStatus.CREATED


@bp.get("/<bozza_id>")
@redattore
async def dettaglio(bozza_id: str):
    sessione = db()
    return await _dettaglio(sessione, await _bozza_propria(sessione, bozza_id))


@bp.put("/<bozza_id>")
@redattore
async def aggiorna(bozza_id: str):
    dati = corpo(BozzaModifica)
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    if dati.risposte is not None:
        bozza.risposte_json = dati.risposte
    if dati.valori is not None:
        bozza.valori_json = dati.valori
    if dati.personalizzazioni is not None:
        bozza.personalizzazioni_json = dati.personalizzazioni.model_dump()
        # un capoverso riscritto ma tornato uguale al testo standard non è più personalizzato
        valutazione = await valuta(sessione, bozza, utente())
        bozza.personalizzazioni_json = {
            **bozza.personalizzazioni_json,
            "testi": valutazione.testi_effettivi(),
        }
    if dati.riferimenti is not None:
        bozza.riferimenti_json = _riferimenti(dati.riferimenti)
    aggiorna_bozza(bozza, await valuta(sessione, bozza, utente()))
    # il salvataggio è automatico mentre si scrive: nel registro al massimo una modifica
    # ogni 5 minuti per bozza
    ultima = await sessione.scalar(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.entita == "bozza",
            AuditLog.entita_id == bozza.id,
            AuditLog.azione == "MODIFICATA",
        )
    )
    adesso = await sessione.scalar(select(func.now(type_=DateTime)))
    if ultima is None or adesso is None or (adesso - ultima) > timedelta(minutes=5):
        audit(sessione, utente(), "bozza", bozza.id, "MODIFICATA")
    await sessione.commit()
    await sessione.refresh(bozza)
    return await _dettaglio(sessione, bozza)


@bp.delete("/<bozza_id>")
@redattore
async def elimina(bozza_id: str):
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    await sessione.delete(bozza)
    audit(sessione, utente(), "bozza", bozza_id, "ELIMINATA")
    await sessione.commit()
    return nessun_contenuto()


@bp.get("/<bozza_id>/controllo-rapido")
@redattore
async def controllo_rapido(bozza_id: str):
    """Controlli immediati, senza LLM: campi obbligatori, segnaposto, riferimenti normativi."""
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    valutazione = await valuta(sessione, bozza, utente())
    testo = valutazione.testo()
    giorno = data_riferimento(bozza, datetime.now(impostazioni().tz).date())
    riepilogo = valutazione.riepilogo()
    mancanti = [
        f"Fase {f['numero']} - {c['etichetta']}"
        for f in riepilogo["fasi"]
        for c in f["campi"]
        if c["mancante"]
    ]
    mancanti += [f"Domande iniziali - {q['testo']}" for q in riepilogo["domande"] if q["mancante"]]
    return {
        "data_riferimento": giorno,
        "campi_obbligatori_mancanti": mancanti,
        "blocchi": riepilogo["blocchi"],
        "segnaposto": segnaposto_non_compilati(testo),
        "riferimenti": await verifica_riferimenti(sessione, risorse().normattiva, testo, giorno),
        # i dati personali li rileva il modello: nella verifica completa, non qui
        "dati_personali": [],
        "dati_personali_stato": StatoDatiPersonali.NON_VALUTATI,
    }


MIME = {
    "odt": "application/vnd.oasis.opendocument.text",
    "pdf": "application/pdf",
    "pdfa": "application/pdf",
}


class DocumentoQuery(BaseModel):
    formato: Literal["odt", "pdf", "pdfa"] = "odt"
    omissis: bool = False


@bp.get("/<bozza_id>/documento")
@redattore
async def documento(bozza_id: str):
    """Documento sulla carta intestata dell'ente; `omissis=true` oscura i dati personali."""
    q = parametri(DocumentoQuery)
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    valutazione = await valuta(sessione, bozza, utente())
    carta = await carta_intestata(sessione)
    try:
        odt = (
            await documento_odt_con_omissis(
                carta, valutazione, risorse().llm if impostazioni().llm_dati_personali else None
            )
            if q.omissis
            else documento_odt(carta, valutazione)
        )
    except DatiPersonaliNonDisponibili as e:
        # mai un documento "con omissis" con i dati in chiaro
        raise ErroreApi(
            HTTPStatus.SERVICE_UNAVAILABLE,
            f"Documento con omissis non disponibile: rilevamento dei dati personali non "
            f"riuscito ({e}). Riprovare più tardi.",
        ) from e
    contenuto = odt
    if q.formato != "odt":
        try:
            contenuto = await risorse().documenti.converti(odt, "atto.odt", q.formato)
        except DocumentiError as e:
            raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    estensione = "odt" if q.formato == "odt" else "pdf"
    nome = f"atto{'-omissis' if q.omissis else ''}.{estensione}"
    audit(
        sessione,
        utente(),
        "bozza",
        bozza.id,
        "DOCUMENTO",
        {"formato": q.formato, "omissis": q.omissis},
    )
    await sessione.commit()
    return allegato(contenuto, MIME[q.formato], nome)


class EspandiIn(BaseModel):
    sezione: str = Field(min_length=1, max_length=100)
    appunti: str = Field(min_length=3, max_length=5000)
    oggetto: str = ""


@bp.post("/espandi")
@redattore
async def espandi():
    """Riscrive appunti sintetici in linguaggio amministrativo (LLM)."""
    dati = corpo(EspandiIn)
    llm = risorse().llm
    if llm is None:
        raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, "Modello linguistico non configurato")
    try:
        testo = await espandi_appunti(llm, dati.sezione, dati.appunti, dati.oggetto)
    except LlmError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    return {"testo": testo}
