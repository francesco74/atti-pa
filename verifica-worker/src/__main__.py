"""Avvio del worker di verifica: `python /app` (esegue questo file; `src` è piatto).

Gestisce SIGTERM (arresto del pod): termina la verifica in corso e poi esce.
Il file di heartbeat è usato dalla liveness probe di Kubernetes.
"""

import asyncio
import signal
from pathlib import Path

from common.coda import Coda
from common.config import get_settings
from common.db import crea_engine, crea_sessionmaker
from common.llm import crea_llm
from common.log import configura_da_ambiente
from common.normattiva import NormattivaClient
from worker import Worker


async def main() -> None:
    settings = get_settings()
    engine = crea_engine(settings.database_url)
    normattiva = NormattivaClient(
        base_url=settings.normattiva_base_url,
        timeout=settings.normattiva_timeout,
        tentativi=settings.normattiva_tentativi,
    )
    llm = crea_llm(settings)
    coda = Coda(settings.rabbitmq_url, settings.rabbitmq_prefisso)
    worker = Worker(
        crea_sessionmaker(engine),
        normattiva,
        llm,
        settings,
        coda,
        heartbeat=Path(settings.worker_heartbeat),
    )

    loop = asyncio.get_running_loop()
    for segnale in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(segnale, worker.ferma)
    try:
        await worker.esegui()
    finally:
        await coda.chiudi()
        await llm.close()
        await normattiva.close()
        await engine.dispose()


if __name__ == "__main__":
    configura_da_ambiente()
    asyncio.run(main())
