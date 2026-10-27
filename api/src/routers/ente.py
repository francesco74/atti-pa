"""Amministrazione dell'ente: modi di accesso (utenti locali, Active Directory) e utenti.

Riservata all'amministratore dell'ente (ruolo ADMIN) e all'amministratore
dell'installazione. I dati dell'ente e la carta intestata sono in routers/modelli.py.
"""

import asyncio
import logging
from http import HTTPStatus

from flask import Blueprint
from ldap3.core.exceptions import LDAPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from auth import password as pw
from auth.ldap import GRUPPI_PREDEFINITI, ConfigLdap, ruoli_da_gruppi
from deps import amministratore_ente, audit, db, ente, risorse, utente
from schemas import UtenteOut
from web import ErroreApi, corpo
from common.models import Ente, OrigineUtente, Ruolo, User

log = logging.getLogger("atti_api.ente")

bp = Blueprint("ente", __name__, url_prefix="/api/v1/ente")


# --- accesso -------------------------------------------------------------------------------


class AccessoIn(BaseModel):
    accesso_locale: bool = True
    ldap: ConfigLdap | None = None  # None: Active Directory non usato


def _accesso(e: Ente) -> dict:
    return {
        "accesso_locale": e.accesso_locale,
        "ldap": e.ldap_json,
        "gruppi_predefiniti": GRUPPI_PREDEFINITI,
        "ruoli": list(Ruolo.TUTTI),
    }


@bp.get("/accesso")
@amministratore_ente
async def accesso():
    return _accesso(await db().get(Ente, ente().id))


@bp.put("/accesso")
@amministratore_ente
async def aggiorna_accesso():
    dati = corpo(AccessoIn)
    if not dati.accesso_locale and dati.ldap is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Serve almeno un modo di accesso")
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    e.accesso_locale = dati.accesso_locale
    e.ldap_json = dati.ldap.model_dump() if dati.ldap else None
    audit(
        sessione, utente(), "ente", e.id, "ACCESSO",
        {"locale": e.accesso_locale, "ldap": dati.ldap.url if dati.ldap else None},
    )  # fmt: skip
    await sessione.commit()
    return _accesso(e)


class ProvaIn(BaseModel):
    ldap: ConfigLdap
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


@bp.post("/accesso/prova")
@amministratore_ente
async def prova_accesso():
    """Prova la configurazione di Active Directory (anche non ancora salvata) con un account:
    mostra i gruppi letti e i ruoli che ne derivano."""
    dati = corpo(ProvaIn)
    try:
        trovato = await asyncio.to_thread(
            risorse().authenticator(dati.ldap).autentica, dati.username, dati.password
        )
    except LDAPException as e:
        return {"esito": "ERRORE", "messaggio": f"Server non raggiungibile o certificato non valido: {e}"}
    if trovato is None:
        return {"esito": "CREDENZIALI", "messaggio": "Credenziali rifiutate dal server"}
    return {
        "esito": "OK",
        "utente": trovato.username,
        "nome": trovato.nome_completo,
        "gruppi": trovato.gruppi,
        "ruoli": ruoli_da_gruppi(trovato.gruppi, dati.ldap.gruppi),
    }


# --- utenti --------------------------------------------------------------------------------


def _utente_out(u: User) -> dict:
    return {**UtenteOut.model_validate(u).model_dump(mode="json"), "attivo": u.attivo}


@bp.get("/utenti")
@amministratore_ente
async def elenco_utenti():
    utenti = (
        await db().scalars(select(User).where(User.ente_id == ente().id).order_by(User.username))
    ).all()
    return [_utente_out(u) for u in utenti]


def _ruoli(v: list[str]) -> list[str]:
    sconosciuti = set(v) - set(Ruolo.TUTTI)
    if sconosciuti:
        raise ValueError(f"Ruoli sconosciuti: {', '.join(sorted(sconosciuti))}")
    return [r for r in Ruolo.TUTTI if r in v]


class UtenteNuovoIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._@-]{2,100}$")
    nome_completo: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    ruoli: list[str] = Field(min_length=1)
    password: str

    @field_validator("ruoli")
    @classmethod
    def _controlla_ruoli(cls, v: list[str]) -> list[str]:
        return _ruoli(v)


class UtenteIn(BaseModel):
    nome_completo: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    ruoli: list[str] | None = None  # solo utenti locali: quelli AD vengono dai gruppi
    attivo: bool = True

    @field_validator("ruoli")
    @classmethod
    def _controlla_ruoli(cls, v: list[str] | None) -> list[str] | None:
        return v if v is None else _ruoli(v)


class NuovaPasswordIn(BaseModel):
    password: str


@bp.post("/utenti")
@amministratore_ente
async def crea_utente():
    """Utente locale dell'ente (per chi non è in Active Directory)."""
    dati = corpo(UtenteNuovoIn)
    e = ente()
    if not e.accesso_locale:
        raise ErroreApi(HTTPStatus.CONFLICT, "L'accesso con utenti locali non è abilitato per l'ente")
    if errore := pw.controlla_nuova(dati.password):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, errore)
    sessione = db()
    username = dati.username.lower()
    if await sessione.scalar(select(User).where(User.ente_id == e.id, User.username == username)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Nome utente già usato")
    u = User(
        ente_id=e.id, username=username, origine=OrigineUtente.LOCALE,
        password_hash=pw.calcola(dati.password), nome_completo=dati.nome_completo,
        email=dati.email, ruoli=dati.ruoli,
    )  # fmt: skip
    sessione.add(u)
    await sessione.flush()
    audit(sessione, utente(), "utente", u.id, "CREATO", {"username": username, "ruoli": dati.ruoli})
    await sessione.commit()
    return _utente_out(u), HTTPStatus.CREATED


async def _utente_dell_ente(sessione, utente_id: str) -> User:
    u = await sessione.get(User, utente_id)
    if u is None or u.ente_id != ente().id:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Utente non trovato")
    return u


@bp.put("/utenti/<utente_id>")
@amministratore_ente
async def aggiorna_utente(utente_id: str):
    dati = corpo(UtenteIn)
    sessione = db()
    u = await _utente_dell_ente(sessione, utente_id)
    if u.id == utente().id and (not dati.attivo or (dati.ruoli is not None and Ruolo.ADMIN not in dati.ruoli)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Non puoi disattivarti né toglierti il ruolo di amministratore")
    if u.origine == OrigineUtente.LOCALE:
        u.nome_completo = dati.nome_completo
        u.email = dati.email
        if dati.ruoli is not None:
            u.ruoli = dati.ruoli
    if u.attivo and not dati.attivo:
        u.token_version = (u.token_version or 0) + 1  # chiude le sessioni aperte
    u.attivo = dati.attivo
    audit(sessione, utente(), "utente", u.id, "AGGIORNATO", {"attivo": u.attivo, "ruoli": u.ruoli})
    await sessione.commit()
    return _utente_out(u)


@bp.put("/utenti/<utente_id>/password")
@amministratore_ente
async def reimposta_password(utente_id: str):
    dati = corpo(NuovaPasswordIn)
    if errore := pw.controlla_nuova(dati.password):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, errore)
    sessione = db()
    u = await _utente_dell_ente(sessione, utente_id)
    if u.origine != OrigineUtente.LOCALE:
        raise ErroreApi(HTTPStatus.BAD_REQUEST, "La password di dominio si cambia in Active Directory")
    u.password_hash = pw.calcola(dati.password)
    u.token_version = (u.token_version or 0) + 1
    audit(sessione, utente(), "utente", u.id, "PASSWORD_REIMPOSTATA")
    await sessione.commit()
    return _utente_out(u)
