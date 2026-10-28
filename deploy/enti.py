"""Enti dell'installazione, da riga di comando (non c'è un'interfaccia web per gestirli).

Uso, dalla radice del repository o nel container dell'API (python enti.py ...); il database
è quello di DATABASE_URL, anche dal .env:

    python deploy/enti.py elenco
    python deploy/enti.py mostra CODICE
    python deploy/enti.py crea CODICE "Nome" DOMINIO... [--moduli redazione,...]
    python deploy/enti.py rinomina CODICE "Nome"
    python deploy/enti.py domini CODICE DOMINIO...      # sostituisce i domini dell'ente
    python deploy/enti.py moduli CODICE redazione,...   # sostituisce i moduli attivi ("" nessuno)
    python deploy/enti.py disattiva CODICE              # non si raggiunge più, i dati restano
    python deploy/enti.py attiva CODICE
    python deploy/enti.py reimposta CODICE              # admin con la password iniziale

Ogni ente nasce con l'utente locale admin, con la password iniziale (PASSWORD_INIZIALE) da
cambiare al primo accesso; poi l'admin configura l'ente dall'app (Active Directory, utenti,
dati dell'ente, modelli). "reimposta" serve se la password dell'admin è dimenticata: lo
riporta alla password iniziale, lo riattiva e riabilita l'accesso con utenti locali.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy import func, select  # noqa: E402

from auth import password as pw  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db import crea_engine, crea_sessionmaker  # noqa: E402
from common.models import (  # noqa: E402
    UTENTE_ADMIN,
    Ente,
    EnteDominio,
    Modulo,
    OrigineUtente,
    Ruolo,
    User,
)

_CODICE = re.compile(r"[a-z][a-z0-9]{1,49}")
_DOMINIO = re.compile(r"(?=.{3,255}$)[a-z0-9-]+(\.[a-z0-9-]+)+")


def _password_iniziale() -> str:
    valore = get_settings().password_iniziale
    if not valore:
        raise ValueError("Manca PASSWORD_INIZIALE nella configurazione")
    if errore := pw.controlla_nuova(valore):
        raise ValueError(f"PASSWORD_INIZIALE non valida: {errore}")
    return valore


def _moduli(testo: str) -> list[str]:
    moduli = [m.strip() for m in testo.split(",") if m.strip()]
    if set(moduli) - set(Modulo.TUTTI):
        raise ValueError(f"Moduli disponibili: {', '.join(Modulo.TUTTI)}")
    return [m for m in Modulo.TUTTI if m in moduli]


def _domini_validi(domini: list[str]) -> list[str]:
    puliti = list(dict.fromkeys(d.strip().lower() for d in domini if d.strip()))
    errati = [d for d in puliti if not _DOMINIO.fullmatch(d)]
    if errati:
        raise ValueError(f"Domini non validi: {', '.join(errati)}")
    return puliti


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


async def _domini(db, ente: Ente) -> list[str]:
    return list(
        (await db.scalars(select(EnteDominio.dominio).where(EnteDominio.ente_id == ente.id))).all()
    )


async def _assegna_domini(db, ente: Ente, domini: list[str]) -> None:
    for d in domini:
        esistente = await db.get(EnteDominio, d)
        if esistente is not None and esistente.ente_id != ente.id:
            raise ValueError(f"Il dominio {d} è già di un altro ente")
    for vecchio in (await db.scalars(select(EnteDominio).where(EnteDominio.ente_id == ente.id))).all():
        if vecchio.dominio not in domini:
            await db.delete(vecchio)
    attuali = await _domini(db, ente)
    for d in domini:
        if d not in attuali:
            db.add(EnteDominio(dominio=d, ente_id=ente.id))


async def _reimposta_admin(db, ente: Ente, password: str) -> None:
    admin = await db.scalar(
        select(User).where(User.ente_id == ente.id, User.username == UTENTE_ADMIN)
    )
    if admin is None:
        admin = User(
            ente_id=ente.id, username=UTENTE_ADMIN, origine=OrigineUtente.LOCALE,
            nome_completo=f"Amministratore {ente.nome}",
        )  # fmt: skip
        db.add(admin)
    elif admin.origine != OrigineUtente.LOCALE:
        raise ValueError(f"{UTENTE_ADMIN} dell'ente {ente.codice} è un utente di Active Directory")
    admin.ruoli = sorted({*(admin.ruoli or []), Ruolo.ADMIN})
    admin.password_hash = pw.calcola(password)
    admin.cambio_password = True
    admin.token_version = (admin.token_version or 0) + 1  # chiude le sessioni aperte
    admin.attivo = True
    ente.accesso_locale = True


async def _descrizione(db, e: Ente) -> dict:
    utenti = await db.scalar(select(func.count(User.id)).where(User.ente_id == e.id))
    admin = await db.scalar(select(User).where(User.ente_id == e.id, User.username == UTENTE_ADMIN))
    accesso = [n for n, si in (("locali", e.accesso_locale), ("AD", bool(e.ldap_json))) if si]
    return {
        "codice": e.codice,
        "nome": e.nome + ("" if e.attivo else " (disattivato)"),
        "domini": ", ".join(await _domini(db, e)) or "-",
        "moduli": ", ".join(e.moduli_json or []) or "-",
        "accesso": " + ".join(accesso) or "-",
        "utenti": str(utenti or 0),
        "admin": "assente" if admin is None
        else "password da cambiare" if admin.cambio_password
        else "attivo" if admin.attivo else "disattivato",
    }


async def elenco(db, _args) -> str:
    righe = [await _descrizione(db, e) for e in (await db.scalars(select(Ente).order_by(Ente.codice))).all()]
    if not righe:
        return "Nessun ente"
    colonne = ["codice", "nome", "domini", "moduli", "accesso", "utenti"]
    larghezze = {c: max(len(c), *(len(r[c]) for r in righe)) for c in colonne}
    return "\n".join(
        "  ".join(r[c].ljust(larghezze[c]) for c in colonne).rstrip()
        for r in [{c: c.upper() for c in colonne}, *righe]
    )


async def mostra(db, args) -> str:
    d = await _descrizione(db, await _ente(db, args.codice))
    return "\n".join(f"{k:8} {v}" for k, v in d.items())


async def crea(db, args) -> str:
    if not _CODICE.fullmatch(args.codice):
        raise ValueError("Codice non valido: lettere minuscole e cifre, es. comunelucca")
    password = _password_iniziale()
    domini = _domini_validi(args.domini)
    if await db.scalar(select(Ente).where(Ente.codice == args.codice)):
        raise ValueError(f"Codice già usato: {args.codice}")
    ente = Ente(codice=args.codice, nome=args.nome, moduli_json=_moduli(args.moduli), dati_json={})
    db.add(ente)
    await db.flush()
    await _assegna_domini(db, ente, domini)
    await _reimposta_admin(db, ente, password)
    return (
        f"Ente {args.codice} creato ({', '.join(domini) or 'senza domini'}). Accedere come "
        f"{UTENTE_ADMIN} con la password iniziale: andrà cambiata subito."
    )


async def rinomina(db, args) -> str:
    ente = await _ente(db, args.codice)
    ente.nome = args.nome
    return f"Ente {ente.codice}: {ente.nome}"


async def domini(db, args) -> str:
    ente = await _ente(db, args.codice)
    nuovi = _domini_validi(args.domini)
    await _assegna_domini(db, ente, nuovi)
    return f"Domini dell'ente {ente.codice}: {', '.join(nuovi) or 'nessuno'}"


async def moduli(db, args) -> str:
    ente = await _ente(db, args.codice)
    ente.moduli_json = _moduli(args.moduli)
    return f"Moduli dell'ente {ente.codice}: {', '.join(ente.moduli_json) or 'nessuno'}"


async def disattiva(db, args) -> str:
    ente = await _ente(db, args.codice)
    ente.attivo = False
    return f"Ente {ente.codice} disattivato: i suoi domini non danno più accesso, i dati restano"


async def attiva(db, args) -> str:
    ente = await _ente(db, args.codice)
    ente.attivo = True
    return f"Ente {ente.codice} attivo"


async def reimposta(db, args) -> str:
    password = _password_iniziale()
    ente = await _ente(db, args.codice)
    await _reimposta_admin(db, ente, password)
    return (
        f"{UTENTE_ADMIN} dell'ente {ente.codice} riportato alla password iniziale, da cambiare "
        "al primo accesso"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[1:]),
    )  # fmt: skip
    comandi = parser.add_subparsers(dest="comando", required=True)
    comandi.add_parser("elenco", help="tutti gli enti")
    c = comandi.add_parser("mostra", help="dettaglio di un ente")
    c.add_argument("codice")
    c = comandi.add_parser("crea", help="nuovo ente con il suo admin")
    c.add_argument("codice", help="lettere minuscole e cifre, es. comunelucca")
    c.add_argument("nome")
    c.add_argument("domini", nargs="*", help="es. comunelucca.provincia.lucca.it")
    c.add_argument("--moduli", default=",".join(Modulo.TUTTI), help="moduli attivi")
    c = comandi.add_parser("rinomina", help="cambia il nome dell'ente")
    c.add_argument("codice")
    c.add_argument("nome")
    c = comandi.add_parser("domini", help="sostituisce i domini dell'ente")
    c.add_argument("codice")
    c.add_argument("domini", nargs="*")
    c = comandi.add_parser("moduli", help="sostituisce i moduli attivi dell'ente")
    c.add_argument("codice")
    c.add_argument("moduli", help=f"separati da virgole: {', '.join(Modulo.TUTTI)}")
    for nome, aiuto in (
        ("disattiva", "l'ente non si raggiunge più"),
        ("attiva", "riattiva l'ente"),
        ("reimposta", "riporta admin alla password iniziale"),
    ):
        comandi.add_parser(nome, help=aiuto).add_argument("codice")
    args = parser.parse_args()
    funzione = globals()[args.comando]
    try:
        print(asyncio.run(_con_database(lambda db: funzione(db, args))))
        return 0
    except (ValueError, LookupError) as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
