"""Ricava le strutture coinvolte delle attività dalle note scritte a mano.

Le attività della mappatura avevano le strutture coinvolte solo come testo libero; ora si
scelgono dall'anagrafica (colonna ac_attivita.coinvolte, migrazione 0007). Lo script cerca nel
testo i codici delle strutture dell'ente (es. "U.O. 2.1", "SETTORE 3") e le descrizioni intere
abbastanza lunghe (common/anticorruzione/strutture.py) e le aggiunge alle coinvolte
dell'attività, senza togliere quelle già scelte. Il testo resta com'è, come nota: si toglie a
mano quando non serve più.

    python deploy/manutenzione/strutture_coinvolte.py --dry-run   # elenca cosa aggiungerebbe
    python deploy/manutenzione/strutture_coinvolte.py           # aggiorna il database
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select  # noqa: E402

from common.anticorruzione.strutture import riconosci_strutture  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db import crea_engine, crea_sessionmaker  # noqa: E402
from common.models import AcAttivita, Ente, Struttura  # noqa: E402


async def ricava(prova: bool) -> int:
    engine = crea_engine(get_settings().database_url)
    esaminate = aggiornate = senza_esito = 0
    try:
        async with crea_sessionmaker(engine)() as db:
            for ente in await db.scalars(select(Ente).order_by(Ente.codice)):
                strutture = [(s.id, s.codice, s.descrizione)
                             for s in await db.scalars(select(Struttura).where(Struttura.ente_id == ente.id))]  # fmt: skip
                codici = {sid: codice for sid, codice, _ in strutture}
                attivita = await db.scalars(select(AcAttivita).where(
                    AcAttivita.ente_id == ente.id, AcAttivita.strutture_coinvolte.is_not(None)).order_by(AcAttivita.codice))  # fmt: skip
                for a in attivita:
                    if not (a.strutture_coinvolte or "").strip():
                        continue
                    esaminate += 1
                    trovate = riconosci_strutture(a.strutture_coinvolte, strutture)
                    nuove = [s for s in trovate if s not in (a.coinvolte or [])]
                    if not trovate:
                        senza_esito += 1
                        print(f"  {ente.codice} {a.codice}: nessuna struttura riconosciuta in «{a.strutture_coinvolte[:80]}»")
                        continue
                    if not nuove:
                        continue
                    aggiornate += 1
                    print(f"  {ente.codice} {a.codice}: + {', '.join(codici[s] for s in nuove)}")
                    if not prova:
                        a.coinvolte = sorted({*(a.coinvolte or []), *nuove})
            if not prova:
                await db.commit()
        azione = "da aggiornare" if prova else "aggiornate"
        print(f"Attività con note esaminate: {esaminate}, {azione}: {aggiornate}, senza strutture riconosciute: {senza_esito}")
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="elenca senza modificare")
    return asyncio.run(ricava(parser.parse_args().dry_run))


if __name__ == "__main__":
    sys.exit(main())
