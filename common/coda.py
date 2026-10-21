"""Code RabbitMQ tra i componenti.

Flusso di un controllo:

    API --conversione--> converter --convertiti--> verifica-worker
    API --verifica-----------------------------> verifica-worker   (rianalisi, bozze)

Messaggi (JSON, persistenti, code durevoli `<RABBITMQ_PREFISSO>.<coda>`):
- conversione: {"atto_id", "verifica_id", "percorso", "nome_file"}  (percorso relativo
  ad ARCHIVIO_DIR, cartella condivisa tra API e converter); per il testo di una norma
  inserita manualmente {"testo_norma_id", "percorso", "nome_file"}
- convertiti:  {"atto_id", "verifica_id", "markdown", "errore"}      (uno dei due è null),
  oppure {"testo_norma_id", "markdown", "errore"}
- verifica:    {"verifica_id"}

Lo stato resta nel database (tabella verifiche, stato dell'atto): un messaggio è solo un
avviso che c'è lavoro. Se l'invio fallisce, o un messaggio si perde, il worker lo reinvia
partendo dallo stato nel database (vedi WORKER_REINVIO_MINUTI). I consumatori devono
quindi tollerare messaggi duplicati.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

log = logging.getLogger("common.coda")

CONVERSIONE = "conversione"
CONVERTITI = "convertiti"
VERIFICA = "verifica"
CODE = (CONVERSIONE, CONVERTITI, VERIFICA)

Gestore = Callable[[dict[str, Any]], Awaitable[None]]

ATTESA_MASSIMA = 30  # secondi tra due tentativi di connessione all'avvio


async def connetti_in_attesa(url: str) -> aio_pika.abc.AbstractRobustConnection:
    """Connessione a RabbitMQ che aspetta il broker: tentativi a intervalli crescenti
    (1, 2, 4... fino a 30 secondi). Si interrompe solo con l'arresto del processo."""
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
        attesa, tentativo = min(attesa * 2, ATTESA_MASSIMA), tentativo + 1


class Coda:
    def __init__(self, url: str, prefisso: str = "atti-pa"):
        self.url = url
        self.prefisso = prefisso
        self._connessione: aio_pika.abc.AbstractRobustConnection | None = None
        self._canale: aio_pika.abc.AbstractChannel | None = None
        self._consumi: list[tuple[aio_pika.abc.AbstractQueue, str]] = []

    def nome(self, coda: str) -> str:
        return f"{self.prefisso}.{coda}"

    async def connetti(self, attendi: bool = False) -> None:
        """Connessione con riconnessione automatica; dichiara le code (idempotente).

        `attendi`: all'avvio di un consumatore, se RabbitMQ non risponde riprova finché non
        è disponibile invece di fallire. La riconnessione dopo una caduta è automatica.
        """
        if self._canale is not None and not self._canale.is_closed:
            return
        if attendi:
            self._connessione = await connetti_in_attesa(self.url)
        else:
            self._connessione = await aio_pika.connect_robust(self.url)
        self._canale = await self._connessione.channel(publisher_confirms=True)
        # un messaggio alla volta per consumatore: una verifica può durare minuti
        await self._canale.set_qos(prefetch_count=1)
        for coda in CODE:
            await self._canale.declare_queue(self.nome(coda), durable=True)
        log.info("Connesso a RabbitMQ (%s.*)", self.prefisso)

    async def pubblica(self, coda: str, dati: dict[str, Any]) -> None:
        await self.connetti()
        messaggio = aio_pika.Message(
            json.dumps(dati).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._canale.default_exchange.publish(messaggio, routing_key=self.nome(coda))
        log.debug("Pubblicato su %s: %s", self.nome(coda), _riassunto(dati))

    async def consuma(self, coda: str, gestore: Gestore) -> None:
        """Consegna i messaggi a `gestore`; conferma dopo l'elaborazione.

        Un errore imprevisto non rimette il messaggio in coda (eviterebbe un ciclo infinito
        su un messaggio difettoso): lo stato nel database permette il reinvio.
        """
        await self.connetti()
        queue = await self._canale.get_queue(self.nome(coda))

        async def ricevi(messaggio: AbstractIncomingMessage) -> None:
            try:
                dati = json.loads(messaggio.body)
                log.debug("Ricevuto da %s: %s", self.nome(coda), _riassunto(dati))
                await gestore(dati)
            except Exception:
                log.exception("Errore nell'elaborazione di un messaggio di %s", self.nome(coda))
                await messaggio.reject(requeue=False)
            else:
                await messaggio.ack()

        self._consumi.append((queue, await queue.consume(ricevi)))

    async def smetti_di_consumare(self) -> None:
        """Non riceve altri messaggi (arresto): quelli in elaborazione proseguono."""
        for queue, tag in self._consumi:
            await queue.cancel(tag)
        self._consumi.clear()

    async def chiudi(self) -> None:
        if self._connessione is not None:
            await self._connessione.close()
            self._connessione = self._canale = None

    close = chiudi  # stessa interfaccia degli altri client chiusi alla fine dell'API


def _riassunto(dati: dict[str, Any]) -> dict[str, Any]:
    """Il contenuto del messaggio per i log, senza i testi lunghi."""
    return {
        k: (f"<{len(v)} caratteri>" if isinstance(v, str) and len(v) > 200 else v)
        for k, v in dati.items()
    }
