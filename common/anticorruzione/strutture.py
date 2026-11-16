"""Riconoscimento delle strutture dell'anagrafica in un testo libero (es. le note sulle
strutture coinvolte di un'attività): per codice ("U.O. 2.1", "SETTORE 3") o per descrizione
intera, se abbastanza lunga da non essere ambigua."""

from __future__ import annotations

import re
from collections.abc import Iterable

# una descrizione si riconosce solo se ha almeno tanti caratteri (es. "Gare" no)
DESCRIZIONE_MINIMA = 12


def _spazi(testo: str) -> str:
    return re.sub(r"\s+", " ", testo).strip().lower()


def _modello_codice(codice: str) -> re.Pattern[str]:
    """Il codice come parola intera: "U.O. 2.1" non trova "U.O. 2.10" né "U.O. 2.1.3"."""
    parti = [re.escape(p) for p in _spazi(codice).split(" ")]
    return re.compile(r"(?<![\w.])" + r"\s*".join(parti) + r"(?![\w]|\.\d)", re.IGNORECASE)


def riconosci_strutture(testo: str | None, strutture: Iterable[tuple[str, str, str | None]]) -> list[str]:
    """Id delle strutture nominate nel testo, nell'ordine dell'anagrafica. [strutture]: (id,
    codice, descrizione)."""
    if not testo or not testo.strip():
        return []
    normale = _spazi(testo)
    trovate = []
    for sid, codice, descrizione in strutture:
        per_codice = bool(codice) and _modello_codice(codice).search(testo) is not None
        per_descrizione = bool(descrizione) and len(descrizione.strip()) >= DESCRIZIONE_MINIMA and _spazi(descrizione) in normale
        if per_codice or per_descrizione:
            trovate.append(sid)
    return trovate
