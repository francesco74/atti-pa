"""Modulo assistente: chat con l'LLM configurato per il lavoro quotidiano degli utenti (email,
riassunti, riformulazioni). Le conversazioni non si salvano: l'app invia a ogni richiesta i
messaggi precedenti. Non legge atti né norme: per quello c'è il chatbot RAG (progetto esterno).

Documenti allegati: li converte in testo il RAG dell'ente (common/rag.py), con un lavoro
asincrono che l'app segue finché non è concluso; il testo entra poi nel messaggio. Il file non
resta in atti-pa e la chiave del RAG non arriva mai all'app.
"""

import re
from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field

from deps import autenticato, ente, risorse
from web import ErroreApi, corpo, file_caricato
from common.llm import PROVIDER_ESTERNI, LlmError
from common.models import Modulo
from common.rag import FORMATI_CONVERSIONE, RagClient, RagError

bp = Blueprint("assistente", __name__, url_prefix="/api/v1/assistente")

utente_assistente = autenticato(modulo=Modulo.ASSISTENTE)

MAX_MESSAGGI = 100
JOB_ID = re.compile(r"^[0-9a-f]{32}$")


class Messaggio(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ConversazioneIn(BaseModel):
    messaggi: list[Messaggio] = Field(min_length=1)


def _llm():
    llm = risorse().llm
    if llm is None:
        raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, "Modello linguistico non configurato")
    return llm


def _max_caratteri() -> int:
    return risorse().settings.assistente_max_caratteri


def _numero(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _rag() -> RagClient | None:
    try:
        return RagClient.dell_ente(risorse().rag_http, ente().rag_json, risorse().settings.chiave_cifratura)
    except RagError:
        return None  # chiave non decifrabile: gli allegati non si offrono


def _rag_obbligatorio() -> RagClient:
    try:
        client = RagClient.dell_ente(risorse().rag_http, ente().rag_json, risorse().settings.chiave_cifratura)
    except RagError as e:
        raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, str(e)) from e
    if client is None:
        raise ErroreApi(HTTPStatus.CONFLICT, "Allegati non disponibili: il collegamento al RAG non è configurato")
    return client


@bp.get("")
@utente_assistente
async def informazioni():
    """Se il modello è esterno (l'app apre la chat con un avviso sui dati personali) e i formati
    dei documenti che si possono allegare (nessuno senza collegamento al RAG)."""
    return {
        "llm_esterno": _llm().provider in PROVIDER_ESTERNI,
        "formati_allegati": list(FORMATI_CONVERSIONE) if _rag() else [],
        "max_mb_allegato": risorse().settings.upload_max_mb,
        "max_caratteri": _max_caratteri(),
    }


@bp.post("/messaggi")
@utente_assistente
async def messaggio():
    """Risposta del modello alla conversazione, che termina con il messaggio dell'utente."""
    dati = corpo(ConversazioneIn)
    if dati.messaggi[-1].role != "user":
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "L'ultimo messaggio deve essere dell'utente")
    if len(dati.messaggi) > MAX_MESSAGGI or sum(len(m.content) for m in dati.messaggi) > _max_caratteri():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Conversazione troppo lunga: iniziane una nuova")
    try:
        testo = (await _llm().conversa([m.model_dump() for m in dati.messaggi])).strip()
    except LlmError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    if not testo:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, "Il modello non ha restituito alcuna risposta")
    return {"testo": testo}


@bp.post("/allegati")
@utente_assistente
async def allega():
    """Avvia la conversione in testo di un documento: restituisce il lavoro da seguire."""
    client = _rag_obbligatorio()
    file = file_caricato()
    nome = file.filename or "documento"
    estensione = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if estensione not in FORMATI_CONVERSIONE:
        raise ErroreApi(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            f"Formato non ammesso: si possono allegare {', '.join(FORMATI_CONVERSIONE)}",
        )
    try:
        job_id = await client.avvia_conversione(file.read(), nome)
    except RagError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    return {"job_id": job_id, "nome": nome}, HTTPStatus.ACCEPTED


@bp.get("/allegati/<job_id>")
@utente_assistente
async def stato_allegato(job_id: str):
    """Stato della conversione (queued, running, completed, failed); a conversione conclusa,
    il testo del documento, se rientra nel limite della conversazione. Il RAG consegna l'esito
    una volta sola: se la risposta si è persa, il lavoro non c'è più e va riallegato."""
    if not JOB_ID.match(job_id):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Allegato non trovato")
    try:
        r = await _rag_obbligatorio().conversione(job_id)
    except RagError as e:
        if e.stato_http == 404:
            return {
                "stato": "failed",
                "errore": "Il risultato della conversione non è più disponibile: allega di nuovo il documento",
            }
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    stato = r.get("status")
    if stato == "failed":
        return {"stato": "failed", "errore": r.get("error") or "Conversione non riuscita"}
    if stato != "completed":
        return {"stato": stato if stato in ("queued", "running") else "queued"}
    testo = (r.get("content") or "").strip()
    if not testo:
        return {"stato": "failed", "errore": "Il documento non contiene testo leggibile"}
    if len(testo) > _max_caratteri():
        return {
            "stato": "failed",
            "errore": f"Il documento ha {_numero(len(testo))} caratteri: supera il limite di "
            f"{_numero(_max_caratteri())} che il modello può leggere in una conversazione",
        }
    return {"stato": "completed", "testo": testo}
