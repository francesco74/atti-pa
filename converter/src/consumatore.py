"""Consumatore della coda di conversione: file dell'atto -> Markdown.

Avvio: `python consumatore.py` (stessa immagine del servizio HTTP, processo separato).

Riceve da `<prefisso>.conversione` {"percorso", "nome_file"} più gli identificativi del
lavoro ("atto_id" e "verifica_id" per un atto da controllare, "testo_norma_id" per il testo
di una norma inserita manualmente), legge il file dall'archivio (ARCHIVIO_DIR, percorso
relativo), lo converte e pubblica su `<prefisso>.convertiti` gli stessi identificativi con
"markdown" ed "errore". Non accede al database: lo stato lo aggiorna il verifica-worker.
Formato dei messaggi: common/coda.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from pathlib import Path, PurePosixPath

import aio_pika

from main import Convertitore, ErroreConversione, Settings, configura_logging
from markdown import ConversioneNonRiuscita, odt_in_markdown, pdf_in_markdown

log = logging.getLogger("converter.consumatore")

CONVERSIONE = "conversione"
CONVERTITI = "convertiti"


def converti_in_markdown(convertitore: Convertitore, contenuto: bytes, nome_file: str) -> str:
    estensione = Path(nome_file).suffix.lower()
    if estensione == ".pdf":
        return pdf_in_markdown(contenuto)
    if estensione == ".odt":
        return odt_in_markdown(contenuto)
    if estensione in (".docx", ".doc", ".rtf"):
        try:
            odt = convertitore.converti(contenuto, estensione, "odt")
        except ErroreConversione as e:
            raise ConversioneNonRiuscita(e.messaggio) from e
        return odt_in_markdown(odt)
    raise ConversioneNonRiuscita(f"Formato non supportato: {estensione or 'sconosciuto'}")


def leggi_file(archivio_dir: str, percorso: str) -> bytes:
    base = Path(archivio_dir).resolve()
    pieno = (base / PurePosixPath(percorso)).resolve()
    if base not in pieno.parents:
        raise ConversioneNonRiuscita("Percorso del file fuori dall'archivio")
    try:
        return pieno.read_bytes()
    except FileNotFoundError as e:
        raise ConversioneNonRiuscita("File non presente nell'archivio") from e


async def _connetti_in_attesa(url: str) -> aio_pika.abc.AbstractRobustConnection:
    """All'avvio aspetta RabbitMQ invece di fallire: tentativi a intervalli crescenti
    (1, 2, 4... fino a 30 secondi). Dopo la prima connessione la riconnessione è automatica.

    Il converter non usa la libreria comune: stessa logica di common/coda.py.
    """
    attesa, tentativo = 1, 1
    while True:
        try:
            return await aio_pika.connect_robust(url)
        except (OSError, aio_pika.exceptions.AMQPError) as e:
            log.warning(
                "RabbitMQ non raggiungibile (tentativo %d: %s): nuovo tentativo tra %d s",
                tentativo,
                e or type(e).__name__,
                attesa,
            )
        await asyncio.sleep(attesa)
        attesa, tentativo = min(attesa * 2, 30), tentativo + 1


async def main() -> None:
    settings = Settings()
    configura_logging(settings.log_level)
    convertitore = Convertitore(settings)
    connessione = await _connetti_in_attesa(settings.rabbitmq_url)
    canale = await connessione.channel(publisher_confirms=True)
    # una conversione alla volta per processo: LibreOffice occupa molta memoria
    await canale.set_qos(prefetch_count=1)
    nomi = {c: f"{settings.rabbitmq_prefisso}.{c}" for c in (CONVERSIONE, CONVERTITI)}
    for nome in nomi.values():
        await canale.declare_queue(nome, durable=True)
    coda = await canale.get_queue(nomi[CONVERSIONE])

    async def ricevi(messaggio: aio_pika.abc.AbstractIncomingMessage) -> None:
        async with messaggio.process(requeue=False):
            dati = json.loads(messaggio.body)
            # identificativi del lavoro, restituiti così come sono a chi riceve il risultato
            lavoro = {k: v for k, v in dati.items() if k not in ("percorso", "nome_file")}
            descrizione = ", ".join(f"{k} {v}" for k, v in lavoro.items() if v)
            log.info("Conversione di %s (%s)", dati.get("nome_file"), descrizione)
            markdown, errore = None, None
            try:
                contenuto = await asyncio.to_thread(
                    leggi_file, settings.archivio_dir, dati["percorso"]
                )
                markdown = await asyncio.to_thread(
                    converti_in_markdown, convertitore, contenuto, dati["nome_file"]
                )
                log.info("%s convertito: %d caratteri", descrizione, len(markdown))
            except ConversioneNonRiuscita as e:
                errore = str(e)
                log.warning("%s non convertito: %s", descrizione, errore)
            risposta = {**lavoro, "markdown": markdown, "errore": errore}
            await canale.default_exchange.publish(
                aio_pika.Message(
                    json.dumps(risposta).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=nomi[CONVERTITI],
            )

    await coda.consume(ricevi)
    log.info("In attesa di file da convertire su %s", nomi[CONVERSIONE])
    fine = asyncio.Event()
    loop = asyncio.get_running_loop()
    for segnale in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(segnale, fine.set)
    await fine.wait()
    await connessione.close()


if __name__ == "__main__":
    asyncio.run(main())
