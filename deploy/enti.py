"""Enti dell'installazione e amministratori, da riga di comando.

Uso, dalla radice del repository (il database è quello di DATABASE_URL, anche dal .env):

    python deploy/enti.py installazione USERNAME           # amministratore dell'installazione
    python deploy/enti.py crea CODICE "Nome" DOMINIO...    # nuovo ente con i suoi domini
    python deploy/enti.py amministratore CODICE USERNAME   # primo amministratore locale dell'ente
    python deploy/enti.py elenco

La password si inserisce quando richiesta (o con la variabile PASSWORD, per gli script).
Il resto (Active Directory, utenti, moduli) si configura dall'app: l'amministratore
dell'installazione gestisce gli enti, quello dell'ente utenti e accessi.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy import select  # noqa: E402

from auth import password as pw  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db import crea_engine, crea_sessionmaker  # noqa: E402
from common.models import Ente, EnteDominio, Modulo, OrigineUtente, Ruolo, User  # noqa: E402


def _password() -> str:
    valore = os.environ.get("PASSWORD") or getpass.getpass("Password: ")
    if errore := pw.controlla_nuova(valore):
        raise ValueError(errore)
    if "PASSWORD" not in os.environ and getpass.getpass("Ripeti la password: ") != valore:
        raise ValueError("Le password non coincidono")
    return valore


async def _con_database(funzione):
    engine = crea_engine(get_settings().database_url)
    try:
        async with crea_sessionmaker(engine)() as db:
            risultato = await funzione(db)
            await db.commit()
            return risultato
    finally:
        await engine.dispose()


async def _ente(db, codice: str) -> Ente:
    ente = await db.scalar(select(Ente).where(Ente.codice == codice))
    if ente is None:
        raise LookupError(f"Ente inesistente: {codice}")
    return ente


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    comandi = parser.add_subparsers(dest="comando", required=True)
    c = comandi.add_parser("installazione", help="crea l'amministratore dell'installazione")
    c.add_argument("username")
    c = comandi.add_parser("crea", help="crea un ente")
    c.add_argument("codice", help="lettere minuscole e cifre, es. provincialucca")
    c.add_argument("nome")
    c.add_argument("domini", nargs="*", help="es. attipa.provincia.lucca.it")
    c.add_argument("--moduli", default=",".join(Modulo.TUTTI), help="moduli abilitati")
    c = comandi.add_parser("amministratore", help="crea un amministratore locale dell'ente")
    c.add_argument("codice")
    c.add_argument("username")
    comandi.add_parser("elenco")
    args = parser.parse_args()

    try:
        if args.comando == "installazione":
            password = _password()

            async def installazione(db):
                username = args.username.lower()
                user = await db.scalar(
                    select(User).where(User.ente_id.is_(None), User.username == username)
                )
                if user is None:
                    user = User(username=username, origine=OrigineUtente.LOCALE, ente_id=None)
                    db.add(user)
                user.ruoli = [Ruolo.INSTALLAZIONE]
                user.password_hash = pw.calcola(password)
                user.token_version = (user.token_version or 0) + 1
                user.attivo = True
                return f"Amministratore dell'installazione {username} pronto"

            print(asyncio.run(_con_database(installazione)))
        elif args.comando == "crea":
            if not re.fullmatch(r"[a-z][a-z0-9]{1,49}", args.codice):
                raise ValueError("Codice non valido: lettere minuscole e cifre, es. provincialucca")
            moduli = [m for m in args.moduli.split(",") if m]
            if set(moduli) - set(Modulo.TUTTI):
                raise ValueError(f"Moduli disponibili: {', '.join(Modulo.TUTTI)}")

            async def crea(db):
                if await db.scalar(select(Ente).where(Ente.codice == args.codice)):
                    raise ValueError(f"Codice già usato: {args.codice}")
                ente = Ente(codice=args.codice, nome=args.nome, moduli_json=moduli, dati_json={})
                db.add(ente)
                await db.flush()
                for d in args.domini:
                    d = d.strip().lower()
                    if await db.get(EnteDominio, d):
                        raise ValueError(f"Il dominio {d} è già di un altro ente")
                    db.add(EnteDominio(dominio=d, ente_id=ente.id))
                return f"Ente {args.codice} creato ({', '.join(args.domini) or 'senza domini'})"

            print(asyncio.run(_con_database(crea)))
        elif args.comando == "amministratore":
            password = _password()

            async def amministratore(db):
                ente = await _ente(db, args.codice)
                username = args.username.lower()
                user = await db.scalar(
                    select(User).where(User.ente_id == ente.id, User.username == username)
                )
                if user is not None and user.origine != OrigineUtente.LOCALE:
                    raise ValueError(f"{username} è un utente di Active Directory")
                if user is None:
                    user = User(ente_id=ente.id, username=username, origine=OrigineUtente.LOCALE)
                    db.add(user)
                user.ruoli = sorted({*(user.ruoli or []), Ruolo.ADMIN})
                user.password_hash = pw.calcola(password)
                user.token_version = (user.token_version or 0) + 1
                user.attivo = True
                ente.accesso_locale = True
                return f"Amministratore {username} dell'ente {ente.codice} pronto"

            print(asyncio.run(_con_database(amministratore)))
        else:

            async def elenco(db):
                righe = []
                for e in (await db.scalars(select(Ente).order_by(Ente.codice))).all():
                    domini = (
                        await db.scalars(select(EnteDominio.dominio).where(EnteDominio.ente_id == e.id))
                    ).all()
                    stato = "" if e.attivo else " (disattivato)"
                    righe.append(f"{e.codice:20} {e.nome}{stato}  domini: {', '.join(domini) or '-'}  moduli: {', '.join(e.moduli_json or [])}")
                return "\n".join(righe) or "Nessun ente"

            print(asyncio.run(_con_database(elenco)))
        return 0
    except (ValueError, LookupError) as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
