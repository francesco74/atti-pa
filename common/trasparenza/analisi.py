"""Analisi e estrazione del modulo trasparenza, senza database: preparazione dei contenuti
(pagina web, documento da URL, file caricati), prompt dell'analisi generato dallo schema o dal
controllo scelto, chiamata all'LLM, pulizia del report. Le esegue il worker
(lavori della tabella trasparenza_lavori). Ripreso da PApuntozeroIA (app.py).

I documenti arrivano all'LLM come testo: PDF e documenti di testo convertiti in Markdown dal
converter, fogli di calcolo come tabelle, CSV come sono, pagine web come HTML del contenuto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import fonti
from .estrazione import MAX_TESTO, estrai, json_schema
from .registro import genera_prompt, get_schema, trova_prompt
from .sicurezza import sanifica_html

log = logging.getLogger("common.trasparenza.analisi")

ANALISI = "ANALISI"
ESTRAZIONE = "ESTRAZIONE"

OUTPUT_RULES = """
Genera ESCLUSIVAMENTE un documento HTML5 completo con CSS interno, non impostare dimensioni massime in larghezza e strutturato come segue:
STILI IN LINEA: colori, sfondi e bordi dei badge (esiti, esito di validazione, livello Open Data) e delle celle delle
tabelle vanno applicati con l'attributo style direttamente sull'elemento. Il report viene poi modificato in un editor e
convertito in PDF o Word, che NON conservano il CSS interno: un badge con testo bianco e sfondo definito solo nel CSS
interno diventerebbe invisibile. Il CSS interno resta per le impostazioni generali (font, margini, spaziature). Gli
attributi class richiesti più avanti (es. class="esito-validazione") vanno comunque mantenuti.

1. ANALISI DESCRITTIVA DEI RISULTATI:
   - Fornisci un testo narrativo dettagliato che descriva l'esito globale dell'audit.
   - Commenta la qualità dei dati rispetto ai requisiti delle Istruzioni operative ANAC (All. 4 alla delibera n. 495/2024, come modificato dalla delibera n. 481/2025), limitandoti a quelli verificabili dal documento: integrità, completezza (esattezza e accuratezza), tempestività, costante aggiornamento, semplicità di consultazione, comprensibilità, omogeneità, facile accessibilità e riutilizzabilità (formato aperto), conformità ai documenti originali, indicazione della provenienza (se il dato è una rielaborazione), riservatezza.
   - Spiega eventuali criticità riscontrate nei formati, nella tempestività e nella completezza dei dati.

2. SINTESI TECNICA, OPEN DATA ED ESITO DI VALIDAZIONE:
   - Inserisci un badge colorato per l'esito globale ed un badge colorato per il Livello Open Data assegnato.
   - Indica l'esito di validazione secondo il § 2 delle Istruzioni operative, scegliendo uno solo tra:
     * "Pubblicabile" (nessuna difformità);
     * "Pubblicabile provvisoriamente" (difformità lievi: il dato va sostituito non appena disponibili dati conformi);
     * "Non pubblicabile" (difformità macroscopiche).
     Motiva l'esito in una frase.
   - Il badge dell'esito di validazione deve essere un unico elemento con class="esito-validazione" che contenga
     SOLO il testo dell'esito (es. <span class="esito-validazione" style="...">Pubblicabile provvisoriamente</span>):
     serve all'applicazione per classificare i documenti salvati.

3. TABELLA RIEPILOGATIVA FINALE:
   - Crea una tabella con colonne: ["Campo", "Valore Rilevato", "Esito", "Nota Correttiva"].
   - Usa solamente uno tra i seguenti Badge per gli Esiti:
     * VERDE (#28a745) con etichetta "Positivo".
     * ROSSO (#dc3545) con etichetta "Negativo (Dato mancante o errore grave)".
     * ARANCIO (#ffc107) con etichetta "Parziale (Dato presente ma formato errato)".
     * GRIGIO (#6c757d) con etichetta "Non Applicabile".
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


def pulisci_report(testo: str) -> str:
    """Report HTML dell'LLM: senza delimitatori di codice, solo stili e corpo, sanificato."""
    testo = re.sub(r"^\s*```[a-zA-Z]*\n", "", testo.strip())
    testo = re.sub(r"\n```\s*$", "", testo.strip())
    soup = BeautifulSoup(testo, "html.parser")
    stili = "".join(str(s) for s in soup.find_all("style"))
    corpo = soup.find("body")
    html = stili + (corpo.decode_contents() if corpo else testo)
    return f"<div class=\'compliance-section\'>{sanifica_html(html)}</div>"


# --- contenuti -------------------------------------------------------------------------------


async def testo_file(f: File, documenti) -> str:
    """Testo di un file per l'LLM (`documenti`: client del converter)."""
    if f.estensione in fonti.TESTI:
        return fonti.testo_csv(f.contenuto)
    if f.estensione in fonti.FOGLI:
        try:
            return fonti.tabella_foglio(f.contenuto, f.estensione)
        except Exception as e:  # noqa: BLE001 - file danneggiato o formato inatteso
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

    @property
    def testo(self) -> str:
        return "\n\n".join(self.parti)


async def contenuti(
    url: str, files: list[File], documenti, *, analizza_pdf=False, segui_link=False, client=None
) -> Contenuti:
    """Pagina web (con PDF e link collegati), documento indicato da un URL o file caricati.
    `client`: client HTTP da usare (nei test)."""
    if url:
        est = fonti.estensione(urlparse(url).path)
        if est in fonti.ESTENSIONI:  # l'URL è direttamente un documento
            nome, dati = await fonti.documento_da_url(url, client)
            files = [File(nome if fonti.estensione(nome) == est else f"documento.{est}", dati)]
        else:
            pagina = await fonti.pagina(url, analizza_pdf=analizza_pdf, segui_link=segui_link, client=client)
            parti = [_intestato(f"CONTENUTO DELLA PAGINA WEB ({url})", pagina.html)]
            for nome, dati in pagina.pdf:
                try:
                    parti.append(_intestato(f"DOCUMENTO PDF COLLEGATO: {nome}", await testo_file(File(nome, dati), documenti)))
                except Exception as e:  # noqa: BLE001 - un allegato illeggibile non ferma l'analisi
                    log.warning("PDF collegato %s non convertito: %s", nome, e)
            return Contenuti(parti, url=url)
    if not files:
        raise AnalisiNonRiuscita("Indica una pagina web o carica dei documenti")
    if len(files) == 1:
        return Contenuti([await testo_file(files[0], documenti)], estensione=files[0].estensione)
    mappa = "\n".join(
        f"Documento [{i}]: {f.nome} | Note utente: {f.descrizione or 'nessuna'} | Estensione: {f.estensione.upper()}"
        for i, f in enumerate(files, start=1)
    )
    parti = [_intestato("MAPPA DEI DOCUMENTI ALLEGATI ALL'AUDIT", mappa)]
    for f in files:
        parti.append(_intestato(f"DOCUMENTO {f.nome} (note: {f.descrizione or 'nessuna'})", await testo_file(f, documenti)))
    return Contenuti(parti, estensione="Insieme di documenti misti")


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
    return {"html": pulisci_report(await llm.genera(prompt, c.testo))}


async def estrai_dati(schema_id: str, variante_id: str, c: Contenuti, llm) -> dict:
    """Dati per precompilare il form dello schema, con gli avvisi su ciò che manca."""
    _controlla_lunghezza(c)
    schema = get_schema(schema_id)
    if schema is None:
        raise AnalisiNonRiuscita("Schema non previsto")
    variante = schema.variante(variante_id) if variante_id else None

    async def genera(prompt: str, schema_risposta: dict) -> dict:
        return await llm.dati_json(SISTEMA_ESTRAZIONE, f"{prompt}\n\n{c.testo}", json_schema(schema_risposta))

    return await estrai(schema, variante, genera)
