"""Composizione del testo e del documento di una bozza a partire da template e dati."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from common.dati_personali import (
    DatiPersonaliNonDisponibili,
    applica_omissis,
    trova_dati_personali,
)
from common.llm import LlmClient
from common.models import Bozza, Riferimento, Template
from common.odt import compila, estrai_testo


def testo_riferimenti(riferimenti: list[Riferimento | dict]) -> str:
    righe = []
    for r in riferimenti:
        citazione = r["citazione"] if isinstance(r, dict) else r.citazione
        righe.append(f"Visto l'{citazione};")
    return "\n".join(righe)


def valori_bozza(bozza: Bozza) -> dict[str, str]:
    valori = {k: "" if v is None else str(v) for k, v in (bozza.dati_json or {}).items()}
    valori["oggetto"] = bozza.oggetto
    valori["riferimenti_normativi"] = testo_riferimenti(bozza.riferimenti_json or [])
    if bozza.data_adozione_prevista:
        valori["data_adozione"] = bozza.data_adozione_prevista.strftime("%d/%m/%Y")
    return valori


_SEPARATORE = "\n\n"


async def valori_con_omissis(valori: dict[str, str], llm: LlmClient | None) -> dict[str, str]:
    """I valori dei campi con i dati personali oscurati: una chiamata al modello per tutti.

    Solleva DatiPersonaliNonDisponibili se il modello non c'è o non risponde.
    """
    if llm is None:
        raise DatiPersonaliNonDisponibili(
            "rilevamento con il modello linguistico disattivato (LLM_DATI_PERSONALI)"
        )
    chiavi = list(valori)
    inizi, posizione = {}, 0
    for k in chiavi:
        inizi[k] = posizione
        posizione += len(valori[k]) + len(_SEPARATORE)
    unito = _SEPARATORE.join(valori[k] for k in chiavi)
    dati = await trova_dati_personali(llm, unito, interattiva=True)
    risultato = {}
    for k in chiavi:
        inizio, fine = inizi[k], inizi[k] + len(valori[k])
        nel_campo = [
            replace(d, inizio=d.inizio - inizio, fine=d.fine - inizio)
            for d in dati
            if d.inizio >= inizio and d.fine <= fine
        ]
        risultato[k] = applica_omissis(valori[k], nel_campo)
    return risultato


def testo_semplice(bozza: Bozza) -> str:
    """Testo dell'atto quando non è stato scelto un template."""
    v = valori_bozza(bozza)
    parti = [f"OGGETTO: {v['oggetto']}", v["riferimenti_normativi"]]
    parti += [f"{k.replace('_', ' ').upper()}:\n{testo}" for k, testo in v.items()
              if k not in ("oggetto", "riferimenti_normativi", "data_adozione") and testo]  # fmt: skip
    return "\n\n".join(p for p in parti if p)


def documento_odt(bozza: Bozza, template: Template) -> bytes:
    return compila(template.file_contenuto, valori_bozza(bozza))


async def documento_odt_con_omissis(
    bozza: Bozza, template: Template, llm: LlmClient | None
) -> bytes:
    """Documento da pubblicare, con i dati personali rilevati dal modello oscurati."""
    return compila(template.file_contenuto, await valori_con_omissis(valori_bozza(bozza), llm))


def aggiorna_testo(bozza: Bozza, template: Template | None) -> None:
    bozza.contenuto_testo = (
        estrai_testo(documento_odt(bozza, template)) if template else testo_semplice(bozza)
    )


def data_riferimento(bozza: Bozza, oggi: date) -> date:
    return bozza.data_adozione_prevista or oggi
