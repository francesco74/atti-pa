"""Servizio interno di conversione documenti (Flask), sulla libreria pa-common.

- `/converti`: documenti delle bozze in PDF, PDF/A, ODT o DOCX con LibreOffice headless;
- `/markdown`: testo dei documenti in Markdown per l'LLM (PDF con OCR delle pagine
  scansionate, ODT, DOC/DOCX/RTF, fogli di calcolo), usato dalla trasparenza.

Usato dall'API (e dal worker) nel namespace. La configurazione arriva dalle variabili
d'ambiente (vedi `Settings`).

In produzione: `gunicorn -c python:gunicorn_conf "main:create_app()"`.
"""

from __future__ import annotations

import logging
import shutil
from http import HTTPStatus
from pathlib import Path
from typing import Literal

from flask import Flask, request
from pa_common.conversione import FORMATI as FORMATI_MARKDOWN
from pa_common.conversione import Tempi, in_markdown_sync
from pa_common.conversione.libreoffice import FILTRI, INGRESSI, LibreOffice, Occupato
from pa_common.errori import ConversioneNonRiuscita, ErroreOcr, FileNonValido, TempoScaduto
from pa_common.ocr import Ocr, crea_ocr
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from werkzeug.exceptions import HTTPException

log = logging.getLogger("documenti")

ESTENSIONI_AMMESSE = INGRESSI
MIME = {
    "pdf": "application/pdf",
    "pdfa": "application/pdf",
    "odt": "application/vnd.oasis.opendocument.text",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


# .env della radice del repository (in sviluppo: converter/src/../../.env) e della cartella
# di avvio; nell'immagine (/app/main.py) la radice non esiste e resta solo il secondo
_QUI = Path(__file__).resolve()
_FILE_ENV = tuple(
    p for p in ((_QUI.parents[2] / ".env") if len(_QUI.parents) > 2 else None, Path(".env")) if p
)


class Settings(BaseSettings):
    # .env della radice del repository e della cartella di avvio, solo in sviluppo
    # (esclusi dalle immagini Docker); le variabili d'ambiente prevalgono
    model_config = SettingsConfigDict(
        env_file=_FILE_ENV,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    soffice_bin: str = "soffice"
    # Attesa in coda + conversione restano sotto il timeout del client nell'API
    # (DOCUMENTI_TIMEOUT, 150 s): l'API riceve sempre una risposta esplicita
    conversione_timeout: int = 120
    coda_timeout: int = 25
    # Ogni LibreOffice occupa 300-500 MB: due in parallelo stanno nel limite di 1,5 GB del pod
    conversioni_parallele: int = 2
    upload_max_mb: int = 20  # come UPLOAD_MAX_MB dell'API
    max_pagine_pdf: int = 300  # PDF più lunghi rifiutati
    # OCR delle pagine scansionate (pa_common.ocr), come nel RAG: fornitore gemini, openai,
    # anthropic, mistral, vllm (OCR_BASE_URL obbligatorio) o ollama; il modello deve leggere
    # le immagini. Senza la chiave (fornitori esterni) i PDF scansionati sono rifiutati.
    ocr_provider: str = "gemini"
    ocr_model: str = "gemini-3-flash-preview"
    ocr_api_key: str = ""
    ocr_base_url: str = ""
    ocr_richieste_al_minuto: int = 10
    ocr_tentativi: int = 6
    # Consumatore della coda di conversione (consumatore.py): stessi valori di API e worker
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_prefisso: str = "atti-pa"
    archivio_dir: str = "/var/lib/atti-pa/archivio"  # in sola lettura per il converter
    # DEBUG (diagnostica dettagliata), INFO (normale), WARNING (solo anomalie), ERROR
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _livello_maiuscolo(cls, valore: object) -> object:
        return valore.strip().upper() if isinstance(valore, str) else valore


class ErroreConversione(Exception):
    def __init__(self, stato: int, messaggio: str):
        super().__init__(messaggio)
        self.stato = stato
        self.messaggio = messaggio


def configura_logging(livello: str) -> None:
    """Stesso formato degli altri componenti (common.log)."""
    logging.basicConfig(
        level=livello, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", force=True
    )
    logging.getLogger("werkzeug").setLevel(logging.INFO if livello == "DEBUG" else logging.WARNING)
    for nome in ("gunicorn.error", "gunicorn.access"):
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.INFO if livello == "DEBUG" else livello)


def crea_libreoffice(settings: Settings) -> LibreOffice:
    return LibreOffice(
        settings.soffice_bin,
        timeout=settings.conversione_timeout,
        parallele=settings.conversioni_parallele,
        attesa=settings.coda_timeout,
    )


ESTERNI = {"gemini", "openai", "anthropic", "mistral"}


def crea_ocr_da(settings: Settings) -> Ocr | None:
    """L'OCR configurato, None se manca la configurazione (i PDF scansionati sono rifiutati)."""
    fornitore = settings.ocr_provider.strip().lower()
    if not fornitore:
        log.info("OCR spento (OCR_PROVIDER vuoto): i PDF scansionati sono rifiutati")
        return None
    if fornitore in ESTERNI and not settings.ocr_api_key:
        log.warning("OCR %s senza OCR_API_KEY: i PDF scansionati sono rifiutati", fornitore)
        return None
    try:
        return crea_ocr(
            fornitore,
            settings.ocr_model,
            api_key=settings.ocr_api_key,
            base_url=settings.ocr_base_url or None,
            al_minuto=settings.ocr_richieste_al_minuto,
            tentativi=settings.ocr_tentativi,
        )
    except (ErroreOcr, ImportError) as e:
        log.error("OCR non utilizzabile: %s", e)
        return None


def converti_in_markdown(
    contenuto: bytes,
    nome_file: str,
    *,
    libreoffice: LibreOffice,
    ocr: Ocr | None,
    settings: Settings,
    tempi: Tempi | None = None,
) -> str:
    """Testo di un documento in Markdown (pa-common): sbusta le firme .p7m, OCR delle pagine
    scansionate. Solleva `ConversioneNonRiuscita` o `FileNonValido`."""
    return in_markdown_sync(
        contenuto,
        nome_file,
        ocr=ocr,
        libreoffice=libreoffice,
        max_pagine=settings.max_pagine_pdf,
        tempi=tempi,
    )


def create_app(settings: Settings | None = None) -> Flask:
    if settings is None:
        settings = Settings()
        configura_logging(settings.log_level)
    libreoffice = crea_libreoffice(settings)
    ocr = crea_ocr_da(settings)
    # l'API aspetta al massimo DOCUMENTI_TIMEOUT (150 s): i livelli dell'estrazione dei PDF
    # restano sotto, l'OCR completo di un PDF lungo può comunque superarlo
    tempi = Tempi(
        layout_ai=settings.conversione_timeout,
        semplice=settings.conversione_timeout / 2,
        rasterizza=settings.conversione_timeout / 2,
    )

    app = Flask("documenti")
    app.config["MAX_CONTENT_LENGTH"] = (settings.upload_max_mb + 1) * 1024 * 1024

    @app.errorhandler(ErroreConversione)
    def errore_conversione(e: ErroreConversione):
        return {"detail": e.messaggio}, e.stato

    @app.errorhandler(HTTPException)
    def errore_http(e: HTTPException):
        messaggio = "File troppo grande" if e.code == 413 else e.name
        return {"detail": messaggio}, e.code

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "libreoffice": shutil.which(settings.soffice_bin) is not None,
            "ocr": repr(ocr) if ocr else None,
        }

    @app.post("/converti")
    def converti_file():
        formato = request.args.get("formato", "pdf")
        if formato not in FILTRI:
            raise ErroreConversione(HTTPStatus.UNPROCESSABLE_ENTITY, "Formato di uscita non valido")
        file = request.files.get("file")
        if file is None:
            raise ErroreConversione(HTTPStatus.UNPROCESSABLE_ENTITY, "File mancante")
        estensione = Path(file.filename or "").suffix.lower()
        if estensione not in ESTENSIONI_AMMESSE:
            log.warning("File %r rifiutato: formato non supportato", file.filename)
            raise ErroreConversione(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Formato non supportato")
        limite = settings.upload_max_mb * 1024 * 1024
        contenuto = file.read(limite + 1)
        if len(contenuto) > limite:
            log.warning("File %r rifiutato: oltre %d MB", file.filename, settings.upload_max_mb)
            raise ErroreConversione(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
        try:
            risultato = libreoffice.converti(contenuto, estensione, formato)
        except Occupato as e:
            raise ErroreConversione(HTTPStatus.SERVICE_UNAVAILABLE, str(e)) from e
        except TempoScaduto as e:
            raise ErroreConversione(HTTPStatus.GATEWAY_TIMEOUT, str(e)) from e
        except ConversioneNonRiuscita as e:
            raise ErroreConversione(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
        return app.response_class(risultato, mimetype=MIME[formato])

    @app.post("/markdown")
    def markdown_file():
        """Testo del documento in Markdown (usato dal modulo trasparenza)."""
        file = request.files.get("file")
        if file is None:
            raise ErroreConversione(HTTPStatus.UNPROCESSABLE_ENTITY, "File mancante")
        if Path(file.filename or "").suffix.lower() not in FORMATI_MARKDOWN | {".p7m", ".jpeg", ".tiff"}:
            raise ErroreConversione(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Formato non supportato")
        limite = settings.upload_max_mb * 1024 * 1024
        contenuto = file.read(limite + 1)
        if len(contenuto) > limite:
            raise ErroreConversione(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
        try:
            testo = converti_in_markdown(
                contenuto, file.filename or "", libreoffice=libreoffice, ocr=ocr, settings=settings, tempi=tempi
            )
        except Occupato as e:
            raise ErroreConversione(HTTPStatus.SERVICE_UNAVAILABLE, str(e)) from e
        except TempoScaduto as e:
            raise ErroreConversione(HTTPStatus.GATEWAY_TIMEOUT, str(e)) from e
        except (ConversioneNonRiuscita, FileNonValido) as e:
            raise ErroreConversione(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
        return {"markdown": testo}

    log.info(
        "Servizio documenti: %s, %d conversioni parallele, timeout %d s, OCR %s, log %s",
        settings.soffice_bin,
        settings.conversioni_parallele,
        settings.conversione_timeout,
        repr(ocr) if ocr else "spento",
        settings.log_level,
    )
    return app
