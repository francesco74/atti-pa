from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UtenteOut(Schema):
    id: str
    username: str
    nome_completo: str | None
    email: str | None
    ufficio: str | None
    decreto_incarico: str | None
    ruoli: list[str]
    ultimo_accesso: datetime | None = None
