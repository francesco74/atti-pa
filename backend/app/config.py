from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    normattiva_base_url: str = "https://api.normattiva.it/t/normattiva.api"
    normattiva_timeout: float = 30.0

    database_url: str = "mysql+aiomysql://atti_pa:password@localhost:3306/atti_pa"

    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "mistral-small"

    auth_enabled: bool = False
    ldap_url: str = ""
    ldap_base_dn: str = ""
    jwt_secret: str = "cambiami"


@lru_cache
def get_settings() -> Settings:
    return Settings()
