"""Contenuti da dare all'LLM per l'analisi o l'estrazione: pagine web (con i PDF collegati e
alcuni link del contenuto). Fogli di calcolo e CSV li legge pa-common (analisi.testo_file),
PDF e documenti di testo li converte in Markdown il converter.
Su httpx asincrono.
"""

from __future__ import annotations

import asyncio
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
