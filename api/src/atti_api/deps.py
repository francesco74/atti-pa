from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atti_api.auth.ldap import LdapAuthenticator
from atti_api.auth.token import COOKIE, decodifica_token
from atti_common.config import Settings
from atti_common.models import AuditLog, Ruolo, User


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_authenticator(request: Request) -> LdapAuthenticator:
    return request.app.state.authenticator


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]

_NON_AUTENTICATO = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    "Autenticazione richiesta",
    headers={"WWW-Authenticate": "Bearer"},
)


def _token_richiesta(request: Request) -> str | None:
    intestazione = request.headers.get("Authorization", "")
    if intestazione.lower().startswith("bearer "):
        return intestazione[7:].strip()
    return request.cookies.get(COOKIE)


async def _utente_locale(db: AsyncSession) -> User:
    """Utente unico per l'uso personale senza Active Directory (AUTH_ENABLED=false)."""
    user = await db.scalar(select(User).where(User.username == "locale"))
    if user is None:
        user = User(username="locale", nome_completo="Utente locale", ruoli=list(Ruolo.TUTTI))
        db.add(user)
        await db.commit()
    return user


async def utente_corrente(request: Request, db: DbDep, settings: SettingsDep) -> User:
    if not settings.auth_enabled:
        return await _utente_locale(db)
    token = _token_richiesta(request)
    if not token:
        raise _NON_AUTENTICATO
    payload = decodifica_token(token, settings)
    if not payload:
        raise _NON_AUTENTICATO
    user = await db.get(User, payload["sub"])
    if user is None or not user.attivo:
        raise _NON_AUTENTICATO
    return user


UtenteDep = Annotated[User, Depends(utente_corrente)]


def richiede_ruolo(*ruoli: str):
    """Dipendenza che ammette solo gli utenti con almeno uno dei ruoli (ADMIN sempre ammesso)."""

    async def _verifica(user: UtenteDep) -> User:
        if not user.ha_ruolo(Ruolo.ADMIN, *ruoli):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Operazione non consentita")
        return user

    return _verifica


AdminDep = Annotated[User, Depends(richiede_ruolo(Ruolo.ADMIN))]
RedattoreDep = Annotated[User, Depends(richiede_ruolo(Ruolo.REDATTORE))]
ControlloreDep = Annotated[User, Depends(richiede_ruolo(Ruolo.CONTROLLORE))]


def audit(
    db: AsyncSession,
    user: User | None,
    entita: str,
    entita_id: str,
    azione: str,
    dettaglio: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            entita=entita,
            entita_id=str(entita_id),
            azione=azione,
            dettaglio=dettaglio,
        )
    )
