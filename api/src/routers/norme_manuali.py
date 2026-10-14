"""Norme inserite manualmente: regolamenti interni, leggi regionali, altre fonti.

Una norma manuale ha uno o più testi, ciascuno vigente da una data. Il file caricato va
nell'archivio e il converter lo trasforma in Markdown (coda "conversione"); il testo
diviso in articoli si rivede, si corregge se serve e si conferma: da quel momento la
verifica degli atti lo usa come le norme di Normattiva.

La norma è identificata dalla URN "urn:nir:locale:<tipo>:<data>;<numero>", passata nella
query string (`?urn=...`) perché contiene ":" e ";".
"""

import asyncio
import logging
from datetime import date, datetime
from http import HTTPStatus

from flask import Blueprint
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import undefer

from deps import archivia_caricato, audit, autenticato, impostazioni, notifica, risorse, utente
from deps import db as sessione_db
from documenti import DocumentiError
from schemas import Schema
from web import ErroreApi, allegato, corpo, file_caricato, modulo, nessun_contenuto, parametri
from common import archivio, coda
from common.models import (
    FonteNorma,
    NormaArticoloVersione,
    NormaAtto,
    NormaTestoCaricato,
    Riferimento,
    Ruolo,
    StatoTestoNorma,
)
from common.normattiva.urn import TIPI_MANUALI, Urn, e_manuale
from common.norme_manuali import ricostruisci_versioni, scomponi

log = logging.getLogger("atti_api.norme_manuali")

bp = Blueprint("norme_manuali", __name__, url_prefix="/api/v1/norme-manuali")

# consultazione per tutti; inserimento e modifica per controllori e amministratori, perché
# le norme manuali entrano nella verifica di tutti gli atti
gestore = autenticato(Ruolo.CONTROLLORE)


def _denominazioni(citazione: str, valori: list[str]) -> list[str]:
    """Denominazioni senza duplicati; la citazione è sempre tra queste."""
    risultato: list[str] = []
    for valore in [citazione, *valori]:
        valore = " ".join(valore.split())
        if valore and valore.lower() not in (v.lower() for v in risultato):
            risultato.append(valore)
    return risultato


class TestoOut(Schema):
    id: str
    vigenza_inizio: date
    file_nome: str
    file_dimensione: int
    stato: str
    errore: str | None
    created_at: datetime | None
    confermato_il: datetime | None


class NormaManualeOut(BaseModel):
    urn: str
    tipo: str
    tipo_descrizione: str
    data_provvedimento: date
    numero: str
    citazione: str
    titolo: str | None
    denominazioni: list[str]
    abrogata_dal: date | None
    testi: list[TestoOut]


class TestoDettaglioOut(TestoOut):
    urn_atto: str
    testo: str | None
    anteprima: dict | None  # articoli riconosciuti nel testo (vedi common/norme_manuali.py)


class UrnQuery(BaseModel):
    urn: str


class NormaManualeIn(BaseModel):
    tipo: str
    data: date  # data di approvazione o di emanazione
    numero: str = Field(min_length=1, max_length=20)
    citazione: str = Field(min_length=3, max_length=255)  # es. "Regolamento di contabilità"
    titolo: str | None = None
    denominazioni: str = ""  # una per riga
    vigenza_inizio: date  # il testo caricato vale da questa data

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, valore: str) -> str:
        if valore not in TIPI_MANUALI:
            raise ValueError(f"Tipo non valido: {', '.join(TIPI_MANUALI)}")
        return valore


class NormaManualeModifica(BaseModel):
    citazione: str = Field(min_length=3, max_length=255)
    titolo: str | None = None
    denominazioni: list[str] = []
    abrogata_dal: date | None = None


class NuovoTestoIn(BaseModel):
    vigenza_inizio: date


class TestoModifica(BaseModel):
    testo: str
    vigenza_inizio: date | None = None


async def _testi(db, urn: str) -> list[NormaTestoCaricato]:
    return list(
        (
            await db.scalars(
                select(NormaTestoCaricato)
                .where(NormaTestoCaricato.urn_atto == urn)
                .order_by(NormaTestoCaricato.vigenza_inizio.desc(), NormaTestoCaricato.created_at)
            )
        ).all()
    )


async def _out(db, norma: NormaAtto) -> dict:
    u = Urn.parse(norma.urn)
    return NormaManualeOut(
        urn=norma.urn,
        tipo=u.denominazione,
        tipo_descrizione=TIPI_MANUALI.get(u.denominazione, u.denominazione),
        data_provvedimento=norma.data_provvedimento,
        numero=norma.numero,
        citazione=norma.citazione,
        titolo=norma.titolo,
        denominazioni=norma.denominazioni_json or [],
        abrogata_dal=norma.abrogata_dal,
        testi=[TestoOut.model_validate(t) for t in await _testi(db, norma.urn)],
    ).model_dump(mode="json")


async def _norma(db, urn: str) -> NormaAtto:
    norma = await db.get(NormaAtto, urn) if e_manuale(urn) else None
    if norma is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Norma non trovata")
    return norma


async def _testo(db, testo_id: str, con_testo: bool = False) -> NormaTestoCaricato:
    query = select(NormaTestoCaricato).where(NormaTestoCaricato.id == testo_id)
    if con_testo:
        query = query.options(undefer(NormaTestoCaricato.testo))
    testo = await db.scalar(query)
    if testo is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Testo non trovato")
    return testo


def _dettaglio(testo: NormaTestoCaricato) -> dict:
    anteprima = scomponi(testo.testo).to_dict() if testo.testo else None
    return TestoDettaglioOut(
        **TestoOut.model_validate(testo).model_dump(),
        urn_atto=testo.urn_atto,
        testo=testo.testo,
        anteprima=anteprima,
    ).model_dump(mode="json")


async def _archivia_testo(db, urn: str, vigenza_inizio: date) -> NormaTestoCaricato:
    """Archivia il file caricato e crea il testo da convertire (commit a carico del chiamante)."""
    nome, mime, archiviato = await archivia_caricato(file_caricato())
    testo = NormaTestoCaricato(
        urn_atto=urn,
        vigenza_inizio=vigenza_inizio,
        file_nome=nome,
        file_mime=mime,
        file_percorso=archiviato.percorso,
        file_sha256=archiviato.sha256,
        file_dimensione=archiviato.dimensione,
        stato=StatoTestoNorma.IN_CONVERSIONE,
        caricato_da=utente().id,
    )
    db.add(testo)
    return testo


async def _converti(testo: NormaTestoCaricato) -> None:
    await notifica(
        coda.CONVERSIONE,
        {"testo_norma_id": testo.id, "percorso": testo.file_percorso, "nome_file": testo.file_nome},
    )


# --- Norme -------------------------------------------------------------------------------


@bp.get("/tipi")
@autenticato()
async def tipi():
    return [{"codice": k, "descrizione": v} for k, v in TIPI_MANUALI.items()]


@bp.get("")
@autenticato()
async def elenco():
    db = sessione_db()
    norme = (
        await db.scalars(
            select(NormaAtto)
            .where(NormaAtto.fonte == FonteNorma.MANUALE)
            .order_by(NormaAtto.citazione)
        )
    ).all()
    return [await _out(db, n) for n in norme]


@bp.get("/norma")
@autenticato()
async def dettaglio():
    db = sessione_db()
    return await _out(db, await _norma(db, parametri(UrnQuery).urn))


@bp.post("")
@gestore
async def crea():
    """Nuova norma con il suo primo testo (file PDF, ODT, DOCX o DOC)."""
    dati = modulo(NormaManualeIn)
    db, user = sessione_db(), utente()
    try:
        urn = str(Urn.manuale(dati.tipo, dati.data, dati.numero))
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    if await db.get(NormaAtto, urn) is not None:
        raise ErroreApi(
            HTTPStatus.CONFLICT,
            "La norma è già presente: per un testo modificato aggiungi un nuovo testo",
        )
    norma = NormaAtto(
        urn=urn,
        fonte=FonteNorma.MANUALE,
        denominazione=TIPI_MANUALI[dati.tipo].upper()[:100],
        data_provvedimento=dati.data,
        numero=dati.numero.strip(),
        titolo=(dati.titolo or "").strip() or None,
        citazione=dati.citazione.strip(),
        denominazioni_json=_denominazioni(dati.citazione, dati.denominazioni.splitlines()),
    )
    db.add(norma)
    await db.flush()
    testo = await _archivia_testo(db, urn, dati.vigenza_inizio)
    try:
        await db.flush()
        audit(db, user, "norma", urn, "AGGIUNTA_MANUALE", {"file": testo.file_nome})
        await db.commit()
    except Exception:
        archivio.elimina(impostazioni().archivio_dir, testo.file_percorso)
        raise
    await _converti(testo)
    return await _out(db, norma), HTTPStatus.CREATED


@bp.put("/norma")
@gestore
async def modifica():
    dati = corpo(NormaManualeModifica)
    db = sessione_db()
    norma = await _norma(db, parametri(UrnQuery).urn)
    norma.citazione = dati.citazione.strip()
    norma.titolo = (dati.titolo or "").strip() or None
    norma.denominazioni_json = _denominazioni(dati.citazione, dati.denominazioni)
    norma.abrogata_dal = dati.abrogata_dal
    audit(db, utente(), "norma", norma.urn, "MODIFICATA", dati.model_dump(mode="json"))
    await db.commit()
    return await _out(db, norma)


@bp.delete("/norma")
@gestore
async def elimina():
    db = sessione_db()
    norma = await _norma(db, parametri(UrnQuery).urn)
    usata = await db.scalar(
        select(func.count()).select_from(Riferimento).where(Riferimento.urn_atto == norma.urn)
    )
    if usata:
        raise ErroreApi(
            HTTPStatus.CONFLICT,
            f"La norma è usata da {usata} riferimenti della libreria: eliminali prima",
        )
    testi = await _testi(db, norma.urn)
    await db.execute(delete(NormaArticoloVersione).where(NormaArticoloVersione.urn_atto == norma.urn))
    await db.execute(delete(NormaTestoCaricato).where(NormaTestoCaricato.urn_atto == norma.urn))
    await db.delete(norma)
    audit(db, utente(), "norma", norma.urn, "ELIMINATA")
    await db.commit()
    for t in testi:
        archivio.elimina(impostazioni().archivio_dir, t.file_percorso)
        archivio.elimina(impostazioni().archivio_dir, archivio.percorso_anteprima(t.id))
    return nessun_contenuto()


# --- Testi ---------------------------------------------------------------------------------


@bp.post("/testi")
@gestore
async def nuovo_testo():
    """Nuovo testo della norma (es. dopo una modifica del regolamento), vigente da una data."""
    dati = modulo(NuovoTestoIn)
    db = sessione_db()
    norma = await _norma(db, parametri(UrnQuery).urn)
    testo = await _archivia_testo(db, norma.urn, dati.vigenza_inizio)
    try:
        await db.flush()
        audit(db, utente(), "norma", norma.urn, "NUOVO_TESTO", {"file": testo.file_nome})
        await db.commit()
    except Exception:
        archivio.elimina(impostazioni().archivio_dir, testo.file_percorso)
        raise
    await _converti(testo)
    return _dettaglio(await _testo(db, testo.id, con_testo=True)), HTTPStatus.CREATED


@bp.get("/testi/<testo_id>")
@autenticato()
async def dettaglio_testo(testo_id: str):
    """Testo convertito e anteprima della divisione in articoli, commi e lettere."""
    return _dettaglio(await _testo(sessione_db(), testo_id, con_testo=True))


@bp.put("/testi/<testo_id>")
@gestore
async def correggi_testo(testo_id: str):
    """Corregge il testo convertito (e la data); se già confermato, aggiorna le versioni."""
    dati = corpo(TestoModifica)
    db = sessione_db()
    testo = await _testo(db, testo_id, con_testo=True)
    if testo.stato not in (StatoTestoNorma.DA_CONFERMARE, StatoTestoNorma.ATTIVO):
        raise ErroreApi(HTTPStatus.CONFLICT, "Il testo non è modificabile in questo stato")
    if testo.stato == StatoTestoNorma.ATTIVO and not scomponi(dati.testo).articoli:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Nel testo non c'è nessun articolo")
    testo.testo = dati.testo
    if dati.vigenza_inizio:
        testo.vigenza_inizio = dati.vigenza_inizio
    if testo.stato == StatoTestoNorma.ATTIVO:
        await ricostruisci_versioni(db, testo.urn_atto)
    audit(db, utente(), "norma", testo.urn_atto, "TESTO_CORRETTO", {"testo": testo.id})
    await db.commit()
    return _dettaglio(await _testo(db, testo_id, con_testo=True))


@bp.post("/testi/<testo_id>/conferma")
@gestore
async def conferma_testo(testo_id: str):
    """Rende il testo vigente dalla sua data: da qui lo usano le verifiche degli atti."""
    db = sessione_db()
    testo = await _testo(db, testo_id, con_testo=True)
    if testo.stato != StatoTestoNorma.DA_CONFERMARE:
        raise ErroreApi(HTTPStatus.CONFLICT, "Il testo non è da confermare")
    if not scomponi(testo.testo or "").articoli:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Nel testo non c'è nessun articolo")
    # un altro testo confermato con la stessa data viene sostituito da questo
    precedenti = (
        await db.scalars(
            select(NormaTestoCaricato).where(
                NormaTestoCaricato.urn_atto == testo.urn_atto,
                NormaTestoCaricato.stato == StatoTestoNorma.ATTIVO,
                NormaTestoCaricato.vigenza_inizio == testo.vigenza_inizio,
            )
        )
    ).all()
    for p in precedenti:
        p.stato = StatoTestoNorma.SOSTITUITO
    testo.stato = StatoTestoNorma.ATTIVO
    testo.confermato_il = datetime.now().replace(microsecond=0)
    versioni = await ricostruisci_versioni(db, testo.urn_atto)
    audit(db, utente(), "norma", testo.urn_atto, "TESTO_CONFERMATO", {"testo": testo.id})
    await db.commit()
    log.info("Norma %s: testo %s confermato, %d versioni", testo.urn_atto, testo.id, versioni)
    return _dettaglio(await _testo(db, testo_id, con_testo=True))


@bp.delete("/testi/<testo_id>")
@gestore
async def elimina_testo(testo_id: str):
    db = sessione_db()
    testo = await _testo(db, testo_id)
    era_attivo = testo.stato == StatoTestoNorma.ATTIVO
    urn, percorso = testo.urn_atto, testo.file_percorso
    await db.delete(testo)
    await db.flush()
    if era_attivo:
        await ricostruisci_versioni(db, urn)
    audit(db, utente(), "norma", urn, "TESTO_ELIMINATO", {"testo": testo_id})
    await db.commit()
    archivio.elimina(impostazioni().archivio_dir, percorso)
    archivio.elimina(impostazioni().archivio_dir, archivio.percorso_anteprima(testo_id))
    return nessun_contenuto()


@bp.get("/testi/<testo_id>/file")
@autenticato()
async def file_testo(testo_id: str):
    testo = await _testo(sessione_db(), testo_id)
    try:
        contenuto = await asyncio.to_thread(
            archivio.leggi, impostazioni().archivio_dir, testo.file_percorso
        )
    except archivio.FileNonInArchivio as e:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "File non presente nell'archivio") from e
    return allegato(contenuto, testo.file_mime, testo.file_nome)


@bp.get("/testi/<testo_id>/anteprima")
@autenticato()
async def anteprima_testo(testo_id: str):
    """Il file originale in PDF, da mostrare nel browser durante la revisione.

    Un PDF è restituito così com'è; ODT, DOC e DOCX sono convertiti da LibreOffice (servizio
    converter) alla prima richiesta e la copia PDF resta nell'archivio.
    """
    testo = await _testo(sessione_db(), testo_id)
    cartella = impostazioni().archivio_dir
    nome_pdf = f"{testo.file_nome.rsplit('.', 1)[0]}.pdf"
    try:
        if testo.file_mime == "application/pdf":
            pdf = await asyncio.to_thread(archivio.leggi, cartella, testo.file_percorso)
            return allegato(pdf, "application/pdf", testo.file_nome, in_linea=True)
        percorso = archivio.percorso_anteprima(testo.id)
        try:
            pdf = await asyncio.to_thread(archivio.leggi, cartella, percorso)
        except archivio.FileNonInArchivio:
            originale = await asyncio.to_thread(archivio.leggi, cartella, testo.file_percorso)
            pdf = await risorse().documenti.converti(originale, testo.file_nome, "pdf")
            await asyncio.to_thread(archivio.scrivi, cartella, percorso, pdf)
    except archivio.FileNonInArchivio as e:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "File non presente nell'archivio") from e
    except DocumentiError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, f"Anteprima non disponibile: {e}") from e
    return allegato(pdf, "application/pdf", nome_pdf, in_linea=True)
