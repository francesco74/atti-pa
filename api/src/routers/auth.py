"""Accesso: utenti locali o Active Directory dell'ente del dominio, sessione in cookie.

L'ente si ricava dal dominio della richiesta solo qui (e per la configurazione pubblica):
dopo l'accesso è scritto nel token. Da un dominio che non è di un ente non si accede.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Literal

from flask import Blueprint, g, jsonify, make_response, request
from ldap3.core.exceptions import LDAPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import DateTime, func, select

from auth import password as pw
from auth.ldap import ConfigLdap, ruoli_da_gruppi
from auth.token import COOKIE, crea_token
from deps import (
    audit,
    autenticato,
    db,
    dominio_richiesta,
    ente_richiesta,
    impostazioni,
    risorse,
    utente,
)
from schemas import UtenteOut
from web import ErroreApi, corpo, nessun_contenuto
from common.models import AuditLog, Ente, OrigineUtente, Struttura, User

log = logging.getLogger("atti_api.auth")

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


def config_ldap(ente: Ente | None) -> ConfigLdap | None:
    if ente is None or not ente.ldap_json:
        return None
    try:
        return ConfigLdap.model_validate(ente.ldap_json)
    except ValidationError:
        log.error("Configurazione Active Directory dell'ente %s non valida", ente.codice)
        return None


@bp.get("/ente")
async def ente_pubblico():
    """Ente del dominio e modi di accesso, per la pagina di login (senza autenticazione)."""
    ente = await ente_richiesta()
    if ente is None:
        return {"ente": None, "dominio": dominio_richiesta(), "accesso_locale": False, "accesso_ldap": False}
    ldap = config_ldap(ente)
    return {
        "ente": {"codice": ente.codice, "nome": ente.nome, "assistenza": ente.assistenza},
        "dominio": dominio_richiesta(),
        "accesso_locale": ente.accesso_locale,
        "accesso_ldap": ldap is not None,
        "dominio_ldap": ldap.dominio if ldap else None,
    }


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)
    # ldap: account di dominio; locale: utente dell'app. Se manca, AD quando c'è.
    modo: Literal["ldap", "locale"] | None = None


async def _troppi_tentativi(sessione, ente: Ente, username: str) -> bool:
    s = impostazioni()
    # ora del database, la stessa con cui sono registrati i tentativi
    adesso = await sessione.scalar(select(func.now(type_=DateTime)))
    dal = adesso - timedelta(minutes=s.login_finestra_minuti)
    falliti = await sessione.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.entita == "login",
            AuditLog.azione == "FALLITO",
            AuditLog.entita_id == username.lower(),
            AuditLog.ente_id == ente.id,
            AuditLog.created_at >= dal,
        )
    )
    return (falliti or 0) >= s.login_tentativi


async def _fallito(sessione, ente: Ente, username: str, motivo: str) -> None:
    sessione.add(
        AuditLog(
            ente_id=ente.id,
            entita="login",
            entita_id=username.lower(),
            azione="FALLITO",
            dettaglio={"motivo": motivo, "ip": request.remote_addr, "dominio": dominio_richiesta()},
        )
    )
    await sessione.commit()


async def _login_ldap(sessione, ente: Ente, config: ConfigLdap, dati: LoginIn) -> User | None:
    try:
        # il bind LDAP è bloccante: gira in un thread per non fermare l'event loop
        utente_ad = await asyncio.to_thread(
            risorse().authenticator(config).autentica, dati.username, dati.password
        )
    except LDAPException as e:
        raise ErroreApi(
            HTTPStatus.SERVICE_UNAVAILABLE, "Server di autenticazione non raggiungibile"
        ) from e
    if utente_ad is None:
        return None
    ruoli = ruoli_da_gruppi(utente_ad.gruppi, config.gruppi)
    if not ruoli:
        log.warning(
            "Accesso negato a %s (%s): nessuno dei gruppi AD configurati", utente_ad.username, ente.codice
        )
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Utente non abilitato all'uso dell'applicazione")
    # Provisioning just-in-time: anagrafica e ruoli aggiornati a ogni accesso
    user = await sessione.scalar(
        select(User).where(User.ente_id == ente.id, User.username == utente_ad.username)
    )
    if user is None:
        user = User(ente_id=ente.id, username=utente_ad.username, origine=OrigineUtente.LDAP)
        sessione.add(user)
    elif user.origine != OrigineUtente.LDAP:
        log.warning("%s esiste come utente locale dell'ente %s", utente_ad.username, ente.codice)
        raise ErroreApi(HTTPStatus.CONFLICT, "Esiste già un utente locale con questo nome")
    elif not user.attivo:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Utente disattivato")
    user.nome_completo = utente_ad.nome_completo
    user.email = utente_ad.email
    if utente_ad.ufficio:  # senza Reparto in Active Directory resta quello indicato nel profilo
        user.ufficio = utente_ad.ufficio
    user.ruoli = ruoli
    return user


async def _login_locale(sessione, ente: Ente, dati: LoginIn) -> User | None:
    if not ente.accesso_locale:
        return None
    user = await sessione.scalar(
        select(User).where(
            User.ente_id == ente.id,
            User.username == dati.username.strip().lower(),
            User.origine == OrigineUtente.LOCALE,
        )
    )
    if user is None:
        return None
    ok, da_rigenerare = pw.verifica(user.password_hash, dati.password)
    if not ok:
        return None
    if not user.attivo:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Utente disattivato")
    if da_rigenerare:  # hash ereditato (Werkzeug o bcrypt): si porta al formato attuale
        user.password_hash = pw.calcola(dati.password)
    return user


def dati_utente(user: User, ente: Ente) -> dict:
    """Utente con l'ente su cui lavora e i moduli abilitati (per il menu dell'app)."""
    return {
        **UtenteOut.model_validate(user).model_dump(mode="json"),
        "cambio_password": user.cambio_password,
        "ente": {
            "id": ente.id,
            "codice": ente.codice,
            "nome": ente.nome,
            "moduli": ente.moduli_json or [],
            "logo": ente.logo_mime is not None,  # l'app lo usa come icona e come sfondo
            "assistenza": ente.assistenza,  # testo per l'assistenza agli utenti
        },
    }


def _risposta_con_sessione(user: User, ente: Ente, stato=HTTPStatus.OK):
    settings = impostazioni()
    token = crea_token(user, settings)
    risposta = jsonify(token=token, scadenza_minuti=settings.jwt_scadenza_minuti, utente=dati_utente(user, ente))
    risposta.status_code = stato
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


@bp.post("/login")
async def login():
    dati = corpo(LoginIn)
    sessione = db()
    ente = await ente_richiesta()
    if ente is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Questo indirizzo non è associato a un ente")
    if await _troppi_tentativi(sessione, ente, dati.username):
        raise ErroreApi(
            HTTPStatus.TOO_MANY_REQUESTS,
            "Troppi tentativi falliti: riprovare tra qualche minuto",
        )
    config = config_ldap(ente)
    usa_ldap = dati.modo == "ldap" or (dati.modo is None and config is not None)
    if usa_ldap:
        if config is None:
            raise ErroreApi(HTTPStatus.BAD_REQUEST, "Accesso con Active Directory non configurato")
        user = await _login_ldap(sessione, ente, config, dati)
    else:
        user = await _login_locale(sessione, ente, dati)
    if user is None:
        await _fallito(sessione, ente, dati.username, "credenziali")
        raise ErroreApi(HTTPStatus.UNAUTHORIZED, "Credenziali non valide")
    user.ultimo_accesso = datetime.now()
    await sessione.flush()
    audit(sessione, user, "utente", user.id, "LOGIN", {"modo": "ldap" if usa_ldap else "locale"})
    await sessione.commit()
    log.info("Accesso di %s (%s) con ruoli %s", user.username, ente.codice, ", ".join(user.ruoli or []))
    return _risposta_con_sessione(user, ente)


@bp.post("/logout")
def logout():
    risposta = make_response(nessun_contenuto())
    risposta.delete_cookie(COOKIE, path="/api")
    return risposta


@bp.get("/me")
@autenticato(modulo=None)
async def me():
    return dati_utente(utente(), g.ente)


class ProfiloIn(BaseModel):
    ufficio: str | None = Field(default=None, max_length=255)
    decreto_incarico: str | None = Field(default=None, max_length=255)
    struttura_id: str | None = None  # solo se l'utente non ne ha ancora una


@bp.put("/profilo")
@autenticato(modulo=None)
async def profilo():
    """Settore (se Active Directory non lo dà) e decreto di incarico dell'utente, usati per
    precompilare gli atti. La struttura organizzativa l'utente la sceglie una sola volta, se
    non ce l'ha: da lei dipendono proposte e monitoraggio dell'anticorruzione, quindi poi la
    cambia solo l'amministratore (Amministrazione → Utenti)."""
    dati = corpo(ProfiloIn)
    sessione = db()
    user = await sessione.merge(utente())
    user.ufficio = (dati.ufficio or "").strip() or None
    user.decreto_incarico = (dati.decreto_incarico or "").strip() or None
    if dati.struttura_id and dati.struttura_id != user.struttura_id:
        if user.struttura_id is not None:
            raise ErroreApi(HTTPStatus.CONFLICT, "La struttura è già assegnata: per cambiarla rivolgiti all'amministratore")
        s = await sessione.get(Struttura, dati.struttura_id)
        if s is None or s.ente_id != g.ente.id or not s.attiva:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Struttura non trovata")
        user.struttura_id = s.id
    audit(
        sessione, user, "utente", user.id, "PROFILO",
        {"ufficio": user.ufficio, "decreto_incarico": user.decreto_incarico, "struttura_id": user.struttura_id},
    )  # fmt: skip
    await sessione.commit()
    return dati_utente(user, g.ente)


class PasswordIn(BaseModel):
    attuale: str = Field(min_length=1, max_length=500)
    nuova: str = Field(min_length=1, max_length=500)


@bp.put("/password")
@autenticato(modulo=None)
async def cambia_password():
    """Cambio della propria password (solo utenti locali): le altre sessioni si chiudono.
    È l'unica operazione ammessa con la password iniziale ancora da cambiare."""
    dati = corpo(PasswordIn)
    sessione = db()
    user = await sessione.merge(utente())
    if user.origine != OrigineUtente.LOCALE:
        raise ErroreApi(HTTPStatus.BAD_REQUEST, "La password di dominio si cambia in Active Directory")
    ok, _ = pw.verifica(user.password_hash, dati.attuale)
    if not ok:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Password attuale non corretta")
    if errore := pw.controlla_nuova(dati.nuova):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, errore)
    if dati.nuova == dati.attuale:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "La nuova password deve essere diversa")
    user.password_hash = pw.calcola(dati.nuova)
    user.cambio_password = False
    user.token_version = (user.token_version or 0) + 1
    audit(sessione, user, "utente", user.id, "PASSWORD")
    await sessione.commit()
    return _risposta_con_sessione(user, g.ente)
