"""Richieste HTTP in uscita del modulo trasparenza, protette da SSRF: solo http/https verso
indirizzi pubblici, ogni redirect verificato, IP effettivamente contattato controllato
(difesa dal DNS rebinding), dimensione massima. Impediscono di usare il worker per
raggiungere la rete interna (database, servizi del cluster, metadata del cloud).
Su httpx asincrono.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTE = 25 * 1024 * 1024
MAX_REDIRECT = 5
INTESTAZIONI = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


class UrlNonConsentito(ValueError):
    """URL con schema non ammesso, verso un indirizzo non pubblico, o risorsa troppo grande."""


def _ip_pubblico(ip: str) -> bool:
    indirizzo = ipaddress.ip_address(ip)
    if isinstance(indirizzo, ipaddress.IPv6Address) and indirizzo.ipv4_mapped:
        indirizzo = indirizzo.ipv4_mapped
    return indirizzo.is_global and not indirizzo.is_multicast


@lru_cache(maxsize=512)
def _host_pubblico(host: str, porta: int) -> bool:
    try:
        risultati = socket.getaddrinfo(host, porta, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    indirizzi = {r[4][0] for r in risultati}
    return bool(indirizzi) and all(_ip_pubblico(ip) for ip in indirizzi)


def verifica_url(url: str) -> str:
    """Solleva UrlNonConsentito se l'URL non è http/https o se l'host risolve (anche solo
    in parte) su indirizzi privati, di loopback, link-local... Bloccante (risoluzione DNS)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UrlNonConsentito(f"Schema non ammesso: {parsed.scheme or 'assente'}")
    if not parsed.hostname:
        raise UrlNonConsentito("URL senza host")
    porta = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not _host_pubblico(parsed.hostname.lower(), porta):
        raise UrlNonConsentito(f"Host non consentito: {parsed.hostname}")
    return url


def url_consentito(url: str) -> bool:
    try:
        verifica_url(url)
        return True
    except UrlNonConsentito:
        return False


@dataclass
class Scaricato:
    url: str  # dopo i redirect
    stato: int
    tipo: str  # Content-Type senza parametri
    contenuto: bytes
    disposizione: str = ""  # Content-Disposition (nome del file scaricato)


def _ip_connesso(risposta: httpx.Response) -> str | None:
    flusso = risposta.extensions.get("network_stream")
    try:
        return flusso.get_extra_info("server_addr")[0] if flusso else None
    except Exception:  # noqa: BLE001 - informazione non disponibile
        return None


async def scarica(
    client: httpx.AsyncClient, url: str, *, timeout: float = 15, max_byte: int = MAX_BYTE
) -> Scaricato:
    """GET con la protezione SSRF; i redirect si seguono a mano, verificandoli uno per uno."""
    attuale = url
    for _ in range(MAX_REDIRECT + 1):
        await asyncio.to_thread(verifica_url, attuale)
        async with client.stream(
            "GET", attuale, headers=INTESTAZIONI, timeout=timeout, follow_redirects=False
        ) as risposta:
            ip = _ip_connesso(risposta)
            if ip and not _ip_pubblico(ip):
                raise UrlNonConsentito(f"Connessione a un indirizzo non pubblico: {ip}")
            if risposta.is_redirect:
                attuale = urljoin(attuale, risposta.headers.get("Location", ""))
                continue
            lunghezza = risposta.headers.get("Content-Length", "")
            if lunghezza.isdigit() and int(lunghezza) > max_byte:
                raise UrlNonConsentito(f"Risorsa troppo grande ({lunghezza} byte)")
            contenuto = bytearray()
            async for blocco in risposta.aiter_bytes():
                contenuto.extend(blocco)
                if len(contenuto) > max_byte:
                    raise UrlNonConsentito(f"Risorsa oltre il limite di {max_byte} byte")
            tipo = risposta.headers.get("Content-Type", "").split(";")[0].strip().lower()
            disposizione = risposta.headers.get("Content-Disposition", "")
            return Scaricato(attuale, risposta.status_code, tipo, bytes(contenuto), disposizione)
    raise UrlNonConsentito("Troppi redirect")
