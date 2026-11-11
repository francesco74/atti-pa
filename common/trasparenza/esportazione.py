"""Dati di una scheda di trasparenza in formato aperto (JSON, XML, CSV), dai dati del form da cui
è generata (non dall'HTML, che si può ritoccare nell'editor).

I valori seguono le convenzioni dei dati aperti: date in ISO 8601 (AAAA-MM-GG), numeri e importi
come numeri con il punto decimale, campi vuoti assenti (in JSON a null); i campi nascosti dalle
condizioni dello schema non compaiono. Le chiavi sono gli id dei campi dello schema, stabili;
le etichette leggibili sono nel dizionario "campi".
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

from .registro import Campo, Schema, _compilato, _contesto, _visibile

FORMATI = {
    "json": "application/json",
    "xml": "application/xml",
    "csv": "text/csv; charset=utf-8",
}


def _numero(testo: str) -> float | int:
    """Numero all'italiana (1.234,56) in numero."""
    valore = float(testo.replace(".", "").replace(",", "."))
    return int(valore) if valore.is_integer() and "," not in testo else valore


def valore(campo: Campo, testo: str) -> Any:
    """Valore del form nel formato aperto; testo non riconosciuto lasciato com'è."""
    testo = testo.strip()
    if not testo:
        return None
    try:
        if campo.tipo == "data":
            sep = campo.separatore_data
            return datetime.strptime(testo, f"%d{sep}%m{sep}%Y").date().isoformat()
        if campo.tipo in ("anno", "numero"):
            return int(testo)
        if campo.tipo in ("importo", "percentuale", "decimale"):
            return _numero(testo)
    except ValueError:
        return testo
    if campo.tipo == "iban":
        return testo.replace(" ", "").upper()
    return testo


def _elemento(campi: list[Campo], elemento: dict, parametri: dict) -> dict:
    ctx = _contesto(parametri, elemento)
    risultato: dict[str, Any] = {}
    for c in campi:
        if not _visibile(c.visibile_se, ctx):
            continue
        if c.tipo == "elenco":
            sotto = [s for s in (elemento.get(c.id) or []) if isinstance(s, dict) and _compilato([s])]
            risultato[c.id] = [_elemento(c.campi or [], s, parametri) for s in sotto]
        else:
            risultato[c.id] = valore(c, str(elemento.get(c.id) or ""))
    return risultato


def _etichette(campi: list[Campo], prefisso: str = "") -> dict[str, str]:
    etichette: dict[str, str] = {}
    for c in campi:
        etichette[f"{prefisso}{c.id}"] = c.etichetta
        if c.tipo == "elenco":
            etichette |= _etichette(c.campi or [], f"{prefisso}{c.id}.")
    return etichette


def dati_aperti(schema: Schema, dati: dict, ente: str) -> dict:
    """La scheda come dizionario: schema e fonte, ente, parametri, sezione ed elementi."""
    parametri = dati.get("parametri") or {}
    sezione = schema.sezione(dati.get("sezione") or "")
    alternativo = str(dati.get("alternativo") or "").strip()
    righe = [r for r in (dati.get("righe") or []) if isinstance(r, dict)]
    risultato: dict[str, Any] = {
        "schema": {
            "id": schema.id,
            "articolo": schema.articolo,
            "titolo": schema.titolo,
            "fonte": schema.fonte.descrizione,
        },
        "ente": ente,
        "generato_il": datetime.now().replace(microsecond=0).isoformat(),
        "ambito_soggettivo": str(dati.get("ambito_soggettivo") or "TENUTO").upper(),
        "parametri": {
            p.id: {"valore": o.valore, "etichetta": o.etichetta}
            for p in schema.parametri
            if (o := p.opzione(parametri.get(p.id))) is not None
        },
    }
    if alternativo and schema.adempimento_alternativo:
        risultato["adempimento_alternativo"] = alternativo
        return risultato
    if sezione is None:
        return risultato
    risultato["sezione"] = {"id": sezione.id, "titolo": sezione.titolo}
    risultato["campi"] = _etichette(sezione.campi)
    risultato["elementi"] = [_elemento(sezione.campi, r, parametri) for r in righe]
    if note := str(dati.get("note") or "").strip():
        risultato["note"] = note
    return risultato


def in_json(d: dict) -> bytes:
    return json.dumps(d, ensure_ascii=False, indent=2).encode()


def _xml_valore(padre: ET.Element, nome: str, v: Any) -> None:
    if v is None:
        return
    if isinstance(v, list):
        elenco = ET.SubElement(padre, nome)
        for x in v:
            _xml_elemento(ET.SubElement(elenco, "elemento"), x)
        return
    ET.SubElement(padre, nome).text = str(v)


def _xml_elemento(nodo: ET.Element, elemento: dict) -> None:
    for chiave, v in elemento.items():
        _xml_valore(nodo, chiave, v)


def in_xml(d: dict) -> bytes:
    """Stessa struttura del JSON: gli id dei campi (^[a-z][a-z0-9_]*$) sono nomi di tag validi."""
    radice = ET.Element("scheda")
    s = d["schema"]
    schema = ET.SubElement(radice, "schema", id=s["id"])
    for chiave in ("articolo", "titolo", "fonte"):
        ET.SubElement(schema, chiave).text = s[chiave]
    for chiave in ("ente", "generato_il", "ambito_soggettivo"):
        ET.SubElement(radice, chiave).text = d[chiave]
    if d["parametri"]:
        parametri = ET.SubElement(radice, "parametri")
        for pid, p in d["parametri"].items():
            ET.SubElement(parametri, "parametro", id=pid, etichetta=p["etichetta"]).text = p["valore"]
    if "adempimento_alternativo" in d:
        ET.SubElement(radice, "adempimento_alternativo").text = d["adempimento_alternativo"]
    if "sezione" in d:
        ET.SubElement(radice, "sezione", id=d["sezione"]["id"]).text = d["sezione"]["titolo"]
        campi = ET.SubElement(radice, "campi")
        for cid, etichetta in d["campi"].items():
            ET.SubElement(campi, "campo", id=cid, etichetta=etichetta)
        elementi = ET.SubElement(radice, "elementi")
        for e in d["elementi"]:
            _xml_elemento(ET.SubElement(elementi, "elemento"), e)
    if "note" in d:
        ET.SubElement(radice, "note").text = d["note"]
    ET.indent(radice)
    return ET.tostring(radice, encoding="utf-8", xml_declaration=True) + b"\n"


def _testo_csv(v: Any, etichette: dict[str, str], prefisso: str) -> str:
    """Valore di una cella; un elenco annidato diventa "Etichetta: valore; ..." per elemento,
    con gli elementi separati da " | "."""
    if v is None:
        return ""
    if isinstance(v, list):
        return " | ".join(
            "; ".join(f"{etichette.get(f'{prefisso}{k}', k)}: {x}" for k, x in e.items() if x not in (None, "", []))
            for e in v
        )
    return str(v)


def in_csv(d: dict) -> bytes:
    """Un elemento per riga, una colonna per campo visibile in almeno un elemento (intestazioni
    con le etichette), separatore virgola (RFC 4180). UTF-8 con BOM, perché Excel riconosca le
    lettere accentate."""
    etichette = d.get("campi") or {}
    colonne = [c for c in etichette if "." not in c]
    elementi = d.get("elementi") or []
    colonne = [c for c in colonne if any(c in e for e in elementi)] or colonne
    uscita = io.StringIO()
    w = csv.writer(uscita, lineterminator="\r\n")
    w.writerow([etichette[c] for c in colonne])
    for e in elementi:
        w.writerow([_testo_csv(e.get(c), etichette, f"{c}.") for c in colonne])
    return ("﻿" + uscita.getvalue()).encode()
