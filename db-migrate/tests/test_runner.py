import os
from pathlib import Path

import pytest
from sqlalchemy import text

from db_migrate.runner import applica, carica_migrazioni, dividi_istruzioni

MIGRAZIONI = Path(__file__).resolve().parents[1] / "src" / "migrations"


def test_dividi_ignora_commenti_e_stringhe():
    sql = """
    -- commento con ; punto e virgola
    CREATE TABLE a (x INT); /* blocco; */
    INSERT INTO a VALUES ('uno;due'), ('l''apostrofo; ok');
    """
    istruzioni = dividi_istruzioni(sql)
    assert len(istruzioni) == 2
    assert istruzioni[1].endswith("('l''apostrofo; ok')")


def test_migrazioni_valide():
    migrazioni = carica_migrazioni(MIGRAZIONI)
    assert migrazioni[0].nome == "0001_schema_iniziale.sql"
    assert all(dividi_istruzioni(m.sql) for m in migrazioni)


# Test di integrazione: richiede un MySQL/MariaDB di prova
URL_TEST = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not URL_TEST, reason="TEST_DATABASE_URL non impostato")
async def test_applica_su_database_reale():
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(URL_TEST)
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        tabelle = (await conn.execute(text("SHOW TABLES"))).scalars().all()
        for t in tabelle:
            await conn.execute(text(f"DROP TABLE `{t}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    migrazioni = carica_migrazioni(MIGRAZIONI)
    prima = await applica(engine, migrazioni)
    seconda = await applica(engine, migrazioni)

    async with engine.connect() as conn:
        n = (await conn.execute(text("SELECT COUNT(*) FROM tipologie_atto"))).scalar()
    await engine.dispose()

    assert prima == [m.nome for m in migrazioni]
    assert seconda == []
    assert n > 0
