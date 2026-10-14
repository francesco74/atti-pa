"""Servizio interno di conversione documenti con LibreOffice headless (Flask).

Raggiungibile solo dall'API (NetworkPolicy). Ogni conversione usa un profilo LibreOffice
separato in una cartella temporanea, così più conversioni possono girare in parallelo.
La configurazione arriva dalle variabili d'ambiente (vedi `Settings`).

In produzione: `gunicorn -c python:gunicorn_conf "main:create_app()"`.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Literal

from flask import Flask, request
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from werkzeug.exceptions import HTTPException

log = logging.getLogger("documenti")

ESTENSIONI_AMMESSE = {".odt", ".docx", ".doc", ".rtf"}

# Filtri di esportazione LibreOffice
FILTRI = {
    "pdf": 'pdf:writer_pdf_Export:{"SelectPdfVersion":{"type":"long","value":"0"}}',
    "pdfa": 'pdf:writer_pdf_Export:{"SelectPdfVersion":{"type":"long","value":"2"}}',
    "odt": "odt",
}
MIME = {
    "pdf": "application/pdf",
    "pdfa": "application/pdf",
    "odt": "application/vnd.oasis.opendocument.text",
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


class Convertitore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._semaforo = threading.BoundedSemaphore(settings.conversioni_parallele)

    def converti(self, contenuto: bytes, estensione: str, formato: str) -> bytes:
        s = self.settings
        log.debug("Conversione %s -> %s (%d byte) in attesa", estensione, formato, len(contenuto))
        if not self._semaforo.acquire(timeout=s.coda_timeout):
            log.warning(
                "Conversione rifiutata: %d già in corso da oltre %d s",
                s.conversioni_parallele,
                s.coda_timeout,
            )
            raise ErroreConversione(HTTPStatus.SERVICE_UNAVAILABLE, "Servizio occupato, riprovare")
        try:
            return self._esegui(contenuto, estensione, formato)
        finally:
            self._semaforo.release()

    def _esegui(self, contenuto: bytes, estensione: str, formato: str) -> bytes:
        inizio = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="conv-") as cartella:
            base = Path(cartella)
            sorgente = base / f"documento{estensione}"
            sorgente.write_bytes(contenuto)
            uscita = base / "uscita"
            comando = [
                self.settings.soffice_bin,
                f"-env:UserInstallation={(base / 'profilo').as_uri()}",
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to",
                FILTRI[formato],
                "--outdir",
                str(uscita),
                str(sorgente),
            ]
            try:
                processo = subprocess.run(
                    comando,
                    check=False,
                    capture_output=True,
                    timeout=self.settings.conversione_timeout,
                )
            except subprocess.TimeoutExpired as e:
                log.warning(
                    "Conversione %s -> %s interrotta dopo %d s",
                    estensione,
                    formato,
                    self.settings.conversione_timeout,
                )
                raise ErroreConversione(
                    HTTPStatus.GATEWAY_TIMEOUT, "Conversione troppo lunga"
                ) from e
            estensione_uscita = "pdf" if formato.startswith("pdf") else formato
            risultato = uscita / f"documento.{estensione_uscita}"
            if processo.returncode != 0 or not risultato.exists():
                log.error("Conversione fallita: %s", processo.stderr.decode(errors="replace")[:500])
                raise ErroreConversione(
                    HTTPStatus.UNPROCESSABLE_ENTITY, "Il documento non può essere convertito"
                )
            dati = risultato.read_bytes()
        log.debug(
            "Conversione %s -> %s completata in %.1f s (%d byte)",
            estensione,
            formato,
            time.perf_counter() - inizio,
            len(dati),
        )
        return dati


def create_app(settings: Settings | None = None) -> Flask:
    if settings is None:
        settings = Settings()
        configura_logging(settings.log_level)
    convertitore = Convertitore(settings)

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
        return {"status": "ok", "libreoffice": shutil.which(settings.soffice_bin) is not None}

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
        risultato = convertitore.converti(contenuto, estensione, formato)
        return app.response_class(risultato, mimetype=MIME[formato])

    log.info(
        "Servizio documenti: %s, %d conversioni parallele, timeout %d s, log %s",
        settings.soffice_bin,
        settings.conversioni_parallele,
        settings.conversione_timeout,
        settings.log_level,
    )
    return app
