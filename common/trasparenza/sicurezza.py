"""Difese dell'HTML della trasparenza: sanificazione di ciò che entra o esce (risposte
dell'LLM, documenti generati, documenti salvati dall'editor, HTML da convertire) ed esito di
validazione riportato in un report. Ripreso da PApuntozeroIA (security.py).
"""

import re

import nh3
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Sanificazione HTML
# ---------------------------------------------------------------------------

# Tag di formattazione e tabelle usati dai template, dall'editor (Summernote)
# e dai report dell'IA. Nessun tag attivo (script, iframe, object, form, ...).
_TAG_AMMESSI = set(nh3.ALLOWED_TAGS) | {"style", "font"}
_TAG_AMMESSI -= {"area", "map", "nav"}

_ATTRIBUTI_COMUNI = {"style", "class", "title", "align", "valign", "width", "height", "dir", "lang"}
_ATTRIBUTI_AMMESSI = {
    "*": _ATTRIBUTI_COMUNI,
    "a": {"href", "target", "name"},
    "img": {"src", "alt", "border"},
    "table": {"border", "cellpadding", "cellspacing", "bgcolor", "summary"},
    "td": {"colspan", "rowspan", "bgcolor", "nowrap", "scope", "headers"},
    "th": {"colspan", "rowspan", "bgcolor", "nowrap", "scope", "headers"},
    "tr": {"bgcolor"},
    "col": {"span"},
    "colgroup": {"span"},
    "font": {"color", "face", "size"},
    "ol": {"start", "type", "reversed"},
    "li": {"value"},
    "time": {"datetime"},
}

# 'data' è ammesso a questo livello solo per le immagini incorporate: i link
# 'data:' vengono rimossi nel passaggio successivo (_rimuovi_data_non_immagini).
_SCHEMI_URL_AMMESSI = {"http", "https", "mailto", "tel", "data"}

_DATA_IMMAGINE = re.compile(r"^data:image/(png|jpe?g|gif|webp|bmp);base64,[A-Za-z0-9+/=\s]*$", re.IGNORECASE)

_CSS_COMMENTI = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_PERICOLOSO = [
    (re.compile(r"@import[^;]*;?", re.IGNORECASE), ""),
    (re.compile(r"url\s*\([^)]*\)", re.IGNORECASE), "none"),
    (re.compile(r"expression\s*\(", re.IGNORECASE), "invalid("),
    (re.compile(r"(-moz-binding|behavior)\s*:", re.IGNORECASE), "invalid:"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), ""),
]


def pulisci_css(css: str) -> str:
    """Rimuove dal CSS ciò che può caricare risorse esterne o eseguire codice."""
    # Le sequenze di escape CSS (es. '\75 rl(' = 'url(') permetterebbero di
    # aggirare i filtri: si eliminano insieme ai commenti prima dei controlli.
    css = _CSS_COMMENTI.sub("", css).replace("\\", "")
    for pattern, sostituto in _CSS_PERICOLOSO:
        css = pattern.sub(sostituto, css)
    return css


def _filtra_attributo(tag: str, attributo: str, valore: str):
    if attributo == "style":
        return pulisci_css(valore)
    if valore.strip().lower().startswith("data:"):
        # 'data:' solo come sorgente di immagini raster (niente SVG né HTML).
        if tag == "img" and attributo == "src" and _DATA_IMMAGINE.match(valore.strip()):
            return valore
        return None
    return valore


def _pulisci_blocchi_style(html: str) -> str:
    return re.sub(
        r"(<style[^>]*>)(.*?)(</style>)",
        lambda m: m.group(1) + pulisci_css(m.group(2)) + m.group(3),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def sanifica_html(html) -> str:
    """
    Restituisce una versione sicura dell'HTML: niente script, handler di eventi,
    iframe/object/form, link javascript:/data:, CSS che carica risorse esterne.
    La formattazione (tabelle, stili in linea, blocchi <style>) è preservata.
    """
    if not html:
        return ""
    pulito = nh3.clean(
        str(html),
        tags=_TAG_AMMESSI,
        clean_content_tags={"script", "title", "noscript", "template", "textarea", "xmp", "iframe", "object"},
        attributes=_ATTRIBUTI_AMMESSI,
        attribute_filter=_filtra_attributo,
        url_schemes=_SCHEMI_URL_AMMESSI,
        strip_comments=True,
    )
    return _pulisci_blocchi_style(pulito)


# ---------------------------------------------------------------------------
# Esito di validazione (Istruzioni operative ANAC, § 2)
# ---------------------------------------------------------------------------

ESITI_VALIDAZIONE = ("Non pubblicabile", "Pubblicabile provvisoriamente", "Pubblicabile")
_RE_ESITO_TESTO = re.compile(
    r"esito\s+di\s+validazione\W{0,40}?(non\s+pubblicabile|pubblicabile\s+provvisoriamente|pubblicabile)",
    re.IGNORECASE,
)


def _normalizza_esito(testo: str) -> str | None:
    testo = re.sub(r"\s+", " ", testo or "").strip().lower()
    for esito in ESITI_VALIDAZIONE:  # dal più specifico al più generico
        if testo.startswith(esito.lower()):
            return esito
    return None


def estrai_esito(html: str | None) -> str | None:
    """Esito di validazione di un report di analisi: dal badge con class="esito-validazione"
    richiesto all'LLM o, in mancanza, dal testo "Esito di validazione: ...". None per i
    documenti che non lo contengono (schede generate dal form, verbali)."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    badge = soup.select_one(".esito-validazione")
    if badge is not None and (esito := _normalizza_esito(badge.get_text(" "))):
        return esito
    trovato = _RE_ESITO_TESTO.search(soup.get_text(" "))
    return _normalizza_esito(trovato.group(1)) if trovato else None
