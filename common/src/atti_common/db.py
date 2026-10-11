from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from atti_common.config import get_settings


def crea_engine(url: str | None = None) -> AsyncEngine:
    url = url or get_settings().database_url
    opzioni = {"pool_pre_ping": True, "pool_recycle": 1800} if url.startswith("mysql") else {}
    return create_async_engine(url, **opzioni)


def crea_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
