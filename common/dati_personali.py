"""Rilevamento dei dati personali da valutare per la pubblicazione (omissis), con l'LLM.

Il modello legge il testo e restituisce, per ogni dato, la categoria e il testo esatto
(nome, codice fiscale, frase che rivela una condizione di salute...): riconosce anche i dati
scritti in forme libere e distingue dal contesto i dati delle persone fisiche da quelli di
imprese, enti e funzionari nell'esercizio delle funzioni. Un dato proposto dal modello è
accettato solo se il testo indicato si trova davvero nell'atto; ogni sua occorrenza
diventa un dato da oscurare.

Gli atti più lunghi del limite dell'LLM (LLM_MAX_CARATTERI_ATTO) sono divisi in parti,
così nessuna parte del testo resta senza controllo.

Non sostituisce la valutazione del responsabile: segnala i punti da controllare.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from common.llm import LlmClient, LlmError, testo_prompt
from common.riconoscimento import posizioni_estratto

log = logging.getLogger("common.dati_personali")

# Categorie particolari (art. 9 GDPR), dati giudiziari (art. 10), minori e dati da cui si
# ricavano l'identità o la situazione economica: priorità alta
_ALTA = {
    "CODICE_FISCALE",
    "DOCUMENTO",
    "IBAN",
    "SALUTE",
    "CONDIZIONE_ECONOMICA",
    "GIUDIZIARIO",
    "MINORE",
    "DATI_PARTICOLARI",
}


class StatoDatiPersonali:
    VALUTATI = "VALUTATI"
    NON_VALUTATI = "NON_VALUTATI"  # nessun modello, o rilevamento disattivato
    ERRORE = "ERRORE"


class DatiPersonaliNonDisponibili(Exception):
    """Il modello non ha risposto: il rilevamento non è stato eseguito."""


@dataclass
class DatoPersonale:
    categoria: str
    testo: str
    inizio: int
    fine: int
    priorita: str
    motivo: str | None = None


def _parti(testo: str, massimo: int) -> list[tuple[int, str]]:
    """Il testo in parti di al massimo `massimo` caratteri, tagliate tra due paragrafi."""
    parti, inizio = [], 0
    while inizio < len(testo):
        fine = min(len(testo), inizio + massimo)
        if fine < len(testo):
            taglio = testo.rfind("\n\n", inizio + massimo // 2, fine)
            if taglio == -1:
                taglio = testo.rfind("\n", inizio + massimo // 2, fine)
            fine = taglio if taglio != -1 else fine
        parti.append((inizio, testo[inizio:fine]))
        inizio = fine
    return parti


async def trova_dati_personali(
    llm: LlmClient, testo: str, *, interattiva: bool = False
) -> list[DatoPersonale]:
    """Dati personali nel testo secondo il modello, con la loro posizione.

    `interattiva`: chiamata durante una richiesta HTTP (timeout breve, LLM_TIMEOUT_REDAZIONE).
    Solleva DatiPersonaliNonDisponibili se il modello non risponde.
    """
    candidati: list[DatoPersonale] = []
    parti = _parti(testo, llm.max_caratteri_atto)
    for n, (scostamento, parte) in enumerate(parti, 1):
        if not parte.strip():
            continue
        prompt = testo_prompt(
            "dati_personali_utente",
            parte=f"parte {n} di {len(parti)}" if len(parti) > 1 else "testo completo",
            testo_atto=parte,
        )
        try:
            risposta = await llm.trova_dati_personali(prompt, interattiva=interattiva)
        except LlmError as e:
            raise DatiPersonaliNonDisponibili(str(e)) from e
        for d in risposta.dati:
            posizioni = posizioni_estratto(parte, d.testo)
            if not posizioni:
                log.debug("Dato proposto dal modello non presente nel testo: %r", d.testo)
                continue
            for inizio, fine in posizioni:
                candidati.append(
                    DatoPersonale(
                        categoria=d.categoria,
                        testo=testo[scostamento + inizio : scostamento + fine],
                        inizio=scostamento + inizio,
                        fine=scostamento + fine,
                        priorita="ALTA" if d.categoria in _ALTA else "MEDIA",
                        motivo=d.motivo,
                    )
                )
    # dati sovrapposti (es. un nome dentro una frase sulla salute): vale il più ampio
    candidati.sort(key=lambda d: (d.inizio - d.fine, d.inizio))
    scelti: list[DatoPersonale] = []
    for d in candidati:
        if not any(d.inizio < s.fine and s.inizio < d.fine for s in scelti):
            scelti.append(d)
    log.debug("%d dati personali rilevati dal modello", len(scelti))
    return sorted(scelti, key=lambda d: d.inizio)


def applica_omissis(testo: str, dati: list[DatoPersonale], marcatore: str = "[OMISSIS]") -> str:
    """Sostituisce i dati indicati con il marcatore, dalla fine per non spostare gli indici."""
    for d in sorted(dati, key=lambda d: d.inizio, reverse=True):
        testo = testo[: d.inizio] + marcatore + testo[d.fine :]
    return testo


def come_dict(dati: list[DatoPersonale]) -> list[dict]:
    return [asdict(d) for d in dati]
