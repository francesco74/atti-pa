"""Composizione del testo e del documento di una bozza a partire da template e dati."""

from __future__ import annotations

from datetime import date

from atti_common.dati_personali import applica_omissis, trova_dati_personali
from atti_common.models import Bozza, Riferimento, Template
from atti_common.odt import compila, estrai_testo


def testo_riferimenti(riferimenti: list[Riferimento | dict]) -> str:
    righe = []
    for r in riferimenti:
        citazione = r["citazione"] if isinstance(r, dict) else r.citazione
        righe.append(f"Visto l'{citazione};")
    return "\n".join(righe)


def valori_bozza(bozza: Bozza, omissis: bool = False) -> dict[str, str]:
    valori = {k: "" if v is None else str(v) for k, v in (bozza.dati_json or {}).items()}
    valori["oggetto"] = bozza.oggetto
    valori["riferimenti_normativi"] = testo_riferimenti(bozza.riferimenti_json or [])
    if bozza.data_adozione_prevista:
        valori["data_adozione"] = bozza.data_adozione_prevista.strftime("%d/%m/%Y")
    if omissis:
        valori = {k: applica_omissis(v, trova_dati_personali(v)) for k, v in valori.items()}
    return valori


def testo_semplice(bozza: Bozza) -> str:
    """Testo dell'atto quando non è stato scelto un template."""
    v = valori_bozza(bozza)
    parti = [f"OGGETTO: {v['oggetto']}", v["riferimenti_normativi"]]
    parti += [f"{k.replace('_', ' ').upper()}:\n{testo}" for k, testo in v.items()
              if k not in ("oggetto", "riferimenti_normativi", "data_adozione") and testo]  # fmt: skip
    return "\n\n".join(p for p in parti if p)


def documento_odt(bozza: Bozza, template: Template, omissis: bool = False) -> bytes:
    return compila(template.file_contenuto, valori_bozza(bozza, omissis))


def aggiorna_testo(bozza: Bozza, template: Template | None) -> None:
    bozza.contenuto_testo = (
        estrai_testo(documento_odt(bozza, template)) if template else testo_semplice(bozza)
    )


def data_riferimento(bozza: Bozza, oggi: date) -> date:
    return bozza.data_adozione_prevista or oggi
