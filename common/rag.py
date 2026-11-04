"""Client delle API esterne del progetto RAG (chatbot e motore RAG, sviluppato a parte e
collegato solo tramite API: vedi progettazione/architettura.md, sezione 9).

Ogni ente ha il proprio collegamento (Ente.rag_json): indirizzo dell'API e chiave, salvata
cifrata con CHIAVE_CIFRATURA. La chiave determina i topic consultabili; per la conversione dei
documenti basta una chiave valida. La conversione è asincrona: si avvia, si riceve un job_id e
se ne chiede lo stato finché non è conclusa. Il RAG cancella il file a conversione finita e il
risultato appena lo consegna (completed o failed): una seconda richiesta risponde 404, quindi se
la risposta si perde il documento va riconvertito.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from common import cifratura

log = logging.getLogger("common.rag")

# Formati che la conversione del RAG accetta (POST /external/v1/convert)
FORMATI_CONVERSIONE = ("pdf", "docx", "odt", "xlsx", "ods", "txt", "md", "png", "jpg", "jpeg")


class RagError(Exception):
    def __init__(self, messaggio: str, stato_http: int | None = None):
        super().__init__(messaggio)
        self.stato_http = stato_http  # risposta del RAG, se c'è stata


def cifra(testo: str, segreto: str) -> str:
    try:
        return cifratura.cifra(testo, segreto)
    except cifratura.ErroreCifratura as e:
        raise RagError(str(e)) from e


def decifra(cifrato: str, segreto: str) -> str:
    try:
        return cifratura.decifra(cifrato, segreto, "La chiave del RAG")
    except cifratura.ErroreCifratura as e:
        raise RagError(str(e)) from e


@dataclass
class RagClient:
    http: httpx.AsyncClient  # condiviso da tutti gli enti (Risorse.rag_http)
    url: str  # indirizzo dell'API, es. https://rag.ente.it/api
    chiave: str

    @classmethod
    def dell_ente(cls, http: httpx.AsyncClient, rag_json: dict | None, segreto: str) -> RagClient | None:
        """Client del collegamento dell'ente; None se l'ente non l'ha configurato."""
        if not rag_json or not rag_json.get("url") or not rag_json.get("chiave_cifrata"):
            return None
        return cls(http, rag_json["url"], decifra(rag_json["chiave_cifrata"], segreto))

    async def _richiesta(self, metodo: str, percorso: str, **opzioni) -> dict:
        try:
            r = await self.http.request(
                metodo,
                self.url.rstrip("/") + "/external/v1" + percorso,
                headers={"Authorization": f"Bearer {self.chiave}"},
                **opzioni,
            )
        except httpx.TimeoutException as e:
            raise RagError("Il RAG non ha risposto in tempo") from e
        except httpx.HTTPError as e:
            log.warning("RAG %s non raggiungibile: %r", self.url, e)
            raise RagError(f"RAG non raggiungibile: {e or type(e).__name__}") from e
        if r.status_code >= 400:
            try:
                messaggio = r.json().get("error")
            except ValueError:
                messaggio = None
            if r.status_code == 401:
                messaggio = "Chiave del RAG non valida o scaduta"
            log.warning("RAG %s %s -> %d %s", metodo, percorso, r.status_code, messaggio or r.text[:200])
            raise RagError(messaggio or f"Il RAG ha risposto con l'errore HTTP {r.status_code}", r.status_code)
        return r.json()

    async def topics(self) -> list[dict]:
        """Topic consultabili con la chiave (usato anche per provare il collegamento)."""
        return (await self._richiesta("GET", "/topics"))["topics"]

    async def avvia_conversione(self, contenuto: bytes, nome: str, formato: str = "markdown") -> str:
        dati = await self._richiesta(
            "POST", "/convert", files={"file": (nome, contenuto)}, data={"format": formato}
        )
        return dati["job_id"]

    async def conversione(self, job_id: str) -> dict:
        """Stato della conversione: status queued | running | completed (con content) | failed
        (con error). L'esito finale si riceve una volta sola."""
        return await self._richiesta("GET", f"/convert/{job_id}")
