"""Composizione dei documenti HTML della trasparenza: schede generate dal form di uno schema
e verbali di validazione, con il nome e il logo dell'ente. I modelli sono in modelli/, con
segnaposto _nome_: una riga con un segnaposto senza valore viene omessa (note, sottotitolo,
logo assente)."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from .registro import Schema, genera_documento
from .sicurezza import sanifica_html

MODELLI = Path(__file__).resolve().parent / "modelli"
_SEGNAPOSTO = re.compile(r"_([a-z][a-z0-9_]*[a-z0-9])_")  # non le righe "_____" da compilare

# Tipi dei documenti salvati
SCHEDA = "SCHEDA"  # generata dal form di uno schema (con i dati per rigenerarla)
ANALISI = "ANALISI"  # report di un'analisi con l'LLM (con l'esito di validazione)
VERBALE = "VERBALE"  # verbale di validazione
TIPI = (SCHEDA, ANALISI, VERBALE)


def _modello(nome: str) -> str:
    return (MODELLI / f"{nome}.html").read_text(encoding="utf-8")


def compila(modello: str, valori: dict[str, str]) -> str:
    """Sostituisce i segnaposto riga per riga; omette le righe con un segnaposto vuoto."""
    righe = []
    for riga in modello.splitlines():
        riga = riga.strip()
        sostituiti = {n: str(valori.get(n, "")).strip() for n in _SEGNAPOSTO.findall(riga)}
        if not all(sostituiti.values()):
            continue
        for nome, valore in sostituiti.items():
            riga = riga.replace(f"_{nome}_", valore)
        righe.append(riga)
    return " ".join(righe)


def logo_incorporato(logo: bytes | None, mime: str | None) -> str:
    """Logo dell'ente come data URI (il documento resta autosufficiente anche esportato)."""
    if not logo or not mime:
        return ""
    return f"data:{mime};base64,{base64.b64encode(logo).decode()}"


def scheda(schema: Schema, dati: dict, nome_ente: str, logo: str = "") -> str:
    """Documento da pubblicare generato dai dati (già validati) del form di uno schema."""
    valori = {**genera_documento(schema, dati), "client_description": nome_ente, "logo": logo}
    return sanifica_html(compila(_modello("scheda"), valori))


def verbale(documenti: list[str], logo: str = "") -> str:
    """Verbale di validazione seguito dai documenti indicati, nell'ordine dato."""
    html = compila(_modello("verbale"), {"logo": logo})
    for d in documenti:
        html += f" <br/><hr><br /> {d}"
    return sanifica_html(html)
