import asyncio
import logging
from datetime import datetime
from http import HTTPStatus

from flask import Blueprint, jsonify, make_response
from ldap3.core.exceptions import LDAPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth.ldap import ruoli_da_gruppi
from auth.token import COOKIE, crea_token
from deps import audit, autenticato, db, impostazioni, risorse, utente
from schemas import UtenteOut
from web import ErroreApi, corpo, nessun_contenuto, out
from common.models import User

log = logging.getLogger("atti_api.auth")

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


class LoginIn(BaseModel):
    username: str
    password: str


@bp.post("/login")
async def login():
    dati = corpo(LoginIn)
    settings = impostazioni()
    if not settings.auth_enabled:
        raise ErroreApi(HTTPStatus.BAD_REQUEST, "Autenticazione disattivata")
    try:
        # il bind LDAP è bloccante: gira in un thread per non fermare l'event loop
        utente_ad = await asyncio.to_thread(
            risorse().authenticator.autentica, dati.username, dati.password
        )
    except LDAPException as e:
        raise ErroreApi(
            HTTPStatus.SERVICE_UNAVAILABLE, "Server di autenticazione non raggiungibile"
        ) from e
    if utente_ad is None:
        raise ErroreApi(HTTPStatus.UNAUTHORIZED, "Credenziali non valide")

    ruoli = ruoli_da_gruppi(utente_ad.gruppi, settings)
    if not ruoli:
        log.warning(
            "Accesso negato a %s: nessuno dei gruppi AD configurati (%s, %s, %s, %s)",
            utente_ad.username,
            settings.ldap_gruppo_redattori,
            settings.ldap_gruppo_controllori,
            settings.ldap_gruppo_gestori_modelli,
            settings.ldap_gruppo_admin,
        )
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Utente non abilitato all'uso dell'applicazione")

    # Provisioning just-in-time: anagrafica e ruoli aggiornati a ogni accesso
    sessione = db()
    user = await sessione.scalar(select(User).where(User.username == utente_ad.username))
    if user is None:
        user = User(username=utente_ad.username)
        sessione.add(user)
    elif not user.attivo:
        log.warning("Accesso negato a %s: utente disattivato", utente_ad.username)
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Utente disattivato")
    user.nome_completo = utente_ad.nome_completo
    user.email = utente_ad.email
    if utente_ad.ufficio:  # senza Reparto in Active Directory resta quello indicato nel profilo
        user.ufficio = utente_ad.ufficio
    user.ruoli = ruoli
    user.ultimo_accesso = datetime.now()
    await sessione.flush()
    audit(sessione, user, "utente", user.id, "LOGIN")
    await sessione.commit()
    log.info("Accesso di %s con ruoli %s", user.username, ", ".join(ruoli))

    token = crea_token(user, settings)
    risposta = jsonify(
        token=token,
        scadenza_minuti=settings.jwt_scadenza_minuti,
        utente=out(UtenteOut, user),
    )
    risposta.set_cookie(
        COOKIE,
        token,
        max_age=settings.jwt_scadenza_minuti * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="Strict",
        path="/api",
    )
    return risposta


@bp.post("/logout")
def logout():
    risposta = make_response(nessun_contenuto())
    risposta.delete_cookie(COOKIE, path="/api")
    return risposta


@bp.get("/me")
@autenticato()
async def me():
    return out(UtenteOut, utente())


class ProfiloIn(BaseModel):
    ufficio: str | None = Field(default=None, max_length=255)
    decreto_incarico: str | None = Field(default=None, max_length=255)


@bp.put("/profilo")
@autenticato()
async def profilo():
    """Settore (se Active Directory non lo dà) e decreto di incarico dell'utente, usati per
    precompilare gli atti."""
    dati = corpo(ProfiloIn)
    sessione = db()
    user = await sessione.merge(utente())
    user.ufficio = (dati.ufficio or "").strip() or None
    user.decreto_incarico = (dati.decreto_incarico or "").strip() or None
    audit(
        sessione, user, "utente", user.id, "PROFILO",
        {"ufficio": user.ufficio, "decreto_incarico": user.decreto_incarico},
    )  # fmt: skip
    await sessione.commit()
    return out(UtenteOut, user)
