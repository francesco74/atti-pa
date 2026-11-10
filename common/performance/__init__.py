"""Modulo performance: regole e calcoli comuni.

Un obiettivo annuale di una struttura ha una percentuale di impegno rispetto agli altri
obiettivi della stessa struttura nello stesso anno; è composto da azioni e misure, ciascuna con
l'impegno rispetto alle altre dello stesso obiettivo, il completamento e una scadenza. Gli
impegni di un insieme non possono superare 100 e l'insieme è completo quando arrivano a 100.

Il completamento di un obiettivo è la media dei completamenti delle azioni e misure pesata con
il loro impegno; quello di una struttura in un anno è la media dei completamenti degli obiettivi
pesata con il loro impegno. Finché gli impegni non arrivano a 100 il valore si calcola sui pesi
presenti ed è provvisorio (l'insieme è segnato incompleto).

Un'azione o misura può avere degli indicatori: cosa si misura, il valore da raggiungere
(target) e quello rilevato. Con almeno un indicatore il suo completamento è la media del
raggiungimento degli indicatori (ciascuno da 0 a 100); senza, si inserisce a mano.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

TOTALE = 100
TIPI_OBIETTIVO = ("OPERATIVO", "FUNZIONAMENTO", "MIGLIORAMENTO")
TIPI_ELEMENTO = ("AZIONE", "MISURA")
TIPI_INDICATORE = ("NUMERO", "PERCENTUALE", "SI_NO", "DATA")
VERSI = ("CRESCENTE", "DECRESCENTE")


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


# --- indicatori -------------------------------------------------------------------------------
# Un indicatore è un dict con: tipo, partenza, target, target_data, verso, rilevato,
# rilevato_data (le date come date o in ISO).


def _data(v) -> date | None:
    return date.fromisoformat(v) if isinstance(v, str) else v


def raggiungimento(ind: dict) -> float:
    """Quanto dell'indicatore è raggiunto, da 0 a 100.

    - numero, percentuale: crescente (rilevato - partenza) / (target - partenza), con la partenza
      a 0 se manca; decrescente (partenza - rilevato) / (partenza - target), o senza partenza
      target / rilevato; a target raggiunto 100;
    - sì/no: 100 se rilevato "sì";
    - data: 100 se raggiunto entro la data del target.
    Senza rilevazione 0."""
    tipo = ind.get("tipo")
    if tipo == "SI_NO":
        return 100.0 if ind.get("rilevato") == 1 else 0.0
    if tipo == "DATA":
        fatto, entro = _data(ind.get("rilevato_data")), _data(ind.get("target_data"))
        return 100.0 if fatto is not None and entro is not None and fatto <= entro else 0.0
    rilevato, target, partenza = ind.get("rilevato"), ind.get("target"), ind.get("partenza")
    if rilevato is None or target is None:
        return 0.0
    if ind.get("verso") == "DECRESCENTE":
        if rilevato <= target:
            return 100.0
        if partenza is None:
            valore = target / rilevato * 100 if rilevato > 0 else 0.0
        else:
            valore = (partenza - rilevato) / (partenza - target) * 100 if partenza > target else 0.0
    else:
        if rilevato >= target:
            return 100.0
        partenza = partenza or 0.0
        valore = (rilevato - partenza) / (target - partenza) * 100 if target > partenza else 0.0
    return round(min(max(valore, 0.0), 100.0), 1)


def completamento_indicatori(indicatori: Iterable[dict]) -> int | None:
    """Completamento di un'azione o misura dai suoi indicatori (media del raggiungimento,
    arrotondata); None senza indicatori (si inserisce a mano)."""
    valori = [raggiungimento(i) for i in indicatori]
    return int(sum(valori) / len(valori) + 0.5) if valori else None


def errore_indicatore(ind: dict) -> str | None:
    """Cosa manca o non torna nella definizione di un indicatore (None: va bene)."""
    tipo, target, partenza = ind.get("tipo"), ind.get("target"), ind.get("partenza")
    if tipo not in TIPI_INDICATORE:
        return "tipo non valido"
    if tipo == "DATA":
        return None if ind.get("target_data") else "indica la data entro cui raggiungerlo"
    if tipo == "SI_NO":
        return None
    if target is None:
        return "indica il valore da raggiungere (target)"
    if tipo == "PERCENTUALE" and not (0 <= target <= 100 and (partenza is None or 0 <= partenza <= 100)):
        return "le percentuali vanno da 0 a 100"
    if partenza is not None:
        if ind.get("verso") == "DECRESCENTE" and partenza <= target:
            return "se più basso è meglio, la partenza deve essere più alta del target"
        if ind.get("verso") != "DECRESCENTE" and partenza >= target:
            return "la partenza deve essere più bassa del target"
    return None


def numero(v: float | None) -> str:
    """Numero in forma italiana, senza decimali inutili: 3.0 -> "3", 2.5 -> "2,5"."""
    if v is None:
        return "—"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}".rstrip("0").replace(".", ",")


def valore_indicatore(ind: dict, valore: float | date | str | None) -> str:
    """Un valore (target, partenza o rilevato) nella forma dell'indicatore."""
    tipo = ind.get("tipo")
    if valore is None:
        return "—"
    if tipo == "DATA":
        return f"{_data(valore):%d/%m/%Y}"
    if tipo == "SI_NO":
        return "sì" if valore == 1 else "no"
    if tipo == "PERCENTUALE":
        return f"{numero(valore)}%"
    return f"{numero(valore)} {ind.get('unita') or ''}".strip()


def testo_indicatore(ind: dict) -> str:
    """Sintesi della definizione, es. "Eventi a cui si partecipa: 3 eventi"; "Tempo medio: da
    40 a 30 giorni (più basso è meglio)"; "Regolamento adottato: sì"; "...: entro il 30/06/2026"."""
    tipo = ind.get("tipo")
    if tipo == "SI_NO":
        obiettivo = "sì"
    elif tipo == "DATA":
        obiettivo = f"entro il {valore_indicatore(ind, ind.get('target_data'))}"
    else:
        obiettivo = valore_indicatore(ind, ind.get("target"))
        if ind.get("partenza") is not None:
            obiettivo = f"da {valore_indicatore(ind, ind.get('partenza'))} a {obiettivo}"
        if ind.get("verso") == "DECRESCENTE":
            obiettivo += " (più basso è meglio)"
    return f"{ind.get('descrizione') or ''}: {obiettivo}"


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
    dall'anno, misure non più nella mappatura o di altre strutture, azioni e misure senza
    indicatori, obiettivo senza azioni o senza misure della mappatura. [elementi]: {tipo,
    descrizione, impegno, scadenza (date), misura_id, indicatori (se noti)}; [strutture_misure]: misura_id -> struttura responsabile della misura."""
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
        if "indicatori" in x and not x["indicatori"]:
            c(INFO, f"{nome}: nessun indicatore, il raggiungimento non si misura")
        if x["tipo"] == "MISURA":
            if not x.get("misura_id"):
                c(AVVISO, f"{nome}: la misura non è più nella mappatura dei rischi")
            elif strutture_misure is not None:
                responsabile = strutture_misure.get(x["misura_id"])
                if responsabile and responsabile != struttura_id:
                    c(INFO, f"{nome}: la misura è attribuita a un'altra struttura nella mappatura")
    return sorted(esito, key=lambda v: v["livello"] != AVVISO)

