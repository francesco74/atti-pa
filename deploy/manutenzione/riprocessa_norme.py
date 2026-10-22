"""Rielabora i testi delle norme già salvati con la versione attuale del parser.

Serve dopo una correzione di common/normattiva/parser.py: le versioni degli articoli
nella libreria conservano l'HTML originale di Normattiva, da cui si ricalcolano struttura
(commi e lettere), impronta del testo e rinvii, senza riscaricare nulla.

    python deploy/manutenzione/riprocessa_norme.py --prova   # elenca le differenze
    python deploy/manutenzione/riprocessa_norme.py           # aggiorna il database
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import undefer  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.db import crea_engine, crea_sessionmaker  # noqa: E402
from common.models import NormaArticoloVersione  # noqa: E402
from common.normattiva.parser import parse_articolo  # noqa: E402


async def riprocessa(prova: bool) -> int:
    engine = crea_engine(get_settings().database_url)
    cambiate = 0
    try:
        async with crea_sessionmaker(engine)() as db:
            versioni = (
                await db.scalars(
                    select(NormaArticoloVersione).options(undefer("*"))
                )
            ).all()
            for v in versioni:
                articolo = parse_articolo(v.testo_html)
                if articolo.hash() == v.hash_testo:
                    continue
                cambiate += 1
                prima = len((v.struttura_json or {}).get("commi") or [])
                print(
                    f"  {v.urn_atto}~art{v.articolo} (vigente dal {v.vigenza_inizio}): "
                    f"commi {prima} -> {len(articolo.commi)}"
                )
                if not prova:
                    v.rubrica = articolo.rubrica
                    v.struttura_json = articolo.to_dict()
                    v.hash_testo = articolo.hash()
                    v.rinvii_json = articolo.rinvii
            if not prova:
                await db.commit()
        azione = "da aggiornare" if prova else "aggiornate"
        print(f"Versioni esaminate: {len(versioni)}, {azione}: {cambiate}")
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prova", action="store_true", help="elenca senza modificare")
    return asyncio.run(riprocessa(parser.parse_args().prova))


if __name__ == "__main__":
    sys.exit(main())
