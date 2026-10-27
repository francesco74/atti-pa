from datetime import UTC, datetime, timedelta

import jwt

from common.config import Settings
from common.models import User

ALGORITMO = "HS256"
COOKIE = "atti_pa_token"


def crea_token(user: User, settings: Settings) -> str:
    """Token della sessione: l'ente vi è scritto, così i dati non dipendono dal dominio della
    richiesta; la versione permette di revocare le sessioni (cambio password, disattivazione)."""
    ora = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "ente": user.ente_id,
        "tv": user.token_version or 0,
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
