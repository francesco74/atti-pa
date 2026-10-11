"""Applicazione ordinata delle migrazioni SQL.

Ogni file `NNNN_descrizione.sql` nella cartella delle migrazioni viene eseguito una sola
volta, in ordine di nome. L'esecuzione è protetta da un lock di database (GET_LOCK), così
due Job avviati insieme non applicano la stessa migrazione due volte.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("db_migrate")

_NOME_FILE = re.compile(r"^(\d{4})_[\w-]+\.sql$")
_LOCK = "atti_pa_migrazioni"


@dataclass(frozen=True)
class Migrazione:
    versione: str
    nome: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def carica_migrazioni(cartella: Path) -> list[Migrazione]:
    migrazioni = []
    for f in sorted(cartella.glob("*.sql")):
        m = _NOME_FILE.match(f.name)
        if not m:
            raise ValueError(f"Nome di migrazione non valido: {f.name}")
        migrazioni.append(Migrazione(m.group(1), f.name, f.read_text(encoding="utf-8")))
    versioni = [m.versione for m in migrazioni]
    if len(versioni) != len(set(versioni)):
        raise ValueError("Numeri di migrazione duplicati")
    return migrazioni


def dividi_istruzioni(sql: str) -> list[str]:
    """Divide uno script in istruzioni, ignorando commenti e ';' dentro le stringhe."""
    istruzioni: list[str] = []
    corrente: list[str] = []
    in_stringa: str | None = None
    i = 0
    while i < len(sql):
        c = sql[i]
        if in_stringa:
            corrente.append(c)
            if c == "\\" and i + 1 < len(sql):
                corrente.append(sql[i + 1])
                i += 1
            elif c == in_stringa:
                in_stringa = None
        elif c in ("'", '"', "`"):
            in_stringa = c
            corrente.append(c)
        elif sql.startswith("--", i):
            fine = sql.find("\n", i)
            i = len(sql) if fine == -1 else fine
            continue
        elif sql.startswith("/*", i):
            fine = sql.find("*/", i + 2)
            i = len(sql) if fine == -1 else fine + 2
            continue
        elif c == ";":
            istruzione = "".join(corrente).strip()
            if istruzione:
                istruzioni.append(istruzione)
            corrente = []
        else:
            corrente.append(c)
        i += 1
    resto = "".join(corrente).strip()
    if resto:
        istruzioni.append(resto)
    return istruzioni


async def applica(engine: AsyncEngine, migrazioni: list[Migrazione]) -> list[str]:
    """Applica le migrazioni mancanti. Restituisce i nomi di quelle applicate."""
    applicate: list[str] = []
    async with engine.connect() as conn:
        ottenuto = (await conn.execute(text("SELECT GET_LOCK(:n, 300)"), {"n": _LOCK})).scalar()
        if ottenuto != 1:
            raise RuntimeError("Impossibile ottenere il lock delle migrazioni")
        try:
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrazioni ("
                    " versione VARCHAR(10) PRIMARY KEY,"
                    " nome VARCHAR(255) NOT NULL,"
                    " checksum CHAR(64) NOT NULL,"
                    " applicata_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ") ENGINE=InnoDB"
                )
            )
            await conn.commit()
            righe = await conn.execute(text("SELECT versione, checksum FROM schema_migrazioni"))
            gia = dict(righe.all())

            for m in migrazioni:
                if m.versione in gia:
                    if gia[m.versione] != m.checksum:
                        raise RuntimeError(
                            f"La migrazione {m.nome} è stata modificata dopo l'applicazione"
                        )
                    continue
                log.info("Applico %s", m.nome)
                # Le istruzioni DDL in MySQL fanno commit implicito: una migrazione fallita
                # a metà va corretta con una nuova migrazione.
                for istruzione in dividi_istruzioni(m.sql):
                    await conn.exec_driver_sql(istruzione)
                await conn.execute(
                    text(
                        "INSERT INTO schema_migrazioni (versione, nome, checksum) "
                        "VALUES (:v, :n, :c)"
                    ),
                    {"v": m.versione, "n": m.nome, "c": m.checksum},
                )
                await conn.commit()
                applicate.append(m.nome)
        finally:
            await conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": _LOCK})
            await conn.commit()
    return applicate
