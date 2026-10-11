"""Servizio interno di conversione documenti con LibreOffice headless.

Raggiungibile solo dall'API (NetworkPolicy). Ogni conversione usa un profilo LibreOffice
separato in una cartella temporanea, così più conversioni possono girare in parallelo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile

log = logging.getLogger("documenti")

SOFFICE = os.environ.get("SOFFICE_BIN", "soffice")
TIMEOUT = int(os.environ.get("CONVERSIONE_TIMEOUT", "120"))
MAX_MB = int(os.environ.get("UPLOAD_MAX_MB", "20"))
_semaforo = asyncio.Semaphore(int(os.environ.get("CONVERSIONI_PARALLELE", "2")))

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

app = FastAPI(title="atti-pa documenti", version="0.1.0")


async def converti(contenuto: bytes, estensione: str, formato: str) -> bytes:
    async with _semaforo:
        with tempfile.TemporaryDirectory(prefix="conv-") as cartella:
            base = Path(cartella)
            sorgente = base / f"documento{estensione}"
            sorgente.write_bytes(contenuto)
            profilo = (base / "profilo").as_uri()
            uscita = base / "uscita"
            processo = await asyncio.create_subprocess_exec(
                SOFFICE,
                f"-env:UserInstallation={profilo}",
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to",
                FILTRI[formato],
                "--outdir",
                str(uscita),
                str(sorgente),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, errori = await asyncio.wait_for(processo.communicate(), timeout=TIMEOUT)
            except TimeoutError as e:
                processo.kill()
                raise HTTPException(504, "Conversione troppo lunga") from e
            estensione_uscita = "pdf" if formato.startswith("pdf") else formato
            risultato = uscita / f"documento.{estensione_uscita}"
            if processo.returncode != 0 or not risultato.exists():
                log.error("Conversione fallita: %s", errori.decode(errors="replace")[:500])
                raise HTTPException(422, "Il documento non può essere convertito")
            return risultato.read_bytes()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "libreoffice": shutil.which(SOFFICE) is not None}


@app.post("/converti")
async def converti_file(
    file: Annotated[UploadFile, File()],
    formato: Annotated[Literal["pdf", "pdfa", "odt"], Query()] = "pdf",
) -> Response:
    estensione = Path(file.filename or "").suffix.lower()
    if estensione not in ESTENSIONI_AMMESSE:
        raise HTTPException(415, "Formato non supportato")
    contenuto = await file.read(MAX_MB * 1024 * 1024 + 1)
    if len(contenuto) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, "File troppo grande")
    risultato = await converti(contenuto, estensione, formato)
    return Response(risultato, media_type=MIME[formato])
