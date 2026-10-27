"""Amministrazione dell'installazione: enti, domini, moduli abilitati, primo amministratore.

Riservata all'amministratore dell'installazione (utente locale senza ente, creato con
deploy/enti.py). Ogni ente si raggiunge dai suoi domini (es. attipa.provincia.lucca.it):
per un nuovo dominio servono anche il record DNS, l'host nell'Ingress e il certificato.
"""

import logging
import re
from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from auth import password as pw
from deps import audit, db, installazione, utente
from web import ErroreApi, corpo
from common.models import Ente, EnteDominio, Modulo, OrigineUtente, Ruolo, User

log = logging.getLogger("atti_api.enti")

bp = Blueprint("enti", __name__, url_prefix="/api/v1/enti")

_DOMINIO = re.compile(r"^(?=.{3,255}$)[a-z0-9-]+(\.[a-z0-9-]+)+$")


def _domini(v: list[str]) -> list[str]:
    puliti = [d.strip().lower() for d in v if d.strip()]
    errati = [d for d in puliti if not _DOMINIO.match(d)]
    if errati:
        raise ValueError(f"Domini non validi: {', '.join(errati)}")
    return list(dict.fromkeys(puliti))


def _moduli(v: list[str]) -> list[str]:
    sconosciuti = set(v) - set(Modulo.TUTTI)
    if sconosciuti:
        raise ValueError(f"Moduli sconosciuti: {', '.join(sorted(sconosciuti))}")
    return [m for m in Modulo.TUTTI if m in v]


class EnteIn(BaseModel):
    nome: str = Field(min_length=2, max_length=255)
    domini: list[str] = []
    moduli: list[str] = []
    attivo: bool = True

    @field_validator("domini")
    @classmethod
    def _controlla_domini(cls, v: list[str]) -> list[str]:
        return _domini(v)

    @field_validator("moduli")
    @classmethod
    def _controlla_moduli(cls, v: list[str]) -> list[str]:
        return _moduli(v)


class EnteNuovoIn(EnteIn):
    # usato anche nelle URN delle norme manuali: lettere minuscole e cifre
    codice: str = Field(pattern=r"^[a-z][a-z0-9]{1,49}$")


class AmministratoreIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._@-]{2,100}$")
    nome_completo: str | None = Field(default=None, max_length=255)
    password: str


async def _out(sessione, e: Ente) -> dict:
    domini = (await sessione.scalars(select(EnteDominio.dominio).where(EnteDominio.ente_id == e.id))).all()
    utenti = (await sessione.scalars(select(User).where(User.ente_id == e.id))).all()
    return {
        "id": e.id,
        "codice": e.codice,
        "nome": e.nome,
        "attivo": e.attivo,
        "moduli": e.moduli_json or [],
        "domini": sorted(domini),
        "accesso_locale": e.accesso_locale,
        "accesso_ldap": bool(e.ldap_json),
        "utenti": len(utenti),
        "amministratori": sorted(u.username for u in utenti if u.ha_ruolo(Ruolo.ADMIN)),
    }


@bp.get("")
@installazione
async def elenco():
    sessione = db()
    enti = (await sessione.scalars(select(Ente).order_by(Ente.nome))).all()
    return {"enti": [await _out(sessione, e) for e in enti], "moduli": list(Modulo.TUTTI)}


async def _imposta_domini(sessione, e: Ente, domini: list[str]) -> None:
    for d in domini:
        esistente = await sessione.get(EnteDominio, d)
        if esistente is not None and esistente.ente_id != e.id:
            raise ErroreApi(HTTPStatus.CONFLICT, f"Il dominio {d} è già di un altro ente")
    for vecchio in (await sessione.scalars(select(EnteDominio).where(EnteDominio.ente_id == e.id))).all():
        if vecchio.dominio not in domini:
            await sessione.delete(vecchio)
    await sessione.flush()
    for d in domini:
        if await sessione.get(EnteDominio, d) is None:
            sessione.add(EnteDominio(dominio=d, ente_id=e.id))


@bp.post("")
@installazione
async def crea():
    dati = corpo(EnteNuovoIn)
    sessione = db()
    if await sessione.scalar(select(Ente).where(Ente.codice == dati.codice)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Codice già usato")
    e = Ente(codice=dati.codice, nome=dati.nome, moduli_json=dati.moduli, attivo=dati.attivo, dati_json={})
    sessione.add(e)
    await sessione.flush()
    await _imposta_domini(sessione, e, dati.domini)
    audit(sessione, utente(), "ente", e.id, "CREATO", {"codice": e.codice, "domini": dati.domini})
    await sessione.commit()
    return await _out(sessione, e), HTTPStatus.CREATED


@bp.put("/<ente_id>")
@installazione
async def aggiorna(ente_id: str):
    dati = corpo(EnteIn)
    sessione = db()
    e = await sessione.get(Ente, ente_id)
    if e is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Ente non trovato")
    e.nome = dati.nome
    e.moduli_json = dati.moduli
    e.attivo = dati.attivo
    await _imposta_domini(sessione, e, dati.domini)
    audit(
        sessione, utente(), "ente", e.id, "AGGIORNATO",
        {"domini": dati.domini, "moduli": dati.moduli, "attivo": dati.attivo},
    )  # fmt: skip
    await sessione.commit()
    return await _out(sessione, e)


@bp.post("/<ente_id>/amministratori")
@installazione
async def crea_amministratore(ente_id: str):
    """Primo amministratore locale dell'ente: poi configura da sé Active Directory e utenti."""
    dati = corpo(AmministratoreIn)
    if errore := pw.controlla_nuova(dati.password):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, errore)
    sessione = db()
    e = await sessione.get(Ente, ente_id)
    if e is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Ente non trovato")
    username = dati.username.lower()
    if await sessione.scalar(select(User).where(User.ente_id == e.id, User.username == username)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Nome utente già usato nell'ente")
    e.accesso_locale = True
    u = User(
        ente_id=e.id, username=username, origine=OrigineUtente.LOCALE,
        password_hash=pw.calcola(dati.password), nome_completo=dati.nome_completo,
        ruoli=[Ruolo.ADMIN],
    )  # fmt: skip
    sessione.add(u)
    await sessione.flush()
    audit(sessione, utente(), "utente", u.id, "CREATO", {"ente": e.codice, "ruoli": u.ruoli})
    await sessione.commit()
    return await _out(sessione, e), HTTPStatus.CREATED
