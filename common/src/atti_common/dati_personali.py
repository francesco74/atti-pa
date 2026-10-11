"""Rilevamento deterministico di dati personali da valutare per la pubblicazione (omissis).

Non sostituisce la valutazione del responsabile: segnala i punti da controllare.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_PATTERN: list[tuple[str, re.Pattern]] = [
    ("CODICE_FISCALE", re.compile(r"\b[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE)),
    ("IBAN", re.compile(r"\bIT\s?\d{2}\s?[A-Z]\s?(?:\d\s?){10}(?:[0-9A-Z]\s?){12}\b", re.IGNORECASE)),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("TELEFONO", re.compile(r"(?<!\d)(?:\+39\s?)?(?:3\d{2}|0\d{1,3})[\s./-]?\d{3,4}[\s./-]?\d{3,4}(?!\d)")),
    ("DATA_DI_NASCITA", re.compile(r"\bnat[oa]\s+(?:a|ad|il)\s+[^,;.\n]{2,60}", re.IGNORECASE)),
    ("RESIDENZA", re.compile(r"\bresident[ei]\s+(?:a|in)\s+[^,;.\n]{2,60}", re.IGNORECASE)),
    ("SALUTE", re.compile(
        r"\b(?:disabilit[àa]|invalidit[àa]|patologi[ae]|diagnosi|handicap|l\.\s?104/1992|"
        r"legge\s+104|certificato\s+medico|stato\s+di\s+salute)\b",
        re.IGNORECASE,
    )),
    ("CONDIZIONE_ECONOMICA", re.compile(
        r"\b(?:ISEE|indigen[tz]|disagio\s+economico|sfratto|morosit[àa])\b", re.IGNORECASE
    )),
]  # fmt: skip

# Categorie particolari (art. 9 GDPR) o dati da cui si ricavano: priorità alta
_ALTA = {"SALUTE", "CODICE_FISCALE", "IBAN", "CONDIZIONE_ECONOMICA"}


@dataclass
class DatoPersonale:
    categoria: str
    testo: str
    inizio: int
    fine: int
    priorita: str


def trova_dati_personali(testo: str) -> list[DatoPersonale]:
    trovati: list[DatoPersonale] = []
    occupati: list[tuple[int, int]] = []
    for categoria, pattern in _PATTERN:
        for m in pattern.finditer(testo):
            if any(m.start() < f and m.end() > i for i, f in occupati):
                continue
            occupati.append((m.start(), m.end()))
            trovati.append(
                DatoPersonale(
                    categoria=categoria,
                    testo=m.group(0).strip(),
                    inizio=m.start(),
                    fine=m.end(),
                    priorita="ALTA" if categoria in _ALTA else "MEDIA",
                )
            )
    return sorted(trovati, key=lambda d: d.inizio)


def applica_omissis(testo: str, dati: list[DatoPersonale], marcatore: str = "[OMISSIS]") -> str:
    """Sostituisce i dati indicati con il marcatore, dalla fine per non spostare gli indici."""
    for d in sorted(dati, key=lambda d: d.inizio, reverse=True):
        testo = testo[: d.inizio] + marcatore + testo[d.fine :]
    return testo


def come_dict(dati: list[DatoPersonale]) -> list[dict]:
    return [asdict(d) for d in dati]
