"""Risorse condivise, sessione del database e autenticazione delle viste Flask."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import wraps
from http import HTTPStatus
from typing import Any

from flask import current_app, g, request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from auth.ldap import LdapAuthenticator
from auth.token import COOKIE, decodifica_token
from web import ErroreApi
from common import archivio
from common.config import Settings
from common.models import AuditLog, Ruolo, User
from common.testo import mime_da_nome

log = logging.getLogger("atti_api.auth")


@dataclass
class Risorse:
    """Oggetti creati all'avvio e condivisi da tutte le richieste (`app.state`)."""

    settings: Settings
    authenticator: LdapAuthenticator
    engine: AsyncEngine | None = None
    sessionmaker: async_sessionmaker[AsyncSession] | None = None
    normattiva: Any = None
    llm: Any = None
    documenti: Any = None
    coda: Any = None  # common.coda.Coda


def risorse() -> Risorse:
    return current_app.state


async def notifica(coda: str, dati: dict) -> None:
    """Pubblica un messaggio dopo il commit; se RabbitMQ non risponde lo stato resta nel
    database e il worker reinvierà il lavoro (WORKER_REINVIO_MINUTI)."""
    try:
        await risorse().coda.pubblica(coda, dati)
    except Exception as e:  # noqa: BLE001 - qualunque errore di rete o del broker
        logging.getLogger("atti_api.coda").warning(
            "Invio sulla coda %s non riuscito, verrà reinviato: %s", coda, e
        )


async def archivia_caricato(file) -> tuple[str, str, archivio.FileArchiviato]:
    """Salva nell'archivio un file caricato (PDF, ODT, DOCX, DOC): nome, MIME, archiviato."""
    nome = file.filename or "documento"
    mime = mime_da_nome(nome)
    if mime is None:
        raise ErroreApi(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Formato non supportato: PDF, ODT, DOCX o DOC"
        )
    limite = impostazioni().upload_max_mb * 1024 * 1024
    contenuto = file.read(limite + 1)
    if len(contenuto) > limite:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
    archiviato = await asyncio.to_thread(
        archivio.salva, impostazioni().archivio_dir, contenuto, nome
    )
    return nome, mime, archiviato


def impostazioni() -> Settings:
    return risorse().settings


def db() -> AsyncSession:
    """Sessione del database della richiesta, chiusa a fine richiesta."""
    if "db" not in g:
        g.db = risorse().sessionmaker()
    return g.db


async def chiudi_db(_errore: BaseException | None = None) -> None:
    sessione = g.pop("db", None)
    if sessione is not None:
        await sessione.close()


_NON_AUTENTICATO = ErroreApi(
    HTTPStatus.UNAUTHORIZED, "Autenticazione richiesta", headers={"WWW-Authenticate": "Bearer"}
)


def _token_richiesta() -> str | None:
    intestazione = request.headers.get("Authorization", "")
    if intestazione.lower().startswith("bearer "):
        return intestazione[7:].strip()
    return request.cookies.get(COOKIE)


async def _utente_locale(sessione: AsyncSession) -> User:
    """Utente unico per l'uso personale senza Active Directory (AUTH_ENABLED=false)."""
    user = await sessione.scalar(select(User).where(User.username == "locale"))
    if user is None:
        user = User(username="locale", nome_completo="Utente locale", ruoli=list(Ruolo.TUTTI))
        sessione.add(user)
        await sessione.commit()
    return user


async def utente_corrente() -> User:
    settings = impostazioni()
    if not settings.auth_enabled:
        return await _utente_locale(db())
    token = _token_richiesta()
    if not token:
        log.debug("%s: nessun token (cookie o Authorization)", request.path)
        raise _NON_AUTENTICATO
    payload = decodifica_token(token, settings)
    if not payload:
        log.debug("%s: token non valido o scaduto", request.path)
        raise _NON_AUTENTICATO
    user = await db().get(User, payload["sub"])
    if user is None or not user.attivo:
        log.debug("%s: utente %s inesistente o disattivato", request.path, payload["sub"])
        raise _NON_AUTENTICATO
    return user


def utente() -> User:
    """Utente autenticato della richiesta (impostato da `autenticato`)."""
    return g.utente


def autenticato(*ruoli: str):
    """Decoratore: richiede un utente autenticato e, se indicati, uno dei ruoli.

    ADMIN è sempre ammesso.
    """

    def decoratore(vista):
        @wraps(vista)
        async def protetta(*args, **kwargs):
            user = await utente_corrente()
            if ruoli and not user.ha_ruolo(Ruolo.ADMIN, *ruoli):
                log.debug("Utente %s senza i ruoli richiesti %s", user.username, ruoli)
                raise ErroreApi(HTTPStatus.FORBIDDEN, "Operazione non consentita")
            g.utente = user
            return await vista(*args, **kwargs)

        return protetta

    return decoratore


solo_admin = autenticato(Ruolo.ADMIN)
redattore = autenticato(Ruolo.REDATTORE)
controllore = autenticato(Ruolo.CONTROLLORE)


def audit(
    sessione: AsyncSession,
    user: User | None,
    entita: str,
    entita_id: str,
    azione: str,
    dettaglio: dict | None = None,
) -> None:
    sessione.add(
        AuditLog(
            user_id=user.id if user else None,
            entita=entita,
            entita_id=str(entita_id),
            azione=azione,
            dettaglio=dettaglio,
        )
    )
