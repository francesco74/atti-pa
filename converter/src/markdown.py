"""Conversione degli atti in Markdown, il testo letto dalle verifiche e dall'LLM.

- ODT: dall'XML del documento (titoli, paragrafi, elenchi, tabelle, grassetto, note);
- DOC/DOCX: LibreOffice li converte in ODT, poi come sopra;
- PDF: PyMuPDF4LLM (titoli e tabelle ricostruiti dall'impaginazione).

Le tabelle sono il motivo principale del Markdown: importi, quadri economici e
imputazioni di bilancio restano associati alle loro colonne.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import zipfile
from xml.etree import ElementTree as ET

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
}
_T = "{%s}" % NS["text"]
_TB = "{%s}" % NS["table"]
log = logging.getLogger("converter.markdown")

_SPAZI = re.compile(r"[ \t]+")
# stili di paragrafo dei titoli (nomi interni ODT, anche dei documenti convertiti da Word)
_STILE_TITOLO = re.compile(r"^(?:Heading|Title|Titolo|Intestazione)(?:_20_(\d))?$", re.IGNORECASE)
_RIGHE_VUOTE = re.compile(r"\n{3,}")


class ConversioneNonRiuscita(ValueError):
    pass


# --- ODT ---------------------------------------------------------------------------------


def _stili_grassetto(radice: ET.Element) -> set[str]:
    """Stili automatici (formattazione diretta) che rendono il testo in grassetto."""
    grassetto = set()
    for stile in radice.iterfind(".//office:automatic-styles/style:style", NS):
        prop = stile.find("style:text-properties", NS)
        if prop is not None and prop.get(f"{{{NS['fo']}}}font-weight") in ("bold", "700"):
            grassetto.add(stile.get(f"{{{NS['style']}}}name"))
    return grassetto


def _genitori_stili(radici: list[ET.Element]) -> dict[str, str]:
    """Stile automatico -> stile da cui deriva (es. P3 -> Heading_20_1)."""
    genitori = {}
    for radice in radici:
        for stile in radice.iterfind(".//style:style", NS):
            nome = stile.get(f"{{{NS['style']}}}name")
            genitore = stile.get(f"{{{NS['style']}}}parent-style-name")
            if nome and genitore:
                genitori[nome] = genitore
    return genitori


def _elenchi_numerati(radici: list[ET.Element]) -> set[str]:
    """Stili di elenco il cui primo livello è numerato (1., a., i.) e non puntato."""
    numerati = set()
    for radice in radici:
        for stile in radice.iterfind(".//text:list-style", NS):
            primo = next(iter(stile), None)
            if primo is not None and primo.tag == _T + "list-level-style-number":
                numerati.add(stile.get(f"{{{NS['style']}}}name"))
    return numerati


class _Odt:
    def __init__(self, radice: ET.Element, stili: ET.Element | None = None):
        radici = [radice] + ([stili] if stili is not None else [])
        self.grassetto = _stili_grassetto(radice)
        self.genitori = _genitori_stili(radici)
        self.numerati = _elenchi_numerati(radici)
        self.note: list[str] = []

    def livello_titolo(self, el: ET.Element) -> int | None:
        """Livello di titolo di un paragrafo con stile "Titolo/Heading", altrimenti None."""
        nome = el.get(_T + "style-name")
        for _ in range(5):  # catena di derivazione degli stili
            if not nome:
                return None
            m = _STILE_TITOLO.match(nome)
            if m:
                return int(m.group(1) or 1)
            nome = self.genitori.get(nome)
        return None

    def inline(self, el: ET.Element) -> str:
        """Testo di un paragrafo con la formattazione in linea."""
        parti = [el.text or ""]
        for figlio in el:
            tag = figlio.tag
            if tag == _T + "s":
                parti.append(" " * int(figlio.get(_T + "c", "1")))
            elif tag == _T + "tab":
                parti.append(" ")
            elif tag == _T + "line-break":
                parti.append("  \n")
            elif tag == _T + "note":
                corpo = figlio.find("text:note-body", NS)
                testo = " ".join(self.inline(p) for p in corpo) if corpo is not None else ""
                self.note.append(_SPAZI.sub(" ", testo).strip())
                parti.append(f"[^{len(self.note)}]")
            elif tag in (_T + "span", _T + "a"):
                interno = self.inline(figlio)
                if figlio.get(_T + "style-name") in self.grassetto and interno.strip():
                    spazio_prima = " " if interno[:1].isspace() else ""
                    spazio_dopo = " " if interno[-1:].isspace() else ""
                    interno = f"{spazio_prima}**{interno.strip()}**{spazio_dopo}"
                parti.append(interno)
            elif tag in (_T + "bookmark", _T + "bookmark-start", _T + "bookmark-end"):
                pass
            else:
                parti.append(self.inline(figlio))
            parti.append(figlio.tail or "")
        return "".join(parti)

    def paragrafo(self, el: ET.Element) -> str:
        testo = _SPAZI.sub(" ", self.inline(el)).strip()
        if testo and el.get(_T + "style-name") in self.grassetto and not testo.startswith("**"):
            testo = f"**{testo}**"
        return testo

    def blocchi(self, contenitore: ET.Element, livello_elenco: int = 0) -> list[str]:
        """Blocchi Markdown (separati da riga vuota) degli elementi del contenitore."""
        risultato: list[str] = []
        for el in contenitore:
            tag = el.tag
            if tag == _T + "h":
                testo = self.paragrafo(el).strip("* ")
                if testo:
                    livello = min(int(el.get(_T + "outline-level", "1")), 6)
                    risultato.append(f"{'#' * livello} {testo}")
            elif tag == _T + "p":
                testo = self.paragrafo(el)
                livello = self.livello_titolo(el)
                if testo and livello:
                    risultato.append(f"{'#' * min(livello, 6)} {testo.strip('* ')}")
                elif testo:
                    risultato.append(testo)
            elif tag == _T + "list":
                righe = self.elenco(el, livello_elenco)
                if righe:
                    risultato.append("\n".join(righe))
            elif tag == _TB + "table":
                risultato.append(self.tabella(el))
            elif tag in (_T + "section", _T + "index-body", _T + "table-of-content"):
                risultato.extend(self.blocchi(el, livello_elenco))
        return risultato

    def elenco(self, el: ET.Element, livello: int, stile: str | None = None) -> list[str]:
        righe = []
        rientro = "   " * livello
        stile = el.get(_T + "style-name") or stile
        numerato = stile in self.numerati
        numero = 0
        for voce in el.findall("text:list-item", NS) + el.findall("text:list-header", NS):
            primo = True
            for figlio in voce:
                if figlio.tag == _T + "list":
                    righe.extend(self.elenco(figlio, livello + 1, stile))
                elif figlio.tag in (_T + "p", _T + "h"):
                    testo = self.paragrafo(figlio)
                    if not testo:
                        continue
                    if primo:
                        numero += 1
                        segno = f"{numero}. " if numerato else "- "
                    else:
                        segno = "   "
                    righe.append(f"{rientro}{segno}{testo}")
                    primo = False
        return righe

    def tabella(self, el: ET.Element) -> str:
        righe: list[list[str]] = []
        for riga in el.iter(_TB + "table-row"):
            celle = []
            for cella in riga:
                if cella.tag not in (_TB + "table-cell", _TB + "covered-table-cell"):
                    continue
                testo = " ".join(self.blocchi(cella)).replace("\n", " ").replace("|", "\\|")
                ripeti = int(cella.get(_TB + "number-columns-repeated", "1"))
                celle.extend([_SPAZI.sub(" ", testo).strip()] * min(ripeti, 50))
            righe.append(celle)
        righe = [r for r in righe if any(r)]
        if not righe:
            return ""
        colonne = max(len(r) for r in righe)
        righe = [r + [""] * (colonne - len(r)) for r in righe]
        # colonne finali vuote in tutte le righe (celle ripetute di riempimento)
        while colonne > 1 and all(not r[colonne - 1] for r in righe):
            colonne -= 1
            righe = [r[:colonne] for r in righe]
        linee = ["| " + " | ".join(righe[0]) + " |", "|" + "---|" * colonne]
        linee += ["| " + " | ".join(r) + " |" for r in righe[1:]]
        return "\n".join(linee)


def odt_in_markdown(contenuto: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenuto)) as zf:
            radice = ET.fromstring(zf.read("content.xml"))
            stili = ET.fromstring(zf.read("styles.xml")) if "styles.xml" in zf.namelist() else None
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ConversioneNonRiuscita("Documento ODT non valido") from e
    corpo = radice.find(".//office:body/office:text", NS)
    if corpo is None:
        raise ConversioneNonRiuscita("Documento ODT senza testo")
    odt = _Odt(radice, stili)
    testo = "\n\n".join(b for b in odt.blocchi(corpo) if b)
    if odt.note:
        testo += "\n\n" + "\n".join(f"[^{i}]: {n}" for i, n in enumerate(odt.note, 1))
    return _RIGHE_VUOTE.sub("\n\n", testo).strip() + "\n"


# --- PDF ---------------------------------------------------------------------------------


_NUMERO_PAGINA = re.compile(
    r"^[-–\s]*(?:pag(?:ina|\.)?\s*)?\d{1,4}(?:\s*(?:di|/)\s*\d{1,4})?[-–\s]*$", re.IGNORECASE
)
_RIGHE_BORDO = 3  # righe in cima e in fondo alla pagina dove stanno intestazioni e piè


def _chiave_riga(riga: str) -> str:
    """Forma confrontabile tra pagine: senza formattazione, numeri e maiuscole."""
    riga = re.sub(r"[#*_`>|]", " ", riga)
    return " ".join(re.sub(r"\d+", "#", riga).lower().split())


def _da_togliere(riga: str, ripetute: set[str]) -> bool:
    chiave = _chiave_riga(riga)
    return chiave in ripetute or bool(_NUMERO_PAGINA.match(chiave.replace("#", "1")))


def senza_intestazioni(pagine: list[str]) -> list[str]:
    """Toglie intestazioni e piè di pagina: le righe ai bordi della pagina che si ripetono
    in almeno metà delle pagine (almeno due) e i numeri di pagina."""
    bordi = []
    for testo in pagine:
        righe = [i for i, r in enumerate(testo.splitlines()) if r.strip()]
        bordi.append(set(righe[:_RIGHE_BORDO] + righe[-_RIGHE_BORDO:]))
    conteggio: dict[str, int] = {}
    for testo, indici in zip(pagine, bordi, strict=True):
        righe = testo.splitlines()
        for chiave in {_chiave_riga(righe[i]) for i in indici}:
            conteggio[chiave] = conteggio.get(chiave, 0) + 1
    soglia = max(2, (len(pagine) + 1) // 2)
    ripetute = {k for k, n in conteggio.items() if k and n >= soglia}

    risultato = []
    for testo, indici in zip(pagine, bordi, strict=True):
        righe = testo.splitlines()
        tenute = [r for i, r in enumerate(righe) if i not in indici or not _da_togliere(r, ripetute)]
        risultato.append("\n".join(tenute))
    return risultato


def pdf_in_markdown(contenuto: bytes) -> str:
    import pymupdf
    import pymupdf4llm

    try:
        documento = pymupdf.open(stream=contenuto, filetype="pdf")
    except (RuntimeError, ValueError) as e:
        raise ConversioneNonRiuscita("PDF non leggibile") from e
    messaggi = io.StringIO()
    with documento, contextlib.redirect_stdout(messaggi):
        # pagina per pagina, con intestazioni e piè di pagina: l'esclusione automatica di
        # PyMuPDF4LLM scarta anche i titoli in cima alla pagina (es. "Art. 22 Dirigenti");
        # le righe davvero ripetute si tolgono dopo. Senza OCR: un PDF scansionato viene
        # rifiutato invece di dipendere da cosa è installato sul server
        pagine = pymupdf4llm.to_markdown(
            documento,
            header=True,
            footer=True,
            use_ocr=False,
            show_progress=False,
            page_chunks=True,
        )
    if messaggi.getvalue().strip():
        log.debug("PyMuPDF4LLM: %s", messaggi.getvalue().strip())
    testo = "\n\n".join(senza_intestazioni([p["text"] for p in pagine]))
    testo = _RIGHE_VUOTE.sub("\n\n", testo).strip()
    if len(re.sub(r"[\s#*|\-]", "", testo)) < 50:
        raise ConversioneNonRiuscita(
            "Il PDF non contiene testo: probabilmente è una scansione. "
            "Caricare il PDF nativo o l'originale ODT/DOCX."
        )
    return testo + "\n"
