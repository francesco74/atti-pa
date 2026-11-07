"""Client del modello di embedding per la ricerca semantica (common/ricerca.py).

API `/embeddings` compatibile OpenAI: vLLM (es. con BAAI/bge-m3), llama.cpp
server, Ollama, Text Embeddings Inference. Si configura a parte dall'LLM, perché di solito è
un altro servizio (EMBEDDING_BASE_URL, EMBEDDING_MODEL); senza configurazione la ricerca resta
solo lessicale.
"""

from __future__ import annotations

import logging

import httpx

from common.config import Settings

log = logging.getLogger(__name__)

LOTTO = 64  # testi per chiamata


class EmbeddingError(Exception):
    pass


class ClientEmbedding:
    def __init__(
        self,
        base_url: str,
        modello: str,
        api_key: str = "",
        *,
        timeout: float = 20.0,
        prefisso_domanda: str = "",
        prefisso_documento: str = "",
        http: httpx.AsyncClient | None = None,
    ):
        self.modello = modello
        self.prefisso_domanda = prefisso_domanda
        self.prefisso_documento = prefisso_documento
        self._url = base_url.rstrip("/") + "/embeddings"
        intestazioni = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http or httpx.AsyncClient(timeout=timeout, headers=intestazioni)

    async def close(self) -> None:
        await self._http.aclose()

    async def vettori(self, testi: list[str], *, domanda: bool = False) -> list[list[float]]:
        """Un vettore per testo, nell'ordine. Alcuni modelli (es. e5) vogliono un prefisso
        diverso per la domanda e per i documenti."""
        prefisso = self.prefisso_domanda if domanda else self.prefisso_documento
        risultato: list[list[float]] = []
        for i in range(0, len(testi), LOTTO):
            lotto = [prefisso + t for t in testi[i : i + LOTTO]]
            try:
                r = await self._http.post(self._url, json={"model": self.modello, "input": lotto})
                r.raise_for_status()
                dati = sorted(r.json()["data"], key=lambda d: d["index"])
                risultato += [d["embedding"] for d in dati]
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                log.warning("Embedding (%s) non riuscito: %r", self.modello, e)
                raise EmbeddingError(f"Modello di embedding non disponibile: {e or type(e).__name__}") from e
        if len(risultato) != len(testi):
            raise EmbeddingError("Il modello di embedding ha restituito un numero di vettori diverso")
        return risultato


def crea_embedding(settings: Settings) -> ClientEmbedding | None:
    """Client configurato, o None se EMBEDDING_BASE_URL è vuoto (ricerca solo lessicale)."""
    if not settings.embedding_base_url:
        return None
    if not settings.embedding_model:
        raise ValueError("EMBEDDING_MODEL è obbligatorio con EMBEDDING_BASE_URL")
    return ClientEmbedding(
        settings.embedding_base_url,
        settings.embedding_model,
        settings.embedding_api_key,
        timeout=settings.embedding_timeout,
        prefisso_domanda=settings.embedding_prefisso_domanda,
        prefisso_documento=settings.embedding_prefisso_documento,
    )
