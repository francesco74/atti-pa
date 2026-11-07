"""Ricerca in linguaggio naturale su elenchi di record (processi e procedimenti della mappatura).

Il risultato è sempre un elenco di record esistenti, ordinati per pertinenza: nessun testo
generato. Due componenti, fuse per rango (reciprocal rank fusion):

- **lessicale**, sempre attiva e senza modello: parole normalizzate (minuscole, senza accenti
  e parole vuote), ridotte alla radice italiana (Snowball) e allargate ai sinonimi di
  `ricerca_sinonimi.yaml` (es. affitto ~ locazione); punteggio BM25 con la denominazione che
  pesa più degli altri campi. Il testo cercato che compare tale e quale nel codice o nella
  denominazione mette il record in cima.
- **semantica**, se è configurato un modello di embedding (EMBEDDING_BASE_URL): similarità del
  coseno tra la domanda e i record. I vettori dei record si calcolano alla prima ricerca e
  quando il testo cambia (impronta), e restano nel database (ricerca_vettori) e in memoria.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import snowballstemmer
import yaml

# peso dei campi nel punteggio lessicale (ripetizione dei termini)
PESO_DENOMINAZIONE = 3
# un risultato lessicale sotto questa frazione del migliore è rumore (parole poco rilevanti)
SOGLIA_RELATIVA = 0.25
# i sinonimi contano meno della parola cercata
PESO_SINONIMO = 0.7
# costante della reciprocal rank fusion
K_FUSIONE = 60
MAX_RISULTATI = 50

_PAROLE_VUOTE = set(
    """
    a ad al allo alla ai agli alle all anche c che chi ci come con col coi contro cui da dal dallo
    dalla dai dagli dalle dall de del dello della dei degli delle dell di e ed fra gli ha hanno ho
    i il in io l la le lo loro ma me mi mia mie mio miei ne nel nello nella nei negli nelle nell
    noi non o od per piu po puo quale quali quando quanto quella quelle quelli quello questa queste
    questi questo se sempre si sia siamo sono su sul sullo sulla sui sugli sulle sull ti tra tu
    tua tue tuo tuoi un una uno vi voi essere avere fare devo posso vorrei voglio serve servono
    occorre bisogna dove cosa come quanto quando chiedere chiedo richiedere richiedo ottenere
    ottengo fa faccio sapere informazioni info mio mia
    """.split()
)

_RE_PAROLA = re.compile(r"[a-z0-9]+")


@cache
def _stemmer():
    return snowballstemmer.stemmer("italian")


def normalizza(testo: str) -> str:
    """Minuscole e senza accenti (perché "attività" e "attivita" coincidano)."""
    t = unicodedata.normalize("NFKD", testo.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def radici(testo: str) -> list[str]:
    """Radici delle parole significative del testo, nell'ordine."""
    parole = [p for p in _RE_PAROLA.findall(normalizza(testo)) if p not in _PAROLE_VUOTE and (len(p) > 1 or p.isdigit())]
    return _stemmer().stemWords(parole)


@cache
def _sinonimi() -> dict[str, frozenset[str]]:
    """Radice -> radici equivalenti, dai gruppi di ricerca_sinonimi.yaml."""
    gruppi = yaml.safe_load((Path(__file__).with_name("ricerca_sinonimi.yaml")).read_text(encoding="utf-8"))
    mappa: dict[str, set[str]] = {}
    for gruppo in gruppi or []:
        r = {x for parola in gruppo for x in radici(str(parola))}
        for x in r:
            mappa.setdefault(x, set()).update(r)
    return {k: frozenset(v - {k}) for k, v in mappa.items()}


def termini_domanda(domanda: str) -> dict[str, float]:
    """Radici della domanda con il loro peso: 1 per le parole scritte, meno per i sinonimi."""
    termini: dict[str, float] = {}
    for r in radici(domanda):
        termini[r] = 1.0
    for r in list(termini):
        for s in _sinonimi().get(r, ()):
            termini.setdefault(s, PESO_SINONIMO)
    return termini


@dataclass
class Documento:
    """Record da cercare: `titolo` (codice e denominazione) pesa di più di `testo`."""

    id: str
    titolo: str
    testo: str = ""

    @property
    def per_embedding(self) -> str:
        return f"{self.titolo}\n{self.testo}"[:4000]

    @property
    def impronta(self) -> str:
        return hashlib.sha256(self.per_embedding.encode()).hexdigest()


@dataclass
class Risultato:
    id: str
    punteggio: float
    parole: list[str] = field(default_factory=list)  # radici trovate (lessicale)
    semantica: bool = False  # trovato (anche) per significato


def lessicale(domanda: str, documenti: list[Documento]) -> list[Risultato]:
    """BM25 (k1=1.2, b=0.75) sulle radici, con sinonimi e titolo pesato; in cima i record il
    cui codice o denominazione contiene il testo cercato tale e quale."""
    termini = termini_domanda(domanda)
    esatta = normalizza(domanda).strip()
    if not termini and not esatta:
        return []
    indici = []
    for d in documenti:
        r = radici(d.titolo) * PESO_DENOMINAZIONE + radici(d.testo)
        freq: dict[str, int] = {}
        for x in r:
            freq[x] = freq.get(x, 0) + 1
        indici.append((d, freq, len(r)))
    n = len(indici) or 1
    media = sum(lung for _, _, lung in indici) / n or 1
    df = {t: sum(1 for _, f, _ in indici if t in f) for t in termini}
    risultati = []
    for d, freq, lung in indici:
        punteggio, parole = 0.0, []
        for t, peso in termini.items():
            tf = freq.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            punteggio += peso * idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * lung / media))
            parole.append(t)
        if esatta and len(esatta) >= 2 and esatta in normalizza(d.titolo):
            punteggio += 1000
        if punteggio > 0:
            risultati.append(Risultato(d.id, punteggio, parole))
    risultati.sort(key=lambda r: -r.punteggio)
    if risultati:
        minimo = risultati[0].punteggio * SOGLIA_RELATIVA
        risultati = [r for r in risultati if r.punteggio >= minimo]
    return risultati[:MAX_RISULTATI]


def coseno(a: list[float], b: list[float]) -> float:
    """Coseno tra vettori già normalizzati (prodotto scalare)."""
    return sum(x * y for x, y in zip(a, b))


def unitario(v: list[float]) -> list[float]:
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]


def semantica(domanda: list[float], vettori: dict[str, list[float]], soglia: float) -> list[Risultato]:
    """Record con similarità almeno [soglia] e vicini al migliore (entro 0,15)."""
    simili = sorted(((coseno(domanda, v), i) for i, v in vettori.items()), reverse=True)
    if not simili or simili[0][0] < soglia:
        return []
    minimo = max(soglia, simili[0][0] - 0.15)
    return [Risultato(i, s, semantica=True) for s, i in simili[:MAX_RISULTATI] if s >= minimo]


def fondi(lessicali: list[Risultato], semantici: list[Risultato]) -> list[Risultato]:
    """Reciprocal rank fusion: conta la posizione in ciascun elenco, non il punteggio (le due
    scale non sono confrontabili). Le corrispondenze esatte restano in cima."""
    fusi: dict[str, Risultato] = {}
    for elenco in (lessicali, semantici):
        for rango, r in enumerate(elenco):
            f = fusi.setdefault(r.id, Risultato(r.id, 0.0))
            f.punteggio += 1 / (K_FUSIONE + rango + 1) + (1 if r.punteggio >= 1000 else 0)
            f.parole = f.parole or r.parole
            f.semantica = f.semantica or r.semantica
    return sorted(fusi.values(), key=lambda r: -r.punteggio)[:MAX_RISULTATI]
