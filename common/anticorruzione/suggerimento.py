"""Valutazione del rischio suggerita dall'intelligenza artificiale.

Dati il processo, l'attività, l'evento rischioso, il fattore abilitante e le misure già
previste, il modello propone per ogni indicatore della metodologia dell'ente un valore della
scala con una motivazione breve, e il giudizio sintetico motivato sulla valutazione complessiva.
Probabilità, impatto e livello si calcolano poi come per le valutazioni fatte a mano (moda e
matrice, common/anticorruzione/metodologia.py).

È una proposta: l'interfaccia la mostra dopo che chi valuta ha espresso la sua, evidenziando
gli indicatori su cui il modello la vede diversamente; nulla si salva senza conferma.
"""

from __future__ import annotations

from common.anticorruzione.metodologia import Indicatore, Metodologia, valuta
from common.llm import LlmError, testo_prompt
from common.trasparenza.estrazione import json_schema


def _indicatori(lista: list[Indicatore]) -> str:
    return "\n".join(f"- id {i.id}: {i.nome}{' - ' + i.descrizione if i.descrizione else ''}" for i in lista)


def schema(m: Metodologia) -> dict:
    ids = [i.id for i in (*m.indicatori_probabilita, *m.indicatori_impatto)]
    return {
        "type": "object",
        "properties": {
            "indicatori": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string", "enum": ids}, "valore": {"type": "string", "enum": list(m.scala)},
                "motivazione": {"type": "string"}}}},
        },
    }  # fmt: skip


async def suggerisci(
    llm,
    m: Metodologia,
    *,
    ente: str,
    processo: str,
    attivita: str,
    evento: str,
    fattore: str | None = None,
    misure: list[str] = (),
) -> dict:
    """La valutazione proposta: valori e motivazioni per indicatore, probabilità, impatto e
    livello calcolati, giudizio sintetico. Due chiamate: i valori, poi (calcolato il livello
    come per le valutazioni a mano, che il modello non sa fare in modo affidabile) il giudizio
    coerente con il risultato. Solleva LlmError se la risposta è incompleta."""
    messaggio = testo_prompt(
        "valutazione_utente", ente=ente, processo=processo or "—", attivita=attivita or "—", evento=evento,
        fattore=fattore or "non indicato", misure="\n".join(f"- {x}" for x in misure) or "nessuna",
        scala=", ".join(m.scala), indicatori_probabilita=_indicatori(m.indicatori_probabilita),
        indicatori_impatto=_indicatori(m.indicatori_impatto),
    )  # fmt: skip
    sistema = testo_prompt("valutazione_sistema")
    risposta = await llm.dati_json(sistema, messaggio, json_schema(schema(m)), interattiva=True)
    per_id = {}
    for x in risposta.get("indicatori") or []:
        if isinstance(x, dict) and x.get("valore") in m.scala:
            per_id.setdefault(str(x.get("id")), (x["valore"], str(x.get("motivazione") or "").strip()))
    prob = {i.id: per_id[i.id][0] for i in m.indicatori_probabilita if i.id in per_id}
    imp = {i.id: per_id[i.id][0] for i in m.indicatori_impatto if i.id in per_id}
    if len(prob) < len(m.indicatori_probabilita) or len(imp) < len(m.indicatori_impatto):
        raise LlmError("Il modello non ha valutato tutti gli indicatori: riprova")
    esito = valuta(m, prob, imp)
    righe = [f"- {nome} ({i.nome}): {per_id[i.id][0]} - {per_id[i.id][1]}"
             for nome, lista in (("probabilità", m.indicatori_probabilita), ("impatto", m.indicatori_impatto)) for i in lista]  # fmt: skip
    giudizio = await llm.scrivi(sistema, testo_prompt(
        "valutazione_giudizio", evento=evento, indicatori="\n".join(righe), probabilita=esito.probabilita,
        impatto=esito.impatto, livello=esito.livello))  # fmt: skip
    return {
        "valori_probabilita": prob,
        "valori_impatto": imp,
        "motivazioni": {k: v[1] for k, v in per_id.items() if k in prob or k in imp},
        "motivazione_valutazione": giudizio.strip(),
        "probabilita": esito.probabilita,
        "impatto": esito.impatto,
        "livello": esito.livello,
    }
