"""Template OpenDocument Text (.odt) con segnaposto `{{ nome_campo }}`.

Un .odt è un archivio ZIP; il testo è in `content.xml`. LibreOffice spezza spesso un
segnaposto in più `<text:span>`: per questo la sostituzione lavora a livello di
paragrafo, ricomponendo il testo e mantenendo lo stile del paragrafo.

Convenzioni:
- `{{ campo }}` è sostituito dal valore del campo; i ritorni a capo diventano nuovi paragrafi
  con lo stesso stile.
- Un segnaposto senza valore resta nel documento come `[[campo]]`, così è riconoscibile
  dal controllo dei segnaposto non compilati.
"""

from __future__ import annotations

import io
import re
import zipfile
from copy import deepcopy

from lxml import etree

NS = {
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
}
_TEXT = f"{{{NS['text']}}}"

SEGNAPOSTO = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
NON_COMPILATO = re.compile(r"\[\[([a-zA-Z_][a-zA-Z0-9_]*)\]\]")


class OdtNonValido(ValueError):
    pass


def _leggi_content(odt: bytes) -> tuple[zipfile.ZipFile, etree._Element]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(odt))
        if zf.read("mimetype").decode().strip() != "application/vnd.oasis.opendocument.text":
            raise OdtNonValido("Il file non è un documento ODT")
        radice = etree.fromstring(zf.read("content.xml"))
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as e:
        raise OdtNonValido("File ODT non leggibile") from e
    return zf, radice


def _testo_paragrafo(p: etree._Element) -> str:
    parti: list[str] = []

    def visita(el: etree._Element) -> None:
        if el.tag == _TEXT + "s":
            parti.append(" " * int(el.get(_TEXT + "c", "1")))
        elif el.tag == _TEXT + "tab":
            parti.append("\t")
        elif el.tag == _TEXT + "line-break":
            parti.append("\n")
        elif el.text:
            parti.append(el.text)
        for figlio in el:
            visita(figlio)
            if figlio.tail:
                parti.append(figlio.tail)

    visita(p)
    return "".join(parti)


def _paragrafi(radice: etree._Element) -> list[etree._Element]:
    return radice.findall(".//text:p", NS) + radice.findall(".//text:h", NS)


def estrai_testo(odt: bytes) -> str:
    _, radice = _leggi_content(odt)
    corpo = radice.find(".//office:text", NS)
    if corpo is None:
        return ""
    righe = [_testo_paragrafo(el) for el in corpo.iter(_TEXT + "p", _TEXT + "h")]
    return "\n".join(righe)


def estrai_segnaposto(odt: bytes) -> list[str]:
    """Nomi dei segnaposto nell'ordine di prima comparsa."""
    _, radice = _leggi_content(odt)
    visti: list[str] = []
    for p in _paragrafi(radice):
        for nome in SEGNAPOSTO.findall(_testo_paragrafo(p)):
            if nome not in visti:
                visti.append(nome)
    return visti


def compila(odt: bytes, valori: dict[str, str]) -> bytes:
    zf, radice = _leggi_content(odt)

    for p in _paragrafi(radice):
        testo = _testo_paragrafo(p)
        if not SEGNAPOSTO.search(testo):
            continue

        def sostituisci(m: re.Match) -> str:
            valore = valori.get(m.group(1))
            return f"[[{m.group(1)}]]" if valore in (None, "") else str(valore)

        nuovo = SEGNAPOSTO.sub(sostituisci, testo)
        righe = nuovo.split("\n")

        # svuota il paragrafo mantenendone attributi e stile
        for figlio in list(p):
            p.remove(figlio)
        p.text = righe[0]
        precedente = p
        for riga in righe[1:]:
            copia = deepcopy(p)
            for figlio in list(copia):
                copia.remove(figlio)
            copia.text = riga
            precedente.addnext(copia)
            precedente = copia

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as nuovo_zip:
        # "mimetype" deve essere il primo file, non compresso
        nuovo_zip.writestr(
            zipfile.ZipInfo("mimetype"), zf.read("mimetype"), compress_type=zipfile.ZIP_STORED
        )
        for info in zf.infolist():
            if info.filename == "mimetype":
                continue
            dati = (
                etree.tostring(radice, xml_declaration=True, encoding="UTF-8")
                if info.filename == "content.xml"
                else zf.read(info.filename)
            )
            nuovo_zip.writestr(info, dati, compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()


def segnaposto_non_compilati(testo: str) -> list[str]:
    """Segnaposto rimasti in un testo: `{{campo}}` mai sostituiti o `[[campo]]` vuoti."""
    nomi = SEGNAPOSTO.findall(testo) + NON_COMPILATO.findall(testo)
    return list(dict.fromkeys(nomi))
