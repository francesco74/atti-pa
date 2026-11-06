"""Modulo performance: regole e calcoli comuni.

Un obiettivo annuale di una struttura ha una percentuale di impegno rispetto agli altri
obiettivi della stessa struttura nello stesso anno; è composto da azioni e misure, ciascuna con
l'impegno rispetto alle altre dello stesso obiettivo, il completamento e una scadenza. Gli
impegni di un insieme non possono superare 100 e l'insieme è completo quando arrivano a 100.

Il completamento di un obiettivo è la media dei completamenti delle azioni e misure pesata con
il loro impegno; quello di una struttura in un anno è la media dei completamenti degli obiettivi
pesata con il loro impegno. Finché gli impegni non arrivano a 100 il valore si calcola sui pesi
presenti ed è provvisorio (l'insieme è segnato incompleto).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

TOTALE = 100
TIPI_OBIETTIVO = ("OPERATIVO", "FUNZIONAMENTO", "MIGLIORAMENTO")
TIPI_ELEMENTO = ("AZIONE", "MISURA")


def media_pesata(voci: Iterable[tuple[int, float | None]]) -> float | None:
    """Media dei valori pesata con gli impegni; None se non c'è nessun peso. Un valore None
    (es. obiettivo senza azioni) conta come 0."""
    totale = somma = 0.0
    for impegno, valore in voci:
        totale += impegno or 0
        somma += (impegno or 0) * (valore or 0)
    return round(somma / totale, 1) if totale else None


def disponibile(impegni_altri: Iterable[int]) -> int:
    """Impegno che resta da assegnare nell'insieme (altri elementi già presenti)."""
    return TOTALE - sum(i or 0 for i in impegni_altri)


def in_ritardo(scadenza: date | None, completamento: int | None, oggi: date | None = None) -> bool:
    """Scadenza passata senza il completamento al 100%."""
    return scadenza is not None and scadenza < (oggi or date.today()) and (completamento or 0) < TOTALE
