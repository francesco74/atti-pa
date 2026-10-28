"""Client del servizio interno di conversione documenti (converter): conversione di formato
con LibreOffice e testo in Markdown di un documento (PDF, ODT, DOCX, DOC, RTF)."""

import logging
import time

import httpx

log = logging.getLogger("common.documenti")


class DocumentiError(Exception):
    pass


class DocumentiClient:
    def __init__(self, base_url: str, timeout: float = 150.0):
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def converti(self, contenuto: bytes, nome_file: str, formato: str) -> bytes:
        log.debug("Conversione di %s (%d byte) in %s", nome_file, len(contenuto), formato)
        inizio = time.perf_counter()
        try:
            r = await self._http.post(
                "/converti", params={"formato": formato}, files={"file": (nome_file, contenuto)}
            )
        except httpx.HTTPError as e:
            raise DocumentiError(f"Servizio documenti non raggiungibile: {e}") from e
        if r.status_code != 200:
            raise DocumentiError(f"Conversione non riuscita ({r.status_code}): {r.text[:200]}")
        log.debug(
            "Conversione di %s completata in %.1f s (%d byte)",
            nome_file,
            time.perf_counter() - inizio,
            len(r.content),
        )
        return r.content

    async def markdown(self, contenuto: bytes, nome_file: str) -> str:
        """Testo del documento in Markdown (per l'LLM)."""
        try:
            r = await self._http.post("/markdown", files={"file": (nome_file, contenuto)})
        except httpx.HTTPError as e:
            raise DocumentiError(f"Servizio documenti non raggiungibile: {e}") from e
        if r.status_code != 200:
            raise DocumentiError(f"Testo di {nome_file} non estratto ({r.status_code}): {r.text[:200]}")
        return r.json()["markdown"]
