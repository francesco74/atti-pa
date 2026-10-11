"""Punto di avvio del CronJob: `python -m normattiva_sync`.

Codici di uscita: 0 = OK, 1 = completato con errori su singoli articoli, 2 = errore bloccante.
Un codice diverso da 0 fa risultare il Job fallito in Kubernetes.
"""

import asyncio
import logging
import sys
from datetime import datetime

from atti_common.config import get_settings
from atti_common.db import crea_engine
from atti_common.normattiva import NormattivaClient, NormattivaError
from normattiva_sync.job import SyncJob
from normattiva_sync.repository import MySqlRepository

log = logging.getLogger("normattiva_sync")


async def main() -> int:
    settings = get_settings()
    engine = crea_engine()
    try:
        async with NormattivaClient() as client:
            job = SyncJob(
                repo=MySqlRepository(engine),
                client=client,
                oggi=datetime.now(settings.tz).date(),
                giorni_iniziali=settings.sync_giorni_iniziali,
                finestra_giorni=settings.sync_finestra_giorni,
                pausa_secondi=settings.sync_pausa_secondi,
            )
            esito = await job.esegui()
    except NormattivaError:
        log.exception("Aggiornamento interrotto")
        return 2
    finally:
        await engine.dispose()

    log.info(
        "Esito %s: %d atti modificati, %d articoli controllati, %d aggiornati, %d errori",
        esito.stato,
        esito.atti_modificati,
        esito.articoli_controllati,
        esito.articoli_aggiornati,
        len(esito.errori),
    )
    for errore in esito.errori:
        log.warning(errore)
    return 0 if esito.stato == "OK" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(asyncio.run(main()))
