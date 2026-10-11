"""Modulo Controllo: sessioni di controllo successivo, atti sorteggiati, revisione, report."""

import csv
import io
import random
import secrets
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from atti_api.deps import ControlloreDep, DbDep, SettingsDep, audit, get_documenti
from atti_api.documenti import DocumentiClient, DocumentiError
from atti_api.routers.verifiche import accoda, checklist_per_tipologia
from atti_api.schemas import Schema
from atti_common.models import (
    AttoControllato,
    Ruolo,
    SessioneControllo,
    StatoVerifica,
    TipologiaAtto,
    User,
    Verifica,
)
from atti_common.odt import estrai_testo
from atti_common.testo import TestoNonEstraibile, estrai, mime_da_nome

router = APIRouter(prefix="/api/v1/controllo", tags=["controllo"])


# --- Sessioni ------------------------------------------------------------------------


class SessioneIn(BaseModel):
    titolo: str = Field(min_length=3, max_length=255)
    periodo_da: date
    periodo_a: date

    @model_validator(mode="after")
    def _periodo(self):
        if self.periodo_a < self.periodo_da:
            raise ValueError("Il periodo è invertito")
        return self


class SessioneOut(Schema):
    id: str
    titolo: str
    periodo_da: date
    periodo_a: date
    stato: str
    criteri_sorteggio: dict | None
    created_at: datetime | None
    conteggio_stati: dict[str, int] = Field(default_factory=dict)


async def _sessione(db, sessione_id: str) -> SessioneControllo:
    s = await db.get(SessioneControllo, sessione_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sessione non trovata")
    return s


async def _conteggi(db, sessione_id: str) -> dict[str, int]:
    righe = await db.execute(
        select(AttoControllato.stato, func.count())
        .where(AttoControllato.sessione_id == sessione_id)
        .group_by(AttoControllato.stato)
    )
    return dict(righe.all())


async def _out(db, s: SessioneControllo) -> SessioneOut:
    out = SessioneOut.model_validate(s)
    out.conteggio_stati = await _conteggi(db, s.id)
    return out


@router.get("/sessioni", response_model=list[SessioneOut])
async def elenco_sessioni(db: DbDep, _: ControlloreDep):
    sessioni = (
        await db.scalars(select(SessioneControllo).order_by(SessioneControllo.periodo_da.desc()))
    ).all()
    return [await _out(db, s) for s in sessioni]


@router.post("/sessioni", response_model=SessioneOut, status_code=status.HTTP_201_CREATED)
async def crea_sessione(dati: SessioneIn, db: DbDep, user: ControlloreDep):
    s = SessioneControllo(**dati.model_dump(), creata_da=user.id)
    db.add(s)
    await db.flush()
    audit(db, user, "sessione", s.id, "CREATA")
    await db.commit()
    await db.refresh(s)
    return await _out(db, s)


@router.get("/sessioni/{sessione_id}", response_model=SessioneOut)
async def dettaglio_sessione(sessione_id: str, db: DbDep, _: ControlloreDep):
    return await _out(db, await _sessione(db, sessione_id))


@router.post("/sessioni/{sessione_id}/chiudi", response_model=SessioneOut)
async def chiudi_sessione(sessione_id: str, db: DbDep, user: ControlloreDep):
    s = await _sessione(db, sessione_id)
    aperti = {k: v for k, v in (await _conteggi(db, s.id)).items() if k != "CHIUSO"}
    if aperti:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Ci sono ancora atti non chiusi: {sum(aperti.values())}"
        )
    s.stato = "CHIUSA"
    audit(db, user, "sessione", s.id, "CHIUSA")
    await db.commit()
    return await _out(db, s)


class SorteggioIn(BaseModel):
    elenco: list[str] = Field(min_length=1, description="Numeri di registro degli atti del periodo")
    percentuale: float = Field(gt=0, le=100)
    minimo: int = Field(default=1, ge=1)
    seme: int | None = None  # se assente viene generato e registrato


@router.post("/sessioni/{sessione_id}/sorteggio")
async def sorteggio(sessione_id: str, dati: SorteggioIn, db: DbDep, user: ControlloreDep) -> dict:
    """Estrazione casuale riproducibile: il seme è registrato per la trasparenza del controllo."""
    s = await _sessione(db, sessione_id)
    if s.criteri_sorteggio:
        raise HTTPException(status.HTTP_409_CONFLICT, "Sorteggio già effettuato per la sessione")
    elenco = sorted({x.strip() for x in dati.elenco if x.strip()})
    quanti = min(len(elenco), max(dati.minimo, round(len(elenco) * dati.percentuale / 100)))
    seme = dati.seme if dati.seme is not None else secrets.randbits(32)
    estratti = sorted(random.Random(seme).sample(elenco, quanti))
    s.criteri_sorteggio = {
        "atti_nel_periodo": len(elenco),
        "percentuale": dati.percentuale,
        "minimo": dati.minimo,
        "seme": seme,
        "estratti": estratti,
        "eseguito_il": datetime.now().isoformat(timespec="seconds"),
        "eseguito_da": user.username,
    }
    audit(db, user, "sessione", s.id, "SORTEGGIO", {"seme": seme, "estratti": len(estratti)})
    await db.commit()
    return s.criteri_sorteggio


# --- Atti ----------------------------------------------------------------------------


class AttoOut(Schema):
    id: str
    sessione_id: str
    numero_registro: str | None
    data_adozione: date
    settore: str | None
    tipologia_atto: str | None
    oggetto: str | None
    file_nome: str
    assegnato_a: str | None
    stato: str
    created_at: datetime | None


@router.get("/sessioni/{sessione_id}/atti", response_model=list[AttoOut])
async def elenco_atti(sessione_id: str, db: DbDep, user: ControlloreDep, solo_miei: bool = False):
    query = (
        select(AttoControllato)
        .where(AttoControllato.sessione_id == sessione_id)
        .order_by(AttoControllato.data_adozione, AttoControllato.numero_registro)
    )
    if solo_miei:
        query = query.where(AttoControllato.assegnato_a == user.id)
    return (await db.scalars(query)).all()


async def _testo_file(contenuto: bytes, nome: str, mime: str, documenti: DocumentiClient) -> str:
    testo = estrai(contenuto, mime)
    if testo is None:  # DOC/DOCX: conversione in ODT con LibreOffice
        try:
            odt = await documenti.converti(contenuto, nome, "odt")
        except DocumentiError as e:
            raise TestoNonEstraibile(str(e)) from e
        testo = estrai_testo(odt)
    return testo


@router.post(
    "/sessioni/{sessione_id}/atti", response_model=AttoOut, status_code=status.HTTP_201_CREATED
)
async def carica_atto(
    sessione_id: str,
    db: DbDep,
    user: ControlloreDep,
    settings: SettingsDep,
    documenti: Annotated[DocumentiClient, Depends(get_documenti)],
    file: Annotated[UploadFile, File(description="Atto in PDF, ODT, DOCX o DOC")],
    data_adozione: Annotated[date, Form()],
    numero_registro: Annotated[str | None, Form()] = None,
    settore: Annotated[str | None, Form()] = None,
    tipologia_atto: Annotated[str | None, Form()] = None,
    oggetto: Annotated[str | None, Form()] = None,
    analizza: Annotated[bool, Form()] = True,
):
    """Carica un atto sorteggiato e, di default, ne avvia l'analisi automatica."""
    s = await _sessione(db, sessione_id)
    if s.stato != "APERTA":
        raise HTTPException(status.HTTP_409_CONFLICT, "La sessione è chiusa")
    if tipologia_atto and await db.get(TipologiaAtto, tipologia_atto) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")
    nome = file.filename or "atto"
    mime = mime_da_nome(nome)
    if mime is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Formato non supportato: PDF, ODT, DOCX o DOC"
        )
    limite = settings.upload_max_mb * 1024 * 1024
    contenuto = await file.read(limite + 1)
    if len(contenuto) > limite:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
    try:
        testo = await _testo_file(contenuto, nome, mime, documenti)
    except TestoNonEstraibile as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    atto = AttoControllato(
        sessione_id=s.id,
        numero_registro=numero_registro,
        data_adozione=data_adozione,
        settore=settore,
        tipologia_atto=tipologia_atto,
        oggetto=oggetto,
        file_nome=nome,
        file_mime=mime,
        file_contenuto=contenuto,
        contenuto_testo=testo,
    )
    db.add(atto)
    await db.flush()
    audit(db, user, "atto_controllato", atto.id, "CARICATO", {"sessione": s.id})
    if analizza:
        checklist_id = await checklist_per_tipologia(db, tipologia_atto)
        await accoda(db, user, data_adozione, checklist_id, atto_controllato_id=atto.id)
        atto.stato = "IN_ANALISI"
    await db.commit()
    await db.refresh(atto)
    return atto


async def _atto(db, atto_id: str) -> AttoControllato:
    atto = await db.get(AttoControllato, atto_id)
    if atto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Atto non trovato")
    return atto


@router.get("/atti/{atto_id}", response_model=AttoOut)
async def dettaglio_atto(atto_id: str, db: DbDep, _: ControlloreDep):
    return await _atto(db, atto_id)


@router.get("/atti/{atto_id}/testo")
async def testo_atto(atto_id: str, db: DbDep, _: ControlloreDep) -> dict:
    atto = await db.scalar(
        select(AttoControllato)
        .where(AttoControllato.id == atto_id)
        .options(undefer(AttoControllato.contenuto_testo))
    )
    if atto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Atto non trovato")
    return {"testo": atto.contenuto_testo or ""}


@router.get("/atti/{atto_id}/file")
async def file_atto(atto_id: str, db: DbDep, _: ControlloreDep) -> Response:
    atto = await db.scalar(
        select(AttoControllato)
        .where(AttoControllato.id == atto_id)
        .options(undefer(AttoControllato.file_contenuto))
    )
    if atto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Atto non trovato")
    return Response(
        atto.file_contenuto,
        media_type=atto.file_mime,
        headers={"Content-Disposition": f'attachment; filename="{atto.file_nome}"'},
    )


class AssegnaIn(BaseModel):
    user_id: str | None


@router.put("/atti/{atto_id}/assegna", response_model=AttoOut)
async def assegna(atto_id: str, dati: AssegnaIn, db: DbDep, user: ControlloreDep):
    atto = await _atto(db, atto_id)
    if dati.user_id:
        controllore = await db.get(User, dati.user_id)
        if controllore is None or not controllore.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Utente non controllore")
    atto.assegnato_a = dati.user_id
    audit(db, user, "atto_controllato", atto.id, "ASSEGNATO", {"a": dati.user_id})
    await db.commit()
    await db.refresh(atto)
    return atto


@router.delete("/atti/{atto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def elimina_atto(atto_id: str, db: DbDep, user: ControlloreDep) -> None:
    atto = await _atto(db, atto_id)
    if atto.stato == "CHIUSO":
        raise HTTPException(status.HTTP_409_CONFLICT, "Un atto con controllo chiuso non si elimina")
    await db.delete(atto)
    audit(db, user, "atto_controllato", atto_id, "ELIMINATO")
    await db.commit()


# --- Report --------------------------------------------------------------------------


async def _dati_report(db, sessione_id: str) -> list[dict]:
    """Ultima verifica di ogni atto, con esito finale (o automatico se non revisionato)."""
    atti = (
        await db.scalars(select(AttoControllato).where(AttoControllato.sessione_id == sessione_id))
    ).all()
    righe = []
    for atto in atti:
        verifica = await db.scalar(
            select(Verifica)
            .where(
                Verifica.atto_controllato_id == atto.id,
                Verifica.stato == StatoVerifica.COMPLETATA,
            )
            .order_by(Verifica.created_at.desc())
            .limit(1)
        )
        esiti = (verifica.esito_finale or verifica.esito_automatico or []) if verifica else []
        riferimenti = (verifica.esito_riferimenti or {}).get("riferimenti", []) if verifica else []
        righe.append(
            {
                "atto": atto,
                "revisionato": bool(verifica and verifica.esito_finale),
                "esiti": esiti,
                "riferimenti_problematici": sum(1 for r in riferimenti if r["esito"] != "VIGENTE"),
                "motivazione": verifica.motivazione if verifica else None,
            }
        )
    return righe


@router.get("/sessioni/{sessione_id}/report")
async def report(sessione_id: str, db: DbDep, _: ControlloreDep) -> dict:
    s = await _sessione(db, sessione_id)
    righe = await _dati_report(db, sessione_id)
    per_criterio: dict[str, dict[str, int]] = {}
    per_settore: dict[str, dict[str, int]] = {}
    for r in righe:
        settore = r["atto"].settore or "Non indicato"
        non_conforme = any(e.get("esito") == "NON_CONFORME" for e in r["esiti"])
        voce = per_settore.setdefault(settore, {"atti": 0, "con_rilievi": 0})
        voce["atti"] += 1
        voce["con_rilievi"] += int(non_conforme or r["riferimenti_problematici"] > 0)
        for e in r["esiti"]:
            conteggio = per_criterio.setdefault(e.get("titolo", "?"), {})
            conteggio[e.get("esito", "?")] = conteggio.get(e.get("esito", "?"), 0) + 1
    return {
        "sessione": {"id": s.id, "titolo": s.titolo, "periodo_da": s.periodo_da,
                     "periodo_a": s.periodo_a, "stato": s.stato},
        "atti_totali": len(righe),
        "atti_revisionati": sum(r["revisionato"] for r in righe),
        "per_settore": per_settore,
        "per_criterio": per_criterio,
        "atti": [
            {
                "id": r["atto"].id,
                "numero_registro": r["atto"].numero_registro,
                "data_adozione": r["atto"].data_adozione,
                "settore": r["atto"].settore,
                "oggetto": r["atto"].oggetto,
                "stato": r["atto"].stato,
                "revisionato": r["revisionato"],
                "non_conformita": [e.get("titolo") for e in r["esiti"]
                                   if e.get("esito") == "NON_CONFORME"],
                "riferimenti_problematici": r["riferimenti_problematici"],
                "motivazione": r["motivazione"],
            }
            for r in righe
        ],
    }  # fmt: skip


@router.get("/sessioni/{sessione_id}/report.csv")
async def report_csv(sessione_id: str, db: DbDep, _: ControlloreDep) -> Response:
    await _sessione(db, sessione_id)
    righe = await _dati_report(db, sessione_id)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Numero", "Data adozione", "Settore", "Oggetto", "Stato", "Revisionato",
                "Non conformità", "Riferimenti problematici", "Motivazione"])  # fmt: skip
    for r in righe:
        a = r["atto"]
        w.writerow([
            a.numero_registro or "", a.data_adozione.strftime("%d/%m/%Y"), a.settore or "",
            a.oggetto or "", a.stato, "sì" if r["revisionato"] else "no",
            " | ".join(e.get("titolo", "") for e in r["esiti"] if e.get("esito") == "NON_CONFORME"),
            r["riferimenti_problematici"], r["motivazione"] or "",
        ])  # fmt: skip
    return Response(
        "﻿" + out.getvalue(),  # BOM: Excel riconosce l'UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="report-{sessione_id[:8]}.csv"'},
    )


# --- Utenti --------------------------------------------------------------------------


class ControlloreOut(Schema):
    id: str
    username: str
    nome_completo: str | None
    ufficio: str | None


@router.get("/controllori", response_model=list[ControlloreOut])
async def controllori(db: DbDep, _: ControlloreDep):
    utenti = (await db.scalars(select(User).where(User.attivo.is_(True)))).all()
    return [u for u in utenti if u.ha_ruolo(Ruolo.CONTROLLORE, Ruolo.ADMIN)]
