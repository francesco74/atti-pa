"""Avvio del worker di verifica: `python -m verifica_worker`.

Gestisce SIGTERM (arresto del pod): termina la verifica in corso e poi esce.
Il file di heartbeat è usato dalla liveness probe di Kubernetes.
"""

import asyncio
import logging
import signal
from pathlib import Path

from atti_common.config import get_settings
from atti_common.db import crea_engine, crea_sessionmaker
from atti_common.llm import LlmClient
from atti_common.normattiva import NormattivaClient
from verifica_worker.worker import Worker

HEARTBEAT = Path("/tmp/heartbeat")


async def main() -> None:
    settings = get_settings()
    engine = crea_engine(settings.database_url)
    normattiva = NormattivaClient(
        base_url=settings.normattiva_base_url, timeout=settings.normattiva_timeout
    )
    llm = LlmClient(
        settings.llm_base_url,
        settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        temperatura=settings.llm_temperatura,
    )
    worker = Worker(crea_sessionmaker(engine), normattiva, llm, settings, heartbeat=HEARTBEAT)

    loop = asyncio.get_running_loop()
    for segnale in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(segnale, worker.ferma)
    try:
        await worker.esegui()
    finally:
        await llm.close()
        await normattiva.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
