"""Verbale del controllo successivo di un atto (art. 147-bis TUEL), in ODT.

Impaginazione semplice (A4, nome dell'ente in testa, tabelle), non la carta intestata degli
atti; il PDF si ottiene con il servizio di conversione. Se il controllore non ha ancora
revisionato, gli esiti sono quelli proposti dalla verifica automatica e il verbale lo dice.
Dei dati personali rilevati riporta solo numero e categorie, mai i valori.
"""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from xml.sax.saxutils import escape

from common.models import AttoControllato, Verifica

ESITI = {
    "CONFORME": "Conforme",
    "NON_CONFORME": "Non conforme",
    "DUBBIO": "Dubbio",
    "NON_APPLICABILE": "Non applicabile",
    "ERRORE": "Non valutato",
    "NON_VALUTATO": "Non valutato",
}
ESITI_RIFERIMENTI = {
    "VIGENTE": "Vigente",
    "ABROGATO": "Abrogata",
    "PARTIZIONE_INESISTENTE": "Articolo, comma o lettera inesistente",
    "NON_TROVATO": "Non trovata",
    "ATTO_SENZA_ARTICOLO": "Senza articolo",
    "ERRORE_VERIFICA": "Verifica non riuscita",
}
STATI_ATTO = {
    "IN_CONVERSIONE": "in conversione",
    "ERRORE_CONVERSIONE": "conversione non riuscita",
    "IN_ANALISI": "in analisi",
    "DA_ANALIZZARE": "da analizzare",
    "ANALIZZATO": "analizzato, da revisionare",
    "IN_REVISIONE": "in revisione",
    "CHIUSO": "controllo concluso",
}


@dataclass
class DatiVerbale:
    ente: str
    controllo: str  # titolo del controllo
    atto: AttoControllato
    verifica: Verifica
    revisore: str | None  # nome di chi ha revisionato
    tipologia: str | None  # descrizione della tipologia di atto
    oggi: date


# --- ODT ---------------------------------------------------------------------------------------

_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'office:version="1.2"'
)

_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
</manifest:manifest>"""

# pagina A4, carattere e stili dei paragrafi
_STILI = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {_NS}>
 <office:font-face-decls/>
 <office:styles>
  <style:default-style style:family="paragraph">
   <style:paragraph-properties fo:margin-bottom="0.15cm"/>
   <style:text-properties style:font-name="Liberation Sans" fo:font-family="'Liberation Sans'" fo:font-size="10pt" fo:language="it" fo:country="IT"/>
  </style:default-style>
  <style:style style:name="Standard" style:family="paragraph"/>
  <style:style style:name="Ente" style:family="paragraph">
   <style:paragraph-properties fo:text-align="center" fo:margin-bottom="0.4cm"/>
   <style:text-properties fo:font-size="13pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="Titolo" style:family="paragraph">
   <style:paragraph-properties fo:text-align="center" fo:margin-bottom="0.05cm"/>
   <style:text-properties fo:font-size="12pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="Sottotitolo" style:family="paragraph">
   <style:paragraph-properties fo:text-align="center" fo:margin-bottom="0.4cm"/>
   <style:text-properties fo:font-style="italic"/>
  </style:style>
  <style:style style:name="Avviso" style:family="paragraph">
   <style:paragraph-properties fo:text-align="center" fo:padding="0.15cm" fo:border="0.06pt solid #b45309" fo:background-color="#fef3c7" fo:margin-bottom="0.4cm"/>
   <style:text-properties fo:font-weight="bold" fo:color="#7c2d12"/>
  </style:style>
  <style:style style:name="Sezione" style:family="paragraph">
   <style:paragraph-properties fo:margin-top="0.5cm" fo:margin-bottom="0.2cm" fo:keep-with-next="always"/>
   <style:text-properties fo:font-size="11pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="Scheda" style:family="paragraph">
   <style:paragraph-properties fo:margin-top="0.3cm" fo:margin-bottom="0.15cm" fo:keep-with-next="always"/>
   <style:text-properties fo:font-weight="bold" fo:font-style="italic"/>
  </style:style>
  <style:style style:name="Cella" style:family="paragraph">
   <style:paragraph-properties fo:margin-bottom="0cm"/>
   <style:text-properties fo:font-size="9pt"/>
  </style:style>
  <style:style style:name="CellaTitolo" style:family="paragraph">
   <style:paragraph-properties fo:margin-bottom="0cm"/>
   <style:text-properties fo:font-size="9pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="Piccolo" style:family="paragraph">
   <style:paragraph-properties fo:margin-bottom="0cm"/>
   <style:text-properties fo:font-size="8pt" fo:color="#555555"/>
  </style:style>
 </office:styles>
 <office:automatic-styles>
  <style:page-layout style:name="A4">
   <style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" fo:margin-top="1.8cm" fo:margin-bottom="1.8cm" fo:margin-left="2cm" fo:margin-right="2cm"/>
  </style:page-layout>
 </office:automatic-styles>
 <office:master-styles>
  <style:master-page style:name="Standard" style:page-layout-name="A4"/>
 </office:master-styles>
</office:document-styles>"""

# tabelle: bordi sottili, intestazione grigia, larghezze delle colonne
_STILI_AUTOMATICI = """
<office:automatic-styles>
 <style:style style:name="Tab" style:family="table">
  <style:table-properties style:width="17cm" table:align="left" fo:margin-bottom="0.2cm"/>
 </style:style>
 <style:style style:name="Cel" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.08cm" fo:border="0.5pt solid #999999"/>
 </style:style>
 <style:style style:name="CelTesta" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.08cm" fo:border="0.5pt solid #999999" fo:background-color="#e5e7eb"/>
 </style:style>
 <style:style style:name="CelNegativa" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.08cm" fo:border="0.5pt solid #999999" fo:background-color="#fee2e2"/>
 </style:style>
 <style:style style:name="CelDubbia" style:family="table-cell">
  <style:table-cell-properties fo:padding="0.08cm" fo:border="0.5pt solid #999999" fo:background-color="#fef3c7"/>
 </style:style>
 <style:style style:name="Grassetto" style:family="text">
  <style:text-properties fo:font-weight="bold"/>
 </style:style>
 {colonne}
</office:automatic-styles>"""


def _colonna(nome: str, cm: float) -> str:
    return (
        f'<style:style style:name="{nome}" style:family="table-column">'
        f'<style:table-column-properties style:column-width="{cm}cm"/></style:style>'
    )


# larghezze delle colonne delle tabelle (totale 17 cm)
_TABELLE = {
    "Dati": [5.0, 12.0],
    "Conteggi": [8.5, 8.5],
    "Controlli": [0.8, 5.2, 2.2, 2.2, 6.6],
    "Riferimenti": [5.0, 4.0, 2.5, 5.5],
}


def _p(testo: str | None, stile: str = "Standard") -> str:
    righe = (testo or "").split("\n")
    return f'<text:p text:style-name="{stile}">' + "<text:line-break/>".join(escape(r) for r in righe) + "</text:p>"


def _cella(contenuto: str | list[str], stile: str = "Cel") -> str:
    """contenuto: testo semplice oppure paragrafi già in XML."""
    corpo = contenuto if isinstance(contenuto, list) else [_p(contenuto, "Cella")]
    return f'<table:table-cell table:style-name="{stile}" office:value-type="string">{"".join(corpo)}</table:table-cell>'


def _tabella(nome: str, intestazione: list[str] | None, righe: list[list[str]]) -> str:
    larghezze = _TABELLE[nome]
    colonne = "".join(
        f'<table:table-column table:style-name="{nome}C{i}"/>' for i in range(len(larghezze))
    )
    testa = ""
    if intestazione:
        testa = (
            "<table:table-header-rows><table:table-row>"
            + "".join(_cella([_p(t, "CellaTitolo")], "CelTesta") for t in intestazione)
            + "</table:table-row></table:table-header-rows>"
        )
    corpo = "".join(f"<table:table-row>{''.join(r)}</table:table-row>" for r in righe)
    return f'<table:table table:name="{nome}{id(righe)}" table:style-name="Tab">{colonne}{testa}{corpo}</table:table>'


def _odt(corpo: str) -> bytes:
    colonne = "".join(
        _colonna(f"{nome}C{i}", cm) for nome, larghezze in _TABELLE.items() for i, cm in enumerate(larghezze)
    )
    contenuto = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {_NS}>'
        + _STILI_AUTOMATICI.format(colonne=colonne)
        + f"<office:body><office:text>{corpo}</office:text></office:body></office:document-content>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/vnd.oasis.opendocument.text",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr("META-INF/manifest.xml", _MANIFEST)
        zf.writestr("styles.xml", _STILI)
        zf.writestr("content.xml", contenuto)
    return out.getvalue()


# --- contenuto ---------------------------------------------------------------------------------


def _data(valore: date | datetime | None) -> str:
    return valore.strftime("%d/%m/%Y") if valore else "—"


def _stile_esito(esito: str | None) -> str:
    return {"NON_CONFORME": "CelNegativa", "DUBBIO": "CelDubbia", "ERRORE": "CelDubbia"}.get(
        esito or "", "Cel"
    )


def esiti_finali(verifica: Verifica) -> tuple[dict[str, dict], list[dict]]:
    """Esiti del controllore per controllo (elemento_id) e osservazioni generali."""
    per_elemento: dict[str, dict] = {}
    generali: list[dict] = []
    for e in verifica.esito_finale or []:
        if e.get("elemento_id"):
            per_elemento[e["elemento_id"]] = e
        else:
            generali.append(e)
    return per_elemento, generali


def verbale_odt(d: DatiVerbale) -> bytes:
    v, atto = d.verifica, d.atto
    revisionata = bool(v.esito_finale) or bool(v.motivazione)
    finali, osservazioni = esiti_finali(v)
    automatici = v.esito_automatico or []
    parti: list[str] = [
        _p(d.ente or "Ente", "Ente"),
        _p("Verbale di controllo successivo di regolarità amministrativa", "Titolo"),
        _p("art. 147-bis, comma 2, D.Lgs. 18 agosto 2000, n. 267", "Sottotitolo"),
    ]
    if not revisionata:
        parti.append(
            _p(
                "Esiti proposti automaticamente, non ancora revisionati dal controllore",
                "Avviso",
            )
        )

    # dati dell'atto e della verifica
    schede = list(dict.fromkeys(e.get("scheda_titolo") or e.get("scheda") for e in automatici))
    dati = [
        ("Controllo", d.controllo),
        ("Numero di registro", atto.numero_registro or "—"),
        ("Data di adozione", _data(atto.data_adozione)),
        ("Settore", atto.settore or "—"),
        ("Oggetto", atto.oggetto or "—"),
        ("Tipologia di atto", d.tipologia or atto.tipologia_atto or "—"),
        ("Modello di atto", atto.modello or "—"),
        ("Specificità", ", ".join(atto.moduli_json or []) or "nessuna"),
        ("Schede di controllo applicate", "\n".join(s for s in schede if s) or "—"),
        ("Norme verificate alla data del", _data(v.data_riferimento)),
        ("Verifica automatica del", _data(v.completata_il)),
        ("Modello linguistico", v.modello_llm or "—"),
        ("Revisione del controllore", d.revisore or "non ancora revisionata"),
        ("Stato del controllo", STATI_ATTO.get(atto.stato, atto.stato)),
    ]
    parti.append(_p("Atto controllato", "Sezione"))
    parti.append(
        _tabella("Dati", None, [[_cella([_p(k, "CellaTitolo")]), _cella(val)] for k, val in dati])
    )

    # esito complessivo: quello del controllore se c'è, altrimenti quello automatico
    def esito_di(e: dict) -> str:
        f = finali.get(e.get("elemento_id") or "")
        return (f or e).get("esito") or "ERRORE"

    conteggio = Counter(esito_di(e) for e in automatici)
    parti.append(_p("Esito complessivo", "Sezione"))
    parti.append(
        _p(
            ("Esiti del controllore" if revisionata else "Esiti proposti dalla verifica automatica")
            + f" su {len(automatici)} controlli:"
        )
    )
    righe = [
        [_cella(etichetta), _cella(str(conteggio.get(codice, 0)), _stile_esito(codice))]
        for codice, etichetta in [
            ("CONFORME", "Conformi"),
            ("NON_CONFORME", "Non conformi"),
            ("DUBBIO", "Dubbi"),
            ("NON_APPLICABILE", "Non applicabili"),
            ("ERRORE", "Non valutati"),
        ]
        if codice != "ERRORE" or conteggio.get("ERRORE")
    ]
    parti.append(_tabella("Conteggi", None, righe))

    # controlli per scheda
    parti.append(_p("Controlli", "Sezione"))
    if not automatici:
        parti.append(_p("Nessun controllo eseguito."))
    numero = 0
    for scheda in dict.fromkeys(e.get("scheda") for e in automatici):
        elementi = [e for e in automatici if e.get("scheda") == scheda]
        parti.append(_p(elementi[0].get("scheda_titolo") or scheda or "Scheda", "Scheda"))
        righe = []
        for e in elementi:
            numero += 1
            f = finali.get(e.get("elemento_id") or "")
            automatico = e.get("esito") or "ERRORE"
            finale = f.get("esito") if f else None
            cambiato = finale is not None and finale != automatico
            note = [_p(e.get("motivazione") or "—", "Cella")]
            if f and f.get("nota"):
                note.append(_p(f"Nota del controllore: {f['nota']}", "Cella"))
            if e.get("norme_usate"):
                note.append(_p("Norme: " + "; ".join(e["norme_usate"]), "Piccolo"))
            titolo = [_p(e.get("titolo") or "", "Cella")]
            if e.get("obbligatorio") is False:
                titolo.append(_p("facoltativo", "Piccolo"))
            righe.append(
                [
                    _cella(str(numero)),
                    _cella(titolo),
                    _cella(ESITI.get(automatico, automatico), _stile_esito(automatico)),
                    _cella(
                        [
                            _p(
                                ESITI.get(finale, finale) if finale else "—",
                                "CellaTitolo" if cambiato else "Cella",
                            ),
                            *([_p("modificato dal controllore", "Piccolo")] if cambiato else []),
                        ],
                        _stile_esito(finale),
                    ),
                    _cella(note),
                ]
            )
        parti.append(
            _tabella(
                "Controlli",
                ["N.", "Controllo", "Esito automatico", "Esito finale", "Motivazione"],
                righe,
            )
        )
    if osservazioni:
        parti.append(_p("Osservazioni del controllore", "Scheda"))
        for o in osservazioni:
            testo = f"{o.get('titolo')}: {ESITI.get(o.get('esito'), o.get('esito'))}"
            parti.append(_p(testo + (f" — {o['nota']}" if o.get("nota") else "")))

    # riferimenti normativi
    rif = v.esito_riferimenti or {}
    riferimenti = rif.get("riferimenti") or []
    parti.append(_p("Riferimenti normativi citati nell'atto", "Sezione"))
    if riferimenti:
        righe = [
            [
                _cella(r.get("testo") or "—"),
                _cella(r.get("citazione") or r.get("titolo_atto") or r.get("urn_atto") or "—"),
                _cella(
                    ESITI_RIFERIMENTI.get(r.get("esito"), r.get("esito") or "—"),
                    "Cel" if r.get("esito") == "VIGENTE" else "CelDubbia",
                ),
                _cella("\n".join(r.get("avvisi") or []) or "—"),
            ]
            for r in riferimenti
        ]
        parti.append(_tabella("Riferimenti", ["Citazione nell'atto", "Norma", "Esito", "Avvisi"], righe))
    else:
        parti.append(_p("Nessun riferimento normativo riconosciuto nel testo."))
    if rif.get("segnaposto"):
        parti.append(_p(f"Parti non compilate nel testo dell'atto: {len(rif['segnaposto'])}."))

    # dati personali: solo numero e categorie
    parti.append(_p("Dati personali", "Sezione"))
    stato_dp = rif.get("dati_personali_stato")
    dp = rif.get("dati_personali") or []
    if stato_dp == "ERRORE":
        parti.append(_p("Rilevamento automatico non riuscito."))
    elif stato_dp != "VALUTATI":
        parti.append(_p("Non valutati."))
    elif not dp:
        parti.append(_p("Nessun dato personale rilevato."))
    else:
        categorie = Counter((x.get("categoria") or "altro").replace("_", " ") for x in dp)
        elenco = ", ".join(f"{c} ({n})" for c, n in categorie.most_common())
        parti.append(
            _p(
                (
                    "Rilevato 1 dato personale"
                    if len(dp) == 1
                    else f"Rilevati {len(dp)} dati personali"
                )
                + f" da valutare per la pubblicazione: {elenco}."
            )
        )
        parti.append(_p("I valori non sono riportati in questo verbale.", "Piccolo"))

    # conclusioni
    parti.append(_p("Conclusioni del controllore", "Sezione"))
    parti.append(_p(v.motivazione or "Non ancora formulate."))
    parti.append(_p(""))
    parti.append(_p("Luogo e data: ______________________________"))
    parti.append(_p(""))
    parti.append(_p(f"Il controllore{f' ({d.revisore})' if d.revisore else ''}: ______________________________"))
    parti.append(_p(""))
    parti.append(_p(f"Verbale generato da Atti PA il {_data(d.oggi)}.", "Piccolo"))
    return _odt("".join(parti))
