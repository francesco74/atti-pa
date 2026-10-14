"""Configurazione dei log, uguale per tutti i componenti.

Il livello si sceglie con LOG_LEVEL:
- DEBUG: diagnostica dettagliata (richieste HTTP, chiamate a Normattiva e all'LLM, passi
  delle verifiche); con LOG_SQL=true anche le query SQL;
- INFO: funzionamento normale (avvio, verifiche completate, accessi, aggiornamenti);
- WARNING: solo anomalie ed errori.
"""

from __future__ import annotations

import logging

from common.config import get_settings

FORMATO = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Librerie esterne molto verbose: i loro dettagli servono solo in debug
_LIBRERIE = ("httpx", "aiomysql", "ldap3", "asyncio", "werkzeug", "aio_pika", "aiormq")


def configura_logging(livello: str = "INFO", sql: bool = False) -> None:
    livello = livello.upper()
    debug = livello == "DEBUG"
    logging.basicConfig(level=livello, format=FORMATO, force=True)
    for nome in _LIBRERIE:
        logging.getLogger(nome).setLevel(logging.INFO if debug else logging.WARNING)
    # httpcore in DEBUG registra ogni singolo byte scambiato: inutile anche in diagnostica
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if debug and sql else logging.WARNING
    )
    # gunicorn usa i propri handler: si allineano formato e livello a quelli dell'applicazione
    for nome in ("gunicorn.error", "gunicorn.access"):
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.propagate = True
        # il DEBUG di gunicorn (connessioni aperte e chiuse) duplica il log delle richieste
        logger.setLevel(logging.INFO if debug else livello)


def configura_da_ambiente() -> None:
    """Applica LOG_LEVEL e LOG_SQL lette dall'ambiente (vedi Settings)."""
    settings = get_settings()
    configura_logging(settings.log_level, settings.log_sql)
