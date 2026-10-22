"""Pacchetti di modelli di atto, specificità e checklist (common/pacchetti.py).

Uso, dalla radice del repository (il database è quello di DATABASE_URL, anche dal .env):

    python deploy/pacchetto.py prova                    # controlla il pacchetto in pacchetto/
    python deploy/pacchetto.py crea                     # crea lo zip standard da distribuire
    python deploy/pacchetto.py analizza FILE.zip        # cosa cambierebbe nel database
    python deploy/pacchetto.py importa FILE.zip         # importa con le azioni proposte
    python deploy/pacchetto.py esporta FILE.zip         # esporta la configurazione dell'ente

Il sistema parte vuoto: il primo pacchetto (lo zip standard creato con "crea") si importa
come i successivi. Al posto di FILE.zip si può indicare una cartella con la struttura del
pacchetto (es. pacchetto/). Di norma i pacchetti si importano da Amministrazione, dove si
sceglie oggetto per oggetto; da qui si applicano le azioni proposte dall'analisi (nei
conflitti si mantiene la versione dell'ente).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from common.config import get_settings  # noqa: E402
from common.db import crea_engine, crea_sessionmaker  # noqa: E402
from common.pacchetti import (  # noqa: E402
    PacchettoNonValido,
    analizza,
    da_cartella,
    da_zip,
    esporta,
    importa,
    in_zip,
    leggi_pacchetto,
)

CARTELLA = RADICE / "pacchetto"  # sorgenti del pacchetto standard


def _file(origine: Path) -> dict[str, str]:
    return da_cartella(origine) if origine.is_dir() else da_zip(origine.read_bytes())


async def _con_database(funzione):
    engine = crea_engine(get_settings().database_url)
    try:
        async with crea_sessionmaker(engine)() as db:
            return await funzione(db)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    comandi = parser.add_subparsers(dest="comando", required=True)
    comandi.add_parser("prova", help="controlla il pacchetto in pacchetto/")
    crea = comandi.add_parser("crea", help="crea lo zip del pacchetto in pacchetto/")
    crea.add_argument("file", nargs="?", type=Path, help="zip da creare (predefinito: nel cwd)")
    for nome in ("analizza", "importa"):
        c = comandi.add_parser(nome)
        c.add_argument("origine", type=Path, help="zip o cartella del pacchetto")
    esp = comandi.add_parser("esporta", help="esporta la configurazione dell'ente")
    esp.add_argument("file", type=Path)
    args = parser.parse_args()

    try:
        if args.comando in ("prova", "crea"):
            file = da_cartella(CARTELLA)
            p = leggi_pacchetto(file)
            conteggi = {t: len(p.di_tipo(t)) for t in ("modello", "modulo", "checklist")}
            print(
                f"{p.manifesto.etichetta}: {conteggi['modello']} modelli, "
                f"{conteggi['modulo']} specificità, {conteggi['checklist']} checklist"
            )
            if args.comando == "crea":
                nome = f"atti-pa-modelli-{p.manifesto.versione}.zip"
                destinazione = args.file or Path(nome)
                destinazione.write_bytes(in_zip(file))
                print(f"Creato {destinazione}")
            return 0

        if args.comando == "esporta":

            async def esp_(db):
                return await esporta(db, "Configurazione dell'ente", "esportazione")

            args.file.write_bytes(in_zip(asyncio.run(_con_database(esp_))))
            print(f"Esportato in {args.file}")
            return 0

        p = leggi_pacchetto(_file(args.origine))

        async def esegui(db):
            for v in await analizza(db, p):
                print(f"{v.stato:13} {v.chiave:45} -> {v.azione}")
            if args.comando == "importa":
                r = await importa(db, p)
                await db.commit()
                print(r)
                for riga in r.errori + r.avvisi:
                    print(f"  {riga}")

        asyncio.run(_con_database(esegui))
        return 0
    except PacchettoNonValido as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
