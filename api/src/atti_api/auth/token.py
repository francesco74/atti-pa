from datetime import UTC, datetime, timedelta

import jwt

from atti_common.config import Settings
from atti_common.models import User

ALGORITMO = "HS256"
COOKIE = "atti_pa_token"


def crea_token(user: User, settings: Settings) -> str:
    ora = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "username": user.username,
        "ruoli": user.ruoli,
        "iat": ora,
        "exp": ora + timedelta(minutes=settings.jwt_scadenza_minuti),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITMO)


def decodifica_token(token: str, settings: Settings) -> dict | None:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[ALGORITMO], options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError:
        return None
