"""Autenticazione pass-through su Active Directory.

La password non viene mai salvata: si tenta un BIND con le credenziali dell'utente e,
se riesce, si leggono gli attributi anagrafici e i gruppi con la stessa connessione.
"""

from __future__ import annotations

import logging
import os
import re
import ssl
from dataclasses import dataclass, field

from ldap3 import NONE, SIMPLE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import parse_dn

from common.config import Settings
from common.models import Ruolo

log = logging.getLogger("atti_api.auth")

# sAMAccountName: niente caratteri che possano alterare UPN o filtri
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_ATTRIBUTI = ["sAMAccountName", "displayName", "mail", "department", "memberOf"]


@dataclass
class UtenteAD:
    username: str
    nome_completo: str | None = None
    email: str | None = None
    ufficio: str | None = None
    gruppi: list[str] = field(default_factory=list)


def _primo(valore):
    if isinstance(valore, list):
        return valore[0] if valore else None
    return valore or None


def _cn(dn: str) -> str | None:
    try:
        for attributo, valore, _ in parse_dn(dn):
            if attributo.lower() == "cn":
                return valore
    except LDAPException:
        return None
    return None


def ruoli_da_gruppi(gruppi: list[str], settings: Settings) -> list[str]:
    """Converte i gruppi AD (DN da memberOf) nei ruoli applicativi.

    Nella configurazione un gruppo può essere indicato col solo CN o con il DN completo.
    """
    dn_utente = {g.lower() for g in gruppi}
    cn_utente = {c.lower() for g in gruppi if (c := _cn(g))}

    def appartiene(gruppo: str) -> bool:
        gruppo = gruppo.strip().lower()
        if not gruppo:
            return False
        return gruppo in dn_utente if "=" in gruppo else gruppo in cn_utente

    mappa = {
        Ruolo.REDATTORE: settings.ldap_gruppo_redattori,
        Ruolo.CONTROLLORE: settings.ldap_gruppo_controllori,
        Ruolo.GESTORE_MODELLI: settings.ldap_gruppo_gestori_modelli,
        Ruolo.ADMIN: settings.ldap_gruppo_admin,
    }
    return [ruolo for ruolo, gruppo in mappa.items() if appartiene(gruppo)]


class LdapAuthenticator:
    def __init__(self, settings: Settings):
        self.settings = settings
        if (
            settings.auth_enabled
            and settings.ldap_url.lower().startswith("ldaps://")
            and not settings.ldap_verifica_certificato
        ):
            log.warning(
                "Verifica del certificato LDAPS disattivata (LDAP_VERIFICA_CERTIFICATO=false): "
                "non è garantito che %s sia il vero domain controller",
                settings.ldap_url,
            )

    def _server(self) -> Server:
        s = self.settings
        usa_ssl = s.ldap_url.lower().startswith("ldaps://")
        tls = None
        if usa_ssl and not s.ldap_verifica_certificato:
            tls = Tls(validate=ssl.CERT_NONE)
        elif usa_ssl:
            # CA dell'ente se montata (ConfigMap ldap-ca), altrimenti quelle di sistema
            ca = s.ldap_ca_cert if s.ldap_ca_cert and os.path.isfile(s.ldap_ca_cert) else None
            tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca)
        return Server(
            s.ldap_url, use_ssl=usa_ssl, tls=tls, get_info=NONE, connect_timeout=s.ldap_timeout
        )

    def _bind(self, username: str, password: str) -> Connection | None:
        log.debug(
            "Bind LDAP su %s come %s@%s",
            self.settings.ldap_url,
            username,
            self.settings.ldap_dominio,
        )
        conn = Connection(
            self._server(),
            user=f"{username}@{self.settings.ldap_dominio}",
            password=password,
            authentication=SIMPLE,
            read_only=True,
            receive_timeout=self.settings.ldap_timeout,
            raise_exceptions=False,
        )
        if conn.bind():
            return conn
        log.debug("Bind LDAP rifiutato per %s: %s", username, conn.result)
        return None

    def autentica(self, username: str, password: str) -> UtenteAD | None:
        """Restituisce i dati dell'utente se le credenziali sono valide, altrimenti None."""
        username = (username or "").strip()
        # una password vuota provocherebbe un bind anonimo "riuscito"
        if not _USERNAME.match(username) or not password:
            log.debug("Login rifiutato: nome utente non valido o password vuota")
            return None
        try:
            conn = self._bind(username, password)
        except LDAPException:
            log.exception("Errore di connessione al server LDAP")
            raise
        if conn is None:
            log.info("Login fallito per %s", username)
            return None
        try:
            filtro = (
                "(&(objectCategory=person)(objectClass=user)"
                f"(sAMAccountName={escape_filter_chars(username)}))"
            )
            conn.search(self.settings.ldap_base_dn, filtro, attributes=_ATTRIBUTI, size_limit=1)
            if not conn.entries:
                log.warning(
                    "Bind riuscito ma utente %s non trovato in %s",
                    username,
                    self.settings.ldap_base_dn,
                )
                return UtenteAD(username=username.lower())
            attr = conn.entries[0].entry_attributes_as_dict
            log.debug("Utente %s: gruppi AD %s", username, attr.get("memberOf"))
            return UtenteAD(
                username=(_primo(attr.get("sAMAccountName")) or username).lower(),
                nome_completo=_primo(attr.get("displayName")),
                email=_primo(attr.get("mail")),
                ufficio=_primo(attr.get("department")),
                gruppi=list(attr.get("memberOf") or []),
            )
        finally:
            conn.unbind()
