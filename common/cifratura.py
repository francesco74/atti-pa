"""Cifratura dei segreti salvati nel database (chiave del RAG, password SMTP dell'ente) con
CHIAVE_CIFRATURA: chi legge il database non li vede in chiaro e non escono mai dall'API."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class ErroreCifratura(Exception):
    pass


def _fernet(segreto: str) -> Fernet:
    if not segreto:
        raise ErroreCifratura("CHIAVE_CIFRATURA non configurata: non si possono salvare né usare segreti cifrati")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(segreto.encode()).digest()))


def cifra(testo: str, segreto: str) -> str:
    return _fernet(segreto).encrypt(testo.encode()).decode()


def decifra(cifrato: str, segreto: str, cosa: str = "Il segreto") -> str:
    try:
        return _fernet(segreto).decrypt(cifrato.encode()).decode()
    except InvalidToken as e:
        raise ErroreCifratura(f"{cosa} salvato non si può decifrare (CHIAVE_CIFRATURA cambiata?): reinseriscilo") from e
