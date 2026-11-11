"""Analisi e estrazione del modulo trasparenza, senza database: preparazione dei contenuti
(pagina web, documento da URL, file caricati), prompt dell'analisi generato dallo schema o dal
controllo scelto, chiamata all'LLM, report HTML composto dalla risposta JSON. Le esegue il worker
(lavori della tabella trasparenza_lavori).

I documenti arrivano all'LLM come testo: PDF e documenti di testo convertiti in Markdown dal
converter, fogli di calcolo come tabelle, CSV come sono, XML e JSON compattati, pagine web come HTML del contenuto.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pa_common.conversione import testo as testo_semplice
from pa_common.conversione.fogli import fogli_in_markdown
from pa_common.errori import ConversioneNonRiuscita
from pydantic import BaseModel, Field, ValidationError

from . import fonti
from .estrazione import MAX_TESTO, estrai, json_schema
from .registro import genera_prompt, get_schema, trova_prompt
from .sicurezza import sanifica_html

log = logging.getLogger("common.trasparenza.analisi")

_RE_TRA_TAG = re.compile(r">\s+<")


def compatta(testo: str, estensione: str) -> str:
    """XML senza gli spazi tra i tag e JSON senza indentazione: i file indentati arrivano presto
    al limite di lunghezza. L'XML resta testo, non lo si interpreta (niente entità esterne); un
    JSON non valido resta com'è."""
    if estensione == "xml":
        return _RE_TRA_TAG.sub("><", testo).strip()
    if estensione == "json":
        try:
            return json.dumps(json.loads(testo), ensure_ascii=False, separators=(",", ":"))
        except ValueError:
            return testo.strip()
    return testo

ANALISI = "ANALISI"
ESTRAZIONE = "ESTRAZIONE"

# Il modello risponde con un JSON compatto (ReportAnalisi) e il report HTML lo compone il
# server: i token generati sono il contenuto e non il markup, che con i modelli locali è la
# parte lenta dell'analisi; badge e tabella sono sempre uguali e leggibili anche in PDF e Word.
OUTPUT_RULES = """
Rispondi ESCLUSIVAMENTE con l'oggetto JSON richiesto, senza HTML né Markdown, con questi campi:

1. "analisi": l'analisi descrittiva dei risultati, in paragrafi di testo semplice (uno per elemento):
   - descrivi l'esito globale dell'audit;
   - commenta la qualità dei dati rispetto ai requisiti delle Istruzioni operative ANAC (All. 4 alla delibera n. 495/2024, come modificato dalla delibera n. 481/2025), limitandoti a quelli verificabili dal documento: integrità, completezza (esattezza e accuratezza), tempestività, costante aggiornamento, semplicità di consultazione, comprensibilità, omogeneità, facile accessibilità e riutilizzabilità (formato aperto), conformità ai documenti originali, indicazione della provenienza (se il dato è una rielaborazione), riservatezza;
   - spiega le criticità riscontrate nei formati, nella tempestività e nella completezza dei dati.
   Sii sintetico: niente ripetizioni di quanto già riportato nei rilievi.

2. "rilievi": la tabella riepilogativa, una riga per ogni campo o controllo verificato, con:
   - "campo": il campo o controllo;
   - "valore_rilevato": il valore trovato nel documento (breve);
   - "esito": uno tra "Positivo", "Negativo" (dato mancante o errore grave), "Parziale" (dato presente ma
     formato errato o incompleto), "Non Applicabile", "Non valutabile";
   - "nota_correttiva": cosa correggere (vuota se l'esito è positivo).

3. "livello_open_data" (da 1 a 5) e "motivazione_open_data" (una frase).

4. "esito_globale": uno tra "Conforme", "Parzialmente conforme", "Non conforme".

5. "esito_validazione", secondo il § 2 delle Istruzioni operative, uno solo tra:
   * "Pubblicabile" (nessuna difformità);
   * "Pubblicabile provvisoriamente" (difformità lievi: il dato va sostituito non appena disponibili dati conformi);
   * "Non pubblicabile" (difformità macroscopiche);
   e "motivazione_validazione": la motivazione in una frase.
"""

WEB_PARSING_RULES = """
Ti verrà fornito il codice HTML della pagina. Segui queste direttive:
1. FILTRO RUMORE: Ignora i menu di navigazione, i footer, i banner e gli script. Concentrati esclusivamente sull'area dei contenuti che descrive i dati da analizzare.
2. ESTRAZIONE CONTATTI: Cerca i dati non solo nel testo visibile, ma anche negli attributi dei link (es. <a href="mailto:..."> o <a href="tel:...">).
3. COERENZA: Se i dati nel codice HTML sono discordanti rispetto ai placeholder forniti, segnalalo nel campo "Dettagli".
"""

OPEN_DATA_RULES = """
In base all'estensione del file (_FILE_EXTENSION_), assegna il livello di Open Data secondo gli standard AGID:
   - **Livello 1**: Formati leggibili da umani ma non strutturati (es. PDF, DOCX).
   - **Livello 2**: Formati strutturati ma proprietari (es. XLS, XLSX).
   - **Livello 3**: Formati strutturati, aperti e non proprietari (es. CSV, ODS, XML, JSON, HTML).
   - **Livello 4**: Dati che utilizzano standard W3C (RDF).
   - **Livello 5**: Linked Open Data (LOD) collegati a dataset esterni.
"""

SISTEMA_ESTRAZIONE = (
    "Estrai dati strutturati dai documenti della Pubblica Amministrazione italiana. Rispondi solo "
    "con l'oggetto JSON richiesto."
)


class AnalisiNonRiuscita(Exception):
    """Errore con un messaggio già pronto per l'utente."""


@dataclass
class File:
    nome: str
    contenuto: bytes
    descrizione: str = ""

    @property
    def estensione(self) -> str:
        return fonti.estensione(self.nome)


@dataclass
class Contesto:
    """Dati dell'ente e della richiesta che entrano nel prompt dell'analisi."""

    ente: str
    caratteristiche: str = ""
    note: str = ""
    data_adozione: str = ""
    data_pubblicazione: str = ""


# --- prompt ----------------------------------------------------------------------------------


def prompt_analisi(controllo: str, contesto: Contesto, *, estensione: str = "", url: str = "") -> str:
    """Prompt dell'analisi per uno schema o un suo controllo (variante), con il contesto.
    Per una pagina web indica l'URL al posto dell'estensione e aggiunge le regole di lettura
    dell'HTML."""
    schema, variante = trova_prompt(controllo)
    if schema is None:
        raise AnalisiNonRiuscita("Schema o controllo non previsto")
    if schema.controlli_per_sezione and variante is None:
        raise AnalisiNonRiuscita("Per questo schema scegli la sezione da controllare")
    prompt = genera_prompt(schema, variante)
    if url:
        prompt = prompt.replace("- Estensione originale file: _FILE_EXTENSION_", "- URL di estrazione: _URL_", 1)
        prompt = prompt.replace(
            "</authority_features>\n",
            "</authority_features>\n\n<istruzioni_web_parsing>\n_WEB_PARSING_RULES_\n</istruzioni_web_parsing>\n",
            1,
        )
        prompt = prompt.rstrip().removesuffix("Ecco il testo del documento da analizzare:").rstrip()
        prompt += "\n\nEcco il codice HTML da analizzare:"
    valori = {
        "_OUTPUT_RULES_": OUTPUT_RULES,
        "_WEB_PARSING_RULES_": WEB_PARSING_RULES,
        "_OPEN_DATA_RULES_": OPEN_DATA_RULES,
        "_ADDITIONAL_REQUESTS_": "",
        "_NOTES_": contesto.note or "nessuna",
        "_CUSTOMER_NAME_": contesto.ente,
        "_AUTHORITY_FEATURES_": contesto.caratteristiche or "Non indicate.",
        "_PUB_DATE_": contesto.data_pubblicazione or "N/A",
        "_ADOPTION_DATE_": contesto.data_adozione or "N/A",
        "_DATA_ANALISI_": datetime.now().strftime("%d/%m/%Y"),
        "_URL_": url,
        "_FILE_EXTENSION_": estensione,
    }
    for segnaposto, valore in valori.items():
        prompt = prompt.replace(segnaposto, valore)
    return prompt


# --- report ----------------------------------------------------------------------------------

EsitoRilievo = Literal["Positivo", "Negativo", "Parziale", "Non Applicabile", "Non valutabile"]
EsitoGlobale = Literal["Conforme", "Parzialmente conforme", "Non conforme"]
EsitoValidazione = Literal["Pubblicabile", "Pubblicabile provvisoriamente", "Non pubblicabile"]


class Rilievo(BaseModel):
    campo: str
    valore_rilevato: str
    esito: EsitoRilievo
    nota_correttiva: str


class ReportAnalisi(BaseModel):
    """Risposta del modello. L'ordine dei campi è quello di generazione: prima l'analisi e i
    rilievi, poi gli esiti che ne discendono."""

    analisi: list[str]
    rilievi: list[Rilievo]
    livello_open_data: int = Field(ge=1, le=5)
    motivazione_open_data: str
    esito_globale: EsitoGlobale
    esito_validazione: EsitoValidazione
    motivazione_validazione: str


def _testo(tipo: str = "string") -> dict:
    return {"type": tipo}


def _scelta(valori: tuple[str, ...]) -> dict:
    return {"type": "string", "enum": list(valori)}


# Schema della risposta (in stile Gemini, tradotto da json_schema come per l'estrazione)
SCHEMA_REPORT = {
    "type": "object",
    "properties": {
        "analisi": {"type": "array", "items": _testo()},
        "rilievi": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "campo": _testo(),
                    "valore_rilevato": _testo(),
                    "esito": _scelta(EsitoRilievo.__args__),
                    "nota_correttiva": _testo(),
                },
            },
        },
        "livello_open_data": {"type": "integer", "minimum": 1, "maximum": 5},
        "motivazione_open_data": _testo(),
        "esito_globale": _scelta(EsitoGlobale.__args__),
        "esito_validazione": _scelta(EsitoValidazione.__args__),
        "motivazione_validazione": _testo(),
    },
}

_COLORI_RILIEVO = {
    "Positivo": "#28a745",
    "Negativo": "#dc3545",
    "Parziale": "#ffc107",
    "Non Applicabile": "#6c757d",
    "Non valutabile": "#6c757d",
}
_COLORI_GLOBALE = {"Conforme": "#28a745", "Parzialmente conforme": "#ffc107", "Non conforme": "#dc3545"}
_COLORI_VALIDAZIONE = {
    "Pubblicabile": "#28a745",
    "Pubblicabile provvisoriamente": "#ffc107",
    "Non pubblicabile": "#dc3545",
}
_COLORE_OPEN_DATA = {1: "#dc3545", 2: "#fd7e14", 3: "#ffc107", 4: "#20c997", 5: "#28a745"}
_TESTO_SCURO = {"#ffc107", "#20c997"}  # sfondi chiari: testo nero
_CELLA = "border: 1px solid #999; padding: 6px; vertical-align: top;"


def _badge(testo: str, colore: str, classe: str = "") -> str:
    attributo = f' class="{classe}"' if classe else ""
    testo_colore = "#000" if colore in _TESTO_SCURO else "#fff"
    return (
        f'<span{attributo} style="background-color: {colore}; color: {testo_colore}; padding: 2px 8px; '
        f'border-radius: 4px; font-weight: bold;">{html_lib.escape(testo)}</span>'
    )


def componi_report(r: ReportAnalisi, titolo: str, fonte: str, non_letti: list[str] = ()) -> str:
    """Report HTML dell'analisi, con stili in linea (si modifica nell'editor e si esporta in
    PDF o Word). L'esito di validazione sta nel badge con class="esito-validazione";
    `non_letti`: documenti collegati alla pagina che non è stato possibile leggere."""
    e = html_lib.escape
    righe = "".join(
        "<tr>"
        f'<td style="{_CELLA}">{e(x.campo)}</td>'
        f'<td style="{_CELLA}">{e(x.valore_rilevato)}</td>'
        f'<td style="{_CELLA}">{_badge(x.esito, _COLORI_RILIEVO[x.esito])}</td>'
        f'<td style="{_CELLA}">{e(x.nota_correttiva)}</td>'
        "</tr>"
        for x in r.rilievi
    )
    intestazione = "".join(
        f'<th style="{_CELLA} background-color: #e9ecef;">{c}</th>'
        for c in ("Campo", "Valore rilevato", "Esito", "Nota correttiva")
    )
    html = (
        f"<h2>Analisi di conformità: {e(titolo)}</h2>"
        f"<p><strong>Fonte:</strong> {e(fonte)}<br/>"
        f"<strong>Data dell'analisi:</strong> {datetime.now():%d/%m/%Y}</p>"
        + (
            "<p><strong>Documenti collegati non letti</strong> (non considerati nell'analisi):</p><ul>"
            + "".join(f"<li>{e(x)}</li>" for x in non_letti)
            + "</ul>"
            if non_letti
            else ""
        )
        + "<h3>1. Analisi descrittiva dei risultati</h3>"
        + "".join(f"<p>{e(paragrafo)}</p>" for paragrafo in r.analisi if paragrafo.strip())
        + "<h3>2. Sintesi tecnica, Open Data ed esito di validazione</h3>"
        f"<p><strong>Esito globale:</strong> {_badge(r.esito_globale, _COLORI_GLOBALE[r.esito_globale])}</p>"
        f"<p><strong>Livello Open Data:</strong> "
        f"{_badge(f'Livello {r.livello_open_data}', _COLORE_OPEN_DATA[r.livello_open_data])} "
        f"{e(r.motivazione_open_data)}</p>"
        f"<p><strong>Esito di validazione:</strong> "
        f"{_badge(r.esito_validazione, _COLORI_VALIDAZIONE[r.esito_validazione], 'esito-validazione')} "
        f"{e(r.motivazione_validazione)}</p>"
        "<h3>3. Tabella riepilogativa</h3>"
        '<table style="width: 100%; border-collapse: collapse; font-size: 13px;">'
        f"<tr>{intestazione}</tr>{righe}</table>"
    )
    return f"<div class='compliance-section'>{sanifica_html(html)}</div>"


# --- contenuti -------------------------------------------------------------------------------


async def testo_file(f: File, documenti) -> str:
    """Testo di un file per l'LLM (`documenti`: client del converter)."""
    if f.estensione in fonti.TESTI:
        return compatta(testo_semplice(f.contenuto), f.estensione)
    if f.estensione in fonti.FOGLI:
        # numeri con il formato interno: le verifiche controllano come il dato è presentato
        # (registro.REGOLA_NUMERI_FOGLI_DI_CALCOLO)
        try:
            return fogli_in_markdown(f.contenuto, f".{f.estensione}", annota_formato=True)
        except ConversioneNonRiuscita as e:
            raise AnalisiNonRiuscita(f"Impossibile leggere il foglio di calcolo {f.nome}: {e}") from e
    if f.estensione in fonti.DOCUMENTI:
        testo = await documenti.markdown(f.contenuto, f.nome)
        if not testo.strip():
            raise AnalisiNonRiuscita(
                f"{f.nome} non contiene testo leggibile (forse è una scansione): per ora non si può analizzare"
            )
        return testo
    raise AnalisiNonRiuscita(f"Formato non ammesso: {f.nome}")


def _intestato(titolo: str, testo: str) -> str:
    return f"--- {titolo} ---\n{testo}\n--- FINE ---"


@dataclass
class Contenuti:
    parti: list[str]
    estensione: str = ""  # del file analizzato (livello Open Data)
    url: str = ""  # della pagina web analizzata
    fonte: str = ""  # per il report: URL o nomi dei file
    non_letti: list[str] = field(default_factory=list)  # documenti collegati saltati, con il motivo

    @property
    def testo(self) -> str:
        return "\n\n".join(self.parti)


async def contenuti(
    url: str,
    files: list[File],
    documenti,
    *,
    analizza_documenti=False,
    max_documenti=fonti.MAX_DOCUMENTI,
    segui_link=False,
    max_link=fonti.MAX_LINK,
    client=None,
) -> Contenuti:
    """Pagina web (con i documenti e i link collegati), documento indicato da un URL o file
    caricati. `client`: client HTTP da usare (nei test)."""
    fonte = url
    if url:
        est = fonti.estensione(urlparse(url).path)
        if est in fonti.ESTENSIONI:  # l'URL è direttamente un documento
            nome, dati = await fonti.documento_da_url(url, client)
            files = [File(nome if fonti.estensione(nome) == est else f"documento.{est}", dati)]
        else:
            pagina = await fonti.pagina(
                url, analizza_documenti=analizza_documenti, max_documenti=max_documenti,
                segui_link=segui_link, max_link=max_link, client=client,
            )  # fmt: skip
            parti = [_intestato(f"CONTENUTO DELLA PAGINA WEB ({url})", pagina.html)]
            non_letti = list(pagina.non_letti)
            for nome, dati in pagina.documenti:
                try:
                    parti.append(_intestato(f"DOCUMENTO COLLEGATO: {nome}", await testo_file(File(nome, dati), documenti)))
                except AnalisiNonRiuscita as e:  # un allegato illeggibile non ferma l'analisi
                    log.warning("Documento collegato %s non letto: %s", nome, e)
                    non_letti.append(f"{nome}: {e}")
                except Exception as e:  # noqa: BLE001 - es. converter non raggiungibile
                    log.warning("Documento collegato %s non convertito: %s", nome, e)
                    non_letti.append(f"{nome}: non convertito in testo")
            return Contenuti(parti, url=url, fonte=fonte, non_letti=non_letti)
    if not files:
        raise AnalisiNonRiuscita("Indica una pagina web o carica dei documenti")
    fonte = fonte or ", ".join(f.nome for f in files)
    if len(files) == 1:
        return Contenuti([await testo_file(files[0], documenti)], estensione=files[0].estensione, fonte=fonte)
    mappa = "\n".join(
        f"Documento [{i}]: {f.nome} | Note utente: {f.descrizione or 'nessuna'} | Estensione: {f.estensione.upper()}"
        for i, f in enumerate(files, start=1)
    )
    parti = [_intestato("MAPPA DEI DOCUMENTI ALLEGATI ALL'AUDIT", mappa)]
    for f in files:
        parti.append(_intestato(f"DOCUMENTO {f.nome} (note: {f.descrizione or 'nessuna'})", await testo_file(f, documenti)))
    return Contenuti(parti, estensione="Insieme di documenti misti", fonte=fonte)


def _controlla_lunghezza(c: Contenuti) -> None:
    if len(c.testo) > MAX_TESTO:
        raise AnalisiNonRiuscita(
            f"Contenuto troppo lungo ({len(c.testo):,} caratteri, massimo {MAX_TESTO:,}): dividilo e riprova".replace(",", ".")
        )


# --- esecuzione ------------------------------------------------------------------------------


async def analizza(controllo: str, c: Contenuti, contesto: Contesto, llm) -> dict:
    """Report HTML dell'analisi con l'esito di validazione."""
    _controlla_lunghezza(c)
    prompt = prompt_analisi(controllo, contesto, estensione=c.estensione, url=c.url)
    log.info("Analisi %s: %d caratteri di contenuto", controllo, len(c.testo))
    risposta = await llm.dati_json(prompt, c.testo, json_schema(SCHEMA_REPORT))
    try:
        report = ReportAnalisi.model_validate(risposta)
    except ValidationError as e:
        raise AnalisiNonRiuscita(f"Il modello ha risposto in un formato non previsto: {e.error_count()} errori") from e
    schema, variante = trova_prompt(controllo)
    titolo = f"{schema.articolo[:1].upper()}{schema.articolo[1:]} - {variante.titolo if variante else schema.titolo}"
    return {"html": componi_report(report, titolo, c.fonte or c.url, c.non_letti)}


async def estrai_dati(schema_id: str, variante_id: str, c: Contenuti, llm, sezione_id: str = "") -> dict:
    """Dati per precompilare il form dello schema, con gli avvisi su ciò che manca."""
    _controlla_lunghezza(c)
    schema = get_schema(schema_id)
    if schema is None:
        raise AnalisiNonRiuscita("Schema non previsto")
    variante = schema.variante(variante_id) if variante_id else None

    async def genera(prompt: str, schema_risposta: dict) -> dict:
        return await llm.dati_json(SISTEMA_ESTRAZIONE, f"{prompt}\n\n{c.testo}", json_schema(schema_risposta))

    risultato = await estrai(schema, variante, genera, sezione_id)
    if c.non_letti:
        risultato["avvisi"] = [*(f"Documento collegato non letto: {x}" for x in c.non_letti), *risultato.get("avvisi", [])]
    return risultato
