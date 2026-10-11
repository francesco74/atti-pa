"""Client per l'LLM on-premise tramite API compatibile OpenAI (vLLM, Ollama, llama.cpp).

Il modello valuta un elemento di checklist alla volta, ricevendo nel prompt il testo
dell'atto e il testo vigente delle norme pertinenti. L'output è vincolato a uno schema
JSON e validato; in caso di risposta non valida si riprova una volta.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("atti_common.llm")

MAX_CARATTERI_ATTO = 60_000


class EsitoElemento(BaseModel):
    esito: Literal["CONFORME", "NON_CONFORME", "NON_APPLICABILE", "DUBBIO"]
    motivazione: str = Field(description="Spiegazione sintetica in italiano")
    evidenza: str | None = Field(
        default=None, description="Breve passaggio dell'atto su cui si basa la valutazione"
    )
    suggerimento: str | None = Field(
        default=None, description="Come correggere l'atto, se non conforme o dubbio"
    )


SCHEMA_ESITO = EsitoElemento.model_json_schema()

SYSTEM_PROMPT = """Sei un esperto di diritto amministrativo degli enti locali italiani e \
supporti il controllo di regolarità amministrativa delle determinazioni dirigenziali.

Regole:
- Valuta SOLO il criterio indicato, basandoti sul testo dell'atto fornito.
- Per le norme usa ESCLUSIVAMENTE il testo normativo vigente riportato nel messaggio; \
non citare norme a memoria e non inventare riferimenti.
- Se il testo dell'atto non contiene elementi sufficienti, rispondi DUBBIO e spiega cosa manca.
- Se il criterio non riguarda questo tipo di atto, rispondi NON_APPLICABILE.
- L'evidenza deve essere un passaggio breve copiato dall'atto, oppure null.
- Rispondi solo con un oggetto JSON conforme allo schema richiesto."""


class LlmError(Exception):
    pass


def costruisci_prompt(
    titolo: str,
    regola: str,
    testo_atto: str,
    norme: list[tuple[str, str]],
    data_riferimento: str,
) -> str:
    if len(testo_atto) > MAX_CARATTERI_ATTO:
        testo_atto = testo_atto[:MAX_CARATTERI_ATTO] + "\n[... testo troncato ...]"
    sezioni = [
        f"## Criterio da verificare\n{titolo}\n\n{regola}",
        f"## Data di riferimento\nL'atto va valutato secondo le norme vigenti al {data_riferimento}.",
    ]
    if norme:
        blocchi = "\n\n".join(f"### {citazione}\n{testo}" for citazione, testo in norme)
        sezioni.append(f"## Testo normativo vigente pertinente (fonte: Normattiva)\n{blocchi}")
    sezioni.append(f"## Testo dell'atto\n<<<\n{testo_atto}\n>>>")
    sezioni.append(
        "Rispondi con JSON: {esito, motivazione, evidenza, suggerimento}. "
        "esito ∈ CONFORME | NON_CONFORME | NON_APPLICABILE | DUBBIO."
    )
    return "\n\n".join(sezioni)


class LlmClient:
    def __init__(
        self,
        base_url: str,
        modello: str,
        api_key: str = "nessuna",
        timeout: float = 180.0,
        temperatura: float = 0.0,
        http: httpx.AsyncClient | None = None,
    ):
        self.modello = modello
        self.temperatura = temperatura
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._http = http or httpx.AsyncClient(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _chiama(self, messaggi: list[dict]) -> str:
        payload = {
            "model": self.modello,
            "messages": messaggi,
            "temperature": self.temperatura,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "esito_elemento", "schema": SCHEMA_ESITO},
            },
        }
        try:
            r = await self._http.post(self._url, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LlmError(f"Chiamata al modello fallita: {e}") from e

    @staticmethod
    def _interpreta(contenuto: str) -> EsitoElemento:
        testo = contenuto.strip()
        if testo.startswith("```"):
            testo = testo.strip("`").removeprefix("json").strip()
        inizio, fine = testo.find("{"), testo.rfind("}")
        if inizio == -1 or fine == -1:
            raise ValueError("Nessun oggetto JSON nella risposta")
        return EsitoElemento.model_validate(json.loads(testo[inizio : fine + 1]))

    async def valuta(self, prompt: str) -> EsitoElemento:
        messaggi = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        contenuto = await self._chiama(messaggi)
        try:
            return self._interpreta(contenuto)
        except (ValueError, ValidationError) as e:
            log.warning("Risposta del modello non valida, nuovo tentativo: %s", e)
            messaggi += [
                {"role": "assistant", "content": contenuto},
                {
                    "role": "user",
                    "content": "La risposta non è un JSON valido secondo lo schema. "
                    "Rispondi solo con l'oggetto JSON.",
                },
            ]
            contenuto = await self._chiama(messaggi)
            try:
                return self._interpreta(contenuto)
            except (ValueError, ValidationError) as e2:
                raise LlmError(f"Risposta del modello non valida: {e2}") from e2
