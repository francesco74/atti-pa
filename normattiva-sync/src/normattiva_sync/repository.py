"""Accesso al database per il job di aggiornamento normative."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from atti_common.normattiva import TestoArticolo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class ArticoloMonitorato:
    urn_atto: str
    articolo: str


@dataclass(frozen=True)
class VersioneSalvata:
    vigenza_inizio: date | None
    hash_testo: str


class Repository(Protocol):
    async def ultima_sincronizzazione_ok(self) -> datetime | None: ...

    async def articoli_monitorati(self) -> list[ArticoloMonitorato]: ...

    async def articoli_senza_versione(self) -> list[ArticoloMonitorato]: ...

    async def versione_corrente(self, art: ArticoloMonitorato) -> VersioneSalvata | None: ...

    async def salva_versione(self, art: ArticoloMonitorato, testo: TestoArticolo) -> None: ...

    async def registra_esecuzione(
        self,
        da: datetime,
        a: datetime,
        atti_modificati: int,
        articoli_aggiornati: int,
        esito: str,
        dettaglio: str | None,
    ) -> None: ...


# Articoli da tenere aggiornati: quelli già scaricati e quelli citati nella libreria riferimenti
_SQL_MONITORATI = """
SELECT DISTINCT urn_atto, articolo FROM norme_articoli_versioni
UNION
SELECT DISTINCT urn_atto, articolo FROM riferimenti
"""

_SQL_SENZA_VERSIONE = """
SELECT DISTINCT r.urn_atto, r.articolo
FROM riferimenti r
LEFT JOIN norme_articoli_versioni v ON v.urn_atto = r.urn_atto AND v.articolo = r.articolo
WHERE v.id IS NULL
"""


class MySqlRepository:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def ultima_sincronizzazione_ok(self) -> datetime | None:
        async with self._engine.connect() as conn:
            r = await conn.execute(
                text("SELECT MAX(intervallo_a) FROM normattiva_sync WHERE esito = 'OK'")
            )
            return r.scalar()

    async def articoli_monitorati(self) -> list[ArticoloMonitorato]:
        async with self._engine.connect() as conn:
            r = await conn.execute(text(_SQL_MONITORATI))
            return [ArticoloMonitorato(u, a) for u, a in r.all()]

    async def articoli_senza_versione(self) -> list[ArticoloMonitorato]:
        async with self._engine.connect() as conn:
            r = await conn.execute(text(_SQL_SENZA_VERSIONE))
            return [ArticoloMonitorato(u, a) for u, a in r.all()]

    async def versione_corrente(self, art: ArticoloMonitorato) -> VersioneSalvata | None:
        async with self._engine.connect() as conn:
            r = await conn.execute(
                text(
                    "SELECT vigenza_inizio, hash_testo FROM norme_articoli_versioni "
                    "WHERE urn_atto = :u AND articolo = :a AND vigenza_fine IS NULL "
                    "ORDER BY vigenza_inizio DESC LIMIT 1"
                ),
                {"u": art.urn_atto, "a": art.articolo},
            )
            riga = r.first()
            return VersioneSalvata(riga[0], riga[1]) if riga else None

    async def salva_versione(self, art: ArticoloMonitorato, testo: TestoArticolo) -> None:
        a = testo.articolo
        parametri = {
            "u": art.urn_atto,
            "a": art.articolo,
            "rubrica": a.rubrica,
            "inizio": testo.vigenza_inizio,
            "fine": testo.vigenza_fine,
            "struttura": json.dumps(a.to_dict(), ensure_ascii=False),
            "html": testo.html,
            "hash": a.hash(),
            "rinvii": json.dumps(a.rinvii),
        }
        async with self._engine.begin() as conn:
            # chiude la versione precedente ancora aperta
            if testo.vigenza_inizio:
                await conn.execute(
                    text(
                        "UPDATE norme_articoli_versioni SET vigenza_fine = :fine_prec "
                        "WHERE urn_atto = :u AND articolo = :a AND vigenza_fine IS NULL "
                        "AND (vigenza_inizio IS NULL OR vigenza_inizio < :inizio)"
                    ),
                    {
                        "u": art.urn_atto,
                        "a": art.articolo,
                        "inizio": testo.vigenza_inizio,
                        "fine_prec": testo.vigenza_inizio - timedelta(days=1),
                    },
                )
            await conn.execute(
                text(
                    "INSERT INTO norme_articoli_versioni "
                    "(urn_atto, articolo, rubrica, vigenza_inizio, vigenza_fine, "
                    " struttura_json, testo_html, hash_testo, rinvii_json) "
                    "VALUES (:u, :a, :rubrica, :inizio, :fine, :struttura, :html, :hash, :rinvii) "
                    "ON DUPLICATE KEY UPDATE rubrica = VALUES(rubrica), "
                    " vigenza_fine = VALUES(vigenza_fine), struttura_json = VALUES(struttura_json), "
                    " testo_html = VALUES(testo_html), hash_testo = VALUES(hash_testo), "
                    " rinvii_json = VALUES(rinvii_json), scaricato_il = CURRENT_TIMESTAMP"
                ),
                parametri,
            )

    async def registra_esecuzione(
        self,
        da: datetime,
        a: datetime,
        atti_modificati: int,
        articoli_aggiornati: int,
        esito: str,
        dettaglio: str | None,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO normattiva_sync "
                    "(intervallo_da, intervallo_a, atti_modificati, articoli_aggiornati, "
                    " esito, dettaglio) VALUES (:da, :a, :m, :ag, :esito, :det)"
                ),
                {
                    "da": da,
                    "a": a,
                    "m": atti_modificati,
                    "ag": articoli_aggiornati,
                    "esito": esito,
                    "det": dettaglio,
                },
            )
