from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from atti_api.auth.ldap import LdapAuthenticator
from atti_api.routers import auth
from atti_common.config import Settings, get_settings
from atti_common.db import crea_engine, crea_sessionmaker


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    authenticator: LdapAuthenticator | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        motore = engine or crea_engine(settings.database_url)
        app.state.engine = motore
        app.state.sessionmaker = crea_sessionmaker(motore)
        yield
        if engine is None:
            await motore.dispose()

    app = FastAPI(
        title="atti-pa",
        version="0.1.0",
        description="Redazione e controllo delle determinazioni dirigenziali",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.authenticator = authenticator or LdapAuthenticator(settings)

    if settings.cors_origini:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origini,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/api/v1/health", tags=["sistema"])
    async def health() -> dict:
        """Liveness probe: il processo risponde."""
        return {"status": "ok"}

    @app.get("/api/v1/ready", tags=["sistema"])
    async def ready() -> dict:
        """Readiness probe: il database è raggiungibile."""
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.include_router(auth.router)
    return app


app = create_app()
