"""Applicazione Flask dell'API atti-pa.

In produzione: `gunicorn -c python:atti_api.gunicorn_conf "atti_api.main:create_app()"`.
In sviluppo: `flask --app "atti_api.main:create_app()" run --port 8000`.
"""

from __future__ import annotations

import atexit
import logging
import time
from pathlib import Path
from http import HTTPStatus

from routers import auth, bozze, checklists, controllo, modelli, norme, norme_manuali
from flask import g, request
from flask_cors import CORS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from auth.ldap import LdapAuthenticator
from ciclo import CicloAsync
from deps import Risorse, chiudi_db
from documenti import DocumentiClient
from routers import editor, pacchetti, verifiche
from web import AttiFlask, ErroreApi
from common.config import Settings, get_settings
from common.db import crea_engine, crea_sessionmaker
from common.coda import Coda
from common.pacchetti import importa_pacchetto_iniziale
from common.llm import crea_llm
from common.log import configura_da_ambiente
from common.normattiva import NormattivaClient

log = logging.getLogger("atti_api")

# Messaggi degli errori generati da Flask/Werkzeug (rotta inesistente, file troppo grande...)
_MESSAGGI = {
    404: "Risorsa non trovata",
    405: "Metodo non consentito",
    413: "File troppo grande",
}


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    authenticator: LdapAuthenticator | None = None,
    normattiva: NormattivaClient | None = None,
    ciclo: CicloAsync | None = None,
) -> AttiFlask:
    if settings is not None and not isinstance(settings, Settings):
        # gunicorn "main:create_app" (senza parentesi) passa l'environ WSGI come primo argomento
        raise TypeError(
            'create_app va chiamata: avviare con gunicorn "main:create_app()" (con le parentesi)'
        )
    if settings is None:
        configura_da_ambiente()
        settings = get_settings()
    if settings.auth_enabled and len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "Con AUTH_ENABLED=true serve JWT_SECRET di almeno 32 caratteri "
            "(es. openssl rand -hex 32)"
        )

    app = AttiFlask("atti_api", ciclo=ciclo)
    # margine di 1 MB per gli altri campi del form multipart
    app.config["MAX_CONTENT_LENGTH"] = (settings.upload_max_mb + 1) * 1024 * 1024

    motore = engine or crea_engine(settings.database_url)
    client_normattiva = normattiva or NormattivaClient(
        base_url=settings.normattiva_base_url,
        timeout=settings.normattiva_timeout,
        tentativi=settings.normattiva_tentativi,
    )
    llm = crea_llm(settings)
    app.state = Risorse(
        settings=settings,
        authenticator=authenticator or LdapAuthenticator(settings),
        engine=motore,
        sessionmaker=crea_sessionmaker(motore),
        normattiva=client_normattiva,
        llm=llm,
        documenti=DocumentiClient(settings.documenti_url, timeout=settings.documenti_timeout),
        # connessione a RabbitMQ al primo invio: l'API parte anche se il broker non risponde
        coda=Coda(settings.rabbitmq_url, settings.rabbitmq_prefisso),
    )

    if settings.importa_pacchetto_iniziale:
        # il database comanda: il pacchetto standard si importa solo se il database è vuoto
        try:
            resoconto = app.ciclo.esegui(
                importa_pacchetto_iniziale(motore, Path(settings.pacchetto_dir))
            )
            if resoconto is None:
                log.info("Modelli e checklist: comanda il database (pacchetto non importato)")
            else:
                log.info("Pacchetto iniziale importato: %s", resoconto)
                for avviso in resoconto.avvisi:
                    log.warning("Modelli e checklist non coerenti: %s", avviso)
        except Exception:
            log.exception("Importazione del pacchetto iniziale non riuscita")

    async def chiudi_risorse() -> None:
        stato = app.state
        for client in (stato.llm, stato.documenti, stato.coda):
            if client is not None:
                await client.close()
        if normattiva is None:
            await client_normattiva.close()
        if engine is None:
            await motore.dispose()

    def alla_chiusura() -> None:
        try:
            app.ciclo.esegui(chiudi_risorse())
        except RuntimeError:
            pass  # loop già fermato (es. nei test)
        finally:
            app.ciclo.chiudi()

    atexit.register(alla_chiusura)

    # Intestazioni X-Forwarded-* impostate dall'Ingress (indirizzo del client, https)
    if settings.proxy_hops:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=settings.proxy_hops,
            x_proto=settings.proxy_hops,
            x_host=settings.proxy_hops,
        )
    if settings.cors_origini:
        CORS(app, origins=settings.cors_origini, supports_credentials=True)

    @app.before_request
    def inizio_richiesta() -> None:
        g.inizio = time.perf_counter()

    @app.after_request
    def registra_richiesta(risposta):
        log.debug(
            "%s %s -> %d (%.0f ms)",
            request.method,
            request.path,
            risposta.status_code,
            (time.perf_counter() - g.get("inizio", time.perf_counter())) * 1000,
        )
        return risposta

    app.teardown_request(chiudi_db)

    @app.errorhandler(ErroreApi)
    def errore_api(e: ErroreApi):
        # Gli errori dei servizi esterni (LLM, Normattiva, documenti, LDAP) diventano 5xx:
        # si registra la causa, che nella risposta al client non compare.
        causa = f" (causa: {e.__cause__!r})" if e.__cause__ else ""
        livello = logging.WARNING if e.stato >= 500 else logging.DEBUG
        log.log(livello, "%s %s -> %d %s%s", request.method, request.path, e.stato, e.detail, causa)
        return {"detail": e.detail}, e.stato, e.headers

    @app.errorhandler(HTTPException)
    def errore_http(e: HTTPException):
        log.debug("%s %s -> %d %s", request.method, request.path, e.code, e.name)
        return {"detail": _MESSAGGI.get(e.code, e.name)}, e.code

    @app.errorhandler(Exception)
    def errore_imprevisto(e: Exception):
        log.exception("Errore non gestito in %s %s", request.method, request.path)
        return {"detail": "Errore interno del server"}, HTTPStatus.INTERNAL_SERVER_ERROR

    @app.get("/api/v1/health")
    def health() -> dict:
        """Liveness probe: il processo risponde."""
        return {"status": "ok"}

    @app.get("/api/v1/ready")
    async def ready() -> dict:
        """Readiness probe: il database è raggiungibile."""
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    for modulo in (
        auth, norme, norme_manuali, checklists, modelli, pacchetti, editor, bozze, verifiche,
        controllo,
    ):  # fmt: skip
        app.register_blueprint(modulo.bp)

    log.info(
        "API avviata: autenticazione %s, LLM %s (%s), documenti %s, log %s",
        "Active Directory" if settings.auth_enabled else "disattivata",
        llm.modello,
        llm.provider,
        settings.documenti_url,
        settings.log_level,
    )
    return app
