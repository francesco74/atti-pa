"""Collega al catalogo la mappatura già presente negli enti.

Dopo la migrazione 0008_catalogo_mappatura.sql, per ogni ente con il modulo anticorruzione:
crea le voci standard del pacchetto che mancano (pacchetto/anticorruzione/catalogo.yaml) e
collega ogni attività, rischio e misura senza voce a quella con lo stesso testo (maiuscole,
spazi e punteggiatura finale non contano), creando una voce dell'ente se non c'è. Elenca
infine le voci molto somiglianti, da valutare se unire dalla scheda Catalogo.

    python deploy/manutenzione/catalogo_mappatura.py --dry-run   # cosa farebbe, senza modificare
    python deploy/manutenzione/catalogo_mappatura.py           # aggiorna il database
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RADICE))

from sqlalchemy import select  # noqa: E402

from common.anticorruzione.catalogo import FILE_CATALOGO, collega_mappatura, crea_voci, leggi_catalogo, simili  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db import crea_engine, crea_sessionmaker  # noqa: E402
from common.models import AcVoce, Ente, Modulo  # noqa: E402

NOMI = {"ATTIVITA": "attività", "RISCHIO": "rischi", "MISURA": "misure"}


async def collega(prova: bool) -> int:
    standard = leggi_catalogo((RADICE / "pacchetto" / FILE_CATALOGO).read_text(encoding="utf-8"))
    engine = crea_engine(get_settings().database_url)
    try:
        async with crea_sessionmaker(engine)() as db:
            for ente in await db.scalars(select(Ente).order_by(Ente.codice)):
                if not ente.modulo_attivo(Modulo.ANTICORRUZIONE):
                    continue
                nuove_std = await crea_voci(db, ente.id, standard)
                esito = await collega_mappatura(db, ente.id)
                print(f"{ente.codice}: voci standard aggiunte {len(nuove_std)}")
                for tipo, c in esito.items():
                    print(f"  {NOMI[tipo]}: collegati {c['collegati']}, voci nuove dell'ente {c['voci_nuove']}")
                coppie = simili(list(await db.scalars(select(AcVoce).where(AcVoce.ente_id == ente.id))))
                if coppie:
                    print("  voci molto somiglianti (da valutare se unire):")
                    for a, b, r in coppie:
                        print(f"    {a.codice} ~ {b.codice} ({r:.0%}): «{a.descrizione[:60]}» / «{b.descrizione[:60]}»")
            if prova:
                await db.rollback()
                print("Prova: nessuna modifica salvata.")
            else:
                await db.commit()
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="mostra cosa farebbe, senza modificare")
    return asyncio.run(collega(parser.parse_args().dry_run))


if __name__ == "__main__":
    sys.exit(main())
