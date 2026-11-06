"""Password degli utenti locali.

Le nuove password usano l'hash scrypt di Werkzeug. Si accettano anche gli hash dei sistemi
che confluiscono nell'installazione (Werkzeug pbkdf2/scrypt, bcrypt): al primo accesso riuscito l'hash viene rigenerato nel formato attuale,
così nessuno deve cambiare password dopo la migrazione.
"""

from __future__ import annotations

import bcrypt
from werkzeug.security import check_password_hash, generate_password_hash

METODO = "scrypt"
LUNGHEZZA_MINIMA = 10


def calcola(password: str) -> str:
    return generate_password_hash(password, method=METODO)


def _bcrypt(valore: str) -> bool:
    return valore.startswith(("$2a$", "$2b$", "$2y$"))


def verifica(hash_salvato: str | None, password: str) -> tuple[bool, bool]:
    """(password giusta, hash da rigenerare nel formato attuale)."""
    if not hash_salvato or not password:
        return False, False
    if _bcrypt(hash_salvato):
        try:
            ok = bcrypt.checkpw(password.encode(), hash_salvato.encode())
        except ValueError:
            return False, False
        return ok, ok
    try:
        ok = check_password_hash(hash_salvato, password)
    except ValueError:  # formato sconosciuto
        return False, False
    return ok, ok and not hash_salvato.startswith(f"{METODO}:")


def controlla_nuova(password: str) -> str | None:
    """Messaggio d'errore se la nuova password non è accettabile."""
    if len(password) < LUNGHEZZA_MINIMA:
        return f"La password deve avere almeno {LUNGHEZZA_MINIMA} caratteri"
    if password.isalpha() or password.isdigit():
        return "La password deve contenere sia lettere sia numeri o simboli"
    return None
