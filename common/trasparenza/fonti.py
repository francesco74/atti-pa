"""Contenuti da dare all'LLM per l'analisi o l'estrazione: pagine web (con i documenti collegati
e alcuni link del contenuto). Fogli di calcolo, CSV, XML e JSON li legge pa-common (analisi.testo_file),
PDF e documenti di testo li converte in Markdown il converter.
Su httpx asincrono.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from email.message import Message
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .rete import INTESTAZIONI, Scaricato, UrlNonConsentito, scarica, url_consentito, verifica_url

log = logging.getLogger("common.trasparenza.fonti")

DOCUMENTI = {"pdf", "doc", "docx", "odt"}  # testo in Markdown dal converter
FOGLI = {"xls", "xlsx", "ods"}
TESTI = {"csv", "xml", "json"}  # testo semplice (XML e JSON compattati)
ESTENSIONI = DOCUMENTI | FOGLI | TESTI

MAX_LINK = 5  # link del contenuto seguiti in una pagina, se non indicato
MAX_LINK_MASSIMO = 15  # limite al numero di link scelto dall'utente
MAX_DOCUMENTI = 5  # documenti collegati letti da una pagina, se non indicato
MAX_DOCUMENTI_MASSIMO = 10  # limite al numero di documenti scelto dall'utente
MAX_IFRAME = 3
# link senza estensione che potrebbero scaricare un documento (es. /download/123, allegato.php?id=)
_RE_DOWNLOAD = re.compile(r"download|allegat|attachment|scarica|getfile", re.IGNORECASE)
# formato dal Content-Type, quando né il nome né l'indirizzo hanno un'estensione ammessa
_TIPI = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "text/csv": "csv",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/json": "json",
}
_RUMORE = ("menu", "sidebar", "nav", "header", "footer", "topbar", "widget", "breadcrumb")


def estensione(nome: str) -> str:
    return nome.rsplit(".", 1)[-1].lower() if "." in nome else ""


def _estensione_url(indirizzo: str) -> str:
    return estensione(urlparse(indirizzo).path)


def _nome_disposizione(valore: str) -> str:
    """Nome del file dal Content-Disposition (anche filename*=UTF-8''...), senza percorso."""
    if not valore:
        return ""
    m = Message()
    m["content-disposition"] = valore
    return (m.get_filename() or "").replace("\\", "/").split("/")[-1].strip()


def nome_documento(r: Scaricato) -> str | None:
    """Nome con un'estensione ammessa per un file scaricato: dal Content-Disposition,
    dall'indirizzo o dal Content-Type; None se non è un documento leggibile (es. una pagina)."""
    if r.tipo == "text/html":
        return None
    nome = _nome_disposizione(r.disposizione) or unquote(urlparse(r.url).path.split("/")[-1])
    if estensione(nome) in ESTENSIONI:
        return nome
    est = _TIPI.get(r.tipo)
    return f"{nome or 'documento'}.{est}" if est else None


# --- pagine web ------------------------------------------------------------------------------


@dataclass
class Pagina:
    html: str  # contenuto della pagina, delle pagine collegate e degli iframe
    documenti: list[tuple[str, bytes]] = field(default_factory=list)  # (nome, contenuto)
    non_letti: list[str] = field(default_factory=list)  # documenti collegati saltati, con il motivo


def _contenuto(soup: BeautifulSoup) -> str:
    """Solo l'area dei contenuti: niente head, script, stili, navigazione."""
    if soup.head:
        soup.head.decompose()
    for tag in soup(["script", "style", "meta", "link", "nav", "footer", "aside", "header", "noscript"]):
        tag.decompose()
    body = soup.find("body")
    return str(body) if body else str(soup)


def _link_a_documento(a, href: str) -> bool:
    """Link che porta (o potrebbe portare) a un documento: estensione ammessa, oppure
    attributo download o indirizzo da download, fuori dalla navigazione."""
    if _estensione_url(href) in ESTENSIONI:
        return True
    return (a.has_attr("download") or bool(_RE_DOWNLOAD.search(href))) and not _link_di_navigazione(a)


def _nome_unico(nome: str, usati: set[str]) -> str:
    base, punto, est = nome.rpartition(".")
    candidato, n = nome, 2
    while candidato in usati:
        candidato, n = f"{base}_{n}{punto}{est}", n + 1
    usati.add(candidato)
    return candidato


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
    analizza_documenti: bool = False,
    max_documenti: int = MAX_DOCUMENTI,
    segui_link: bool = False,
    max_link: int = MAX_LINK,
    client: httpx.AsyncClient | None = None,
) -> Pagina:
    """Scarica la pagina; con `analizza_documenti` anche fino a `max_documenti` documenti
    collegati (al più MAX_DOCUMENTI_MASSIMO, nei formati ammessi; segnati nel testo con
    [FILE ALLEGATO: nome]), con `segui_link` fino a `max_link` pagine collegate dal contenuto
    (al più MAX_LINK_MASSIMO)."""
    max_link = max(1, min(max_link, MAX_LINK_MASSIMO))
    max_documenti = max(1, min(max_documenti, MAX_DOCUMENTI_MASSIMO))
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

        if analizza_documenti:
            await _documenti_collegati(client, url, soup, max_documenti, risultato)

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
                    or _estensione_url(href) in ESTENSIONI
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


async def _documenti_collegati(client, url: str, soup, massimo: int, risultato: Pagina) -> None:
    """Scarica fino a `massimo` documenti linkati dalla pagina. I link con un'estensione
    ammessa che non si leggono finiscono in `non_letti`; quelli solo "da download" che non
    portano a un documento (es. una pagina) si ignorano. I tentativi sono limitati al doppio
    del massimo, perché i link da download possono essere molti."""
    visti: set[str] = set()
    usati: set[str] = set()
    tentativi = 0
    for a in soup.find_all("a", href=True):
        if len(risultato.documenti) >= massimo or tentativi >= 2 * massimo:
            break
        href = a.get("href").strip()
        if not href or href.startswith("#") or not _link_a_documento(a, href):
            continue
        indirizzo = urljoin(url, href)
        if indirizzo in visti:
            continue
        visti.add(indirizzo)
        tentativi += 1
        dichiarato = _estensione_url(indirizzo) in ESTENSIONI
        etichetta = unquote(urlparse(indirizzo).path.split("/")[-1]) or indirizzo
        try:
            r = await scarica(client, indirizzo, timeout=10)
            if r.stato >= 400:
                raise ValueError(f"errore HTTP {r.stato}")
        except (httpx.HTTPError, UrlNonConsentito, ValueError) as e:
            log.warning("Documento %s non scaricato: %s", indirizzo, e)
            if dichiarato:
                risultato.non_letti.append(f"{etichetta}: non scaricato ({str(e) or type(e).__name__})")
            continue
        nome = nome_documento(r)
        if nome is None:
            if dichiarato:
                risultato.non_letti.append(f"{etichetta}: il sito non ha restituito un documento")
            continue
        nome = _nome_unico(nome, usati)
        risultato.documenti.append((nome, r.contenuto))
        segno = soup.new_tag("span")
        segno.string = f" [FILE ALLEGATO: {nome}] "
        a.insert_after(segno)


async def documento_da_url(url: str, client: httpx.AsyncClient | None = None) -> tuple[str, bytes]:
    """File scaricato da un URL che punta direttamente a un documento: (nome, contenuto)."""
    async with client or httpx.AsyncClient() as client:
        r = await scarica(client, url)
    if r.stato >= 400:
        raise ValueError(f"Il documento non è scaricabile (errore HTTP {r.stato})")
    return urlparse(r.url).path.split("/")[-1] or f"documento.{estensione(urlparse(url).path)}", r.contenuto
