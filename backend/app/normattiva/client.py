"""Client asincrono per le API OpenData di Normattiva.

Riferimento: "Normattiva - Specifiche API Open Data" (IPZS), rev. 10/03/2026.
Dati IPZS in licenza CC BY 4.0: citare la fonte quando si ridistribuiscono.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Self

import httpx

from app.config import get_settings
from app.normattiva.parser import Articolo, parse_articolo
from app.normattiva.urn import Urn

_PREFISSO = "/bff-opendata/v1/api/v1"
ATTRIBUZIONE = (
    "Fonte: Normattiva (https://www.normattiva.it), "
    "Istituto Poligrafico e Zecca dello Stato, licenza CC BY 4.0"
)


class NormattivaError(Exception):
    pass


class AttoNonTrovato(NormattivaError):
    pass


class RisultatoAmbiguo(NormattivaError):
    """La URN corrisponde a più testi (es. ripubblicazioni in GU)."""

    def __init__(self, urn: str, candidati: list[TestoArticolo]):
        super().__init__(f"{len(candidati)} risultati per {urn}")
        self.urn = urn
        self.candidati = candidati


@dataclass
class TestoArticolo:
    urn: str
    titolo_atto: str
    sottotitolo: str | None
    denominazione: str
    data_provvedimento: date | None
    numero: str
    data_gu: date | None
    vigenza_inizio: date | None
    vigenza_fine: date | None  # None = in vigore
    html: str
    articolo: Articolo

    def in_vigore_al(self, giorno: date) -> bool:
        if self.vigenza_inizio and giorno < self.vigenza_inizio:
            return False
        return not (self.vigenza_fine and giorno > self.vigenza_fine)


def _data_vigenza(valore: str | None) -> date | None:
    """Converte le date di vigenza Normattiva ("20130821", "99999999", "0")."""
    if not valore or valore in ("0", "99999999") or len(valore) != 8:
        return None
    try:
        return datetime.strptime(valore, "%Y%m%d").date()
    except ValueError:
        return None


def _data(anno: Any, mese: Any, giorno: Any) -> date | None:
    try:
        return date(int(anno), int(mese), int(giorno))
    except (TypeError, ValueError):
        return None


def _testo_da_risposta(urn: str, dati: dict) -> TestoArticolo:
    html = dati.get("articoloHtml") or ""
    sottotitolo = dati.get("sottoTitolo")
    return TestoArticolo(
        urn=urn,
        titolo_atto=(dati.get("titolo") or "").strip(),
        sottotitolo=" ".join(sottotitolo.split()) if sottotitolo else None,
        denominazione=dati.get("tipoProvvedimentoDescrizione") or "",
        data_provvedimento=_data(
            dati.get("annoProvvedimento"),
            dati.get("meseProvvedimento"),
            dati.get("giornoProvvedimento"),
        ),
        numero=str(dati.get("numeroProvvedimento") or ""),
        data_gu=_data(dati.get("annoGU"), dati.get("meseGU"), dati.get("giornoGU")),
        vigenza_inizio=_data_vigenza(dati.get("articoloDataInizioVigenza")),
        vigenza_fine=_data_vigenza(dati.get("articoloDataFineVigenza")),
        html=html,
        articolo=parse_articolo(html),
    )


class NormattivaClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        tentativi: int = 3,
        http: httpx.AsyncClient | None = None,
    ):
        settings = get_settings()
        self._base = (base_url or settings.normattiva_base_url).rstrip("/") + _PREFISSO
        self._tentativi = tentativi
        self._http = http or httpx.AsyncClient(
            timeout=timeout or settings.normattiva_timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def _post(self, percorso: str, payload: dict) -> Any:
        ultimo_errore: Exception | None = None
        for tentativo in range(self._tentativi):
            try:
                r = await self._http.post(self._base + percorso, json=payload)
            except httpx.TransportError as e:
                ultimo_errore = e
            else:
                if r.status_code == 404:
                    raise AttoNonTrovato(payload)
                if r.status_code < 500:
                    r.raise_for_status()
                    return r.json()
                ultimo_errore = NormattivaError(f"HTTP {r.status_code}: {r.text[:200]}")
            await asyncio.sleep(2**tentativo)
        raise NormattivaError(f"Normattiva non raggiungibile: {ultimo_errore}")

    async def articolo(self, urn: Urn | str, vigenza: date | None = None) -> TestoArticolo:
        """Testo di un articolo, vigente alla data indicata (default: oggi)."""
        u = Urn.parse(urn) if isinstance(urn, str) else urn
        if vigenza:
            u = u.alla_data(vigenza)
        if not u.articolo:
            raise ValueError("Specificare l'articolo nella URN (es. ~art50)")

        risposta = await self._post("/atto/dettaglio-atto-urn", {"urn": str(u)})
        dati = (risposta or {}).get("data") or {}
        if dati.get("atto"):
            return _testo_da_risposta(str(u), dati["atto"])
        lista = dati.get("lista") or []
        if not lista:
            raise AttoNonTrovato(str(u))
        candidati = [_testo_da_risposta(str(u), d) for d in lista]
        raise RisultatoAmbiguo(str(u), candidati)

    async def atti_aggiornati(self, da: datetime, a: datetime) -> list[dict]:
        """Atti modificati nell'intervallo (usato dal job di aggiornamento cache)."""
        risposta = await self._post(
            "/ricerca/aggiornati",
            {
                "dataInizioAggiornamento": da.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "dataFineAggiornamento": a.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            },
        )
        return (risposta or {}).get("listaAtti") or []

    async def ricerca(
        self, testo: str, pagina: int = 1, per_pagina: int = 20, recenti: bool = True
    ) -> dict:
        return await self._post(
            "/ricerca/semplice",
            {
                "testoRicerca": testo,
                "orderType": "recente" if recenti else "vecchio",
                "paginazione": {"paginaCorrente": pagina, "numeroElementiPerPagina": per_pagina},
            },
        )
