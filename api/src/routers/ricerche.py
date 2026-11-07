"""Registro delle ricerche e feedback (common/registro_ricerche.py).

- Registrazione delle ricerche concluse e dei feedback degli utenti interni: chiunque sia
  autenticato, per gli ambiti dei moduli attivi. Quella dei cittadini è in routers/pubblico.py.
- Consultazione: chi ha il ruolo ANALISI_RICERCHE (o l'amministratore dell'ente). Le ricerche
  senza risposta sono raggruppate per chiave, i feedback sono elencati; ricerche e feedback si
  segnano gestiti con una nota; riepilogo per mese ed esportazione CSV.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import date, datetime, timedelta
from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from deps import autenticato, db, ente, ente_id, utente
from web import ErroreApi, allegato, corpo, parametri
from common import registro_ricerche as reg
from common.models import RicercaFeedback, RicercaRegistrata, Ruolo

bp = Blueprint("ricerche", __name__, url_prefix="/api/v1/ricerche")

autenticato_qualsiasi = autenticato(modulo=None)
analista = autenticato(Ruolo.ANALISI_RICERCHE, modulo=None)


# --- registrazione (comune a interne e pubbliche) -------------------------------------------


class RicercaIn(BaseModel):
    ambito: str = Field(max_length=50)
    testo: str = Field(min_length=1, max_length=300)
    risultati: int = Field(ge=0, le=10_000)
    esito: Literal["TROVATA", "NESSUN_RISULTATO", "RISULTATI_DEBOLI", "NON_APERTI"]
    posizione: int | None = Field(default=None, ge=1, le=10_000)
    semantica: bool = False


class FeedbackIn(BaseModel):
    ambito: str = Field(max_length=50)
    tipo: Literal["RICERCA", "SCHEDA", "ACCESSIBILITA"]
    ricerca_id: str | None = Field(default=None, max_length=36)  # RICERCA
    riferimento_id: str | None = Field(default=None, max_length=36)  # SCHEDA
    riferimento: str | None = Field(default=None, max_length=500)  # titolo della scheda
    utile: bool
    commento: str | None = Field(default=None, max_length=2000)
    # ACCESSIBILITA: email per la risposta (facoltativa, non oscurata: la lascia chi segnala)
    contatto: str | None = Field(default=None, max_length=255, pattern=r"^([^@\s]+@[^@\s]+\.[^@\s]+)?$")


async def registra_ricerca(ente_id_: str, ambiti: dict, pubblica: bool, dati: RicercaIn) -> dict:
    if dati.ambito not in ambiti:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Ambito di ricerca non valido")
    r = reg.nuova_ricerca(ente_id_, dati.ambito, pubblica, dati.testo, dati.risultati, dati.esito,
                          dati.posizione, dati.semantica)  # fmt: skip
    sessione = db()
    sessione.add(r)
    await sessione.commit()
    return {"id": r.id}


async def registra_feedback(ente_id_: str, ambiti: dict, pubblica: bool, dati: FeedbackIn) -> dict:
    if dati.ambito not in ambiti:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Ambito non valido")
    sessione = db()
    testo = None
    if dati.tipo == "RICERCA":
        r = await sessione.get(RicercaRegistrata, dati.ricerca_id) if dati.ricerca_id else None
        if r is None or r.ente_id != ente_id_ or r.pubblica != pubblica:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Ricerca non trovata")
        if await sessione.scalar(select(RicercaFeedback.id).where(RicercaFeedback.ricerca_id == r.id)):
            raise ErroreApi(HTTPStatus.CONFLICT, "Feedback già inviato")
        testo = r.testo
    elif dati.tipo == "SCHEDA" and not dati.riferimento_id:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Scheda non indicata")
    elif dati.tipo == "ACCESSIBILITA" and not (dati.commento or "").strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Descrivi il problema")
    commento = reg.oscura(dati.commento.strip()) if dati.commento and dati.commento.strip() else None
    f = RicercaFeedback(
        ente_id=ente_id_, ambito=dati.ambito, pubblica=pubblica, tipo=dati.tipo,
        ricerca_id=dati.ricerca_id if dati.tipo == "RICERCA" else None, testo=testo,
        riferimento_id=dati.riferimento_id if dati.tipo == "SCHEDA" else None,
        riferimento=dati.riferimento if dati.tipo != "RICERCA" else None,
        utile=dati.utile and dati.tipo != "ACCESSIBILITA", commento=commento,
        contatto=(dati.contatto or "").strip() or None if dati.tipo == "ACCESSIBILITA" else None,
    )  # fmt: skip
    sessione.add(f)
    await sessione.commit()
    return {"id": f.id}


@bp.post("/registro")
@autenticato_qualsiasi
async def registro():
    """Ricerca conclusa di un utente interno (senza il suo nome)."""
    return await registra_ricerca(ente_id(), reg.ambiti_disponibili(ente()), False, corpo(RicercaIn)), 201


@bp.post("/feedback")
@autenticato_qualsiasi
async def feedback():
    return await registra_feedback(ente_id(), reg.ambiti_disponibili(ente()), False, corpo(FeedbackIn)), 201


# --- consultazione --------------------------------------------------------------------------


class Filtri(BaseModel):
    da: date | None = None
    a: date | None = None
    ambito: str | None = Field(default=None, max_length=50)
    pubblica: bool | None = None  # None: tutte
    gestite: bool = False  # anche quelle già gestite


class FiltriFeedback(Filtri):
    utile: bool | None = None
    tipo: Literal["RICERCA", "SCHEDA", "ACCESSIBILITA"] | None = None


def _filtra(q, modello, f: Filtri):
    q = q.where(modello.ente_id == ente_id())
    if f.da:
        q = q.where(modello.created_at >= datetime.combine(f.da, datetime.min.time()))
    if f.a:
        q = q.where(modello.created_at < datetime.combine(f.a + timedelta(days=1), datetime.min.time()))
    if f.ambito:
        q = q.where(modello.ambito == f.ambito)
    if f.pubblica is not None:
        q = q.where(modello.pubblica == f.pubblica)
    return q


def _data(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


@bp.get("/ambiti")
@analista
async def ambiti():
    return [{"id": k, "descrizione": d} for k, d in reg.ambiti_disponibili(ente()).items()]


async def _senza_risposta(f: Filtri) -> list[dict]:
    """Ricerche senza risposta raggruppate per ambito e chiave, le più frequenti (non gestite)
    prima."""
    q = _filtra(select(RicercaRegistrata), RicercaRegistrata, f).where(RicercaRegistrata.esito.in_(reg.SENZA_RISPOSTA))
    gruppi: dict[tuple[str, str], list[RicercaRegistrata]] = {}
    for r in await db().scalars(q):
        gruppi.setdefault((r.ambito, r.chiave), []).append(r)
    risultato = []
    for (ambito, chiave), righe in gruppi.items():
        da_gestire = [r for r in righe if r.gestita_il is None]
        if not da_gestire and not f.gestite:
            continue
        testi = Counter(r.testo for r in righe)
        gestita = max((r for r in righe if r.gestita_il), key=lambda r: r.gestita_il, default=None)
        risultato.append({
            "ambito": ambito, "chiave": chiave, "testo": testi.most_common(1)[0][0],
            "varianti": [t for t, _ in testi.most_common(5)],
            "volte": len(righe), "da_gestire": len(da_gestire),
            "pubbliche": sum(r.pubblica for r in righe),
            "esiti": dict(Counter(r.esito for r in righe)),
            "ultima": _data(max(r.created_at for r in righe if r.created_at)),
            "nota": gestita.nota if gestita else None, "gestita_da": gestita.gestita_da if gestita else None,
            "gestita_il": _data(gestita.gestita_il) if gestita else None,
        })  # fmt: skip
    risultato.sort(key=lambda g: (-g["da_gestire"], -g["volte"], g["testo"]))
    return risultato


@bp.get("/senza-risposta")
@analista
async def senza_risposta():
    return await _senza_risposta(parametri(Filtri))


class GestioneIn(BaseModel):
    nota: str = Field(default="", max_length=2000)


class GestioneGruppoIn(GestioneIn):
    ambito: str = Field(max_length=50)
    chiave: str = Field(max_length=300)


def _gestore() -> str:
    u = utente()
    return u.nome_completo or u.username


@bp.put("/senza-risposta/gestione")
@analista
async def gestisci_gruppo():
    """Segna gestite le ricerche del gruppo ancora da gestire, con una nota (es. "aggiunta la
    parola morosità alla descrizione"). Le ricerche successive ricompaiono da gestire."""
    dati = corpo(GestioneGruppoIn)
    sessione = db()
    esito = await sessione.execute(
        update(RicercaRegistrata)
        .where(RicercaRegistrata.ente_id == ente_id(), RicercaRegistrata.ambito == dati.ambito,
               RicercaRegistrata.chiave == dati.chiave, RicercaRegistrata.esito.in_(reg.SENZA_RISPOSTA),
               RicercaRegistrata.gestita_il.is_(None))  # fmt: skip
        .values(gestita_il=datetime.now(), gestita_da=_gestore(), nota=dati.nota.strip() or None)
    )
    await sessione.commit()
    return {"gestite": esito.rowcount or 0}


def _feedback(x: RicercaFeedback) -> dict:
    return {
        "id": x.id, "ambito": x.ambito, "pubblica": x.pubblica, "tipo": x.tipo, "testo": x.testo,
        "riferimento_id": x.riferimento_id, "riferimento": x.riferimento, "utile": x.utile,
        "commento": x.commento, "contatto": x.contatto, "quando": _data(x.created_at), "gestito_il": _data(x.gestito_il),
        "gestito_da": x.gestito_da, "nota": x.nota,
    }  # fmt: skip


async def _elenco_feedback(f: FiltriFeedback) -> list[RicercaFeedback]:
    q = _filtra(select(RicercaFeedback), RicercaFeedback, f)
    if f.utile is not None:
        q = q.where(RicercaFeedback.utile == f.utile)
    if f.tipo:
        q = q.where(RicercaFeedback.tipo == f.tipo)
    if not f.gestite:
        q = q.where(RicercaFeedback.gestito_il.is_(None))
    return list(await db().scalars(q.order_by(RicercaFeedback.created_at.desc()).limit(2000)))


@bp.get("/feedback")
@analista
async def elenco_feedback():
    return [_feedback(x) for x in await _elenco_feedback(parametri(FiltriFeedback))]


@bp.put("/feedback/<feedback_id>/gestione")
@analista
async def gestisci_feedback(feedback_id: str):
    dati = corpo(GestioneIn)
    sessione = db()
    x = await sessione.get(RicercaFeedback, feedback_id)
    if x is None or x.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Feedback non trovato")
    x.gestito_il, x.gestito_da, x.nota = datetime.now(), _gestore(), dati.nota.strip() or None
    await sessione.commit()
    return _feedback(x)


@bp.get("/riepilogo")
@analista
async def riepilogo():
    """Per mese: ricerche, trovate, senza risposta, feedback utili e non utili; e le schede
    con più feedback negativi."""
    f = parametri(Filtri)
    mesi: dict[str, dict] = {}

    def mese(d: datetime) -> dict:
        chiave = d.strftime("%Y-%m")
        return mesi.setdefault(chiave, {"mese": chiave, "ricerche": 0, "trovate": 0, "senza_risposta": 0,
                                        "utili": 0, "non_utili": 0})  # fmt: skip

    for r in await db().scalars(_filtra(select(RicercaRegistrata), RicercaRegistrata, f)):
        m = mese(r.created_at)
        m["ricerche"] += 1
        m["trovate" if r.esito == reg.TROVATA else "senza_risposta"] += 1
    schede: Counter = Counter()
    for x in await db().scalars(_filtra(select(RicercaFeedback), RicercaFeedback, f)):
        mese(x.created_at)["utili" if x.utile else "non_utili"] += 1
        if x.tipo == "SCHEDA" and not x.utile:
            schede[x.riferimento or x.riferimento_id] += 1
    return {
        "mesi": [mesi[k] for k in sorted(mesi)],
        "schede_non_utili": [{"riferimento": k, "volte": v} for k, v in schede.most_common(20)],
    }


def _csv(intestazioni: list[str], righe: list[list]) -> bytes:
    uscita = io.StringIO()
    w = csv.writer(uscita, delimiter=";")
    w.writerow(intestazioni)
    w.writerows(righe)
    return ("﻿" + uscita.getvalue()).encode()  # BOM: Excel riconosce l'UTF-8


@bp.get("/esporta/senza-risposta")
@analista
async def esporta_senza_risposta():
    gruppi = await _senza_risposta(parametri(Filtri))
    righe = [[g["ambito"], g["testo"], " | ".join(g["varianti"]), g["volte"], g["da_gestire"], g["pubbliche"],
              g["ultima"], g["nota"] or ""] for g in gruppi]  # fmt: skip
    intestazioni = ["Ambito", "Domanda", "Varianti", "Volte", "Da gestire", "Dai cittadini", "Ultima", "Nota"]
    return allegato(_csv(intestazioni, righe), "text/csv; charset=utf-8", "ricerche-senza-risposta.csv")


@bp.get("/esporta/feedback")
@analista
async def esporta_feedback():
    elenco = await _elenco_feedback(parametri(FiltriFeedback))
    righe = [[x.ambito, "cittadino" if x.pubblica else "interno", x.tipo, x.testo or x.riferimento or "",
              "sì" if x.utile else "no", x.commento or "", x.contatto or "", _data(x.created_at), x.nota or ""]
             for x in elenco]  # fmt: skip
    intestazioni = ["Ambito", "Da", "Su", "Ricerca o pagina", "Utile", "Commento", "Contatto", "Quando", "Nota"]
    return allegato(_csv(intestazioni, righe), "text/csv; charset=utf-8", "feedback.csv")
