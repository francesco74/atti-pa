"""Relazioni di sintesi (relazione annuale del RPCT, sottosezione "Rischi corruttivi e
trasparenza" del PIAO, relazione sulla performance) costruite solo sui dati del sistema.

I dati e le tabelle di ogni sezione si calcolano in modo deterministico (routers/relazioni.py);
il modello ne scrive solo il testo, una sezione alla volta, con un prompt che vieta di
aggiungere fatti (common/prompt/relazione_*.md). I numeri del testo si confrontano con quelli
dei dati: quelli che non vi compaiono si segnalano da verificare. La bozza si rivede e si
esporta in DOCX o ODT.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field

_RE_NUMERO = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?")


@dataclass
class Tabella:
    titolo: str
    intestazioni: list[str]
    righe: list[list]

    def per_api(self) -> dict:
        return {"titolo": self.titolo, "intestazioni": self.intestazioni, "righe": self.righe}


@dataclass
class Sezione:
    id: str
    titolo: str
    dati: dict  # fatti per il testo (anche per il controllo dei numeri)
    tabelle: list[Tabella] = field(default_factory=list)

    def per_api(self) -> dict:
        return {"id": self.id, "titolo": self.titolo, "dati": self.dati, "tabelle": [t.per_api() for t in self.tabelle]}


def percentuale(parte: int, totale: int) -> float:
    return round(parte / totale * 100, 1) if totale else 0.0


def _normalizza(testo: str) -> str:
    """Numero in forma confrontabile: "12,5" e "12.5" -> "12.5"; "1.234" -> "1234"; "12,0" -> "12"."""
    t = testo.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    t = t.replace(",", ".")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


def numeri_ammessi(dati) -> set[str]:
    """Numeri presenti nei dati (anche dentro i testi, es. "l. 190/2012", "U.O. 2.1")."""
    testo = json.dumps(dati, ensure_ascii=False)
    ammessi = {_normalizza(n) for n in _RE_NUMERO.findall(testo)}
    for n in re.findall(r"\d+(?:\.\d+)", testo):  # anche le parti: "2.1" -> "2", "1"
        ammessi.update(n.split("."))
    return ammessi


def numeri_da_verificare(testo: str, dati) -> list[str]:
    """Numeri del testo che non compaiono nei dati (senza doppioni, nell'ordine del testo)."""
    ammessi = numeri_ammessi(dati)
    visti: list[str] = []
    for n in _RE_NUMERO.findall(testo):
        if _normalizza(n) not in ammessi and n not in visti:
            visti.append(n)
    return visti


def html_relazione(titolo: str, sottotitolo: str, sezioni: list[dict]) -> str:
    """HTML della relazione da convertire in DOCX/ODT: titolo, sezioni con testo e tabelle."""
    e = html.escape
    parti = [f"<h1>{e(titolo)}</h1>"]
    if sottotitolo:
        parti.append(f"<p><i>{e(sottotitolo)}</i></p>")
    for s in sezioni:
        parti.append(f"<h2>{e(str(s.get('titolo') or ''))}</h2>")
        for paragrafo in [p.strip() for p in str(s.get("testo") or "").split("\n") if p.strip()]:
            parti.append(f"<p>{e(paragrafo)}</p>")
        for t in s.get("tabelle") or []:
            if t.get("titolo"):
                parti.append(f"<p><b>{e(str(t['titolo']))}</b></p>")
            intestazione = "".join(f"<th>{e(str(c))}</th>" for c in t.get("intestazioni") or [])
            righe = "".join("<tr>" + "".join(f"<td>{e('' if c is None else str(c))}</td>" for c in r) + "</tr>"
                            for r in t.get("righe") or [])  # fmt: skip
            parti.append(f'<table border="1" cellpadding="4" cellspacing="0"><tr>{intestazione}</tr>{righe}</table>')
    stile = "body{font-family:sans-serif;font-size:11pt} table{border-collapse:collapse;margin:6pt 0} th{background:#eee}"
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{stile}</style></head><body>{"".join(parti)}</body></html>'
