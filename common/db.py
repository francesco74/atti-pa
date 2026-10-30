from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from common.config import get_settings


def crea_engine(url: str | None = None) -> AsyncEngine:
    url = url or get_settings().database_url
    opzioni = {"pool_pre_ping": True, "pool_recycle": 1800} if url.startswith("mysql") else {}
    motore = create_async_engine(url, **opzioni)
    if url.startswith("sqlite"):
        # nei test: chiavi esterne controllate come in MySQL
        event.listen(motore.sync_engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    return motore


def crea_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
