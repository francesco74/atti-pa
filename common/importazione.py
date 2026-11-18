"""Importazione con l'LLM di dati da documenti lunghi (PIAO, Piano della performance, PTPCT),
a parti: il testo si divide in parti di qualche decina di migliaia di caratteri, sovrapposte
perché una scheda o una tabella spezzata tra due parti si legga intera almeno in una; ogni parte
che può contenere i dati cercati (`pertinente`) va al modello con le istruzioni e lo schema della
risposta, e chi chiama unisce i risultati. Il modello trascrive, non inventa: i dati si rivedono
prima di salvarli.

Le parti si leggono una alla volta: con i modelli locali la risposta di una parte (una tabella
trascritta) richiede uno o due minuti. Una parte non letta (modello che non risponde, risposta
non valida) non ferma le altre: diventa un avviso.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from common.llm import LlmError, testo_prompt
from common.trasparenza.estrazione import json_schema

log = logging.getLogger(__name__)

PARTE = 18_000  # caratteri per parte: la risposta resta nel timeout dell'LLM
SOVRAPPOSIZIONE = 1_500
MAX_PARTI = 60  # oltre, il lavoro supererebbe il tempo massimo del worker
MAX_TESTO = 2_000_000


class ImportazioneNonRiuscita(ValueError):
    """Documento senza i dati cercati, troppo lungo o illeggibile: errore definitivo del lavoro."""


def parti(testo: str, dimensione: int = PARTE, sovrapposizione: int = SOVRAPPOSIZIONE) -> list[str]:
    """Il testo in parti di al più [dimensione] caratteri, tagliate a fine riga quando si può,
    ognuna che riprende le ultime [sovrapposizione] della precedente."""
    testo = re.sub(r"[ \t]{3,}", "  ", testo)  # gli allineamenti delle tabelle in PDF: solo spazio
    risultato, inizio = [], 0
    while inizio < len(testo):
        fine = min(inizio + dimensione, len(testo))
        if fine < len(testo):
            a_capo = testo.rfind("\n", inizio + dimensione // 2, fine)
            fine = a_capo + 1 if a_capo > 0 else fine
        risultato.append(testo[inizio:fine])
        if fine >= len(testo):
            break
        inizio = max(fine - sovrapposizione, inizio + 1)
    return risultato


async def estrai_a_parti(
    testo: str,
    llm,
    *,
    prompt: str,
    schema: dict,
    pertinente: Callable[[str], bool],
    cosa: str,
    avanza: Callable[[int, int], Awaitable[None]] | None = None,
    dimensione: int = PARTE,
) -> tuple[list[dict], list[str]]:
    """Le risposte del modello per ogni parte pertinente del testo, con gli avvisi sulle parti
    non lette. [prompt]: nome del prompt dell'utente (segnaposto `testo`); [schema]: risposta in
    stile Gemini (common/trasparenza/estrazione); [cosa]: cosa si cerca, per i messaggi."""
    if len(testo) > MAX_TESTO:
        raise ImportazioneNonRiuscita(
            f"Documento troppo lungo ({len(testo):,} caratteri, massimo {MAX_TESTO:,}): carica solo la parte con {cosa}".replace(",", ".")
        )
    candidate = [p for p in parti(testo, dimensione) if pertinente(p)]
    if not candidate:
        raise ImportazioneNonRiuscita(f"Nel documento non ci sono {cosa}")
    if len(candidate) > MAX_PARTI:
        raise ImportazioneNonRiuscita(
            f"Documento troppo lungo ({len(candidate)} parti da leggere, massimo {MAX_PARTI}): carica solo la parte con {cosa}"
        )
    sistema, formato = testo_prompt("importazione_sistema"), json_schema(schema)
    risposte, avvisi = [], []
    for i, parte in enumerate(candidate, start=1):
        try:
            risposte.append(await llm.dati_json(sistema, testo_prompt(prompt, testo=parte), formato))
        except LlmError as e:
            log.warning("Importazione: parte %d di %d non letta: %s", i, len(candidate), e)
            avvisi.append(f"Parte {i} di {len(candidate)} del documento non letta: {e}")
        if avanza is not None:
            await avanza(i, len(candidate))
    if not risposte:
        raise ImportazioneNonRiuscita(f"Il documento non si è potuto leggere: {avvisi[0] if avvisi else 'nessuna risposta'}")
    return risposte, avvisi
