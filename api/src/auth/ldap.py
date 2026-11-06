"""Autenticazione pass-through sull'Active Directory dell'ente.

La configurazione è per ente (Ente.ldap_json, modificabile dall'amministratore dell'ente):
più enti dell'installazione possono avere domini AD diversi. La password non viene mai
salvata: si tenta un BIND con le credenziali dell'utente e, se riesce, si leggono gli
attributi anagrafici e i gruppi con la stessa connessione.
"""

from __future__ import annotations

import logging
import re
import ssl
from dataclasses import dataclass, field

from ldap3 import NONE, SIMPLE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import parse_dn
from pydantic import BaseModel, Field, field_validator

from common.models import Ruolo

log = logging.getLogger("atti_api.auth")

# sAMAccountName: niente caratteri che possano alterare UPN o filtri
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_ATTRIBUTI = ["sAMAccountName", "displayName", "mail", "department", "memberOf"]

GRUPPI_PREDEFINITI = {
    Ruolo.REDATTORE: "ATTI-PA-Redattori",
    Ruolo.CONTROLLORE: "ATTI-PA-Controllori",
    Ruolo.GESTORE_MODELLI: "ATTI-PA-Gestori-Modelli",
    Ruolo.TRASPARENZA: "ATTI-PA-Trasparenza",
    Ruolo.ANTICORRUZIONE_REFERENTE: "ATTI-PA-Anticorruzione-Referenti",
    Ruolo.ANTICORRUZIONE_RPCT: "ATTI-PA-Anticorruzione-RPCT",
    Ruolo.PERFORMANCE_RESPONSABILE: "ATTI-PA-Performance-Responsabili",
    Ruolo.PERFORMANCE_AMMINISTRATORE: "ATTI-PA-Performance-Amministratori",
    Ruolo.ADMIN: "ATTI-PA-Admin",
}


class ConfigLdap(BaseModel):
    """Active Directory di un ente."""

    url: str = Field(pattern=r"^ldaps?://\S+$")  # es. ldaps://dc.ente.local
    dominio: str = Field(min_length=1)  # per il bind con UPN: utente@dominio
    base_dn: str = Field(min_length=1)  # es. DC=ente,DC=local
    # certificato della CA che ha firmato quello del domain controller (PEM); vuoto = CA di
    # sistema
    ca_pem: str | None = None
    # Disattivarla solo per prove o con certificati autofirmati in una rete fidata: le
    # password viaggiano cifrate ma senza garanzia di parlare con il vero domain controller
    verifica_certificato: bool = True
    timeout: int = Field(default=10, ge=1, le=60)  # il login è interattivo
    # ruolo applicativo -> gruppo AD (CN o DN completo)
    gruppi: dict[str, str] = Field(default_factory=lambda: dict(GRUPPI_PREDEFINITI))

    @field_validator("gruppi")
    @classmethod
    def _ruoli_noti(cls, v: dict[str, str]) -> dict[str, str]:
        sconosciuti = set(v) - set(Ruolo.TUTTI)
        if sconosciuti:
            raise ValueError(f"Ruoli sconosciuti: {', '.join(sorted(sconosciuti))}")
        return {r: g.strip() for r, g in v.items() if g and g.strip()}

    @field_validator("ca_pem")
    @classmethod
    def _pem(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and "BEGIN CERTIFICATE" not in v:
            raise ValueError("Il certificato della CA deve essere in formato PEM")
        return v or None


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


def ruoli_da_gruppi(gruppi: list[str], mappa: dict[str, str]) -> list[str]:
    """Converte i gruppi AD (DN da memberOf) nei ruoli applicativi secondo la mappa
    ruolo -> gruppo dell'ente. Un gruppo si indica col solo CN o con il DN completo."""
    dn_utente = {g.lower() for g in gruppi}
    cn_utente = {c.lower() for g in gruppi if (c := _cn(g))}

    def appartiene(gruppo: str) -> bool:
        gruppo = gruppo.strip().lower()
        if not gruppo:
            return False
        return gruppo in dn_utente if "=" in gruppo else gruppo in cn_utente

    return [ruolo for ruolo in Ruolo.TUTTI if appartiene(mappa.get(ruolo, ""))]


class LdapAuthenticator:
    def __init__(self, config: ConfigLdap):
        self.config = config
        if config.url.lower().startswith("ldaps://") and not config.verifica_certificato:
            log.warning(
                "Verifica del certificato LDAPS disattivata per %s: non è garantito che sia "
                "il vero domain controller",
                config.url,
            )

    def _server(self) -> Server:
        c = self.config
        usa_ssl = c.url.lower().startswith("ldaps://")
        tls = None
        if usa_ssl and not c.verifica_certificato:
            tls = Tls(validate=ssl.CERT_NONE)
        elif usa_ssl:
            # CA dell'ente se indicata, altrimenti quelle di sistema
            tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_data=c.ca_pem)
        return Server(c.url, use_ssl=usa_ssl, tls=tls, get_info=NONE, connect_timeout=c.timeout)

    def _bind(self, username: str, password: str) -> Connection | None:
        log.debug("Bind LDAP su %s come %s@%s", self.config.url, username, self.config.dominio)
        conn = Connection(
            self._server(),
            user=f"{username}@{self.config.dominio}",
            password=password,
            authentication=SIMPLE,
            read_only=True,
            receive_timeout=self.config.timeout,
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
            log.exception("Errore di connessione al server LDAP %s", self.config.url)
            raise
        if conn is None:
            log.info("Login fallito per %s", username)
            return None
        try:
            filtro = (
                "(&(objectCategory=person)(objectClass=user)"
                f"(sAMAccountName={escape_filter_chars(username)}))"
            )
            conn.search(self.config.base_dn, filtro, attributes=_ATTRIBUTI, size_limit=1)
            if not conn.entries:
                log.warning(
                    "Bind riuscito ma utente %s non trovato in %s", username, self.config.base_dn
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
