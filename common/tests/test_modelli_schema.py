"""Verifica che i modelli ORM corrispondano allo schema creato dalle migrazioni."""

import os

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from atti_common.models import Base

URL_TEST = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not URL_TEST, reason="TEST_DATABASE_URL non impostato (schema migrato)")
async def test_modelli_allineati_alle_migrazioni():
    engine = create_async_engine(URL_TEST)
    async with engine.connect() as conn:
        colonne_db = await conn.run_sync(
            lambda c: {
                t: {col["name"] for col in inspect(c).get_columns(t)}
                for t in inspect(c).get_table_names()
            }
        )
    await engine.dispose()

    for tabella in Base.metadata.sorted_tables:
        assert tabella.name in colonne_db, f"Tabella mancante nelle migrazioni: {tabella.name}"
        colonne_orm = {c.name for c in tabella.columns}
        assert colonne_orm == colonne_db[tabella.name], tabella.name
