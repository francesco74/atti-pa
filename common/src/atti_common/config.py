from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurazione letta da variabili d'ambiente (ConfigMap/Secret in Kubernetes)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fuso_orario: str = "Europe/Rome"

    normattiva_base_url: str = "https://api.normattiva.it/t/normattiva.api"
    normattiva_timeout: float = 30.0

    database_url: str = "mysql+aiomysql://atti_pa:password@localhost:3306/atti_pa"

    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "mistral-small"

    auth_enabled: bool = False
    ldap_url: str = ""
    ldap_base_dn: str = ""
    jwt_secret: str = "cambiami"

    # Job di aggiornamento normative
    sync_giorni_iniziali: int = 7  # finestra alla prima esecuzione
    sync_finestra_giorni: int = 7  # ampiezza massima di ogni chiamata a "ricerca/aggiornati"
    sync_pausa_secondi: float = 0.5  # pausa tra chiamate per non sovraccaricare Normattiva

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.fuso_orario)


@lru_cache
def get_settings() -> Settings:
    return Settings()
