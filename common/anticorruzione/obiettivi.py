"""Importazione degli obiettivi di performance dal file del Piano (ripresa da Si.Ge.Ri.Co.):
sette colonne nell'ordine codice, titolo, tipo, anno, centro del Piano, descrizione del centro,
responsabile; le righe prima dei dati (titoli, intestazioni) si saltano. Formati: .xlsx, CSV
e le tabelle HTML salvate con estensione .xls (come le esportano alcuni gestionali); i .xls
veri vanno salvati come .xlsx."""

from __future__ import annotations

import csv
import io
import re

from bs4 import BeautifulSoup

COLONNE = ("codice", "titolo", "tipo", "anno", "centro", "centro_descrizione", "responsabile")


class FileNonLeggibile(ValueError):
    pass


def _tabella(contenuto: bytes, nome: str) -> list[list[str]]:
    nome = nome.lower()
    if contenuto[:5].lower().startswith(b"<") or b"<table" in contenuto[:4096].lower():
        soup = BeautifulSoup(contenuto, "lxml")
        return [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in soup.find_all("tr")]
    if nome.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            foglio = load_workbook(io.BytesIO(contenuto), read_only=True, data_only=True).active
        except Exception as e:  # noqa: BLE001 - file danneggiato o non xlsx
            raise FileNonLeggibile(f"File Excel non leggibile: {e}") from e
        return [["" if v is None else str(v).strip() for v in r] for r in foglio.iter_rows(values_only=True)]
    if nome.endswith(".csv"):
        testo = contenuto.decode("utf-8-sig", errors="replace")
        separatore = max(";,\t", key=testo[:8192].count)  # le righe di titolo non hanno separatori
        return [[v.strip() for v in r] for r in csv.reader(io.StringIO(testo), delimiter=separatore)]
    if nome.endswith(".xls"):
        raise FileNonLeggibile("I file .xls del vecchio formato non si leggono: salvalo come .xlsx e riprova")
    raise FileNonLeggibile("Formato non ammesso: usa un file .xlsx, .csv o .xls (tabella HTML)")


def _anno(valore: str) -> int | None:
    try:
        anno = int(float(valore.replace(",", ".")))
    except (ValueError, AttributeError):
        return None
    return anno if 2000 <= anno <= 2100 else None


def leggi(contenuto: bytes, nome: str) -> list[dict]:
    """Obiettivi del file, uno per codice e anno (il primo che compare)."""
    risultato, visti = [], set()
    for riga in _tabella(contenuto, nome):
        riga = (riga + [""] * len(COLONNE))[: len(COLONNE)]
        valori = dict(zip(COLONNE, (v.strip() for v in riga), strict=True))
        anno = _anno(valori["anno"])
        if not valori["codice"] or valori["codice"].lower() == "codice" or anno is None:
            continue  # titoli, intestazioni, righe vuote
        if (valori["codice"], anno) in visti:
            continue
        visti.add((valori["codice"], anno))
        risultato.append({**{k: v or None for k, v in valori.items()}, "anno": anno})
    return risultato


def _normalizza(testo: str) -> str:
    return re.sub(r"\s+", " ", testo).strip().upper()


def abbina_struttura(centro: str | None, strutture: dict[str, str]) -> str | None:
    """Struttura dell'ente per il centro del Piano (`strutture`: id -> codice). Il centro può
    avere un suffisso dopo "_" (es. "STAFF B_NOV. 2024" -> "STAFF B")."""
    if not centro:
        return None
    per_codice = {_normalizza(codice): sid for sid, codice in strutture.items()}
    for candidato in (centro, centro.split("_", 1)[0]):
        if (sid := per_codice.get(_normalizza(candidato))) is not None:
            return sid
    return None
