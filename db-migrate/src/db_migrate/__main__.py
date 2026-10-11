"""Job Kubernetes di migrazione: `python -m db_migrate`."""

import asyncio
import logging
import sys
from pathlib import Path

from atti_common.db import crea_engine
from db_migrate.runner import applica, carica_migrazioni

log = logging.getLogger("db_migrate")

CARTELLA = Path(__file__).resolve().parent.parent / "migrations"


async def main() -> int:
    migrazioni = carica_migrazioni(CARTELLA)
    engine = crea_engine()
    try:
        applicate = await applica(engine, migrazioni)
    except Exception:
        log.exception("Migrazione fallita")
        return 1
    finally:
        await engine.dispose()
    if applicate:
        log.info("Migrazioni applicate: %s", ", ".join(applicate))
    else:
        log.info("Database già aggiornato (%d migrazioni)", len(migrazioni))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(asyncio.run(main()))
