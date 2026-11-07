"""Modulo trasparenza: catalogo degli schemi ANAC, schede generate dal form, analisi ed
estrazioni con l'LLM (lavori in coda eseguiti dal worker), documenti salvati, verbale di
validazione, esportazione in PDF o DOCX.

I documenti sono privati di chi li salva; l'amministratore dell'ente li vede tutti (in
sola lettura). Logica in common/trasparenza.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, Literal

from bs4 import BeautifulSoup
from flask import Blueprint, request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from deps import audit, autenticato, db, ente_id, impostazioni, notifica, risorse, utente
from web import ErroreApi, allegato, corpo, nessun_contenuto
from common import archivio, coda
from common.documenti import DocumentiError
from common.anticorruzione import art35 as dati_art35
from common.anticorruzione.metodologia import chiave_naturale
from common.models import (
    AcProcesso, Ente, Modulo, Ruolo, StatoVerifica, Struttura, TrasparenzaDocumento, TrasparenzaLavoro, User,
)  # fmt: skip
from common.trasparenza import documenti as doc
from common.trasparenza.analisi import ANALISI, ESTRAZIONE
from common.trasparenza.fonti import ESTENSIONI, MAX_LINK, MAX_LINK_MASSIMO, estensione
from common.trasparenza.registro import SCHEMI, get_schema, trova_prompt, valida_dati
from common.trasparenza.sicurezza import estrai_esito, sanifica_html

bp = Blueprint("trasparenza", __name__, url_prefix="/api/v1/trasparenza")

operatore = autenticato(Ruolo.TRASPARENZA, modulo=Modulo.TRASPARENZA)

MAX_HTML = 10 * 1024 * 1024
MAX_DATI_SCHEMA = 2 * 1024 * 1024
GIORNI_LAVORI = 30  # i lavori più vecchi non compaiono nell'elenco
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def _logo() -> str:
    e = await db().scalar(select(Ente).where(Ente.id == ente_id()).options(undefer(Ente.logo)))
    return doc.logo_incorporato(e.logo, e.logo_mime)


def _schema_dei_dati(dati: dict[str, Any]):
    """Schema indicato dai dati del form (campo pdf_type)."""
    schema = get_schema(str(dati.get("pdf_type") or ""))
    if schema is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Schema di pubblicazione non previsto")
    return schema


# --- catalogo e schede ---------------------------------------------------------------------


@bp.get("/schemi")
@operatore
async def schemi():
    """Definizioni degli schemi, con cui l'app costruisce i form."""
    return [s.per_frontend() for s in SCHEMI.values()]


@bp.get("/procedimenti-mappatura")
@operatore
async def procedimenti_mappatura():
    """Procedimenti della mappatura dell'anticorruzione nel formato della sezione PROCEDIMENTI
    dello schema ART_35, da importare nella scheda (con i dati mancanti). Vuoto se l'ente non ha
    il modulo anticorruzione."""
    e = await db().get(Ente, ente_id())
    if not e.modulo_attivo(Modulo.ANTICORRUZIONE):
        return []
    sessione = db()
    strutture = {s.id: s for s in await sessione.scalars(select(Struttura).where(Struttura.ente_id == e.id))}
    procedimenti = await sessione.scalars(
        select(AcProcesso).where(AcProcesso.ente_id == e.id, AcProcesso.tipo == "PROCEDIMENTO")
    )
    risultato = []
    for p in sorted(procedimenti, key=lambda p: chiave_naturale(p.codice)):
        elemento = dati_art35.scheda(p, strutture)
        s = strutture.get(p.struttura_id)
        risultato.append({"id": p.id, "codice": p.codice, "denominazione": p.denominazione,
                          "struttura": f"{s.codice} - {s.descrizione}" if s else None,
                          "elemento": elemento, "mancanti": dati_art35.mancanti(elemento)})  # fmt: skip
    return risultato


@bp.post("/schede")
@operatore
async def genera_scheda():
    """Documento da pubblicare generato dai dati del form di uno schema, validati qui."""
    dati = request.get_json(silent=True)
    if not isinstance(dati, dict):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Corpo JSON mancante o non valido")
    schema = _schema_dei_dati(dati)
    if errori := valida_dati(schema, dati):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Dati non validi:\n- " + "\n- ".join(errori))
    e = await db().get(Ente, ente_id())
    return {"html": doc.scheda(schema, dati, e.nome, await _logo())}


# --- analisi ed estrazioni (lavori in coda) -------------------------------------------------

MAX_FILE = 10


class FonteIn(BaseModel):
    """Una pagina web (o un documento indicato dal suo URL) oppure i file caricati."""

    url: str | None = Field(default=None, max_length=2000, pattern=r"^https?://")
    analizza_pdf: bool = False  # della pagina: scarica anche i PDF collegati
    segui_link: bool = False  # della pagina: segue alcuni link del contenuto
    max_link: int = Field(default=MAX_LINK, ge=1, le=MAX_LINK_MASSIMO)  # quanti, con segui_link
    descrizioni: dict[str, str] = {}  # nome del file -> note dell'utente
    note: str = Field(default="", max_length=5000)
    data_adozione: str = Field(default="", max_length=20)  # GG/MM/AAAA
    data_pubblicazione: str = Field(default="", max_length=20)


class AnalisiIn(FonteIn):
    controllo: str = Field(max_length=100)  # schema (es. ART_23) o suo controllo (ART_23_DIRIGENTI)


class EstrazioneIn(FonteIn):
    schema_id: str = Field(max_length=100)
    variante: str | None = Field(default=None, max_length=100)


def _richiesta(modello: type[BaseModel]):
    """Dati della richiesta e file caricati: JSON, oppure multipart con il campo "dati"
    (JSON) e i file nel campo "file"."""
    if request.mimetype == "multipart/form-data":
        try:
            grezzi = json.loads(request.form.get("dati") or "{}")
        except ValueError as e:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Campo 'dati' non valido") from e
        files = [f for f in request.files.getlist("file") if f and f.filename]
    else:
        grezzi, files = request.get_json(silent=True), []
    if not isinstance(grezzi, dict):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Corpo JSON mancante o non valido")
    try:
        dati = modello.model_validate(grezzi)
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    if not dati.url and not files:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica una pagina web o carica dei documenti")
    if dati.url and files:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica una pagina web oppure dei documenti, non entrambi")
    if len(files) > MAX_FILE:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Al massimo {MAX_FILE} documenti per volta")
    for f in files:
        if estensione(f.filename) not in ESTENSIONI:
            raise ErroreApi(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                f"Formato non ammesso: {f.filename} (PDF, DOC, DOCX, ODT, XLS, XLSX, ODS, CSV)",
            )
    return dati, files


async def _accoda(tipo: str, dati: FonteIn, files, specifici: dict) -> dict:
    limite = impostazioni().upload_max_mb * 1024 * 1024
    salvati = []
    for f in files:
        contenuto = f.read(limite + 1)
        if len(contenuto) > limite:
            raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"File troppo grande: {f.filename}")
        a = await asyncio.to_thread(archivio.salva, impostazioni().archivio_dir, contenuto, f.filename)
        salvati.append({"percorso": a.percorso, "nome": f.filename, "descrizione": dati.descrizioni.get(f.filename, "")})
    richiesta = {
        **specifici,
        "url": dati.url, "analizza_pdf": dati.analizza_pdf, "segui_link": dati.segui_link,
        "max_link": dati.max_link,
        "note": dati.note.strip(), "data_adozione": dati.data_adozione.strip(),
        "data_pubblicazione": dati.data_pubblicazione.strip(), "file": salvati,
    }  # fmt: skip
    lavoro = TrasparenzaLavoro(ente_id=ente_id(), utente_id=utente().id, tipo=tipo, richiesta=richiesta)
    sessione = db()
    sessione.add(lavoro)
    await sessione.flush()
    audit(sessione, utente(), "trasparenza_lavoro", lavoro.id, tipo, {**specifici, "url": dati.url, "file": len(salvati)})
    await sessione.commit()
    await sessione.refresh(lavoro)  # created_at è scritto dal database
    await notifica(coda.TRASPARENZA, {"lavoro_id": lavoro.id})
    return _lavoro(lavoro)


def _descrizione(richiesta: dict) -> tuple[str, str]:
    """Controllo (o schema) e fonte del lavoro, per l'elenco dell'app."""
    if richiesta.get("controllo"):
        schema, variante = trova_prompt(richiesta["controllo"])
    else:
        schema, variante = get_schema(richiesta.get("schema_id") or ""), None
    titolo = (
        f"{schema.articolo[:1].upper()}{schema.articolo[1:]} - {variante.titolo if variante else schema.titolo}"
        if schema
        else richiesta.get("controllo") or richiesta.get("schema_id") or ""
    )
    fonte = richiesta.get("url") or ", ".join(f["nome"] for f in richiesta.get("file") or [])
    return titolo, fonte


def _lavoro(lavoro: TrasparenzaLavoro, risultato: bool = False) -> dict:
    titolo, fonte = _descrizione(lavoro.richiesta or {})
    dati = {
        "id": lavoro.id,
        "tipo": lavoro.tipo,
        "stato": lavoro.stato,
        "titolo": titolo,
        "fonte": fonte,
        "errore": lavoro.errore,
        "modello_llm": lavoro.modello_llm,
        "created_at": lavoro.created_at.isoformat() if lavoro.created_at else None,
        "avviato_il": lavoro.avviato_il.isoformat() if lavoro.avviato_il else None,
        "completato_il": lavoro.completato_il.isoformat() if lavoro.completato_il else None,
    }
    if risultato:
        dati["risultato"] = lavoro.risultato
    return dati


@bp.post("/analisi")
@operatore
async def nuova_analisi():
    """Analisi con l'LLM di una pagina o di documenti rispetto a uno schema o a un suo
    controllo; il report arriva con il lavoro (GET /lavori/<id>)."""
    dati, files = _richiesta(AnalisiIn)
    schema, variante = trova_prompt(dati.controllo)
    if schema is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Schema o controllo non previsto")
    if schema.controlli_per_sezione and variante is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Per questo schema scegli la sezione da controllare")
    return await _accoda(ANALISI, dati, files, {"controllo": dati.controllo}), HTTPStatus.ACCEPTED


@bp.post("/estrazioni")
@operatore
async def nuova_estrazione():
    """Dati per precompilare il form di uno schema, estratti da una pagina o da documenti."""
    dati, files = _richiesta(EstrazioneIn)
    schema = get_schema(dati.schema_id)
    if schema is None or (dati.variante and schema.variante(dati.variante) is None):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Schema non previsto")
    specifici = {"schema_id": dati.schema_id, "variante": dati.variante}
    return await _accoda(ESTRAZIONE, dati, files, specifici), HTTPStatus.ACCEPTED


async def _lavoro_utente(lavoro_id: str, *, risultato: bool = False) -> TrasparenzaLavoro:
    """Lavoro di chi l'ha avviato (gli altri non lo vedono)."""
    q = select(TrasparenzaLavoro).where(TrasparenzaLavoro.id == lavoro_id, TrasparenzaLavoro.ente_id == ente_id())
    if risultato:
        q = q.options(undefer(TrasparenzaLavoro.risultato))
    lavoro = await db().scalar(q)
    if lavoro is None or lavoro.utente_id != utente().id:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Lavoro non trovato")
    return lavoro


@bp.get("/lavori")
@operatore
async def elenco_lavori():
    """Lavori dell'utente degli ultimi GIORNI_LAVORI giorni, dal più recente, senza il
    risultato (?tipo=ANALISI o ESTRAZIONE, di norma le analisi)."""
    tipo = request.args.get("tipo", ANALISI)
    if tipo not in (ANALISI, ESTRAZIONE):
        raise ErroreApi(HTTPStatus.BAD_REQUEST, "Tipo di lavoro non previsto")
    dal = datetime.now() - timedelta(days=GIORNI_LAVORI)
    lavori = await db().scalars(
        select(TrasparenzaLavoro)
        .where(
            TrasparenzaLavoro.ente_id == ente_id(),
            TrasparenzaLavoro.utente_id == utente().id,
            TrasparenzaLavoro.tipo == tipo,
            TrasparenzaLavoro.created_at >= dal,
        )
        .order_by(TrasparenzaLavoro.created_at.desc())
        .limit(200)
    )
    return [_lavoro(lavoro) for lavoro in lavori]


@bp.get("/lavori/<lavoro_id>")
@operatore
async def lavoro(lavoro_id: str):
    """Stato del lavoro e, se completato, il risultato. Solo per chi l'ha avviato."""
    lavoro = await _lavoro_utente(lavoro_id, risultato=True)
    return _lavoro(lavoro, risultato=lavoro.stato == StatoVerifica.COMPLETATA)


@bp.post("/lavori/<lavoro_id>/riprova")
@operatore
async def riprova_lavoro(lavoro_id: str):
    """Rimette in coda un lavoro non riuscito, con la stessa richiesta (controllo, fonte, note,
    date e file caricati, che restano finché il lavoro non riesce)."""
    lavoro = await _lavoro_utente(lavoro_id)
    if lavoro.stato != StatoVerifica.ERRORE:
        raise ErroreApi(HTTPStatus.CONFLICT, "Si riprovano solo le analisi non riuscite")
    for f in (lavoro.richiesta or {}).get("file") or []:
        if not archivio.esiste(impostazioni().archivio_dir, f["percorso"]):
            raise ErroreApi(HTTPStatus.CONFLICT, f"Il file {f['nome']} non c'è più: avvia una nuova analisi caricandolo di nuovo")
    sessione = db()
    lavoro.stato, lavoro.errore, lavoro.tentativi = StatoVerifica.IN_CODA, None, 0
    lavoro.avviato_il = lavoro.completato_il = lavoro.worker = None
    audit(sessione, utente(), "trasparenza_lavoro", lavoro.id, "RIPROVATO")
    await sessione.commit()
    await notifica(coda.TRASPARENZA, {"lavoro_id": lavoro.id})
    return _lavoro(lavoro)


@bp.delete("/lavori/<lavoro_id>")
@operatore
async def elimina_lavoro(lavoro_id: str):
    """Toglie il lavoro dall'elenco, con i file caricati che restano (in coda o non riuscito);
    se è ancora in coda lo annulla. Un lavoro in corso si toglie solo quando è concluso."""
    lavoro = await _lavoro_utente(lavoro_id)
    if lavoro.stato == StatoVerifica.IN_CORSO:
        raise ErroreApi(HTTPStatus.CONFLICT, "L'analisi è in corso: si potrà togliere quando sarà conclusa")
    if lavoro.stato != StatoVerifica.COMPLETATA:  # i completati non hanno più i file
        for f in (lavoro.richiesta or {}).get("file") or []:
            await asyncio.to_thread(archivio.elimina, impostazioni().archivio_dir, f["percorso"])
    sessione = db()
    audit(sessione, utente(), "trasparenza_lavoro", lavoro.id, "ELIMINATO", {"stato": lavoro.stato})
    await sessione.delete(lavoro)
    await sessione.commit()
    return nessun_contenuto()


# --- documenti salvati ---------------------------------------------------------------------


class DocumentoIn(BaseModel):
    descrizione: str = Field(min_length=1, max_length=255)
    html: str = Field(min_length=1, max_length=MAX_HTML)
    tipo: Literal["SCHEDA", "ANALISI", "VERBALE"] | None = None  # se manca si ricava
    # dati del form della scheda; assente nell'aggiornamento: restano quelli salvati
    dati_schema: dict[str, Any] | None = None


def _riga(d: TrasparenzaDocumento, autore: User | None) -> dict:
    return {
        "id": d.id,
        "tipo": d.tipo,
        "schema_id": d.schema_id,
        "descrizione": d.descrizione,
        "esito": d.esito,
        "proprio": d.utente_id == utente().id,
        "autore": (autore.nome_completo or autore.username) if autore else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _dati_schema(valore: dict[str, Any] | None) -> dict[str, Any] | None:
    if valore is None:
        return None
    _schema_dei_dati(valore)
    if len(json.dumps(valore, ensure_ascii=False).encode()) > MAX_DATI_SCHEMA:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Dati della scheda troppo grandi")
    return valore


async def _documento(documento_id: str, *, modifica: bool = False) -> TrasparenzaDocumento:
    """Documento dell'utente; l'amministratore legge anche quelli degli altri."""
    d = await db().scalar(
        select(TrasparenzaDocumento)
        .where(TrasparenzaDocumento.id == documento_id, TrasparenzaDocumento.ente_id == ente_id())
        .options(undefer(TrasparenzaDocumento.html), undefer(TrasparenzaDocumento.dati_schema))
    )
    proprio = d is not None and d.utente_id == utente().id
    if d is None or not (proprio or (not modifica and utente().ha_ruolo(Ruolo.ADMIN))):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Documento non trovato")
    return d


@bp.get("/documenti")
@operatore
async def elenco_documenti():
    """Documenti dell'utente; per l'amministratore quelli di tutto l'ente."""
    q = (
        select(TrasparenzaDocumento, User)
        .join(User, User.id == TrasparenzaDocumento.utente_id)
        .where(TrasparenzaDocumento.ente_id == ente_id())
        .order_by(TrasparenzaDocumento.updated_at.desc())
    )
    if not utente().ha_ruolo(Ruolo.ADMIN):
        q = q.where(TrasparenzaDocumento.utente_id == utente().id)
    return [_riga(d, u) for d, u in (await db().execute(q)).all()]


@bp.get("/documenti/<documento_id>")
@operatore
async def documento(documento_id: str):
    d = await _documento(documento_id)
    autore = await db().get(User, d.utente_id)
    return {**_riga(d, autore), "html": sanifica_html(d.html), "dati_schema": d.dati_schema}


@bp.post("/documenti")
@operatore
async def salva_documento():
    dati = corpo(DocumentoIn)
    html = sanifica_html(dati.html)
    dati_schema = _dati_schema(dati.dati_schema)
    esito = estrai_esito(html)
    tipo = dati.tipo or (doc.SCHEDA if dati_schema else doc.ANALISI if esito else doc.VERBALE)
    d = TrasparenzaDocumento(
        ente_id=ente_id(), utente_id=utente().id, tipo=tipo, descrizione=dati.descrizione.strip(),
        html=html, esito=esito, dati_schema=dati_schema,
        schema_id=str(dati_schema["pdf_type"]) if dati_schema else None,
    )  # fmt: skip
    sessione = db()
    sessione.add(d)
    await sessione.flush()
    audit(sessione, utente(), "trasparenza_documento", d.id, "CREATO", {"tipo": tipo})
    await sessione.commit()
    await sessione.refresh(d)
    return _riga(d, utente()), HTTPStatus.CREATED


@bp.put("/documenti/<documento_id>")
@operatore
async def aggiorna_documento(documento_id: str):
    dati = corpo(DocumentoIn)
    d = await _documento(documento_id, modifica=True)
    d.descrizione = dati.descrizione.strip()
    d.html = sanifica_html(dati.html)
    d.esito = estrai_esito(d.html)
    if dati.dati_schema is not None:
        d.dati_schema = _dati_schema(dati.dati_schema)
        d.schema_id = str(d.dati_schema["pdf_type"])
    sessione = db()
    audit(sessione, utente(), "trasparenza_documento", d.id, "AGGIORNATO")
    await sessione.commit()
    await sessione.refresh(d)
    return _riga(d, utente())


@bp.delete("/documenti/<documento_id>")
@operatore
async def elimina_documento(documento_id: str):
    d = await _documento(documento_id, modifica=True)
    sessione = db()
    await sessione.delete(d)
    audit(sessione, utente(), "trasparenza_documento", documento_id, "ELIMINATO")
    await sessione.commit()
    return nessun_contenuto()


# --- verbale ed esportazione ---------------------------------------------------------------


class VerbaleIn(BaseModel):
    documenti: list[str] = Field(default=[], max_length=100)


@bp.post("/verbale")
@operatore
async def verbale():
    """Verbale di validazione seguito dai documenti scelti, nell'ordine indicato."""
    dati = corpo(VerbaleIn)
    contenuti = [(await _documento(i)).html for i in dict.fromkeys(dati.documenti)]
    return {"html": doc.verbale(contenuti, await _logo())}


class EsportaIn(BaseModel):
    html: str = Field(min_length=1, max_length=MAX_HTML)
    nome: str = Field(default="documento", max_length=200)
    formato: Literal["pdf", "docx"] = "pdf"


def _html_da_convertire(html: str) -> bytes:
    """HTML sanificato e autosufficiente: restano solo le immagini incorporate (data URI),
    così il converter non carica nulla dalla rete o dal disco."""
    soup = BeautifulSoup(sanifica_html(html), "html.parser")
    for img in soup.find_all("img"):
        if not str(img.get("src") or "").startswith("data:image/"):
            img.decompose()
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>{soup}</body></html>'.encode()


@bp.post("/esporta")
@operatore
async def esporta():
    dati = corpo(EsportaIn)
    try:
        contenuto = await risorse().documenti.converti(
            _html_da_convertire(dati.html), "documento.html", dati.formato
        )
    except DocumentiError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    nome = re.sub(r"[^A-Za-z0-9_-]+", "-", dati.nome).strip("-") or "documento"
    return allegato(contenuto, MIME[dati.formato], f"{nome}.{dati.formato}")
