"""Estrazione del testo dai file degli atti."""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from atti_common.odt import OdtNonValido, estrai_testo

MIME_PDF = "application/pdf"
MIME_ODT = "application/vnd.oasis.opendocument.text"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_DOC = "application/msword"

ESTENSIONI = {".pdf": MIME_PDF, ".odt": MIME_ODT, ".docx": MIME_DOCX, ".doc": MIME_DOC}


class TestoNonEstraibile(ValueError):
    __test__ = False


def mime_da_nome(nome: str) -> str | None:
    nome = nome.lower()
    return next((m for est, m in ESTENSIONI.items() if nome.endswith(est)), None)


def testo_pdf(contenuto: bytes) -> str:
    try:
        lettore = PdfReader(io.BytesIO(contenuto))
        pagine = [p.extract_text() or "" for p in lettore.pages]
    except (PdfReadError, ValueError) as e:
        raise TestoNonEstraibile("PDF non leggibile") from e
    testo = "\n".join(pagine).strip()
    if len(testo) < 50:
        raise TestoNonEstraibile(
            "Il PDF non contiene testo: probabilmente è una scansione. "
            "Caricare il PDF nativo o l'originale ODT/DOCX."
        )
    return testo


def estrai(contenuto: bytes, mime: str) -> str | None:
    """Testo del file; None se serve una conversione (DOC/DOCX) tramite il servizio documenti."""
    if mime == MIME_PDF:
        return testo_pdf(contenuto)
    if mime == MIME_ODT:
        try:
            return estrai_testo(contenuto)
        except OdtNonValido as e:
            raise TestoNonEstraibile(str(e)) from e
    if mime in (MIME_DOCX, MIME_DOC):
        return None
    raise TestoNonEstraibile("Formato non supportato: caricare PDF, ODT, DOCX o DOC")
