"""Scomposizione dell'HTML di un articolo Normattiva in commi e lettere.

L'API restituisce `articoloHtml` con classi derivate da Akoma Ntoso, tra cui:
    article-num-akn         numero dell'articolo ("Art. 2")
    article-heading-akn     rubrica
    art-comma-div-akn       contenitore di un comma
    comma-num-akn           numero del comma ("1.", "1-bis.")
    pointedList-first-akn   alinea di un comma con elenco
    pointedList-rest-akn    lettere dell'elenco ("a) ...")
    art_aggiornamento-akn   note di aggiornamento (escluse dal testo)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

_SPAZI = re.compile(r"\s+")
_LETTERA = re.compile(
    r"^(?P<lettera>[a-z]{1,2}(?:-(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?)\)\s*(?P<testo>.*)$",
    re.DOTALL,
)
_NUM_COMMA = re.compile(r"^(?P<num>[\w-]+)\.?$")
_URN_IN_LINK = re.compile(r"(urn:nir:[^\s\"'&]+)")


@dataclass
class Lettera:
    lettera: str
    testo: str


@dataclass
class Comma:
    numero: str
    testo: str
    alinea: str | None = None
    lettere: list[Lettera] = field(default_factory=list)


@dataclass
class Articolo:
    numero: str | None
    rubrica: str | None
    commi: list[Comma]
    rinvii: list[str]

    def comma(self, numero: str) -> Comma | None:
        return next((c for c in self.commi if c.numero == numero), None)

    def testo(self) -> str:
        """Testo normalizzato dell'intero articolo (usato anche per l'hash)."""
        return "\n".join(f"{c.numero}. {c.testo}" for c in self.commi)

    def hash(self) -> str:
        return hashlib.sha256(self.testo().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


def _pulisci(testo: str) -> str:
    testo = _SPAZI.sub(" ", testo).strip()
    # marcatori di testo modificato "(( ... ))" e note "((6))"
    testo = re.sub(r"\(\(\s*\d+\s*\)\)", "", testo)
    testo = testo.replace("((", "").replace("))", "")
    return _SPAZI.sub(" ", testo).strip()


def _testo(el: Tag) -> str:
    return _pulisci(el.get_text(" "))


def _estrai_lettera(el: Tag) -> Lettera | None:
    m = _LETTERA.match(_testo(el))
    if not m:
        return None
    return Lettera(lettera=m["lettera"], testo=m["testo"].strip())


def _estrai_comma(div: Tag) -> Comma:
    num_el = div.find(class_="comma-num-akn")
    numero = ""
    if num_el:
        m = _NUM_COMMA.match(_testo(num_el))
        numero = m["num"] if m else _testo(num_el).rstrip(".")
        num_el.extract()

    alinea_el = div.find(class_="pointedList-first-akn")
    lettere_el = div.find_all(class_="pointedList-rest-akn")

    alinea = _testo(alinea_el) if alinea_el else None
    lettere = [lett for el in lettere_el if (lett := _estrai_lettera(el))]

    return Comma(numero=numero, testo=_testo(div), alinea=alinea, lettere=lettere)


INIZIO_COMMA = re.compile(r"^(?P<num>\d+(?:-[a-z]+)?)\.\s+(?P<testo>.*)$", re.DOTALL)


def _commi_da_html(el: Tag) -> list[Comma]:
    """Commi e lettere da un elemento HTML con le righe separate da <br>."""
    righe: list[str] = []
    corrente: list[str] = []
    for nodo in el.children:
        if isinstance(nodo, Tag) and nodo.name == "br":
            righe.append(" ".join(corrente))
            corrente = []
        else:
            corrente.append(nodo.get_text(" ") if isinstance(nodo, Tag) else str(nodo))
    righe.append(" ".join(corrente))
    return commi_da_righe(righe)


def commi_da_righe(righe: list[str]) -> list[Comma]:
    """Commi e lettere da un testo in righe: "1. ...", "a) ...", "2. ...".

    Le righe che precedono il primo comma numerato sono scartate (usato anche per i testi
    caricati manualmente, che le gestiscono prima di chiamare questa funzione).
    """
    commi: list[Comma] = []
    for riga in (_pulisci(r) for r in righe):
        if not riga:
            continue
        if m := INIZIO_COMMA.match(riga):
            commi.append(Comma(numero=m["num"], testo=m["testo"].strip()))
        elif commi and (m := _LETTERA.match(riga)):
            comma = commi[-1]
            if comma.alinea is None:
                comma.alinea = comma.testo
            comma.lettere.append(Lettera(lettera=m["lettera"], testo=m["testo"].strip()))
            comma.testo = f"{comma.testo} {riga}"
        elif commi:  # prosecuzione del comma o della lettera precedente
            comma = commi[-1]
            comma.testo = f"{comma.testo} {riga}"
            if comma.lettere:
                comma.lettere[-1].testo = f"{comma.lettere[-1].testo} {riga}"
    return commi


def parse_articolo(html: str) -> Articolo:
    soup = BeautifulSoup(html, "html.parser")

    # le note di aggiornamento non fanno parte del testo vigente
    for nota in soup.find_all(class_="art_aggiornamento-akn"):
        nota.decompose()

    num_el = soup.find(class_="article-num-akn")
    numero = None
    if num_el:
        numero = re.sub(r"^Art\.?\s*", "", _testo(num_el), flags=re.IGNORECASE) or None

    rubrica_el = soup.find(class_="article-heading-akn") or soup.find(
        class_="article-pre-comma-text-akn"
    )
    rubrica = None
    if rubrica_el:
        rubrica = _testo(rubrica_el).rstrip(".").strip("() ") or None

    rinvii: list[str] = []
    for a in soup.find_all("a", href=True):
        m = _URN_IN_LINK.search(unquote(a["href"]))
        if m and m.group(1) not in rinvii:
            rinvii.append(m.group(1))

    commi = [_estrai_comma(div) for div in soup.find_all(class_="art-comma-div-akn")]
    commi = [c for c in commi if c.numero or c.testo]  # contenitori vuoti dell'HTML

    # testo "piatto" (es. d.lgs. 36/2023): commi e lettere sono righe separate da <br>
    if not commi:
        piatto = soup.find(class_="art-just-text-akn")
        if piatto is not None:
            commi = _commi_da_html(piatto)

    # articoli senza commi numerati (comma unico): il testo può stare nel contenitore dei
    # commi oppure, se quello è vuoto, altrove nel corpo (es. "article-pre-comma-text-akn")
    if not commi:
        da_escludere = ["article-num-akn", "article-heading-akn"]
        if rubrica_el is not None and "article-heading-akn" not in rubrica_el.get("class", []):
            rubrica_el.decompose()  # testo già usato come rubrica
        for corpo in (soup.find(class_="art-commi-div-akn"), soup.find(class_="bodyTesto"), soup):
            if corpo is None:
                continue
            for el in corpo.find_all(class_=da_escludere):
                el.decompose()
            testo = _testo(corpo)
            if testo:
                m = re.match(r"^(?P<num>\d+(?:-[a-z]+)?)\.\s+(?P<testo>.+)$", testo, re.DOTALL)
                numero, testo = (m["num"], m["testo"]) if m else ("1", testo)
                commi = [Comma(numero=numero, testo=testo)]
                break

    return Articolo(numero=numero, rubrica=rubrica, commi=commi, rinvii=rinvii)
