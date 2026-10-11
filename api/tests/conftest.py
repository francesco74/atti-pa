"""Fixture comuni dei test API.

Di default usano SQLite in memoria (schema creato dai modelli ORM). Se è impostato
TEST_DATABASE_URL usano un MySQL/MariaDB già migrato con db-migrate.
"""

import os

import httpx
import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from atti_api.auth.ldap import LdapAuthenticator, UtenteAD
from atti_api.main import create_app
from atti_common.config import Settings
from atti_common.db import crea_sessionmaker
from atti_common.models import Base, TipologiaAtto
from atti_common.testing import FakeNormattiva

URL_TEST = os.environ.get("TEST_DATABASE_URL")

UTENTI_AD = {
    "mrossi": (
        "segreta",
        UtenteAD(
            "mrossi",
            "Mario Rossi",
            "m.rossi@ente.it",
            "Ragioneria",
            ["CN=ATTI-PA-Redattori,OU=Gruppi,DC=ente,DC=local"],
        ),
    ),
    "lbianchi": (
        "segreta",
        UtenteAD(
            "lbianchi",
            "Laura Bianchi",
            None,
            "Segreteria",
            ["CN=ATTI-PA-Controllori,OU=Gruppi,DC=ente,DC=local"],
        ),
    ),
    "admin": (
        "segreta",
        UtenteAD(
            "admin", "Amministratore", None, "CED", ["CN=ATTI-PA-Admin,OU=Gruppi,DC=ente,DC=local"]
        ),
    ),
    "estraneo": ("segreta", UtenteAD("estraneo", "Senza gruppi", None, None, [])),
}


class FakeAuthenticator(LdapAuthenticator):
    def autentica(self, username, password):
        voce = UTENTI_AD.get(username)
        if voce and voce[0] == password:
            return voce[1]
        return None


@pytest.fixture
def settings() -> Settings:
    return Settings(
        auth_enabled=True,
        jwt_secret="test-segreto-sufficientemente-lungo-per-hs256",
        cookie_secure=False,
        database_url=URL_TEST or "sqlite+aiosqlite://",
    )


@pytest.fixture
async def engine():
    if URL_TEST:
        eng = create_async_engine(URL_TEST)
        async with eng.begin() as conn:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for tabella in reversed(Base.metadata.sorted_tables):
                if tabella.name != "tipologie_atto":
                    await conn.execute(delete(tabella))
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    else:
        eng = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with crea_sessionmaker(eng)() as s:
            s.add_all(
                [
                    TipologiaAtto(
                        codice="AFFIDAMENTO_DIRETTO", descrizione="Affidamento", ordine=1
                    ),
                    TipologiaAtto(codice="IMPEGNO_SPESA", descrizione="Impegno", ordine=2),
                    TipologiaAtto(codice="ALTRO", descrizione="Altro", ordine=99),
                ]
            )
            await s.commit()
    yield eng
    await eng.dispose()


@pytest.fixture
def app(settings, engine):
    application = create_app(settings, engine=engine, authenticator=FakeAuthenticator(settings))
    application.state.engine = engine
    application.state.sessionmaker = crea_sessionmaker(engine)
    application.state.normattiva = FakeNormattiva()
    return application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(client, username):
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": "segreta"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def login(client):
    async def _fai(username: str) -> dict:
        return await _login(client, username)

    return _fai
