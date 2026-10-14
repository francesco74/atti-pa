"""Client per l'LLM, con provider scelto in configurazione (LLM_PROVIDER).

- `ollama` (predefinito) e `openai_compatibile` (vLLM, llama.cpp server...): modello
  on-premise, nessun dato esce dall'ente;
- `openai` (ChatGPT) e `gemini` (Google): API compatibile OpenAI del fornitore;
- `anthropic` (Claude): SDK ufficiale `anthropic`.

Il modello valuta un elemento di checklist alla volta, ricevendo nel prompt il testo
dell'atto e il testo vigente delle norme pertinenti. L'output è vincolato a uno schema
JSON e validato; in caso di risposta non valida si riprova una volta.

I testi dei prompt sono file in `common/prompt/` (vedi il README della cartella),
sovrascrivibili con una cartella indicata in LLM_PROMPT_DIR.
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Literal, TypeVar

import anthropic
import httpx
from pydantic import BaseModel, Field, ValidationError

from common.config import Settings, get_settings

log = logging.getLogger("common.llm")

M = TypeVar("M", bound=BaseModel)

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


class EsitoCoerenza(BaseModel):
    id: str = Field(description="Identificativo del riferimento valutato, es. RIF-1")
    esito: Literal["CONFORME", "NON_CONFORME", "NON_APPLICABILE", "DUBBIO"]
    motivazione: str = Field(description="Spiegazione sintetica in italiano")
    evidenza: str | None = Field(
        default=None, description="Breve passaggio dell'atto su cui si basa la valutazione"
    )
    suggerimento: str | None = Field(
        default=None, description="Come correggere l'atto, se non conforme o dubbio"
    )


class EsitiCoerenza(BaseModel):
    esiti: list[EsitoCoerenza] = Field(description="Un esito per ciascun riferimento richiesto")


class CitazioneNorma(BaseModel):
    norma: str = Field(description="Identificativo della norma citata, es. N-1")
    testo: str = Field(description="La citazione copiata esattamente dal testo dell'atto")
    articolo: str | None = Field(default=None, description="Articolo citato, se indicato")
    comma: str | None = Field(default=None, description="Comma citato, se indicato")
    lettera: str | None = Field(default=None, description="Lettera citata, se indicata")


class CitazioniNorme(BaseModel):
    citazioni: list[CitazioneNorma] = Field(
        description="Citazioni delle norme elencate non ancora riconosciute; vuoto se nessuna"
    )


CategoriaDato = Literal[
    "NOME",
    "CODICE_FISCALE",
    "DATA_DI_NASCITA",
    "INDIRIZZO",
    "TELEFONO",
    "EMAIL",
    "IBAN",
    "DOCUMENTO",
    "SALUTE",
    "CONDIZIONE_ECONOMICA",
    "GIUDIZIARIO",
    "MINORE",
    "DATI_PARTICOLARI",
    "ALTRO",
]


class DatoTrovato(BaseModel):
    categoria: CategoriaDato
    testo: str = Field(description="Il dato copiato esattamente dal testo, il più breve possibile")
    motivo: str | None = Field(default=None, description="Perché è un dato personale, in breve")


class DatiTrovati(BaseModel):
    dati: list[DatoTrovato] = Field(description="Dati personali presenti; vuoto se nessuno")


CARTELLA_PROMPT = Path(__file__).resolve().parent / "prompt"

# Segnaposto ammessi in ogni file di prompt
SEGNAPOSTO = {
    "verifica_sistema": set(),
    "verifica_utente": {"titolo", "regola", "data_riferimento", "norme", "testo_atto"},
    "verifica_norme": {"norme"},
    "verifica_norma": {"citazione", "testo"},
    "verifica_correzione": set(),
    "redazione_sistema": set(),
    "redazione_utente": {"oggetto", "sezione", "appunti"},
    "coerenza_sistema": set(),
    "coerenza_utente": {"data_riferimento", "testo_atto", "riferimenti", "elenco_id"},
    "coerenza_riferimento": {"id", "citazione", "testo_citazione", "testo_norma"},
    "riconoscimento_sistema": set(),
    "riconoscimento_utente": {"norme", "riconosciute", "testo_atto"},
    "riconoscimento_norma": {"id", "citazione", "titolo", "denominazioni"},
    "dati_personali_sistema": set(),
    "dati_personali_utente": {"parte", "testo_atto"},
}


@lru_cache
def _modello_prompt(nome: str, cartella: str | None) -> Template:
    """Legge il file del prompt: dalla cartella LLM_PROMPT_DIR se c'è, altrimenti predefinito."""
    file = CARTELLA_PROMPT / f"{nome}.md"
    if cartella and (Path(cartella) / f"{nome}.md").is_file():
        file = Path(cartella) / f"{nome}.md"
    modello = Template(file.read_text(encoding="utf-8").rstrip("\n"))
    sconosciuti = set(modello.get_identifiers()) - SEGNAPOSTO[nome]
    if not modello.is_valid() or sconosciuti:
        dettaglio = f"segnaposto sconosciuti {sorted(sconosciuti)}" if sconosciuti else "sintassi"
        raise ValueError(
            f"Prompt {file} non valido ({dettaglio}). Segnaposto ammessi: "
            f"{sorted(SEGNAPOSTO[nome]) or 'nessuno'}; per un $ letterale scrivere $$"
        )
    log.debug("Prompt %s letto da %s", nome, file)
    return modello


def testo_prompt(nome: str, **valori: str) -> str:
    """Testo del prompt `nome` con i segnaposto ${...} sostituiti dai valori."""
    return _modello_prompt(nome, get_settings().llm_prompt_dir).substitute(valori)


def verifica_prompt() -> None:
    """Carica tutti i prompt: un file mancante o non valido blocca l'avvio."""
    for nome in SEGNAPOSTO:
        _modello_prompt(nome, get_settings().llm_prompt_dir)


class LlmError(Exception):
    pass


def _accorcia(testo: str, massimo: int = 4000) -> str:
    """Limita i testi lunghi (prompt con l'intero atto) nei log di debug."""
    if len(testo) <= massimo:
        return testo
    return f"{testo[:massimo]}\n[... altri {len(testo) - massimo} caratteri ...]"


def costruisci_prompt(
    titolo: str,
    regola: str,
    testo_atto: str,
    norme: list[tuple[str, str]],
    data_riferimento: str,
    max_caratteri: int = MAX_CARATTERI_ATTO,
) -> str:
    """Messaggio per la valutazione di un elemento di checklist (verifica_utente.md)."""
    if len(testo_atto) > max_caratteri:
        testo_atto = testo_atto[:max_caratteri] + "\n[... testo troncato ...]"
    sezione_norme = ""
    if norme:
        blocchi = "\n\n".join(
            testo_prompt("verifica_norma", citazione=citazione, testo=testo)
            for citazione, testo in norme
        )
        sezione_norme = testo_prompt("verifica_norme", norme=blocchi) + "\n\n"
    return testo_prompt(
        "verifica_utente",
        titolo=titolo,
        regola=regola,
        data_riferimento=data_riferimento,
        norme=sezione_norme,
        testo_atto=testo_atto,
    )


class LlmClient:
    """Logica comune a tutti i provider: prompt, nuovo tentativo, log.

    Ogni provider implementa `_completa`, che riceve il prompt di sistema e i messaggi
    (ruoli `user`/`assistant`) e restituisce il testo della risposta.
    """

    provider = "?"

    def __init__(
        self,
        modello: str,
        *,
        timeout: float = 180.0,
        timeout_redazione: float = 60.0,
        max_caratteri_atto: int = MAX_CARATTERI_ATTO,
    ):
        self.modello = modello
        self.timeout = timeout
        self.timeout_redazione = timeout_redazione
        self.max_caratteri_atto = max_caratteri_atto

    async def close(self) -> None:
        pass

    async def _completa(
        self,
        sistema: str,
        messaggi: list[dict],
        *,
        formato: type[BaseModel] | None,
        redazione: bool,
    ) -> str:
        raise NotImplementedError

    async def _chiama(
        self,
        sistema: str,
        messaggi: list[dict],
        *,
        formato: type[BaseModel] | None,
        redazione: bool,
    ) -> str:
        log.debug(
            "Richiesta a %s (modello %s, %d messaggi, %d caratteri)",
            self.provider,
            self.modello,
            len(messaggi),
            len(sistema) + sum(len(m["content"]) for m in messaggi),
        )
        log.debug("Ultimo messaggio inviato:\n%s", _accorcia(messaggi[-1]["content"]))
        inizio = time.perf_counter()
        contenuto = await self._completa(sistema, messaggi, formato=formato, redazione=redazione)
        log.debug(
            "Risposta del modello in %.1f s:\n%s",
            time.perf_counter() - inizio,
            _accorcia(contenuto),
        )
        return contenuto

    @staticmethod
    def _interpreta(contenuto: str, formato: type[M]) -> M:
        testo = contenuto.strip()
        if testo.startswith("```"):
            testo = testo.strip("`").removeprefix("json").strip()
        inizio, fine = testo.find("{"), testo.rfind("}")
        if inizio == -1 or fine == -1:
            raise ValueError("Nessun oggetto JSON nella risposta")
        return formato.model_validate(json.loads(testo[inizio : fine + 1]))

    async def _valuta_json(
        self, sistema: str, prompt: str, formato: type[M], *, interattiva: bool = False
    ) -> M:
        """Richiesta con risposta JSON conforme a `formato`; se non valida si riprova una volta.

        `interattiva`: durante una richiesta HTTP, con il timeout breve della redazione.
        """
        messaggi = [{"role": "user", "content": prompt}]
        contenuto = await self._chiama(sistema, messaggi, formato=formato, redazione=interattiva)
        try:
            return self._interpreta(contenuto, formato)
        except (ValueError, ValidationError) as e:
            log.warning("Risposta del modello non valida, nuovo tentativo: %s", e)
            messaggi += [
                {"role": "assistant", "content": contenuto},
                {"role": "user", "content": testo_prompt("verifica_correzione")},
            ]
            contenuto = await self._chiama(
                sistema, messaggi, formato=formato, redazione=interattiva
            )
            try:
                return self._interpreta(contenuto, formato)
            except (ValueError, ValidationError) as e2:
                raise LlmError(f"Risposta del modello non valida: {e2}") from e2

    async def valuta(self, prompt: str) -> EsitoElemento:
        """Valutazione di un elemento di checklist."""
        return await self._valuta_json(testo_prompt("verifica_sistema"), prompt, EsitoElemento)

    async def valuta_coerenza(self, prompt: str) -> EsitiCoerenza:
        """Coerenza tra un gruppo di riferimenti normativi e il contenuto dell'atto."""
        return await self._valuta_json(testo_prompt("coerenza_sistema"), prompt, EsitiCoerenza)

    async def riconosci_citazioni(self, prompt: str) -> CitazioniNorme:
        """Citazioni delle norme manuali sfuggite al riconoscimento per denominazione."""
        return await self._valuta_json(
            testo_prompt("riconoscimento_sistema"), prompt, CitazioniNorme
        )

    async def trova_dati_personali(self, prompt: str, *, interattiva: bool = False) -> DatiTrovati:
        """Dati personali presenti in un testo (o in una sua parte)."""
        return await self._valuta_json(
            testo_prompt("dati_personali_sistema"), prompt, DatiTrovati, interattiva=interattiva
        )

    async def scrivi(self, sistema: str, testo: str) -> str:
        """Testo libero (redazione): richiesta interattiva, con il suo timeout."""
        messaggi = [{"role": "user", "content": testo}]
        return await self._chiama(sistema, messaggi, formato=None, redazione=True)


class ClientCompatibileOpenAI(LlmClient):
    """API `/chat/completions` compatibile OpenAI: Ollama, vLLM, llama.cpp, OpenAI, Gemini."""

    def __init__(
        self,
        base_url: str,
        modello: str,
        api_key: str = "",
        *,
        provider: str = "openai_compatibile",
        temperatura: float | None = 0.0,
        temperatura_redazione: float | None = 0.2,
        http: httpx.AsyncClient | None = None,
        **opzioni,
    ):
        super().__init__(modello, **opzioni)
        self.provider = provider
        self.temperatura = temperatura
        self.temperatura_redazione = temperatura_redazione
        self._url = base_url.rstrip("/") + "/chat/completions"
        intestazioni = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http or httpx.AsyncClient(timeout=self.timeout, headers=intestazioni)

    async def close(self) -> None:
        await self._http.aclose()

    async def _completa(
        self,
        sistema: str,
        messaggi: list[dict],
        *,
        formato: type[BaseModel] | None,
        redazione: bool,
    ) -> str:
        payload: dict = {
            "model": self.modello,
            "messages": [{"role": "system", "content": sistema}, *messaggi],
        }
        temperatura = self.temperatura_redazione if redazione else self.temperatura
        if temperatura is not None:
            payload["temperature"] = temperatura
        if formato is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": formato.__name__, "schema": formato.model_json_schema()},
            }
        try:
            r = await self._http.post(
                self._url,
                json=payload,
                timeout=self.timeout_redazione if redazione else self.timeout,
            )
            r.raise_for_status()
            dati = r.json()
            log.debug("Token usati: %s", dati.get("usage"))
            return dati["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            log.warning(
                "Chiamata a %s (%s) fallita: HTTP %d %s",
                self.provider,
                self.modello,
                e.response.status_code,
                e.response.text[:300],
            )
            raise LlmError(f"Chiamata al modello fallita: HTTP {e.response.status_code}") from e
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            log.warning("Chiamata a %s (%s) fallita: %s", self.provider, self.modello, e)
            raise LlmError(f"Chiamata al modello fallita: {e}") from e


# Fallback lato server: se i filtri di sicurezza di Claude rifiutano una richiesta, l'API
# la riesegue sul modello che Anthropic raccomanda per quella categoria di rifiuto.
BETA_FALLBACK = "server-side-fallback-2026-07-01"


class ClientAnthropic(LlmClient):
    """Claude tramite l'SDK ufficiale `anthropic` (Messages API).

    Gli esiti usano gli output strutturati (`output_format`): la risposta è JSON conforme
    allo schema. Il ragionamento del modello è regolato da `effort`; la temperatura non si
    imposta (i modelli Claude attuali non la accettano).
    """

    provider = "anthropic"

    def __init__(
        self,
        modello: str,
        api_key: str = "",
        *,
        base_url: str | None = None,
        effort: str = "medium",
        max_token: int = 16_000,
        fallback: bool = True,
        client: anthropic.AsyncAnthropic | None = None,
        **opzioni,
    ):
        super().__init__(modello, **opzioni)
        self.effort = effort
        self.max_token = max_token
        # Claude Haiku non ha un fallback lato server: il parametro non va inviato
        self.fallback = fallback and "haiku" not in modello
        # senza chiave l'SDK usa ANTHROPIC_API_KEY o le credenziali di `ant auth login`
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key or None, base_url=base_url or None, timeout=self.timeout
        )

    async def close(self) -> None:
        await self._client.close()

    async def _completa(
        self,
        sistema: str,
        messaggi: list[dict],
        *,
        formato: type[BaseModel] | None,
        redazione: bool,
    ) -> str:
        argomenti: dict = {
            "model": self.modello,
            "max_tokens": self.max_token,
            "system": sistema,
            "messages": messaggi,
            "output_config": {"effort": self.effort},
            "timeout": self.timeout_redazione if redazione else self.timeout,
        }
        if self.fallback:
            argomenti["betas"] = [BETA_FALLBACK]
            argomenti["fallbacks"] = "default"
        try:
            if formato is not None:
                risposta = await self._client.beta.messages.parse(
                    **argomenti, output_format=formato
                )
            else:
                risposta = await self._client.beta.messages.create(**argomenti)
        except ValidationError as e:
            # testo non conforme allo schema (es. risposta interrotta da un rifiuto)
            raise LlmError(f"Risposta del modello non valida: {e}") from e
        except anthropic.APIStatusError as e:
            log.warning(
                "Chiamata ad Anthropic (%s) fallita: HTTP %d %s (request-id %s)",
                self.modello,
                e.status_code,
                e.message,
                e.request_id,
            )
            raise LlmError(f"Chiamata al modello fallita: HTTP {e.status_code}") from e
        except anthropic.APIError as e:
            log.warning("Chiamata ad Anthropic (%s) fallita: %s", self.modello, e)
            raise LlmError(f"Chiamata al modello fallita: {e}") from e

        log.debug("Token usati: %s (modello %s)", risposta.usage, risposta.model)
        if risposta.stop_reason == "refusal":
            dettagli = risposta.stop_details
            categoria = dettagli.category if dettagli else None
            log.warning("Claude ha rifiutato la richiesta (categoria %s)", categoria)
            raise LlmError(f"Il modello ha rifiutato la richiesta (categoria: {categoria})")
        if risposta.stop_reason == "max_tokens":
            raise LlmError(f"Risposta interrotta: superato il limite di {self.max_token} token")
        return "".join(b.text for b in risposta.content if b.type == "text")


# Provider che inviano gli atti (con i dati personali) fuori dall'ente
PROVIDER_ESTERNI = {"openai", "gemini", "anthropic"}

# Indirizzi delle API dei provider (sovrascrivibili con LLM_BASE_URL)
BASE_URL_PREDEFINITI = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

# Modelli predefiniti per provider (sovrascrivibili con LLM_MODEL)
MODELLI_PREDEFINITI = {
    "ollama": "mistral-small",
    "openai": "gpt-5-mini",
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-opus-5-5",
}


def crea_llm(settings: Settings) -> LlmClient:
    """Client del provider scelto in configurazione (LLM_PROVIDER)."""
    verifica_prompt()
    provider = settings.llm_provider
    modello = settings.llm_model or MODELLI_PREDEFINITI.get(provider, "")
    if not modello:
        raise ValueError(f"LLM_MODEL è obbligatorio con LLM_PROVIDER={provider}")
    if provider in PROVIDER_ESTERNI:
        log.warning(
            "LLM esterno (%s, modello %s): il testo degli atti, compresi gli eventuali dati "
            "personali, viene inviato al fornitore",
            provider,
            modello,
        )
    opzioni = {
        "timeout": settings.llm_timeout,
        "timeout_redazione": settings.llm_timeout_redazione,
        "max_caratteri_atto": settings.llm_max_caratteri_atto,
    }
    if provider == "anthropic":
        return ClientAnthropic(
            modello,
            settings.llm_api_key,
            base_url=settings.llm_base_url,
            effort=settings.llm_effort,
            max_token=settings.llm_max_token,
            fallback=settings.llm_fallback,
            **opzioni,
        )

    predefinito = settings.llm_ollama_url if provider == "ollama" else None
    base_url = settings.llm_base_url or predefinito or BASE_URL_PREDEFINITI.get(provider)
    if not base_url:
        raise ValueError(f"LLM_BASE_URL è obbligatorio con LLM_PROVIDER={provider}")
    if provider in ("openai", "gemini") and not settings.llm_api_key:
        raise ValueError(f"LLM_API_KEY è obbligatorio con LLM_PROVIDER={provider}")
    # I modelli di ragionamento di OpenAI accettano solo la temperatura predefinita
    usa_temperatura = provider != "openai"
    return ClientCompatibileOpenAI(
        base_url,
        modello,
        settings.llm_api_key,
        provider=provider,
        temperatura=settings.llm_temperatura if usa_temperatura else None,
        temperatura_redazione=settings.llm_temperatura_redazione if usa_temperatura else None,
        **opzioni,
    )


async def espandi_appunti(client: LlmClient, sezione: str, appunti: str, oggetto: str) -> str:
    """Trasforma appunti sintetici nel testo formale di una sezione dell'atto."""
    testo = testo_prompt("redazione_utente", oggetto=oggetto, sezione=sezione, appunti=appunti)
    return (await client.scrivi(testo_prompt("redazione_sistema"), testo)).strip()
