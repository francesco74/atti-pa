"""Strumenti comuni delle viste Flask: errori, validazione con pydantic, risposte JSON."""

from __future__ import annotations

import inspect
from datetime import date
from functools import wraps
from http import HTTPStatus
from typing import Any, TypeVar

from flask import Flask, current_app, request
from flask.json.provider import DefaultJSONProvider
from pydantic import BaseModel, TypeAdapter, ValidationError
from werkzeug.datastructures import FileStorage

from ciclo import CicloAsync

M = TypeVar("M", bound=BaseModel)


class ErroreApi(Exception):
    """Errore restituito al client come `{"detail": ...}` con il codice indicato."""

    def __init__(self, stato: int, detail: Any = None, headers: dict[str, str] | None = None):
        super().__init__(detail)
        self.stato = int(stato)
        self.detail = detail if detail is not None else HTTPStatus(self.stato).phrase
        self.headers = headers or {}


class JsonProvider(DefaultJSONProvider):
    """Date in formato ISO (Flask userebbe il formato delle intestazioni HTTP)."""

    sort_keys = False
    ensure_ascii = False

    @staticmethod
    def default(o: Any) -> Any:
        if isinstance(o, date):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


class AttiFlask(Flask):
    """Flask che esegue le viste `async def` sull'event loop persistente del processo."""

    json_provider_class = JsonProvider

    def __init__(self, *args, ciclo: CicloAsync | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo or CicloAsync()

    def ensure_sync(self, func):
        if not inspect.iscoroutinefunction(func):
            return func

        @wraps(func)
        def sincrona(*args, **kwargs):
            return self.ciclo.esegui(func(*args, **kwargs))

        return sincrona


def _valida(modello: type[M], dati: Any) -> M:
    try:
        return modello.model_validate(dati)
    except ValidationError as e:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            e.errors(include_url=False, include_context=False, include_input=False),
        ) from e


def corpo(modello: type[M]) -> M:
    """Corpo JSON della richiesta validato con il modello."""
    dati = request.get_json(silent=True)
    if dati is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Corpo JSON mancante o non valido")
    return _valida(modello, dati)


def parametri(modello: type[M]) -> M:
    """Parametri della query string validati con il modello."""
    return _valida(modello, request.args.to_dict())


def modulo(modello: type[M]) -> M:
    """Campi di un form multipart validati con il modello."""
    return _valida(modello, request.form.to_dict())


def file_caricato(campo: str = "file") -> FileStorage:
    file = request.files.get(campo)
    if file is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"File mancante nel campo '{campo}'")
    return file


def out(schema: type[BaseModel], oggetto: Any) -> Any:
    """Serializza un oggetto (o una lista) ORM con lo schema di uscita."""
    if isinstance(oggetto, list | tuple):
        adattatore = TypeAdapter(list[schema])
        return adattatore.dump_python(adattatore.validate_python(oggetto), mode="json")
    return schema.model_validate(oggetto).model_dump(mode="json")


def nessun_contenuto() -> tuple[str, int]:
    return "", HTTPStatus.NO_CONTENT


def allegato(contenuto: bytes | str, mime: str, nome: str, in_linea: bool = False):
    """File da scaricare, o da mostrare nel browser con `in_linea` (es. PDF in un riquadro)."""
    disposizione = "inline" if in_linea else "attachment"
    return current_app.response_class(
        contenuto,
        content_type=mime,
        headers={"Content-Disposition": f'{disposizione}; filename="{nome}"'},
    )
