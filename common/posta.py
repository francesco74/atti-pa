"""Posta in uscita: configurazione SMTP di ogni ente (Ente.smtp_json, password cifrata con
CHIAVE_CIFRATURA), coda di invio (tabella notifiche_email) e invio.

L'API non spedisce mentre l'utente aspetta: con `accoda` scrive le email nella stessa
transazione dell'operazione che le genera (se l'operazione non si salva, l'email non esiste).
Il worker, a ogni giro di manutenzione, chiama `invia_in_sospeso`: invia con l'SMTP dell'ente e,
se il server non risponde, riprova con attese crescenti (1, 2, 4... minuti) fino a
POSTA_TENTATIVI volte, poi segna l'email in ERRORE. Un indirizzo rifiutato dal server è un
errore definitivo. Con più repliche del worker le righe si prendono con SKIP LOCKED.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common import cifratura
from common.models import Ente, NotificaEmail

log = logging.getLogger("common.posta")

DA_INVIARE, INVIATA, ERRORE = "DA_INVIARE", "INVIATA", "ERRORE"


class ErrorePosta(Exception):
    def __init__(self, messaggio: str, definitivo: bool = False):
        super().__init__(messaggio)
        self.definitivo = definitivo  # riprovare non serve (es. indirizzo rifiutato)


class ConfigSmtp(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    porta: int = Field(default=587, ge=1, le=65535)
    sicurezza: Literal["STARTTLS", "SSL", "NESSUNA"] = "STARTTLS"
    utente: str | None = Field(default=None, max_length=255)  # senza: nessuna autenticazione
    password_cifrata: str | None = None
    mittente: str = Field(min_length=3, max_length=255)  # es. "Comune di Lucca <rpct@...>"
    rispondi_a: str | None = Field(default=None, max_length=255)


def config_ente(smtp_json: dict | None) -> ConfigSmtp | None:
    """Configurazione SMTP dell'ente, None se manca o non è valida."""
    if not smtp_json:
        return None
    try:
        return ConfigSmtp.model_validate(smtp_json)
    except ValidationError:
        log.error("Configurazione SMTP non valida: %s", smtp_json.get("host"))
        return None


def indirizzo_valido(testo: str | None) -> bool:
    indirizzo = parseaddr(testo or "")[1]
    return "@" in indirizzo and "." in indirizzo.rsplit("@", 1)[-1] and " " not in indirizzo


def invia(config: ConfigSmtp, segreto: str, destinatario: str, oggetto: str, testo: str, timeout: float = 20.0) -> None:
    """Invia un'email di solo testo (bloccante: dall'asincrono con asyncio.to_thread)."""
    messaggio = EmailMessage()
    messaggio["From"] = config.mittente
    messaggio["To"] = destinatario
    if config.rispondi_a:
        messaggio["Reply-To"] = config.rispondi_a
    messaggio["Subject"] = oggetto
    messaggio["Date"] = formatdate(localtime=True)
    messaggio["Message-ID"] = make_msgid(domain=parseaddr(config.mittente)[1].rsplit("@", 1)[-1] or None)
    messaggio.set_content(testo)
    try:
        password = (
            cifratura.decifra(config.password_cifrata, segreto, "La password SMTP")
            if config.password_cifrata else None
        )  # fmt: skip
    except cifratura.ErroreCifratura as e:
        raise ErrorePosta(str(e), definitivo=True) from e
    contesto = ssl.create_default_context()
    try:
        if config.sicurezza == "SSL":
            server = smtplib.SMTP_SSL(config.host, config.porta, timeout=timeout, context=contesto)
        else:
            server = smtplib.SMTP(config.host, config.porta, timeout=timeout)
        with server:
            if config.sicurezza == "STARTTLS":
                server.starttls(context=contesto)
            if config.utente:
                server.login(config.utente, password or "")
            server.send_message(messaggio)
    except smtplib.SMTPRecipientsRefused as e:
        raise ErrorePosta(f"Indirizzo rifiutato dal server: {destinatario}", definitivo=True) from e
    except smtplib.SMTPAuthenticationError as e:
        raise ErrorePosta("Autenticazione SMTP non riuscita: controlla utente e password") from e
    except (smtplib.SMTPException, OSError) as e:
        raise ErrorePosta(f"Invio non riuscito: {e}") from e


def accoda(sessione: AsyncSession, ente: Ente, destinatari: Iterable[str | None], oggetto: str, testo: str,
           origine: str | None = None) -> int:  # fmt: skip
    """Mette in coda un'email per ogni destinatario valido (senza doppioni); niente se l'ente
    non ha la posta configurata. Restituisce quante email sono in coda."""
    if config_ente(ente.smtp_json) is None:
        log.debug("Ente %s senza posta configurata: notifica '%s' non inviata", ente.codice, oggetto)
        return 0
    visti: set[str] = set()
    for d in destinatari:
        if not indirizzo_valido(d) or d.strip().lower() in visti:
            continue
        visti.add(d.strip().lower())
        sessione.add(NotificaEmail(ente_id=ente.id, destinatario=d.strip(), oggetto=oggetto[:255], testo=testo,
                                   origine=origine, stato=DA_INVIARE))  # fmt: skip
    return len(visti)


Invio = Callable[[ConfigSmtp, str, str, str, str, float], None]


async def invia_in_sospeso(
    sessionmaker: async_sessionmaker[AsyncSession],
    segreto: str,
    *,
    tentativi: int = 6,
    lotto: int = 50,
    timeout: float = 20.0,
    invio: Invio = invia,
) -> tuple[int, int]:
    """Invia le email in coda il cui momento è arrivato: (inviate, non riuscite)."""
    adesso = datetime.now().replace(microsecond=0)
    inviate = fallite = 0
    async with sessionmaker() as db:
        q = (
            select(NotificaEmail)
            .where(NotificaEmail.stato == DA_INVIARE,
                   or_(NotificaEmail.prossimo_tentativo.is_(None), NotificaEmail.prossimo_tentativo <= adesso))
            .order_by(NotificaEmail.created_at)
            .limit(lotto)
        )  # fmt: skip
        if db.bind.dialect.name != "sqlite":
            q = q.with_for_update(skip_locked=True)
        righe = list(await db.scalars(q))
        configurazioni: dict[str, ConfigSmtp | None] = {}
        for n in righe:
            if n.ente_id not in configurazioni:
                ente = await db.get(Ente, n.ente_id)
                configurazioni[n.ente_id] = config_ente(ente.smtp_json if ente else None)
            config = configurazioni[n.ente_id]
            n.tentativi = (n.tentativi or 0) + 1
            try:
                if config is None:
                    raise ErrorePosta("Posta in uscita non configurata per l'ente", definitivo=True)
                await asyncio.to_thread(invio, config, segreto, n.destinatario, n.oggetto, n.testo, timeout)
            except ErrorePosta as e:
                fallite += 1
                n.errore = str(e)[:2000]
                if e.definitivo or n.tentativi >= tentativi:
                    n.stato = ERRORE
                    log.warning("Email a %s non inviata (%s): %s", n.destinatario, n.origine, e)
                else:
                    n.prossimo_tentativo = adesso + timedelta(minutes=2 ** (n.tentativi - 1))
                    log.info("Email a %s non inviata, nuovo tentativo alle %s: %s",
                             n.destinatario, n.prossimo_tentativo, e)  # fmt: skip
            else:
                inviate += 1
                n.stato, n.inviata_il, n.errore = INVIATA, datetime.now().replace(microsecond=0), None
                log.debug("Email a %s inviata (%s)", n.destinatario, n.origine)
        await db.commit()
    return inviate, fallite
