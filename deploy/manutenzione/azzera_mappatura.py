"""Svuota la mappatura anticorruzione di un ente, prima di importare un pacchetto nuovo.

Elimina aree di rischio, processi con attività, rischi e misure, voci del catalogo, proposte
dei referenti, dichiarazioni del monitoraggio e contatori dei codici della mappatura. Restano
la metodologia, le strutture e il catalogo dei procedimenti (condiviso con la trasparenza),
che il pacchetto nuovo completa senza duplicare. Gli obiettivi della performance tengono la
loro copia di azioni e misure, scollegata dalla mappatura.

Serve per passare dal pacchetto standard di prima (processi del Comune di Lucca) a quello
nuovo: importato sopra, i processi vecchi e nuovi si mescolerebbero. Fare prima il backup.

    python deploy/manutenzione/azzera_mappatura.py --ente CODICE --dry-run   # conta, senza modificare
    python deploy/manutenzione/azzera_mappatura.py --ente CODICE             # svuota
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RADICE))

from sqlalchemy import delete, func, select  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.db import crea_engine, crea_sessionmaker  # noqa: E402
from common.models import (  # noqa: E402
    AcArea, AcAttivita, AcContatore, AcMisura, AcMonitoraggio, AcProcesso, AcProposta, AcRischio, AcVoce, Ente,
)  # fmt: skip

# nell'ordine in cui si eliminano (prima chi rimanda agli altri)
TABELLE = [
    ("dichiarazioni del monitoraggio", AcMonitoraggio),
    ("proposte dei referenti", AcProposta),
    ("misure", AcMisura),
    ("rischi", AcRischio),
    ("attività", AcAttivita),
    ("processi", AcProcesso),
    ("aree di rischio", AcArea),
    ("voci del catalogo", AcVoce),
]


async def azzera(codice: str, prova: bool) -> int:
    engine = crea_engine(get_settings().database_url)
    try:
        async with crea_sessionmaker(engine)() as db:
            ente = await db.scalar(select(Ente).where(Ente.codice == codice))
            if ente is None:
                print(f"Ente {codice} non trovato", file=sys.stderr)
                return 1
            print(f"{ente.codice} - {ente.nome}")
            for nome, modello in TABELLE:
                n = await db.scalar(select(func.count()).select_from(modello).where(modello.ente_id == ente.id))
                print(f"  {nome}: {n}")
                if not prova:
                    await db.execute(delete(modello).where(modello.ente_id == ente.id))
            # contatori dei codici della mappatura: quello dei procedimenti (P.) resta
            contatori = AcContatore.ente_id == ente.id, AcContatore.prefisso != "P."
            print(f"  contatori dei codici: {await db.scalar(select(func.count()).select_from(AcContatore).where(*contatori))}")
            if prova:
                print("Prova: nessuna modifica salvata.")
                await db.rollback()
            else:
                await db.execute(delete(AcContatore).where(*contatori))
                await db.commit()
                print("Mappatura svuotata: ora si importa il pacchetto nuovo (Amministrazione → Pacchetti).")
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ente", required=True, help="codice dell'ente")
    parser.add_argument("--dry-run", action="store_true", help="conta cosa eliminerebbe, senza modificare")
    a = parser.parse_args()
    return asyncio.run(azzera(a.ente, a.dry_run))


if __name__ == "__main__":
    sys.exit(main())
