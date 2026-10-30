"""Metodologia di valutazione del rischio (indicatori, scala, matrice, livelli) e calcolo
della valutazione: moda degli indicatori con la parità risolta verso il valore più alto, poi
la matrice probabilità × impatto. Regole comuni sui codici degli elementi."""

from __future__ import annotations

import re
from collections import Counter
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

FILE_STANDARD = Path(__file__).with_name("metodologia.yaml")


class Indicatore(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    nome: str = Field(min_length=1, max_length=200)
    descrizione: str = ""


class Metodologia(BaseModel):
    scala: list[str] = Field(min_length=2)  # dal più basso
    livelli: list[str] = Field(min_length=2)  # dal più basso
    matrice: dict[str, dict[str, str]]  # probabilità → impatto → livello
    indicatori_probabilita: list[Indicatore] = Field(min_length=1)
    indicatori_impatto: list[Indicatore] = Field(min_length=1)
    fattori_abilitanti: list[str] = []
    categorie_misure: list[str] = []

    @model_validator(mode="after")
    def _coerente(self) -> Metodologia:
        for nome, lista in (("scala", self.scala), ("livelli", self.livelli)):
            if len(set(lista)) != len(lista):
                raise ValueError(f"Valori ripetuti in {nome}")
        for indicatori in (self.indicatori_probabilita, self.indicatori_impatto):
            if len({i.id for i in indicatori}) != len(indicatori):
                raise ValueError("Identificativi degli indicatori ripetuti")
        for p in self.scala:
            for i in self.scala:
                livello = self.matrice.get(p, {}).get(i)
                if livello is None:
                    raise ValueError(f"Matrice incompleta: manca probabilità {p}, impatto {i}")
                if livello not in self.livelli:
                    raise ValueError(f"Livello non previsto nella matrice: {livello}")
        return self

    def ordine_livello(self, livello: str | None) -> int:
        """Posizione del livello (più alto = più grave); -1 se assente o sconosciuto."""
        return self.livelli.index(livello) if livello in self.livelli else -1


@cache
def standard() -> Metodologia:
    return Metodologia.model_validate(yaml.safe_load(FILE_STANDARD.read_text(encoding="utf-8")))


def moda(valori: list[str], scala: list[str]) -> str:
    """Valore più frequente; a parità il più alto nella scala (PNA 2019, prudenza)."""
    conteggi = Counter(valori)
    massimo = max(conteggi.values())
    return max((v for v, n in conteggi.items() if n == massimo), key=scala.index)


class Valutazione(BaseModel):
    probabilita_calcolata: str
    impatto_calcolato: str
    probabilita: str
    impatto: str
    livello: str


def valuta(
    m: Metodologia,
    valori_probabilita: dict[str, str],
    valori_impatto: dict[str, str],
    *,
    probabilita: str | None = None,
    impatto: str | None = None,
) -> Valutazione:
    """Valutazione da tutti gli indicatori. `probabilita` e `impatto` correggono i valori
    calcolati (la motivazione la controlla chi chiama)."""
    for nome, indicatori, valori in (
        ("probabilità", m.indicatori_probabilita, valori_probabilita),
        ("impatto", m.indicatori_impatto, valori_impatto),
    ):
        mancanti = [i.nome for i in indicatori if i.id not in valori]
        if mancanti:
            raise ValueError(f"Indicatori di {nome} non valutati: {', '.join(mancanti)}")
        estranei = set(valori) - {i.id for i in indicatori}
        if estranei:
            raise ValueError(f"Indicatori di {nome} non previsti: {', '.join(sorted(estranei))}")
        fuori_scala = {v for v in valori.values() if v not in m.scala}
        if fuori_scala:
            raise ValueError(f"Valori fuori scala: {', '.join(sorted(fuori_scala))}")
    for valore in (probabilita, impatto):
        if valore is not None and valore not in m.scala:
            raise ValueError(f"Valore fuori scala: {valore}")
    p_calc = moda(list(valori_probabilita.values()), m.scala)
    i_calc = moda(list(valori_impatto.values()), m.scala)
    p, i = probabilita or p_calc, impatto or i_calc
    return Valutazione(
        probabilita_calcolata=p_calc, impatto_calcolato=i_calc, probabilita=p, impatto=i, livello=m.matrice[p][i]
    )


# --- codici --------------------------------------------------------------------------------


def chiave_naturale(codice: str) -> list:
    """Ordinamento naturale dei codici: A.2 prima di A.10."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in re.split(r"(\d+)", codice or "") if p]


def prossimo_codice(prefisso: str, esistenti: list[str]) -> str:
    """Codice successivo con il prefisso dato (es. "A.1." → "A.1.4" se esistono fino ad A.1.3)."""
    numeri = [
        int(m.group(1)) for c in esistenti if c.startswith(prefisso) and (m := re.fullmatch(r"(\d+)", c[len(prefisso):]))
    ]
    return f"{prefisso}{max(numeri, default=0) + 1}"
