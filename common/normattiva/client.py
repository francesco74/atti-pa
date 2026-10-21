"""Client asincrono per le API OpenData di Normattiva.

Riferimento: "Normattiva - Specifiche API Open Data" (IPZS), rev. 10/03/2026.
Dati IPZS in licenza CC BY 4.0: citare la fonte quando si ridistribuiscono.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Self

import httpx

from common.config import get_settings
from common.normattiva.parser import Articolo, parse_articolo
from common.normattiva.urn import Urn

log = logging.getLogger("common.normattiva")

# suffissi degli articoli inseriti, nell'ordine dei "sottoarticoli" di Normattiva (bis = 2)
# flagTipoArticolo di /atto/dettaglio-atto: 0 articolo del testo, 2 articolo di un allegato
# (ricavato provando le API: la specifica OpenAPI non descrive i valori)
_ARTICOLO_TESTO = "0"
_ARTICOLO_ALLEGATO = "2"

_SOTTOARTICOLI = [
    "bis",
    "ter",
    "quater",
    "quinquies",
    "sexies",
    "septies",
    "octies",
    "novies",
    "decies",
]

_PREFISSO = "/bff-opendata/v1/api/v1"
ATTRIBUZIONE = (
    "Fonte: Normattiva (https://www.normattiva.it), "
    "Istituto Poligrafico e Zecca dello Stato, licenza CC BY 4.0"
)


def _descrivi_errore_rete(e: httpx.TransportError) -> str:
    """Errore di rete leggibile: i timeout di httpx non hanno messaggio."""
    if isinstance(e, httpx.ConnectTimeout):
        return (
            "nessuna risposta alla connessione (server irraggiungibile o bloccato da un "
            "firewall o da un proxy della rete)"
        )
    if isinstance(e, httpx.ReadTimeout):
        return "il server non ha risposto entro il tempo massimo (NORMATTIVA_TIMEOUT)"
    if isinstance(e, httpx.ConnectError):
        return f"connessione non riuscita: {e or type(e).__name__}"
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


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
    __test__ = False  # evita che pytest la scambi per una classe di test

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
    data_gu = _data(dati.get("annoGU"), dati.get("meseGU"), dati.get("giornoGU"))
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
        data_gu=data_gu,
        # inizio sconosciuto ("0"): una norma non è in vigore prima della pubblicazione in
        # Gazzetta (Normattiva lo restituisce anche per date anteriori alla legge)
        vigenza_inizio=_data_vigenza(dati.get("articoloDataInizioVigenza")) or data_gu,
        vigenza_fine=_data_vigenza(dati.get("articoloDataFineVigenza")),
        html=html,
        articolo=parse_articolo(html),
    )


class NormattivaClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        tentativi: int | None = None,
        http: httpx.AsyncClient | None = None,
    ):
        settings = get_settings()
        self._base = (base_url or settings.normattiva_base_url).rstrip("/") + _PREFISSO
        self._tentativi = tentativi or settings.normattiva_tentativi
        self._testi_principali: dict[str, tuple[str, str]] = {}  # URN atto -> (codice, data GU)
        self._date_atti: dict[str, str] = {}  # URN con il solo anno -> data completa
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
            log.debug("POST %s %s", percorso, payload)
            inizio = time.perf_counter()
            try:
                r = await self._http.post(self._base + percorso, json=payload)
            except httpx.TransportError as e:
                ultimo_errore = NormattivaError(_descrivi_errore_rete(e))
            else:
                log.debug(
                    "POST %s -> HTTP %d in %.0f ms",
                    percorso,
                    r.status_code,
                    (time.perf_counter() - inizio) * 1000,
                )
                if r.status_code == 404:
                    raise AttoNonTrovato(payload)
                if r.status_code >= 400 and r.status_code < 500:
                    # richiesta rifiutata (es. URN non valida): inutile riprovare
                    raise NormattivaError(
                        f"Richiesta rifiutata (HTTP {r.status_code}): {r.text[:200]}"
                    )
                if r.status_code < 500:
                    return r.json()
                ultimo_errore = NormattivaError(f"HTTP {r.status_code}: {r.text[:200]}")
            if tentativo + 1 == self._tentativi:
                break
            attesa = 2**tentativo
            log.warning(
                "Normattiva %s: tentativo %d/%d fallito (%s), nuovo tentativo tra %d s",
                percorso,
                tentativo + 1,
                self._tentativi,
                ultimo_errore,
                attesa,
            )
            await asyncio.sleep(attesa)
        raise NormattivaError(f"Normattiva non raggiungibile: {ultimo_errore}")

    async def articolo(self, urn: Urn | str, vigenza: date | None = None) -> TestoArticolo:
        """Testo di un articolo, vigente alla data indicata (default: oggi)."""
        u = Urn.parse(urn) if isinstance(urn, str) else urn
        if not u.articolo:
            raise ValueError("Specificare l'articolo nella URN (es. ~art50)")
        if len(u.data) == 4:
            # citazione con il solo anno (es. "D.P.R. 62/2013"): Normattiva vuole la data
            u = await self.con_data_completa(u)
        if vigenza:
            u = u.alla_data(vigenza)

        try:
            risposta = await self._post("/atto/dettaglio-atto-urn", {"urn": str(u)})
        except AttoNonTrovato:
            # es. TUEL art. 147-bis: la URN viene risolta sulla ripubblicazione del 2000, che
            # non contiene gli articoli inseriti dopo; si cerca nel testo principale
            return await self._articolo_da_testo_principale(u, vigenza or date.today())
        dati = (risposta or {}).get("data") or {}
        if dati.get("atto"):
            return _testo_da_risposta(str(u), dati["atto"])
        lista = dati.get("lista") or []
        if not lista:
            raise AttoNonTrovato(str(u))
        candidati = [_testo_da_risposta(str(u), d) for d in lista]
        raise RisultatoAmbiguo(str(u), candidati)

    async def con_data_completa(self, u: Urn) -> Urn:
        """La URN con la data completa del provvedimento, se nella citazione c'è solo l'anno.

        Normattiva rifiuta le URN con il solo anno; la ricerca avanzata sull'intero anno per
        numero trova l'atto, di cui si tiene quello dello stesso tipo (un D.P.R. e una legge
        possono avere lo stesso numero nello stesso anno).
        """
        if len(u.data) != 4:
            return u
        chiave = u.atto
        if chiave not in self._date_atti:
            risposta = await self._post(
                "/ricerca/avanzata",
                {
                    "dataInizioEmanazione": f"{u.data}-01-01",
                    "dataFineEmanazione": f"{u.data}-12-31",
                    "numeroProvvedimento": u.numero,
                    "orderType": "vecchio",
                    "paginazione": {"paginaCorrente": 1, "numeroElementiPerPagina": 20},
                },
            )
            trovati = [
                t
                for a in (risposta or {}).get("listaAtti") or []
                if (t := Urn.da_metadati(a)) is not None
                and (t.autorita, t.denominazione, t.numero) == (u.autorita, u.denominazione, u.numero)
            ]
            if not trovati:
                raise AttoNonTrovato(chiave)
            self._date_atti[chiave] = trovati[0].data
            log.debug("%s: data del provvedimento %s", chiave, trovati[0].data)
        return replace(u, data=self._date_atti[chiave])

    async def _testo_principale(self, u: Urn) -> tuple[str, str]:
        """Codice redazionale e data di Gazzetta del testo principale dell'atto.

        La ricerca avanzata per data e numero restituisce il testo principale, non le sue
        ripubblicazioni.
        """
        chiave = u.atto
        if chiave not in self._testi_principali:
            risposta = await self._post(
                "/ricerca/avanzata",
                {
                    "dataInizioEmanazione": u.data,
                    "dataFineEmanazione": u.data,
                    "numeroProvvedimento": u.numero,
                    "orderType": "vecchio",
                    "paginazione": {"paginaCorrente": 1, "numeroElementiPerPagina": 10},
                },
            )
            atti = [
                a
                for a in (risposta or {}).get("listaAtti") or []
                if a.get("codiceRedazionale") and a.get("dataGU")
            ]
            if not atti:
                raise AttoNonTrovato(chiave)
            self._testi_principali[chiave] = (atti[0]["codiceRedazionale"], atti[0]["dataGU"])
        return self._testi_principali[chiave]

    async def _articolo_da_testo_principale(self, u: Urn, vigenza: date) -> TestoArticolo:
        m = re.fullmatch(r"(\d+)(?:-([a-z]+))?", u.articolo or "")
        if not m or (m[2] and m[2] not in _SOTTOARTICOLI):
            raise AttoNonTrovato(str(u))
        codice, data_gu = await self._testo_principale(u)
        # articolo del testo dell'atto o degli allegati (es. il codice del processo
        # amministrativo è l'allegato 1 del D.Lgs. 104/2010): con l'allegato nella URN si
        # cerca prima lì
        tipi = [_ARTICOLO_TESTO, _ARTICOLO_ALLEGATO]
        if u.allegato:
            tipi.reverse()
        for tipo in tipi:
            log.debug("%s: cerco nel testo principale %s (tipo articolo %s)", u, codice, tipo)
            try:
                risposta = await self._post(
                    "/atto/dettaglio-atto",
                    {
                        "dataGU": data_gu,
                        "codiceRedazionale": codice,
                        "idArticolo": int(m[1]),
                        "sottoArticolo": _SOTTOARTICOLI.index(m[2]) + 2 if m[2] else 1,
                        "flagTipoArticolo": tipo,
                        "dataVigenza": vigenza.isoformat(),
                    },
                )
            except AttoNonTrovato:
                continue
            atto = ((risposta or {}).get("data") or {}).get("atto")
            if atto and atto.get("articoloHtml"):
                return _testo_da_risposta(str(u), atto)
        raise AttoNonTrovato(str(u))

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


def testo_principale(errore: RisultatoAmbiguo) -> TestoArticolo | None:
    """Tra più risultati per la stessa URN preferisce il testo principale.

    Le ripubblicazioni in Gazzetta (testo corredato di note) vengono scartate; se resta più
    di un candidato la scelta è lasciata all'utente.
    """
    principali = [
        c for c in errore.candidati if "ripubblicazione" not in (c.sottotitolo or "").lower()
    ]
    return principali[0] if len(principali) == 1 else None
