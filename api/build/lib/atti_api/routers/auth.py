from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from ldap3.core.exceptions import LDAPException
from pydantic import BaseModel
from sqlalchemy import select

from atti_api.auth.ldap import LdapAuthenticator, ruoli_da_gruppi
from atti_api.auth.token import COOKIE, crea_token
from atti_api.deps import DbDep, SettingsDep, UtenteDep, audit, get_authenticator
from atti_api.schemas import UtenteOut
from atti_common.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["autenticazione"])


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    scadenza_minuti: int
    utente: UtenteOut


@router.post("/login", response_model=LoginOut)
async def login(
    dati: LoginIn,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    authenticator: Annotated[LdapAuthenticator, Depends(get_authenticator)],
):
    if not settings.auth_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Autenticazione disattivata")
    try:
        utente_ad = await run_in_threadpool(authenticator.autentica, dati.username, dati.password)
    except LDAPException as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Server di autenticazione non raggiungibile"
        ) from e
    if utente_ad is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenziali non valide")

    ruoli = ruoli_da_gruppi(utente_ad.gruppi, settings)
    if not ruoli:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Utente non abilitato all'uso dell'applicazione"
        )

    # Provisioning just-in-time: anagrafica e ruoli aggiornati a ogni accesso
    user = await db.scalar(select(User).where(User.username == utente_ad.username))
    if user is None:
        user = User(username=utente_ad.username)
        db.add(user)
    elif not user.attivo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Utente disattivato")
    user.nome_completo = utente_ad.nome_completo
    user.email = utente_ad.email
    user.ufficio = utente_ad.ufficio
    user.ruoli = ruoli
    user.ultimo_accesso = datetime.now()
    await db.flush()
    audit(db, user, "utente", user.id, "LOGIN")
    await db.commit()

    token = crea_token(user, settings)
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.jwt_scadenza_minuti * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api",
    )
    return LoginOut(
        token=token,
        scadenza_minuti=settings.jwt_scadenza_minuti,
        utente=UtenteOut.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/api")


@router.get("/me", response_model=UtenteOut)
async def me(user: UtenteDep):
    return user
