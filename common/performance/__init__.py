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


# --- controlli oggettivi sugli obiettivi -------------------------------------------------------

AVVISO, INFO = "AVVISO", "INFO"


def controlli_obiettivo(
    impegno: int,
    anno: int,
    struttura_id: str,
    elementi: list[dict],
    *,
    misure_attive: bool,
    strutture_misure: dict[str, str | None] | None = None,
) -> list[dict]:
    """Avvisi e informazioni su un obiettivo, senza modello: impegni a zero, scadenze fuori
    dall'anno, misure non più nella mappatura o di altre strutture, obiettivo senza azioni o
    senza misure della mappatura. [elementi]: {tipo, descrizione, impegno, scadenza (date),
    misura_id}; [strutture_misure]: misura_id -> struttura responsabile della misura."""
    esito: list[dict] = []

    def c(livello: str, testo: str) -> None:
        esito.append({"livello": livello, "testo": testo})

    if impegno == 0:
        c(AVVISO, "L'obiettivo ha impegno 0%: non conta nel completamento della struttura")
    if not elementi:
        c(AVVISO, "Nessuna azione o misura: il completamento non si può calcolare")
    elif misure_attive and not any(x["tipo"] == "MISURA" for x in elementi):
        c(INFO, "Nessuna misura della mappatura dei rischi collegata all'obiettivo")
    for x in elementi:
        nome = f"{'Azione' if x['tipo'] == 'AZIONE' else 'Misura'} «{(x['descrizione'] or '')[:60]}»"
        if (x.get("impegno") or 0) == 0:
            c(AVVISO, f"{nome}: impegno 0%, non conta nel completamento")
        scadenza = x.get("scadenza")
        if scadenza is not None and scadenza.year > anno:
            c(AVVISO, f"{nome}: scade il {scadenza:%d/%m/%Y}, dopo la fine dell'anno dell'obiettivo ({anno})")
        elif scadenza is not None and scadenza.year < anno:
            c(AVVISO, f"{nome}: scade il {scadenza:%d/%m/%Y}, prima dell'anno dell'obiettivo ({anno})")
        if x["tipo"] == "MISURA":
            if not x.get("misura_id"):
                c(AVVISO, f"{nome}: la misura non è più nella mappatura dei rischi")
            elif strutture_misure is not None:
                responsabile = strutture_misure.get(x["misura_id"])
                if responsabile and responsabile != struttura_id:
                    c(INFO, f"{nome}: la misura è attribuita a un'altra struttura nella mappatura")
    return sorted(esito, key=lambda v: v["livello"] != AVVISO)

