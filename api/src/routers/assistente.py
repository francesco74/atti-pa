"""Modulo assistente: chat con l'LLM configurato per il lavoro quotidiano degli utenti (email,
riassunti, riformulazioni). Le conversazioni non si salvano: l'app invia a ogni richiesta i
messaggi precedenti. Non legge atti né norme: per quello c'è il chatbot RAG (progetto esterno).

Documenti della conversazione (progettazione/assistente_documenti.md): l'utente li carica in
una sessione temporanea del RAG dell'ente, che li converte, li indicizza e ne cerca i passaggi.
A ogni domanda sui documenti selezionati il RAG restituisce i passaggi pertinenti e l'LLM
risponde solo da quelli, citandoli: nessun documento entra intero nel prompt, quindi si
lavora anche su leggi lunghe. atti-pa fa da tramite: la chiave del RAG non arriva all'app.

Azioni (Riassumi, Confronta, Estrai): leggono i documenti per intero, a blocchi, con decine di
chiamate all'LLM; le esegue il worker (coda "assistente", tabella assistente_lavori) e l'app
ne segue l'avanzamento. Il risultato diventa un messaggio dell'assistente nella conversazione.

La sessione non ha tabelle: l'app riceve un token (id della sessione del RAG con una firma
che lo lega a ente e utente) e lo rimanda nell'intestazione X-Assistente-Sessione. La sessione
si perde ricaricando la pagina o con "Nuova conversazione", e nel RAG scade da sola.
"""

import hashlib
import hmac
import re
from http import HTTPStatus
from typing import Literal

from flask import Blueprint, request
from pydantic import BaseModel, Field
from sqlalchemy.orm import undefer

from deps import autenticato, db, ente, ente_id, notifica, risorse, utente
from web import ErroreApi, corpo, file_caricato
from common import coda
from common.assistente_azioni import CONFRONTO, ESTRAZIONE, RIASSUNTO
from common.llm import PROVIDER_ESTERNI, LlmError, testo_prompt
from common.models import AssistenteLavoro, Modulo, StatoVerifica
from common.rag import FORMATI_CONVERSIONE, RagClient, RagError

bp = Blueprint("assistente", __name__, url_prefix="/api/v1/assistente")

utente_assistente = autenticato(modulo=Modulo.ASSISTENTE)

MAX_MESSAGGI = 100
ID_RAG = re.compile(r"^[0-9a-f]{32}$")
INTESTAZIONE_SESSIONE = "X-Assistente-Sessione"
# Una domanda breve ("e la scadenza?") da sola cerca male: si cerca insieme alla precedente
DOMANDA_BREVE = 80
# Stati del documento nel RAG -> stati dell'API
STATI = {"queued": "in_coda", "converting": "conversione", "indexing": "indicizzazione",
         "ready": "pronto", "failed": "errore"}  # fmt: skip


class Messaggio(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ConversazioneIn(BaseModel):
    messaggi: list[Messaggio] = Field(min_length=1)
    # Documenti della sessione su cui rispondere; vuoto = conversazione libera
    documenti: list[str] = Field(default_factory=list, max_length=20)


def _llm():
    llm = risorse().llm
    if llm is None:
        raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, "Modello linguistico non configurato")
    return llm


def _max_caratteri() -> int:
    return risorse().settings.assistente_max_caratteri


def _rag() -> RagClient | None:
    try:
        return RagClient.dell_ente(risorse().rag_http, ente().rag_json, risorse().settings.chiave_cifratura)
    except RagError:
        return None  # chiave non decifrabile: i documenti non si offrono


def _rag_obbligatorio() -> RagClient:
    try:
        client = RagClient.dell_ente(risorse().rag_http, ente().rag_json, risorse().settings.chiave_cifratura)
    except RagError as e:
        raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, str(e)) from e
    if client is None:
        raise ErroreApi(HTTPStatus.CONFLICT, "Documenti non disponibili: il collegamento al RAG non è configurato")
    return client


def _errore_rag(e: RagError) -> ErroreApi:
    if e.stato_http == 404:
        return ErroreApi(HTTPStatus.NOT_FOUND, "La sessione dei documenti è scaduta: caricali di nuovo")
    if e.stato_http in (409, 413, 415):
        return ErroreApi(e.stato_http, str(e))
    return ErroreApi(HTTPStatus.BAD_GATEWAY, str(e))


# --- Token della sessione --------------------------------------------------------------


def _firma(session_id: str) -> str:
    chiave = ("assistente-sessione:" + risorse().settings.jwt_secret).encode()
    dati = f"{session_id}:{ente_id()}:{utente().id}".encode()
    return hmac.new(chiave, dati, hashlib.sha256).hexdigest()[:32]


def _token(session_id: str) -> str:
    return f"{session_id}.{_firma(session_id)}"


def _sessione() -> str:
    """Id della sessione del RAG dal token dell'intestazione; 404 se manca o non è di questo
    utente (un token copiato da un altro utente o ente non vale)."""
    token = request.headers.get(INTESTAZIONE_SESSIONE, "")
    session_id, _, firma = token.partition(".")
    if not ID_RAG.match(session_id) or not hmac.compare_digest(firma, _firma(session_id)):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Sessione dei documenti non trovata")
    return session_id


def _owner() -> str:
    """Impronta di ente e utente per il RAG, che la conserva senza interpretarla."""
    return hashlib.sha256(f"{ente_id()}:{utente().id}".encode()).hexdigest()[:32]


def _documento(d: dict) -> dict:
    vista = {"id": d["doc_id"], "nome": d["file_name"], "stato": STATI.get(d.get("status"), "in_coda")}
    if d.get("tokens") is not None:
        vista["token"] = d["tokens"]
    if d.get("sections") is not None:
        vista["parti"] = d["sections"]
    if d.get("error"):
        vista["errore"] = d["error"]
    return vista


def _limiti(limits: dict) -> dict:
    return {"max_documenti": limits.get("max_documents"), "max_token": limits.get("max_tokens")}


# --- Rotte -------------------------------------------------------------------------------


@bp.get("")
@utente_assistente
async def informazioni():
    """Se il modello è esterno (l'app apre la chat con un avviso sui dati personali) e i formati
    dei documenti che si possono caricare (nessuno senza collegamento al RAG)."""
    return {
        "llm_esterno": _llm().provider in PROVIDER_ESTERNI,
        "formati_documenti": list(FORMATI_CONVERSIONE) if _rag() else [],
        "max_mb_documento": risorse().settings.upload_max_mb,
        "max_caratteri": _max_caratteri(),
    }


@bp.post("/sessione")
@utente_assistente
async def crea_sessione():
    """Nuova sessione dei documenti nel RAG: il token da rimandare e i limiti."""
    try:
        r = await _rag_obbligatorio().crea_sessione(_owner())
    except RagError as e:
        raise _errore_rag(e) from e
    return {"sessione": _token(r["session_id"]), "scadenza": r.get("expires_at"),
            "limiti": _limiti(r.get("limits") or {})}, HTTPStatus.CREATED  # fmt: skip


@bp.get("/sessione")
@utente_assistente
async def stato_sessione():
    """Documenti con il loro stato, token usati e limiti. Rinnova la scadenza nel RAG."""
    session_id = _sessione()
    try:
        r = await _rag_obbligatorio().sessione(session_id)
    except RagError as e:
        raise _errore_rag(e) from e
    return {
        "documenti": [_documento(d) for d in r.get("documents", [])],
        "token": r.get("tokens", 0),
        "scadenza": r.get("expires_at"),
        "limiti": _limiti(r.get("limits") or {}),
    }


@bp.delete("/sessione")
@utente_assistente
async def chiudi_sessione():
    """Chiude la sessione: il RAG cancella subito documenti e passaggi."""
    session_id = _sessione()
    try:
        await _rag_obbligatorio().chiudi_sessione(session_id)
    except RagError as e:
        if e.stato_http != 404:  # già scaduta: niente da cancellare
            raise _errore_rag(e) from e
    return "", HTTPStatus.NO_CONTENT


@bp.post("/sessione/documenti")
@utente_assistente
async def carica_documento():
    """Carica un documento nella sessione: il RAG lo converte e lo indicizza (si segue lo stato)."""
    session_id = _sessione()
    client = _rag_obbligatorio()
    file = file_caricato()
    nome = file.filename or "documento"
    estensione = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if estensione not in FORMATI_CONVERSIONE:
        raise ErroreApi(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            f"Formato non ammesso: si possono caricare {', '.join(FORMATI_CONVERSIONE)}",
        )
    try:
        r = await client.carica_documento(session_id, file.read(), nome)
    except RagError as e:
        raise _errore_rag(e) from e
    return _documento(r), HTTPStatus.ACCEPTED


@bp.get("/sessione/documenti/<doc_id>")
@utente_assistente
async def stato_documento(doc_id: str):
    session_id = _sessione()
    if not ID_RAG.match(doc_id):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Documento non trovato")
    try:
        return _documento(await _rag_obbligatorio().documento(session_id, doc_id))
    except RagError as e:
        if e.stato_http == 404:
            raise ErroreApi(HTTPStatus.NOT_FOUND, "Documento non trovato o sessione scaduta") from e
        raise _errore_rag(e) from e


@bp.delete("/sessione/documenti/<doc_id>")
@utente_assistente
async def togli_documento(doc_id: str):
    session_id = _sessione()
    if not ID_RAG.match(doc_id):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Documento non trovato")
    try:
        await _rag_obbligatorio().togli_documento(session_id, doc_id)
    except RagError as e:
        if e.stato_http != 404:
            raise _errore_rag(e) from e
    return "", HTTPStatus.NO_CONTENT


def _domanda_di_ricerca(messaggi: list[Messaggio]) -> str:
    """L'ultima domanda; se è breve, insieme alla precedente dell'utente, che ne dà il contesto."""
    domande = [m.content for m in messaggi if m.role == "user"]
    if len(domande) > 1 and len(domande[-1]) < DOMANDA_BREVE:
        return f"{domande[-2]}\n{domande[-1]}"[-2000:]
    return domande[-1][:2000]


def _passaggi(passaggi: list[dict], budget: int) -> tuple[str, list[dict]]:
    """Blocchi dei passaggi per il prompt, nell'ordine di pertinenza, fino al budget di
    caratteri; e le fonti usate, per l'app."""
    blocchi, fonti, usati = [], [], 0
    for p in passaggi:
        parte = int(p["parent_index"]) + 1
        titoli = " › ".join(str(v) for v in (p.get("headings") or {}).values() if v)
        etichetta = f"{p['file_name']}, parte {parte}"
        testo = p["content"].strip()
        resto = budget - usati
        if resto < 500:
            break
        if len(testo) > resto:
            testo = testo[:resto] + " […]"
        blocchi.append(f"<<< {etichetta}{' — ' + titoli if titoli else ''} >>>\n{testo}\n<<< fine >>>")
        fonti.append({"documento": p["file_name"], "parte": parte, "id": p["doc_id"]})
        usati += len(testo)
    return "\n\n".join(blocchi), fonti


@bp.post("/messaggi")
@utente_assistente
async def messaggio():
    """Risposta del modello alla conversazione, che termina con il messaggio dell'utente. Con
    `documenti` la risposta si basa sui passaggi di quei documenti trovati dal RAG, con le fonti."""
    dati = corpo(ConversazioneIn)
    if dati.messaggi[-1].role != "user":
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "L'ultimo messaggio deve essere dell'utente")
    if len(dati.messaggi) > MAX_MESSAGGI or sum(len(m.content) for m in dati.messaggi) > _max_caratteri():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Conversazione troppo lunga: iniziane una nuova")
    messaggi = [m.model_dump() for m in dati.messaggi]
    fonti: list[dict] = []
    if dati.documenti:
        if not all(ID_RAG.match(d) for d in dati.documenti):
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Documenti non validi")
        session_id = _sessione()
        settings = risorse().settings
        try:
            r = await _rag_obbligatorio().cerca(
                session_id, _domanda_di_ricerca(dati.messaggi), dati.documenti, settings.assistente_passaggi
            )
        except RagError as e:
            raise _errore_rag(e) from e
        blocchi, fonti = _passaggi(r.get("passages", []), settings.assistente_caratteri_passaggi)
        messaggi[-1]["content"] = testo_prompt(
            "assistente_documenti",
            passaggi=blocchi or "(nessun passaggio pertinente trovato nei documenti selezionati)",
            domanda=dati.messaggi[-1].content,
        )
    try:
        testo = (await _llm().conversa(messaggi)).strip()
    except LlmError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    if not testo:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, "Il modello non ha restituito alcuna risposta")
    return {"testo": testo, "fonti": fonti} if dati.documenti else {"testo": testo}


# --- Azioni sui documenti -------------------------------------------------------------------

TIPI_AZIONE = {"riassunto": RIASSUNTO, "confronto": CONFRONTO, "estrazione": ESTRAZIONE}
STATI_AZIONE = {StatoVerifica.IN_CODA: "in_coda", StatoVerifica.IN_CORSO: "in_corso",
                StatoVerifica.COMPLETATA: "completata", StatoVerifica.ERRORE: "errore"}  # fmt: skip


class AzioneIn(BaseModel):
    tipo: Literal["riassunto", "confronto", "estrazione"]
    documenti: list[str] = Field(min_length=1, max_length=20)
    # riassunto e confronto: indicazioni facoltative; estrazione: cosa estrarre
    istruzioni: str = Field(default="", max_length=2000)


def _azione(lavoro: AssistenteLavoro, con_testo: bool = False) -> dict:
    vista = {
        "id": lavoro.id,
        "tipo": next(k for k, v in TIPI_AZIONE.items() if v == lavoro.tipo),
        "stato": STATI_AZIONE.get(lavoro.stato, "in_coda"),
        "avanzamento": lavoro.avanzamento or {"fatti": 0, "totale": 0},
    }
    if lavoro.stato == StatoVerifica.ERRORE:
        vista["errore"] = lavoro.errore or "Azione non riuscita"
    if con_testo and lavoro.stato == StatoVerifica.COMPLETATA:
        vista["testo"] = lavoro.risultato or ""
    return vista


async def _lavoro_utente(lavoro_id: str) -> AssistenteLavoro:
    lavoro = await db().get(AssistenteLavoro, lavoro_id, options=[undefer(AssistenteLavoro.risultato)])
    if lavoro is None or lavoro.ente_id != ente_id() or lavoro.utente_id != utente().id:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Azione non trovata")
    return lavoro


@bp.post("/azioni")
@utente_assistente
async def avvia_azione():
    """Avvia Riassumi, Confronta o Estrai sui documenti indicati (pronti nella sessione)."""
    dati = corpo(AzioneIn)
    session_id = _sessione()
    if not all(ID_RAG.match(d) for d in dati.documenti) or len(set(dati.documenti)) != len(dati.documenti):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Documenti non validi")
    if dati.tipo == "confronto" and len(dati.documenti) < 2:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Per confrontare servono almeno due documenti")
    if dati.tipo == "estrazione" and not dati.istruzioni.strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica cosa estrarre")
    try:
        stato = await _rag_obbligatorio().sessione(session_id)
    except RagError as e:
        raise _errore_rag(e) from e
    documenti = {d["doc_id"]: d for d in stato.get("documents", [])}
    for d in dati.documenti:
        if d not in documenti:
            raise ErroreApi(HTTPStatus.NOT_FOUND, "Documento non trovato nella sessione")
        if documenti[d].get("status") != "ready":
            raise ErroreApi(HTTPStatus.CONFLICT, f"Il documento {documenti[d]['file_name']} non è ancora pronto")
    lavoro = AssistenteLavoro(
        ente_id=ente_id(), utente_id=utente().id, tipo=TIPI_AZIONE[dati.tipo],
        richiesta={"sessione": session_id, "istruzioni": dati.istruzioni.strip(),
                   "documenti": [{"id": d, "nome": documenti[d]["file_name"]} for d in dati.documenti]},
    )  # fmt: skip
    sessione = db()
    sessione.add(lavoro)
    await sessione.commit()
    await sessione.refresh(lavoro)
    await notifica(coda.ASSISTENTE, {"lavoro_id": lavoro.id})
    return _azione(lavoro), HTTPStatus.ACCEPTED


@bp.get("/azioni/<lavoro_id>")
@utente_assistente
async def stato_azione(lavoro_id: str):
    """Stato e avanzamento ({fatti, totale} chiamate all'LLM); a lavoro concluso il testo."""
    return _azione(await _lavoro_utente(lavoro_id), con_testo=True)


@bp.delete("/azioni/<lavoro_id>")
@utente_assistente
async def annulla_azione(lavoro_id: str):
    """Annulla l'azione: il worker si ferma al passo successivo."""
    lavoro = await _lavoro_utente(lavoro_id)
    await db().delete(lavoro)
    await db().commit()
    return "", HTTPStatus.NO_CONTENT
