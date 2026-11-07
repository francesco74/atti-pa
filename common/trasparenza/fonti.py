"""Contenuti da dare all'LLM per l'analisi o l'estrazione: pagine web (con i PDF collegati e
alcuni link del contenuto), fogli di calcolo come tabelle con i numeri come li vede l'utente,
CSV come testo. PDF e documenti di testo li converte in Markdown il converter.
Su httpx asincrono.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .rete import INTESTAZIONI, UrlNonConsentito, scarica, url_consentito, verifica_url

log = logging.getLogger("common.trasparenza.fonti")

DOCUMENTI = {"pdf", "doc", "docx", "odt"}  # testo in Markdown dal converter
FOGLI = {"xls", "xlsx", "ods"}
TESTI = {"csv"}
ESTENSIONI = DOCUMENTI | FOGLI | TESTI

MAX_LINK = 5  # link del contenuto seguiti in una pagina, se non indicato
MAX_LINK_MASSIMO = 15  # limite al numero di link scelto dall'utente
MAX_PDF = 5  # PDF collegati scaricati da una pagina
MAX_IFRAME = 3
_RE_PDF = re.compile(r"\.pdf(\?.*)?$", re.IGNORECASE)
_RUMORE = ("menu", "sidebar", "nav", "header", "footer", "topbar", "widget", "breadcrumb")


def estensione(nome: str) -> str:
    return nome.rsplit(".", 1)[-1].lower() if "." in nome else ""


# --- pagine web ------------------------------------------------------------------------------


@dataclass
class Pagina:
    html: str  # contenuto della pagina, delle pagine collegate e degli iframe
    pdf: list[tuple[str, bytes]] = field(default_factory=list)  # (nome, contenuto)


def _contenuto(soup: BeautifulSoup) -> str:
    """Solo l'area dei contenuti: niente head, script, stili, navigazione."""
    if soup.head:
        soup.head.decompose()
    for tag in soup(["script", "style", "meta", "link", "nav", "footer", "aside", "header", "noscript"]):
        tag.decompose()
    body = soup.find("body")
    return str(body) if body else str(soup)


def _link_di_navigazione(a) -> bool:
    if a.find_parent(["nav", "footer", "header", "aside"]):
        return True
    for genitore in a.parents:
        if genitore.name == "[document]":
            break
        classi = genitore.get("class", [])
        testo = " ".join(classi) if isinstance(classi, list) else str(classi)
        identificativi = f"{genitore.get('id', '')} {testo}".lower()
        if any(p in identificativi for p in _RUMORE):
            return True
    return False


async def _rendering_js(url: str, timeout_ms: int = 20_000) -> str:
    """DOM finale della pagina in Chromium headless (contenuti caricati via JavaScript).
    Ogni richiesta del browser deve andare verso indirizzi pubblici (SSRF)."""
    from playwright.async_api import TimeoutError as PWTimeout
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            pagina = await browser.new_page(user_agent=INTESTAZIONI["User-Agent"], locale="it-IT")

            async def filtra(route):
                richiesta = route.request.url
                if richiesta.startswith(("data:", "blob:")) or url_consentito(richiesta):
                    await route.continue_()
                else:
                    log.warning("Richiesta del browser bloccata (SSRF): %s", richiesta)
                    await route.abort()

            await pagina.route("**/*", filtra)
            await pagina.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                await pagina.wait_for_load_state("networkidle", timeout=10_000)
            except PWTimeout:
                log.warning("Rete non ferma per %s: uso il DOM attuale", url)
            return await pagina.content()
        finally:
            await browser.close()


async def pagina(
    url: str,
    *,
    analizza_pdf: bool = False,
    segui_link: bool = False,
    max_link: int = MAX_LINK,
    client: httpx.AsyncClient | None = None,
) -> Pagina:
    """Scarica la pagina; con `analizza_pdf` anche i PDF collegati (segnati nel testo con
    [FILE ALLEGATO: nome]), con `segui_link` fino a `max_link` pagine collegate dal contenuto
    (al più MAX_LINK_MASSIMO)."""
    max_link = max(1, min(max_link, MAX_LINK_MASSIMO))
    await asyncio.to_thread(verifica_url, url)
    async with client or httpx.AsyncClient() as client:
        sorgente: str | bytes | None = None
        # il frammento (#...) non arriva al server: la pagina lo usa per caricare i
        # contenuti con JavaScript, serve il browser
        if urlparse(url).fragment:
            try:
                sorgente = await _rendering_js(url)
            except Exception as e:  # noqa: BLE001 - si ripiega sullo scaricamento semplice
                log.warning("Rendering di %s non riuscito, scaricamento semplice: %s", url, e)
        if sorgente is None:
            r = await scarica(client, url)
            if r.stato >= 400:
                raise ValueError(f"La pagina ha risposto con l'errore HTTP {r.stato}")
            sorgente = r.contenuto
        soup = BeautifulSoup(sorgente, "html.parser")
        risultato = Pagina(html="")
        correlate: list[str] = []

        if analizza_pdf:
            for i, a in enumerate(soup.find_all("a", href=_RE_PDF)[:MAX_PDF]):
                indirizzo = urljoin(url, a.get("href"))
                try:
                    r = await scarica(client, indirizzo, timeout=10)
                    if r.stato >= 400:
                        raise ValueError(f"HTTP {r.stato}")
                except (httpx.HTTPError, UrlNonConsentito, ValueError) as e:
                    log.warning("PDF %s non scaricato: %s", indirizzo, e)
                    continue
                nome = indirizzo.split("/")[-1].split("?")[0] or f"documento_{i + 1}.pdf"
                if not nome.lower().endswith(".pdf"):
                    nome += ".pdf"
                risultato.pdf.append((nome, r.contenuto))
                segno = soup.new_tag("span")
                segno.string = f" [FILE ALLEGATO: {nome}] "
                a.insert_after(segno)

        if segui_link:
            visti = {url}
            for a in soup.find_all("a", href=True):
                if len(correlate) >= max_link:
                    break
                href = a.get("href").strip()
                if (
                    _link_di_navigazione(a)
                    or not href
                    or href.startswith("#")
                    or href.lower().startswith(("mailto:", "tel:", "javascript:"))
                    or _RE_PDF.search(href)
                ):
                    continue
                indirizzo = urljoin(url, href)
                if indirizzo in visti:
                    continue
                visti.add(indirizzo)
                try:
                    r = await scarica(client, indirizzo, timeout=5)
                except (httpx.HTTPError, UrlNonConsentito) as e:
                    log.warning("Link %s non seguito: %s", indirizzo, e)
                    continue
                if r.stato == 200 and r.tipo == "text/html":
                    contenuto = _contenuto(BeautifulSoup(r.contenuto, "html.parser"))
                    correlate.append(
                        f"\n\n--- CONTENUTO PAGINA CORRELATA ({indirizzo}) ---\n{contenuto}"
                        "\n--- FINE PAGINA CORRELATA ---"
                    )

        iframe = [urljoin(url, f.get("src")) for f in soup.find_all("iframe")[:MAX_IFRAME] if f.get("src")]
        parti = [_contenuto(soup), *correlate]
        for indirizzo in iframe:
            try:
                r = await scarica(client, indirizzo, timeout=5)
                parti.append(_contenuto(BeautifulSoup(r.contenuto, "html.parser")))
            except (httpx.HTTPError, UrlNonConsentito) as e:
                log.debug("Iframe %s ignorato: %s", indirizzo, e)
        risultato.html = "\n\n".join(parti)
        return risultato


async def documento_da_url(url: str, client: httpx.AsyncClient | None = None) -> tuple[str, bytes]:
    """File scaricato da un URL che punta direttamente a un documento: (nome, contenuto)."""
    async with client or httpx.AsyncClient() as client:
        r = await scarica(client, url)
    if r.stato >= 400:
        raise ValueError(f"Il documento non è scaricabile (errore HTTP {r.stato})")
    return urlparse(r.url).path.split("/")[-1] or f"documento.{estensione(urlparse(url).path)}", r.contenuto


# --- fogli di calcolo e CSV ------------------------------------------------------------------


def testo_csv(contenuto: bytes) -> str:
    try:
        return contenuto.decode("utf-8")
    except UnicodeDecodeError:
        return contenuto.decode("latin-1")


def _numero_italiano(valore, formato: str) -> str:
    """Valore numerico come lo vede l'utente (punto per le migliaia, virgola per i decimali).
    Il number_format di Excel è scritto sempre in sintassi en-US e non indica come appare
    il dato: va tradotto, altrimenti un formato corretto sembrerebbe sbagliato."""
    if formato == "General":
        return str(int(valore)) if float(valore).is_integer() else str(valore).replace(".", ",")
    m = re.search(r"\.(0+)", formato)
    decimali = len(m.group(1)) if m else 0
    migliaia = "," in (formato.split(".")[0] if "." in formato else formato)
    testo = f"{float(valore):,.{decimali}f}"
    if migliaia:
        return testo.replace(",", "§").replace(".", ",").replace("§", ".")
    return testo.replace(",", "").replace(".", ",")


def _cella_numerica(valore, formato: str) -> str:
    if formato == "General" and float(valore).is_integer():
        return str(int(valore))
    return f"{_numero_italiano(valore, formato)} [visualizzato in Excel; formato interno: {formato}]"


def _righe_xlsx(contenuto: bytes) -> list[list[str]]:
    import openpyxl

    foglio = openpyxl.load_workbook(io.BytesIO(contenuto), data_only=True).active
    righe = []
    for i, riga in enumerate(foglio.iter_rows()):
        valori = []
        for cella in riga:
            v = cella.value
            if i == 0 or v is None or isinstance(v, bool) or not isinstance(v, int | float):
                valori.append("" if v is None else str(v).strip())
            else:
                valori.append(_cella_numerica(v, cella.number_format))
        righe.append(valori)
    return righe


def _righe_xls(contenuto: bytes) -> list[list[str]]:
    import xlrd

    libro = xlrd.open_workbook(file_contents=contenuto, formatting_info=True)
    foglio = libro.sheet_by_index(0)
    righe = []
    for r in range(foglio.nrows):
        valori = []
        for c in range(foglio.ncols):
            v = foglio.cell_value(r, c)
            if r == 0 or v == "" or foglio.cell_type(r, c) != xlrd.XL_CELL_NUMBER:
                valori.append(str(v).strip())
                continue
            fmt = libro.format_map.get(libro.xf_list[foglio.cell_xf_index(r, c)].format_key)
            valori.append(_cella_numerica(v, fmt.format_str if fmt else "General"))
        righe.append(valori)
    return righe


def _righe_ods(contenuto: bytes) -> list[list[str]]:
    from odf.opendocument import load
    from odf.table import Table, TableCell, TableRow
    from odf.teletype import extractText

    foglio = load(io.BytesIO(contenuto)).spreadsheet.getElementsByType(Table)[0]
    righe = []
    for i, riga in enumerate(foglio.getElementsByType(TableRow)):
        celle = riga.getElementsByType(TableCell)
        if not celle:
            continue
        valori = []
        for cella in celle:
            visibile = extractText(cella).strip()
            tipo, grezzo = cella.getAttribute("valuetype"), cella.getAttribute("value")
            if i and tipo in ("float", "currency", "percentage") and grezzo is not None:
                if not (grezzo.endswith(".0") and visibile == grezzo[:-2]):
                    visibile = f"{grezzo} [Visualizzato come: {visibile}]"
            valori.append(visibile)
        righe.append(valori)
    return righe


def tabella_foglio(contenuto: bytes, est: str) -> str:
    """Primo foglio come tabella Markdown (prima riga = intestazioni)."""
    lettori = {"xlsx": _righe_xlsx, "xls": _righe_xls, "ods": _righe_ods}
    if est not in lettori:
        raise ValueError(f"Formato di foglio non supportato: {est}")
    righe = [r for r in lettori[est](contenuto) if any(r)]
    if len(righe) < 2:
        return "Nessun dato valido trovato nel file."
    colonne = max(len(r) for r in righe)
    pulite = [[c.replace("|", "\\|").replace("\n", " ") for c in r] + [""] * (colonne - len(r)) for r in righe]
    testo = ["| " + " | ".join(pulite[0]) + " |", "|" + " --- |" * colonne]
    testo += ["| " + " | ".join(r) + " |" for r in pulite[1:]]
    return "\n".join(testo)
