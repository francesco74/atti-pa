"""Client del servizio interno di conversione documenti."""

import httpx


class DocumentiError(Exception):
    pass


class DocumentiClient:
    def __init__(self, base_url: str, timeout: float = 180.0):
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def converti(self, contenuto: bytes, nome_file: str, formato: str) -> bytes:
        try:
            r = await self._http.post(
                "/converti", params={"formato": formato}, files={"file": (nome_file, contenuto)}
            )
        except httpx.HTTPError as e:
            raise DocumentiError(f"Servizio documenti non raggiungibile: {e}") from e
        if r.status_code != 200:
            raise DocumentiError(f"Conversione non riuscita ({r.status_code})")
        return r.content
