from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurazione letta da variabili d'ambiente (ConfigMap/Secret in Kubernetes)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fuso_orario: str = "Europe/Rome"

    # Normattiva
    normattiva_base_url: str = "https://api.normattiva.it/t/normattiva.api"
    normattiva_timeout: float = 30.0

    # Database
    database_url: str = "mysql+aiomysql://atti_pa:password@localhost:3306/atti_pa"

    # LLM on-premise (API compatibile OpenAI: vLLM, Ollama, llama.cpp server)
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "mistral-small"
    llm_api_key: str = "nessuna"
    llm_timeout: float = 180.0
    llm_temperatura: float = 0.0

    # Autenticazione
    auth_enabled: bool = True
    ldap_url: str = "ldaps://dc.ente.local"
    ldap_dominio: str = "ente.local"  # per il bind con UPN: utente@dominio
    ldap_base_dn: str = "DC=ente,DC=local"
    ldap_ca_cert: str | None = None  # percorso del certificato CA per LDAPS
    ldap_timeout: int = 10
    # Gruppi AD (CN o DN completo) che concedono i ruoli applicativi
    ldap_gruppo_redattori: str = "ATTI-PA-Redattori"
    ldap_gruppo_controllori: str = "ATTI-PA-Controllori"
    ldap_gruppo_admin: str = "ATTI-PA-Admin"

    jwt_secret: str = "cambiami"
    jwt_scadenza_minuti: int = 480
    cookie_secure: bool = True
    cors_origini: list[str] = []

    # Servizio documenti (conversione ODT/PDF con LibreOffice)
    documenti_url: str = "http://documenti:8000"
    upload_max_mb: int = 20

    # Job di aggiornamento normative
    sync_giorni_iniziali: int = 7
    sync_finestra_giorni: int = 7
    sync_pausa_secondi: float = 0.5

    # Worker di verifica
    worker_intervallo_secondi: float = 5.0
    worker_max_tentativi: int = 3
    worker_timeout_minuti: int = 30  # verifiche "IN_CORSO" oltre questo tempo tornano in coda

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.fuso_orario)


@lru_cache
def get_settings() -> Settings:
    return Settings()
