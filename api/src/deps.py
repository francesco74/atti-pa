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
from common.models import AuditLog, Ente, EnteDominio, Modulo, Ruolo, User
from common.testo import mime_da_nome

log = logging.getLogger("atti_api.auth")


@dataclass
class Risorse:
    """Oggetti creati all'avvio e condivisi da tutte le richieste (`app.state`)."""

    settings: Settings
    authenticator: type[LdapAuthenticator]  # costruito con la configurazione AD dell'ente
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


def dominio_richiesta() -> str:
    """Host della richiesta senza porta (dopo X-Forwarded-Host dell'Ingress)."""
    return request.host.split(":")[0].strip().lower()


async def ente_richiesta() -> Ente | None:
    """Ente del dominio della richiesta (o ENTE_PREDEFINITO per i domini non registrati, in
    sviluppo). Serve prima dell'accesso: pagina di login, configurazione pubblica. Dopo
    l'accesso i dati si filtrano per l'ente scritto nel token."""
    if "ente_dominio" in g:
        return g.ente_dominio
    sessione = db()
    ente = None
    dominio = await sessione.get(EnteDominio, dominio_richiesta())
    if dominio is not None:
        ente = await sessione.get(Ente, dominio.ente_id)
    elif impostazioni().ente_predefinito:
        ente = await sessione.scalar(
            select(Ente).where(Ente.codice == impostazioni().ente_predefinito)
        )
    if ente is not None and not ente.attivo:
        ente = None
    g.ente_dominio = ente
    return ente


async def _ente_e_utente_locale(sessione: AsyncSession) -> tuple[Ente, User]:
    """Uso personale senza login (AUTH_ENABLED=false): l'ente predefinito (creato se manca)
    e un utente locale con tutti i ruoli."""
    codice = impostazioni().ente_predefinito or "locale"
    ente = await sessione.scalar(select(Ente).where(Ente.codice == codice))
    if ente is None:
        ente = Ente(codice=codice, nome="Ente", moduli_json=list(Modulo.TUTTI), dati_json={})
        sessione.add(ente)
        await sessione.flush()
    user = await sessione.scalar(
        select(User).where(User.ente_id == ente.id, User.username == "locale")
    )
    if user is None:
        user = User(
            ente_id=ente.id, username="locale", nome_completo="Utente locale",
            origine="LOCALE", ruoli=list(Ruolo.TUTTI),
        )  # fmt: skip
        sessione.add(user)
    await sessione.commit()
    return ente, user


async def utente_corrente() -> User:
    """Utente della sessione; imposta g.ente (l'ente su cui lavora la richiesta)."""
    settings = impostazioni()
    sessione = db()
    if not settings.auth_enabled:
        g.ente, user = await _ente_e_utente_locale(sessione)
        return user
    token = _token_richiesta()
    if not token:
        log.debug("%s: nessun token (cookie o Authorization)", request.path)
        raise _NON_AUTENTICATO
    payload = decodifica_token(token, settings)
    if not payload:
        log.debug("%s: token non valido o scaduto", request.path)
        raise _NON_AUTENTICATO
    user = await sessione.get(User, payload["sub"])
    if user is None or not user.attivo or payload.get("tv", 0) != (user.token_version or 0):
        log.debug("%s: utente %s inesistente, disattivato o sessione revocata", request.path, payload["sub"])
        raise _NON_AUTENTICATO
    ente_dominio = await ente_richiesta()
    if user.installazione:
        # l'amministratore dell'installazione lavora sull'ente del dominio (se c'è)
        g.ente = ente_dominio
        return user
    # il token vale solo sul dominio del suo ente: un Host falsificato non apre altri enti
    if ente_dominio is None or user.ente_id != ente_dominio.id or payload.get("ente") != user.ente_id:
        log.debug("%s: utente %s fuori dal dominio del suo ente", request.path, user.username)
        raise _NON_AUTENTICATO
    g.ente = ente_dominio
    return user


def utente() -> User:
    """Utente autenticato della richiesta (impostato da `autenticato`)."""
    return g.utente


def ente() -> Ente:
    """Ente su cui lavora la richiesta autenticata."""
    if g.get("ente") is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Nessun ente per questo dominio")
    return g.ente


def ente_id() -> str:
    return ente().id


def autenticato(*ruoli: str, modulo: str | None = Modulo.REDAZIONE):
    """Decoratore: richiede un utente autenticato, se indicati uno dei ruoli (ADMIN è sempre
    ammesso) e il modulo abilitato per l'ente. L'amministratore dell'installazione ha i
    poteri dell'amministratore sull'ente del dominio."""

    def decoratore(vista):
        @wraps(vista)
        async def protetta(*args, **kwargs):
            user = await utente_corrente()
            if ruoli and not (user.installazione or user.ha_ruolo(Ruolo.ADMIN, *ruoli)):
                log.debug("Utente %s senza i ruoli richiesti %s", user.username, ruoli)
                raise ErroreApi(HTTPStatus.FORBIDDEN, "Operazione non consentita")
            if modulo is not None:
                if not ente().modulo_attivo(modulo):
                    raise ErroreApi(HTTPStatus.FORBIDDEN, "Modulo non abilitato per l'ente")
            g.utente = user
            return await vista(*args, **kwargs)

        return protetta

    return decoratore


def installazione(vista):
    """Decoratore: solo l'amministratore dell'installazione."""

    @wraps(vista)
    async def protetta(*args, **kwargs):
        user = await utente_corrente()
        if not user.installazione:
            raise ErroreApi(HTTPStatus.FORBIDDEN, "Operazione riservata all'amministratore dell'installazione")
        g.utente = user
        return await vista(*args, **kwargs)

    return protetta


solo_admin = autenticato(Ruolo.ADMIN)
redattore = autenticato(Ruolo.REDATTORE)
controllore = autenticato(Ruolo.CONTROLLORE)
gestore_modelli = autenticato(Ruolo.GESTORE_MODELLI)
# amministrazione dell'ente (utenti, accessi, dati): non dipende dai moduli
amministratore_ente = autenticato(Ruolo.ADMIN, modulo=None)


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
            ente_id=g.ente.id if g.get("ente") is not None else (user.ente_id if user else None),
            user_id=user.id if user else None,
            entita=entita,
            entita_id=str(entita_id),
            azione=azione,
            dettaglio=dettaglio,
        )
    )
