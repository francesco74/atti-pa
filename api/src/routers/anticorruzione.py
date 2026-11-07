"""Modulo anticorruzione (ripreso da Si.Ge.Ri.Co.): metodologia di valutazione del rischio,
mappatura (area -> processo o procedimento -> attività -> rischio con la valutazione ->
misura, ciascuno uno a molti), proposte dei referenti, monitoraggio annuale delle misure,
riepilogo ed esportazione degli allegati al PTPCT. I codici degli elementi li assegna il
sistema e non si riusano.

Tutti gli utenti del modulo leggono; il RPCT (e il suo staff) modifica direttamente. I
referenti (uno per dirigente) propongono la creazione, la modifica o l'eliminazione di un
singolo elemento, solo per i processi della propria struttura; il RPCT approva, respinge o
restituisce ogni proposta. Nel monitoraggio i referenti dichiarano l'attuazione
delle misure della propria struttura (e delle sottostanti) e il RPCT verifica o contesta.
Logica comune in common/anticorruzione.
"""

import json
import re
from datetime import datetime
from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select

from deps import audit, autenticato, db, ente_id, utente
from web import ErroreApi, allegato, corpo, nessun_contenuto, parametri
from common import posta
from common.anticorruzione import art35 as dati_art35
from common.anticorruzione import excel
from common.anticorruzione.metodologia import Metodologia, chiave_area, chiave_naturale, standard, valuta
from common.models import (
    AcArea, AcAttivita, AcContatore, AcMetodologia, AcMisura, AcMonitoraggio, AcProcesso, AcProposta, AcRischio,
    Ente, EnteDominio, Modulo, Ruolo, Struttura, User, nuovo_id,
)  # fmt: skip
from common.trasparenza.registro import SCHEMI

bp = Blueprint("anticorruzione", __name__, url_prefix="/api/v1/anticorruzione")

lettore = autenticato(Ruolo.ANTICORRUZIONE_REFERENTE, Ruolo.ANTICORRUZIONE_RPCT, modulo=Modulo.ANTICORRUZIONE)
rpct = autenticato(Ruolo.ANTICORRUZIONE_RPCT, modulo=Modulo.ANTICORRUZIONE)


# --- metodologia ---------------------------------------------------------------------------


async def metodologia_ente() -> Metodologia:
    riga = await db().get(AcMetodologia, ente_id())
    return Metodologia.model_validate(riga.dati) if riga else standard()


@bp.get("/metodologia")
@lettore
async def metodologia():
    """Metodologia dell'ente (o quella standard se l'ente non l'ha adattata)."""
    riga = await db().get(AcMetodologia, ente_id())
    return {**(await metodologia_ente()).model_dump(), "standard": riga is None}


@bp.put("/metodologia")
@rpct
async def aggiorna_metodologia():
    """Nuova metodologia; le valutazioni esistenti si ricalcolano (quelle con indicatori non
    più previsti restano da rivalutare, senza livello)."""
    m = corpo(Metodologia)
    sessione = db()
    riga = await sessione.get(AcMetodologia, ente_id())
    if riga is None:
        riga = AcMetodologia(ente_id=ente_id())
        sessione.add(riga)
    riga.dati = m.model_dump()
    ricalcolati = da_rivalutare = 0
    for r in await sessione.scalars(select(AcRischio).where(AcRischio.ente_id == ente_id())):
        if r.valori_probabilita is None:
            continue
        try:
            v = valuta(m, r.valori_probabilita, r.valori_impatto or {})
        except ValueError:
            r.probabilita_calcolata = r.impatto_calcolato = r.probabilita = r.impatto = r.livello = None
            da_rivalutare += 1
            continue
        corretta = r.motivazione_correzione and r.probabilita in m.scala and r.impatto in m.scala
        r.probabilita_calcolata, r.impatto_calcolato = v.probabilita_calcolata, v.impatto_calcolato
        if not corretta:
            r.probabilita, r.impatto = v.probabilita, v.impatto
        r.livello = m.matrice[r.probabilita][r.impatto]
        ricalcolati += 1
    audit(sessione, utente(), "ac_metodologia", ente_id(), "AGGIORNATA",
          {"ricalcolati": ricalcolati, "da_rivalutare": da_rivalutare})  # fmt: skip
    await sessione.commit()
    return {"ricalcolati": ricalcolati, "da_rivalutare": da_rivalutare}


@bp.delete("/metodologia")
@rpct
async def ripristina_metodologia():
    """Torna alla metodologia standard (le valutazioni non si ricalcolano da sole)."""
    sessione = db()
    riga = await sessione.get(AcMetodologia, ente_id())
    if riga is not None:
        await sessione.delete(riga)
        audit(sessione, utente(), "ac_metodologia", ente_id(), "STANDARD")
        await sessione.commit()
    return nessun_contenuto()


# --- pubblicazione della mappatura -----------------------------------------------------------


class PubblicazioneIn(BaseModel):
    attiva: bool | None = None  # mappatura (processi e rischi)
    procedimenti_attiva: bool | None = None  # procedimenti (art. 35)


def _pubblicazione(e: Ente) -> dict:
    return {"attiva": bool(e.mappatura_pubblica), "percorso": "/pubblico/mappatura",
            "procedimenti_attiva": bool(e.procedimenti_pubblici), "percorso_procedimenti": "/pubblico/procedimenti"}


@bp.get("/pubblicazione")
@lettore
async def pubblicazione():
    """Se mappatura e procedimenti sono consultabili dai cittadini e i percorsi delle pagine."""
    return _pubblicazione(await db().get(Ente, ente_id()))


@bp.put("/pubblicazione")
@rpct
async def aggiorna_pubblicazione():
    """Accende o spegne le pagine pubbliche della mappatura e dei procedimenti (campi presenti)."""
    dati = corpo(PubblicazioneIn)
    sessione = db()
    e = await sessione.get(Ente, ente_id())
    if dati.attiva is not None:
        e.mappatura_pubblica = dati.attiva
        audit(sessione, utente(), "ente", e.id, "MAPPATURA_PUBBLICA" if dati.attiva else "MAPPATURA_RISERVATA")
    if dati.procedimenti_attiva is not None:
        e.procedimenti_pubblici = dati.procedimenti_attiva
        audit(sessione, utente(), "ente", e.id,
              "PROCEDIMENTI_PUBBLICI" if dati.procedimenti_attiva else "PROCEDIMENTI_RISERVATI")  # fmt: skip
    await sessione.commit()
    return _pubblicazione(e)


@bp.get("/obblighi")
@lettore
async def obblighi():
    """Obblighi di pubblicazione (schemi ANAC) a cui collegare le misure di trasparenza."""
    return sorted(
        ({"id": s.id, "articolo": s.articolo, "titolo": s.titolo} for s in SCHEMI.values()),
        key=lambda o: chiave_naturale(o["id"]),
    )


# --- codici --------------------------------------------------------------------------------


def _lettere(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    testo = ""
    while n > 0:
        n, resto = divmod(n - 1, 26)
        testo = chr(ord("A") + resto) + testo
    return testo


def _numero_lettere(codice: str) -> int | None:
    if not re.fullmatch(r"[A-Z]{1,2}", codice or ""):
        return None
    n = 0
    for c in codice:
        n = n * 26 + ord(c) - ord("A") + 1
    return n


async def _nuovo_codice(sessione, modello, prefisso: str, *, lettere: bool = False) -> str:
    """Codice nuovo, univoco nell'ente, assegnato solo dal sistema: con il prefisso (es. "A.1."
    per le attività del processo A.1) il numero successivo al più alto mai assegnato. Conta
    anche i codici degli elementi eliminati (contatore) e quelli arrivati dal pacchetto
    standard, quindi un codice non si riusa mai. Le aree hanno lettere: A, B... Z, AA."""
    chiave = "#aree" if lettere else prefisso
    contatore = await sessione.get(AcContatore, (ente_id(), chiave), with_for_update=True)
    usati = []
    for codice in await sessione.scalars(select(modello.codice).where(modello.ente_id == ente_id())):
        if lettere:
            n = _numero_lettere(codice)
        else:
            m = re.fullmatch(r"(\d+)", codice[len(prefisso):]) if codice.startswith(prefisso) else None
            n = int(m.group(1)) if m else None
        if n:
            usati.append(n)
    n = max([contatore.ultimo if contatore else 0, *usati]) + 1
    if contatore is None:
        sessione.add(AcContatore(ente_id=ente_id(), prefisso=chiave, ultimo=n))
    else:
        contatore.ultimo = n
    await sessione.flush()  # il prossimo codice nella stessa operazione vede questo
    return _lettere(n) if lettere else f"{prefisso}{n}"


# --- aree di rischio -----------------------------------------------------------------------


class AreaIn(BaseModel):
    descrizione: str = Field(min_length=1, max_length=500)
    descrizione_breve: str | None = Field(default=None, max_length=255)


def _area(a: AcArea) -> dict:
    return {"id": a.id, "codice": a.codice, "descrizione": a.descrizione,
            "descrizione_breve": a.descrizione_breve}  # fmt: skip


async def _area_dell_ente(sessione, area_id: str) -> AcArea:
    a = await sessione.get(AcArea, area_id)
    if a is None or a.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Area di rischio non trovata")
    return a


async def _crea_area(sessione, dati: AreaIn) -> AcArea:
    a = AcArea(id=nuovo_id(), ente_id=ente_id(), codice=await _nuovo_codice(sessione, AcArea, "", lettere=True),
               **dati.model_dump())  # fmt: skip
    sessione.add(a)
    return a


def _modifica_area(a: AcArea, dati: AreaIn) -> None:
    a.descrizione, a.descrizione_breve = dati.descrizione, dati.descrizione_breve


async def _controlla_area_vuota(sessione, a: AcArea) -> None:
    if await sessione.scalar(select(AcProcesso.id).where(AcProcesso.area_id == a.id).limit(1)):
        raise ErroreApi(HTTPStatus.CONFLICT, "L'area ha dei processi: spostali prima di eliminarla")


@bp.get("/aree")
@lettore
async def aree():
    """Aree in ordine alfabetico della descrizione breve."""
    righe = await db().scalars(select(AcArea).where(AcArea.ente_id == ente_id()))
    return [_area(a) for a in sorted(righe, key=chiave_area)]


@bp.post("/aree")
@rpct
async def crea_area():
    dati = corpo(AreaIn)
    sessione = db()
    a = await _crea_area(sessione, dati)
    audit(sessione, utente(), "ac_area", a.id, "CREATA", {"codice": a.codice})
    await sessione.commit()
    return _area(a), HTTPStatus.CREATED


@bp.put("/aree/<area_id>")
@rpct
async def aggiorna_area(area_id: str):
    dati = corpo(AreaIn)
    sessione = db()
    a = await _area_dell_ente(sessione, area_id)
    _modifica_area(a, dati)
    audit(sessione, utente(), "ac_area", a.id, "AGGIORNATA", {"codice": a.codice})
    await sessione.commit()
    return _area(a)


@bp.delete("/aree/<area_id>")
@rpct
async def elimina_area(area_id: str):
    sessione = db()
    a = await _area_dell_ente(sessione, area_id)
    await _controlla_area_vuota(sessione, a)
    audit(sessione, utente(), "ac_area", a.id, "ELIMINATA", {"codice": a.codice})
    await sessione.delete(a)
    await sessione.commit()
    return nessun_contenuto()


# --- mappatura: lettura ------------------------------------------------------------------


async def _strutture_ente(sessione) -> dict[str, Struttura]:
    return {s.id: s for s in await sessione.scalars(select(Struttura).where(Struttura.ente_id == ente_id()))}


def _sottostanti(strutture: dict[str, Struttura], radice: str) -> set[str]:
    """La struttura e tutte quelle sotto di lei."""
    risultato, cresciuto = {radice}, True
    while cresciuto:
        cresciuto = False
        for s in strutture.values():
            if s.padre_id in risultato and s.id not in risultato:
                risultato.add(s.id)
                cresciuto = True
    return risultato


def _processo(p: AcProcesso) -> dict:
    return {
        "id": p.id, "codice": p.codice, "tipo": p.tipo or "PROCESSO", "area_id": p.area_id,
        "denominazione": p.denominazione, "descrizione": p.descrizione, "tempi": p.tempi,
        "attori_esterni": p.attori_esterni, "termine_conclusione": p.termine_conclusione,
        "norma_riferimento": p.norma_riferimento, "art35": p.art35, "struttura_id": p.struttura_id,
        "pacchetto": p.pacchetto,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }  # fmt: skip


def _attivita(a: AcAttivita) -> dict:
    return {"id": a.id, "processo_id": a.processo_id, "codice": a.codice, "descrizione": a.descrizione,
            "strutture_coinvolte": a.strutture_coinvolte}  # fmt: skip


def _rischio(r: AcRischio) -> dict:
    return {
        "id": r.id, "attivita_id": r.attivita_id, "codice": r.codice, "evento": r.evento,
        "fattore_abilitante": r.fattore_abilitante, "valori_probabilita": r.valori_probabilita,
        "valori_impatto": r.valori_impatto, "probabilita_calcolata": r.probabilita_calcolata,
        "impatto_calcolato": r.impatto_calcolato, "probabilita": r.probabilita, "impatto": r.impatto,
        "livello": r.livello, "motivazione_correzione": r.motivazione_correzione,
        "valutato_il": r.valutato_il.isoformat() if r.valutato_il else None,
    }  # fmt: skip


def _misura(m: AcMisura) -> dict:
    return {
        "id": m.id, "rischio_id": m.rischio_id, "codice": m.codice, "descrizione": m.descrizione,
        "tipo": m.tipo, "categoria": m.categoria, "obbligo_trasparenza": m.obbligo_trasparenza,
        "fasi": m.fasi, "tempi": m.tempi, "struttura_id": m.struttura_id,
        "indicatore": m.indicatore, "target": m.target,
    }  # fmt: skip


def _per_codice(righe):
    return sorted(righe, key=lambda x: chiave_naturale(x.codice))


class FiltriProcessi(BaseModel):
    area: str | None = None  # id dell'area
    struttura: str | None = None  # id: la struttura e le sottostanti, più i processi trasversali
    livello: str | None = None  # livello massimo di rischio del processo
    tipo: Literal["PROCESSO", "PROCEDIMENTO"] | None = None
    testo: str | None = Field(default=None, max_length=200)


@bp.get("/processi")
@lettore
async def processi():
    """Processi e procedimenti con i conteggi e il livello di rischio più alto tra i loro rischi."""
    return await elenco_processi(db(), parametri(FiltriProcessi))


async def elenco_processi(sessione, f: FiltriProcessi) -> list[dict]:
    """Processi dell'ente filtrati, con i conteggi e il livello più alto (anche per la pagina
    pubblica)."""
    m = await metodologia_ente()
    q = select(AcProcesso).where(AcProcesso.ente_id == ente_id())
    if f.area:
        q = q.where(AcProcesso.area_id == f.area)
    if f.tipo:
        q = q.where(AcProcesso.tipo == f.tipo)
    elenco = list(await sessione.scalars(q))
    if f.struttura:
        ammesse = _sottostanti(await _strutture_ente(sessione), f.struttura)
        elenco = [p for p in elenco if p.struttura_id is None or p.struttura_id in ammesse]
    attivita = list(await sessione.scalars(select(AcAttivita).where(AcAttivita.ente_id == ente_id())))
    rischi = list(await sessione.scalars(select(AcRischio).where(AcRischio.ente_id == ente_id())))
    misure = list(await sessione.scalars(select(AcMisura.rischio_id).where(AcMisura.ente_id == ente_id())))
    processo_di_attivita = {a.id: a.processo_id for a in attivita}
    processo_di_rischio = {r.id: processo_di_attivita.get(r.attivita_id) for r in rischi}
    conteggi: dict[str, dict] = {}
    for a in attivita:
        conteggi.setdefault(a.processo_id, {"attivita": 0, "rischi": 0, "misure": 0, "livelli": []})["attivita"] += 1
    for r in rischi:
        c = conteggi.get(processo_di_rischio[r.id])
        if c is not None:
            c["rischi"] += 1
            c["livelli"].append(r.livello)
    for rischio_id in misure:
        c = conteggi.get(processo_di_rischio.get(rischio_id))
        if c is not None:
            c["misure"] += 1
    testo = (f.testo or "").strip().lower()
    strutture = await _strutture_ente(sessione) if any(p.tipo == "PROCEDIMENTO" for p in elenco) else {}
    risultato = []
    for p in _per_codice(elenco):
        c = conteggi.get(p.id, {"attivita": 0, "rischi": 0, "misure": 0, "livelli": []})
        livello = max(c["livelli"], key=m.ordine_livello, default=None)
        if m.ordine_livello(livello) < 0:
            livello = None
        if f.livello and livello != f.livello:
            continue
        if testo and testo not in f"{p.codice} {p.denominazione}".lower():
            continue
        risultato.append({**_processo(p), "attivita": c["attivita"], "rischi": c["rischi"],
                          "misure": c["misure"], "livello_massimo": livello})  # fmt: skip
        if p.tipo == "PROCEDIMENTO":  # quanti dati dell'art. 35 mancano (0: completi)
            risultato[-1]["art35_mancanti"] = len(dati_art35.mancanti(dati_art35.scheda(p, strutture)))
    return risultato


async def processo_dell_ente(sessione, processo_id: str) -> AcProcesso:
    p = await sessione.get(AcProcesso, processo_id)
    if p is None or p.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Processo non trovato")
    return p


@bp.get("/processi/<processo_id>")
@lettore
async def processo(processo_id: str):
    """Processo con l'albero delle attività, dei rischi e delle misure; per il referente dice
    anche se può fare proposte (processo della sua struttura)."""
    sessione = db()
    p = await processo_dell_ente(sessione, processo_id)
    ammesse = await _strutture_dell_utente(sessione)
    risultato = {**await albero_processo(sessione, p), "proponibile": ammesse is not None and p.struttura_id in ammesse}
    if p.tipo == "PROCEDIMENTO":
        elemento = dati_art35.scheda(p, await _strutture_ente(sessione))
        risultato |= {"scheda_art35": elemento, "art35_mancanti": dati_art35.mancanti(elemento)}
    return risultato


async def albero_processo(sessione, p: AcProcesso) -> dict:
    attivita = _per_codice(await sessione.scalars(select(AcAttivita).where(AcAttivita.processo_id == p.id)))
    ids_attivita = [a.id for a in attivita]
    rischi = _per_codice(await sessione.scalars(select(AcRischio).where(AcRischio.attivita_id.in_(ids_attivita))))
    misure = _per_codice(await sessione.scalars(select(AcMisura).where(AcMisura.rischio_id.in_([r.id for r in rischi]))))
    return {
        **_processo(p),
        "attivita": [
            {**_attivita(a), "rischi": [
                {**_rischio(r), "misure": [_misura(x) for x in misure if x.rischio_id == r.id]}
                for r in rischi if r.attivita_id == a.id
            ]}
            for a in attivita
        ],
    }  # fmt: skip


# --- mappatura: operazioni sugli elementi ---------------------------------------------------
# Usate sia dalle modifiche dirette del RPCT sia dall'approvazione delle proposte.


async def _struttura_valida(sessione, struttura_id: str | None) -> None:
    if struttura_id is None:
        return
    s = await sessione.get(Struttura, struttura_id)
    if s is None or s.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Struttura non trovata")


async def _tocca(sessione, processo_id: str) -> None:
    """Data di modifica del processo quando cambia qualcosa al suo interno."""
    p = await sessione.get(AcProcesso, processo_id)
    if p is not None:
        p.updated_at = datetime.now()


class ProcessoIn(BaseModel):
    tipo: Literal["PROCESSO", "PROCEDIMENTO"] = "PROCESSO"
    area_id: str | None = None
    denominazione: str = Field(min_length=1, max_length=500)
    descrizione: str | None = None
    tempi: str | None = None
    attori_esterni: str | None = None
    termine_conclusione: str | None = Field(default=None, max_length=255)  # procedimento
    norma_riferimento: str | None = None  # procedimento
    art35: dati_art35.DatiArt35 | None = None  # procedimento: dati propri dell'art. 35
    struttura_id: str | None = None  # vuota: processo trasversale


class AttivitaIn(BaseModel):
    descrizione: str = Field(min_length=1)
    strutture_coinvolte: str | None = None


class RischioIn(BaseModel):
    evento: str = Field(min_length=1)
    fattore_abilitante: str | None = Field(default=None, max_length=500)


class ValutazioneProposta(BaseModel):
    valori_probabilita: dict[str, str]
    valori_impatto: dict[str, str]
    # correzione dei valori calcolati (es. parità nella moda), con motivazione obbligatoria
    probabilita: str | None = None
    impatto: str | None = None
    motivazione_correzione: str | None = Field(default=None, max_length=5000)


class MisuraIn(BaseModel):
    descrizione: str = Field(min_length=1)
    tipo: Literal["GENERALE", "SPECIFICA"] = "SPECIFICA"
    categoria: str | None = Field(default=None, max_length=255)
    obbligo_trasparenza: str | None = Field(default=None, max_length=100)
    fasi: str | None = None
    tempi: str | None = None
    struttura_id: str | None = None
    indicatore: str | None = None
    target: str | None = None


# creazione con gli elementi sottostanti (proposte)
class RischioNuovo(RischioIn):
    valutazione: ValutazioneProposta | None = None
    misure: list[MisuraIn] = []


class AttivitaNuova(AttivitaIn):
    rischi: list[RischioNuovo] = []


class ProcessoNuovo(ProcessoIn):
    attivita: list[AttivitaNuova] = []


class RischioModificato(RischioIn):
    """Modifica di un rischio: evento e valutazione (anche solo una rivalutazione)."""

    valutazione: ValutazioneProposta | None = None


async def _verifica_processo(sessione, dati: ProcessoIn) -> AcArea | None:
    await _struttura_valida(sessione, dati.struttura_id)
    if dati.art35 is not None:
        for campo in dati_art35.STRUTTURE:
            await _struttura_valida(sessione, getattr(dati.art35, campo))
    return await _area_dell_ente(sessione, dati.area_id) if dati.area_id else None


def _imposta_processo(p: AcProcesso, dati: ProcessoIn) -> None:
    for campo, valore in dati.model_dump(include=set(ProcessoIn.model_fields) - {"art35"}).items():
        setattr(p, campo, valore)
    # dati dell'art. 35: un oggetto li sostituisce, null o assenti li lasciano come sono
    if dati.art35 is not None:
        p.art35 = dati.art35.model_dump(exclude_none=True) or None
    if p.tipo == "PROCESSO":
        p.termine_conclusione = p.norma_riferimento = p.art35 = None
    p.updated_at = datetime.now()


async def _crea_processo(sessione, dati: ProcessoIn) -> AcProcesso:
    area = await _verifica_processo(sessione, dati)
    codice = await _nuovo_codice(sessione, AcProcesso, f"{area.codice if area else 'P'}.")
    p = AcProcesso(id=nuovo_id(), ente_id=ente_id(), codice=codice)
    _imposta_processo(p, dati)
    sessione.add(p)
    return p


async def _modifica_processo(sessione, p: AcProcesso, dati: ProcessoIn) -> None:
    """Il codice resta anche se cambia l'area: identifica il processo."""
    await _verifica_processo(sessione, dati)
    _imposta_processo(p, dati)


async def _elimina_sotto_attivita(sessione, ids_attivita: list[str]) -> None:
    """Rischi e misure delle attività (esplicito: SQLite non applica le cascade senza pragma)."""
    ids_rischi = list(await sessione.scalars(select(AcRischio.id).where(AcRischio.attivita_id.in_(ids_attivita))))
    await sessione.execute(delete(AcMisura).where(AcMisura.rischio_id.in_(ids_rischi)))
    await sessione.execute(delete(AcRischio).where(AcRischio.id.in_(ids_rischi)))


async def _elimina_processo(sessione, p: AcProcesso) -> None:
    """Il processo con le sue attività, rischi e misure."""
    ids_attivita = list(await sessione.scalars(select(AcAttivita.id).where(AcAttivita.processo_id == p.id)))
    await _elimina_sotto_attivita(sessione, ids_attivita)
    await sessione.execute(delete(AcAttivita).where(AcAttivita.id.in_(ids_attivita)))
    await sessione.delete(p)


async def _crea_attivita(sessione, p: AcProcesso, dati: AttivitaIn) -> AcAttivita:
    a = AcAttivita(id=nuovo_id(), ente_id=ente_id(), processo_id=p.id,
                   codice=await _nuovo_codice(sessione, AcAttivita, f"{p.codice}."),
                   descrizione=dati.descrizione, strutture_coinvolte=dati.strutture_coinvolte)  # fmt: skip
    sessione.add(a)
    await _tocca(sessione, p.id)
    return a


async def _modifica_attivita(sessione, a: AcAttivita, dati: AttivitaIn) -> None:
    a.descrizione, a.strutture_coinvolte = dati.descrizione, dati.strutture_coinvolte
    await _tocca(sessione, a.processo_id)


async def _elimina_attivita(sessione, a: AcAttivita) -> None:
    await _elimina_sotto_attivita(sessione, [a.id])
    await _tocca(sessione, a.processo_id)
    await sessione.delete(a)


def _esito(m: Metodologia, v: ValutazioneProposta):
    try:
        esito = valuta(m, v.valori_probabilita, v.valori_impatto, probabilita=v.probabilita, impatto=v.impatto)
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    corretta = (esito.probabilita, esito.impatto) != (esito.probabilita_calcolata, esito.impatto_calcolato)
    if corretta and not (v.motivazione_correzione or "").strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Per correggere probabilità o impatto serve la motivazione")
    return esito, corretta


def _valuta(r: AcRischio, m: Metodologia, v: ValutazioneProposta | None) -> None:
    """Valutazione del rischio (None: da valutare): moda degli indicatori (a parità il più
    alto) e matrice della metodologia; la data cambia solo se cambia la valutazione."""
    if v is None:
        r.valori_probabilita = r.valori_impatto = r.probabilita_calcolata = r.impatto_calcolato = None
        r.probabilita = r.impatto = r.livello = r.motivazione_correzione = r.valutato_il = None
        return
    esito, corretta = _esito(m, v)
    nuova = (r.valori_probabilita, r.valori_impatto, r.probabilita, r.impatto) != (
        v.valori_probabilita, v.valori_impatto, esito.probabilita, esito.impatto)  # fmt: skip
    r.valori_probabilita, r.valori_impatto = v.valori_probabilita, v.valori_impatto
    r.probabilita_calcolata, r.impatto_calcolato = esito.probabilita_calcolata, esito.impatto_calcolato
    r.probabilita, r.impatto, r.livello = esito.probabilita, esito.impatto, esito.livello
    r.motivazione_correzione = (v.motivazione_correzione or "").strip() if corretta else None
    if nuova or r.valutato_il is None:
        r.valutato_il = datetime.now()


async def _processo_del_rischio(sessione, rischio: AcRischio) -> str:
    return (await sessione.get(AcAttivita, rischio.attivita_id)).processo_id


async def _crea_rischio(sessione, a: AcAttivita, dati: RischioIn) -> AcRischio:
    r = AcRischio(id=nuovo_id(), ente_id=ente_id(), attivita_id=a.id,
                  codice=await _nuovo_codice(sessione, AcRischio, f"{a.codice}_R."),
                  evento=dati.evento, fattore_abilitante=dati.fattore_abilitante)  # fmt: skip
    sessione.add(r)
    await _tocca(sessione, a.processo_id)
    return r


async def _modifica_rischio(sessione, r: AcRischio, dati: RischioIn) -> None:
    r.evento, r.fattore_abilitante = dati.evento, dati.fattore_abilitante
    await _tocca(sessione, await _processo_del_rischio(sessione, r))


async def _elimina_rischio(sessione, r: AcRischio) -> None:
    await sessione.execute(delete(AcMisura).where(AcMisura.rischio_id == r.id))
    await _tocca(sessione, await _processo_del_rischio(sessione, r))
    await sessione.delete(r)


async def _verifica_misura(sessione, dati: MisuraIn) -> None:
    if dati.obbligo_trasparenza and dati.obbligo_trasparenza not in SCHEMI:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Obbligo di pubblicazione non previsto: {dati.obbligo_trasparenza}")
    await _struttura_valida(sessione, dati.struttura_id)


async def _crea_misura(sessione, r: AcRischio, dati: MisuraIn) -> AcMisura:
    await _verifica_misura(sessione, dati)
    x = AcMisura(id=nuovo_id(), ente_id=ente_id(), rischio_id=r.id,
                 codice=await _nuovo_codice(sessione, AcMisura, f"{r.codice}_M."), **dati.model_dump())  # fmt: skip
    sessione.add(x)
    await _tocca(sessione, await _processo_del_rischio(sessione, r))
    return x


async def _modifica_misura(sessione, x: AcMisura, dati: MisuraIn) -> None:
    await _verifica_misura(sessione, dati)
    for campo, valore in dati.model_dump().items():
        setattr(x, campo, valore)
    await _tocca(sessione, await _processo_del_rischio(sessione, await sessione.get(AcRischio, x.rischio_id)))


async def _elimina_misura(sessione, x: AcMisura) -> None:
    await _tocca(sessione, await _processo_del_rischio(sessione, await sessione.get(AcRischio, x.rischio_id)))
    await sessione.delete(x)


# creazione con gli elementi sottostanti, in ordine: ogni codice nasce da quello del padre
async def _crea_rischio_completo(sessione, a: AcAttivita, dati: RischioNuovo, m: Metodologia) -> AcRischio:
    r = await _crea_rischio(sessione, a, dati)
    _valuta(r, m, dati.valutazione)
    for x in dati.misure:
        await _crea_misura(sessione, r, x)
    return r


async def _crea_attivita_completa(sessione, p: AcProcesso, dati: AttivitaNuova, m: Metodologia) -> AcAttivita:
    a = await _crea_attivita(sessione, p, dati)
    for r in dati.rischi:
        await _crea_rischio_completo(sessione, a, r, m)
    return a


async def _crea_processo_completo(sessione, dati: ProcessoNuovo, m: Metodologia) -> AcProcesso:
    p = await _crea_processo(sessione, dati)
    for a in dati.attivita:
        await _crea_attivita_completa(sessione, p, a, m)
    return p


# --- mappatura: modifiche dirette (RPCT) --------------------------------------------------


@bp.post("/processi")
@rpct
async def crea_processo():
    dati = corpo(ProcessoIn)
    sessione = db()
    p = await _crea_processo(sessione, dati)
    await sessione.flush()
    audit(sessione, utente(), "ac_processo", p.id, "CREATO", {"codice": p.codice})
    await sessione.commit()
    await sessione.refresh(p)
    return _processo(p), HTTPStatus.CREATED


@bp.put("/processi/<processo_id>")
@rpct
async def aggiorna_processo(processo_id: str):
    dati = corpo(ProcessoIn)
    sessione = db()
    p = await processo_dell_ente(sessione, processo_id)
    await _modifica_processo(sessione, p, dati)
    audit(sessione, utente(), "ac_processo", p.id, "AGGIORNATO", {"codice": p.codice})
    await sessione.commit()
    await sessione.refresh(p)
    return _processo(p)


@bp.delete("/processi/<processo_id>")
@rpct
async def elimina_processo(processo_id: str):
    sessione = db()
    p = await processo_dell_ente(sessione, processo_id)
    audit(sessione, utente(), "ac_processo", p.id, "ELIMINATO", {"codice": p.codice})
    await _elimina_processo(sessione, p)
    await sessione.commit()
    return nessun_contenuto()


async def _attivita_dell_ente(sessione, attivita_id: str) -> AcAttivita:
    a = await sessione.get(AcAttivita, attivita_id)
    if a is None or a.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Attività non trovata")
    return a


@bp.post("/processi/<processo_id>/attivita")
@rpct
async def crea_attivita(processo_id: str):
    dati = corpo(AttivitaIn)
    sessione = db()
    a = await _crea_attivita(sessione, await processo_dell_ente(sessione, processo_id), dati)
    audit(sessione, utente(), "ac_attivita", a.id, "CREATA", {"codice": a.codice})
    await sessione.commit()
    return _attivita(a), HTTPStatus.CREATED


@bp.put("/attivita/<attivita_id>")
@rpct
async def aggiorna_attivita(attivita_id: str):
    dati = corpo(AttivitaIn)
    sessione = db()
    a = await _attivita_dell_ente(sessione, attivita_id)
    await _modifica_attivita(sessione, a, dati)
    audit(sessione, utente(), "ac_attivita", a.id, "AGGIORNATA", {"codice": a.codice})
    await sessione.commit()
    return _attivita(a)


@bp.delete("/attivita/<attivita_id>")
@rpct
async def elimina_attivita(attivita_id: str):
    sessione = db()
    a = await _attivita_dell_ente(sessione, attivita_id)
    audit(sessione, utente(), "ac_attivita", a.id, "ELIMINATA", {"codice": a.codice})
    await _elimina_attivita(sessione, a)
    await sessione.commit()
    return nessun_contenuto()


async def _rischio_dell_ente(sessione, rischio_id: str) -> AcRischio:
    r = await sessione.get(AcRischio, rischio_id)
    if r is None or r.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Rischio non trovato")
    return r


@bp.post("/attivita/<attivita_id>/rischi")
@rpct
async def crea_rischio(attivita_id: str):
    dati = corpo(RischioIn)
    sessione = db()
    r = await _crea_rischio(sessione, await _attivita_dell_ente(sessione, attivita_id), dati)
    audit(sessione, utente(), "ac_rischio", r.id, "CREATO", {"codice": r.codice})
    await sessione.commit()
    return _rischio(r), HTTPStatus.CREATED


@bp.put("/rischi/<rischio_id>")
@rpct
async def aggiorna_rischio(rischio_id: str):
    dati = corpo(RischioIn)
    sessione = db()
    r = await _rischio_dell_ente(sessione, rischio_id)
    await _modifica_rischio(sessione, r, dati)
    audit(sessione, utente(), "ac_rischio", r.id, "AGGIORNATO", {"codice": r.codice})
    await sessione.commit()
    return _rischio(r)


@bp.delete("/rischi/<rischio_id>")
@rpct
async def elimina_rischio(rischio_id: str):
    sessione = db()
    r = await _rischio_dell_ente(sessione, rischio_id)
    audit(sessione, utente(), "ac_rischio", r.id, "ELIMINATO", {"codice": r.codice})
    await _elimina_rischio(sessione, r)
    await sessione.commit()
    return nessun_contenuto()


class ValutazioneIn(ValutazioneProposta):
    fattore_abilitante: str | None = Field(default=None, max_length=500)


@bp.put("/rischi/<rischio_id>/valutazione")
@rpct
async def valuta_rischio(rischio_id: str):
    """Valutazione del rischio: moda degli indicatori (a parità il più alto) e matrice della
    metodologia dell'ente; probabilità e impatto si possono correggere con una motivazione."""
    dati = corpo(ValutazioneIn)
    sessione = db()
    r = await _rischio_dell_ente(sessione, rischio_id)
    _valuta(r, await metodologia_ente(), dati)
    if dati.fattore_abilitante is not None:
        r.fattore_abilitante = dati.fattore_abilitante or None
    await _tocca(sessione, await _processo_del_rischio(sessione, r))
    audit(sessione, utente(), "ac_rischio", r.id, "VALUTATO", {"livello": r.livello})
    await sessione.commit()
    return _rischio(r)


async def _misura_dell_ente(sessione, misura_id: str) -> AcMisura:
    m = await sessione.get(AcMisura, misura_id)
    if m is None or m.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Misura non trovata")
    return m


@bp.post("/rischi/<rischio_id>/misure")
@rpct
async def crea_misura(rischio_id: str):
    dati = corpo(MisuraIn)
    sessione = db()
    x = await _crea_misura(sessione, await _rischio_dell_ente(sessione, rischio_id), dati)
    audit(sessione, utente(), "ac_misura", x.id, "CREATA", {"codice": x.codice})
    await sessione.commit()
    return _misura(x), HTTPStatus.CREATED


@bp.put("/misure/<misura_id>")
@rpct
async def aggiorna_misura(misura_id: str):
    dati = corpo(MisuraIn)
    sessione = db()
    x = await _misura_dell_ente(sessione, misura_id)
    await _modifica_misura(sessione, x, dati)
    audit(sessione, utente(), "ac_misura", x.id, "AGGIORNATA", {"codice": x.codice})
    await sessione.commit()
    return _misura(x)


@bp.delete("/misure/<misura_id>")
@rpct
async def elimina_misura(misura_id: str):
    sessione = db()
    x = await _misura_dell_ente(sessione, misura_id)
    audit(sessione, utente(), "ac_misura", x.id, "ELIMINATA", {"codice": x.codice})
    await _elimina_misura(sessione, x)
    await sessione.commit()
    return nessun_contenuto()


# --- proposte ------------------------------------------------------------------------------
# Il referente propone su un singolo elemento della mappatura: creazione (con gli elementi
# sottostanti), modifica o eliminazione, solo per i processi della sua struttura (e delle
# sottostanti). Il RPCT decide ogni proposta; approvandola la applica con le stesse operazioni
# delle modifiche dirette, quindi i codici li assegna il sistema in quel momento.

Oggetto = Literal["AREA", "PROCESSO", "ATTIVITA", "RISCHIO", "MISURA"]

PADRE: dict[str, str] = {"ATTIVITA": "PROCESSO", "RISCHIO": "ATTIVITA", "MISURA": "RISCHIO"}

DATI_PROPOSTA: dict[tuple[str, str], type[BaseModel]] = {
    ("AREA", "CREA"): AreaIn, ("AREA", "MODIFICA"): AreaIn,
    ("PROCESSO", "CREA"): ProcessoNuovo, ("PROCESSO", "MODIFICA"): ProcessoIn,
    ("ATTIVITA", "CREA"): AttivitaNuova, ("ATTIVITA", "MODIFICA"): AttivitaIn,
    ("RISCHIO", "CREA"): RischioNuovo, ("RISCHIO", "MODIFICA"): RischioModificato,
    ("MISURA", "CREA"): MisuraIn, ("MISURA", "MODIFICA"): MisuraIn,
}  # fmt: skip


def _dati_proposta(oggetto: str, tipo: str, dati: dict | None) -> BaseModel:
    try:
        return DATI_PROPOSTA[(oggetto, tipo)].model_validate(dati or {})
    except ValidationError as e:
        errore = e.errors()[0]
        campo = ".".join(str(x) for x in errore["loc"])
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Dati della proposta non validi ({campo}): {errore['msg']}") from e


async def _elemento(sessione, oggetto: str, elemento_id: str | None):
    if not elemento_id:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica l'elemento della mappatura")
    carica = {"AREA": _area_dell_ente, "PROCESSO": processo_dell_ente, "ATTIVITA": _attivita_dell_ente,
              "RISCHIO": _rischio_dell_ente, "MISURA": _misura_dell_ente}[oggetto]  # fmt: skip
    return await carica(sessione, elemento_id)


async def _padre(sessione, oggetto: str, el) -> tuple[str, object] | None:
    """L'elemento che contiene `el` (il processo per l'attività...); per il processo l'area."""
    if oggetto == "MISURA":
        return "RISCHIO", await sessione.get(AcRischio, el.rischio_id)
    if oggetto == "RISCHIO":
        return "ATTIVITA", await sessione.get(AcAttivita, el.attivita_id)
    if oggetto == "ATTIVITA":
        return "PROCESSO", await sessione.get(AcProcesso, el.processo_id)
    if oggetto == "PROCESSO" and el.area_id:
        return "AREA", await sessione.get(AcArea, el.area_id)
    return None


async def _processo_di(sessione, oggetto: str, el) -> AcProcesso | None:
    while el is not None and oggetto not in ("PROCESSO", "AREA"):
        oggetto, el = await _padre(sessione, oggetto, el)
    return el if oggetto == "PROCESSO" else None


def _titolo(oggetto: str, dati: dict) -> str:
    campo = {"AREA": "descrizione_breve", "PROCESSO": "denominazione", "ATTIVITA": "descrizione",
             "RISCHIO": "evento", "MISURA": "descrizione"}[oggetto]  # fmt: skip
    testo = (dati.get(campo) or dati.get("descrizione") or "").strip()
    return testo if len(testo) <= 80 else testo[:79] + "…"


async def _percorso(sessione, oggetto: str, el) -> list[str]:
    """Dall'area all'elemento compreso: "A Autorizzazioni", "A.1 Rilascio...", ..."""
    voci = []
    while el is not None:
        voci.append(f"{el.codice} {_titolo(oggetto, {k: getattr(el, k, None) for k in ('descrizione_breve', 'denominazione', 'descrizione', 'evento')})}")
        padre = await _padre(sessione, oggetto, el)
        oggetto, el = padre if padre else (None, None)
    return list(reversed(voci))


def _valutazione_di(r: AcRischio) -> dict | None:
    if not r.valori_probabilita:
        return None
    campi = ("valori_probabilita", "valori_impatto", "probabilita", "impatto", "motivazione_correzione",
             "probabilita_calcolata", "impatto_calcolato", "livello")  # fmt: skip
    return {k: getattr(r, k) for k in campi}


async def _istantanea(sessione, oggetto: str, el, *, figli: bool = False) -> dict:
    """L'elemento com'è, nella forma dei dati delle proposte (con il codice); con `figli`
    anche gli elementi sottostanti (eliminazione)."""
    if oggetto == "AREA":
        return {"codice": el.codice, **{k: getattr(el, k) for k in AreaIn.model_fields}}
    if oggetto == "MISURA":
        return {"codice": el.codice, **{k: getattr(el, k) for k in MisuraIn.model_fields}}
    if oggetto == "RISCHIO":
        dati = {"codice": el.codice, "evento": el.evento, "fattore_abilitante": el.fattore_abilitante,
                "valutazione": _valutazione_di(el)}  # fmt: skip
        if figli:
            misure = _per_codice(await sessione.scalars(select(AcMisura).where(AcMisura.rischio_id == el.id)))
            dati["misure"] = [await _istantanea(sessione, "MISURA", x) for x in misure]
        return dati
    if oggetto == "ATTIVITA":
        dati = {"codice": el.codice, **{k: getattr(el, k) for k in AttivitaIn.model_fields}}
        if figli:
            rischi = _per_codice(await sessione.scalars(select(AcRischio).where(AcRischio.attivita_id == el.id)))
            dati["rischi"] = [await _istantanea(sessione, "RISCHIO", r, figli=True) for r in rischi]
        return dati
    dati = {"codice": el.codice, **{k: getattr(el, k) for k in ProcessoIn.model_fields}}
    dati["tipo"] = dati["tipo"] or "PROCESSO"
    if figli:
        attivita = _per_codice(await sessione.scalars(select(AcAttivita).where(AcAttivita.processo_id == el.id)))
        dati["attivita"] = [await _istantanea(sessione, "ATTIVITA", a, figli=True) for a in attivita]
    return dati


def _json(dati: dict) -> dict:
    return json.loads(json.dumps(dati, default=str))


async def _verifica_dati(sessione, d: BaseModel, m: Metodologia) -> dict:
    """Dati validi (aree, strutture, obblighi, valutazioni) con l'esito delle valutazioni, da
    mostrare nella proposta; i codici si assegnano all'approvazione."""
    risultato = d.model_dump()
    if isinstance(d, ProcessoIn):
        await _verifica_processo(sessione, d)
    if isinstance(d, MisuraIn):
        await _verifica_misura(sessione, d)
    if isinstance(d, RischioModificato | RischioNuovo) and d.valutazione is not None:
        esito, _ = _esito(m, d.valutazione)
        risultato["valutazione"].update(esito.model_dump())
    for campo in ("attivita", "rischi", "misure"):
        figli = getattr(d, campo, None)
        if figli:
            risultato[campo] = [await _verifica_dati(sessione, f, m) for f in figli]
    return risultato


async def _controlla_permesso(sessione, processo: AcProcesso | None, strutture: list[str | None]) -> None:
    """Il referente propone solo per i processi della sua struttura e delle sottostanti; le
    aree non hanno struttura. Il RPCT non ha limiti."""
    ammesse = await _strutture_dell_utente(sessione)
    if ammesse is None:
        return
    if not ammesse:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Per fare proposte serve la tua struttura nel profilo: chiedila all'amministratore")
    if processo is not None and processo.struttura_id not in ammesse:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Puoi fare proposte solo sui processi della tua struttura")
    if any(s not in ammesse for s in strutture):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Il processo va assegnato alla tua struttura (o a una sottostante)")


def _proposta(pr: AcProposta, autore: User | None, *, dati: bool = False) -> dict:
    contesto = pr.contesto or {}
    risultato = {
        "id": pr.id, "tipo": pr.tipo, "oggetto": pr.oggetto, "stato": pr.stato,
        "elemento_id": pr.elemento_id, "padre_id": pr.padre_id, "processo_id": pr.processo_id,
        "codice": contesto.get("codice"), "titolo": contesto.get("titolo"), "percorso": contesto.get("percorso", []),
        "nota": pr.nota, "motivazione": pr.motivazione, "utente_id": pr.utente_id,
        "autore": (autore.nome_completo or autore.username) if autore else None,
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "inviata_il": pr.inviata_il.isoformat() if pr.inviata_il else None,
        "decisa_il": pr.decisa_il.isoformat() if pr.decisa_il else None,
    }  # fmt: skip
    if dati:
        risultato["dati"], risultato["prima"] = pr.dati, pr.prima
    return risultato


def _e_rpct() -> bool:
    return utente().ha_ruolo(Ruolo.ADMIN, Ruolo.ANTICORRUZIONE_RPCT)


async def _proposta_visibile(sessione, proposta_id: str) -> AcProposta:
    """Proposta dell'utente; il RPCT vede anche quelle degli altri."""
    pr = await sessione.get(AcProposta, proposta_id)
    if pr is None or pr.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Proposta non trovata")
    if pr.utente_id != utente().id and not _e_rpct():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Proposta non trovata")
    return pr


async def _proposta_propria(sessione, proposta_id: str) -> AcProposta:
    """Proposta dell'utente non ancora decisa (inviata o restituita): si corregge o si ritira."""
    pr = await _proposta_visibile(sessione, proposta_id)
    if pr.utente_id != utente().id:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "La proposta è di un altro utente")
    if pr.stato not in ("INVIATA", "RESTITUITA"):
        raise ErroreApi(HTTPStatus.CONFLICT, "La proposta è già stata decisa")
    return pr


class FiltriProposte(BaseModel):
    stato: Literal["INVIATA", "APPROVATA", "RESPINTA", "RESTITUITA"] | None = None


@bp.get("/proposte")
@lettore
async def proposte():
    """Proposte dell'utente; per il RPCT anche quelle degli altri."""
    f = parametri(FiltriProposte)
    sessione = db()
    q = select(AcProposta, User).join(User, User.id == AcProposta.utente_id).where(AcProposta.ente_id == ente_id())
    if f.stato:
        q = q.where(AcProposta.stato == f.stato)
    righe = (await sessione.execute(q.order_by(AcProposta.created_at.desc()))).all()
    return [_proposta(pr, u) for pr, u in righe if pr.utente_id == utente().id or _e_rpct()]


async def _cambiato(sessione, pr: AcProposta) -> bool:
    """La modifica o l'eliminazione inviata riguarda un elemento cambiato (o sparito) dopo."""
    if pr.tipo == "CREA" or pr.stato != "INVIATA":
        return False
    try:
        el = await _elemento(sessione, pr.oggetto, pr.elemento_id)
    except ErroreApi:
        return True
    if pr.tipo == "ELIMINA":
        return False
    return _json(await _istantanea(sessione, pr.oggetto, el)) != pr.prima


@bp.get("/proposte/<proposta_id>")
@lettore
async def proposta(proposta_id: str):
    """Proposta con i dati (per una modifica anche com'era l'elemento) e se l'elemento è
    cambiato dopo."""
    sessione = db()
    pr = await _proposta_visibile(sessione, proposta_id)
    risultato = _proposta(pr, await sessione.get(User, pr.utente_id), dati=True)
    risultato["cambiato"] = await _cambiato(sessione, pr)
    return risultato


class PropostaNuova(BaseModel):
    tipo: Literal["CREA", "MODIFICA", "ELIMINA"]
    oggetto: Oggetto
    elemento_id: str | None = None  # modifica ed eliminazione
    padre_id: str | None = None  # creazione di attività (processo), rischio (attività), misura (rischio)
    dati: dict | None = None  # creazione e modifica (se manca: l'elemento com'è)
    nota: str | None = Field(default=None, max_length=5000)


async def _prepara(sessione, pr: AcProposta, dati: dict | None) -> None:
    """Controlla permessi e dati della proposta e ne compone dati, stato precedente e contesto."""
    m = await metodologia_ente()
    if pr.tipo == "CREA":
        padre = await _elemento(sessione, PADRE[pr.oggetto], pr.padre_id) if pr.oggetto in PADRE else None
        d = _dati_proposta(pr.oggetto, "CREA", dati)
        processo = await _processo_di(sessione, PADRE[pr.oggetto], padre) if padre else None
        await _controlla_permesso(sessione, processo, [d.struttura_id] if pr.oggetto == "PROCESSO" else [])
        pr.dati = await _verifica_dati(sessione, d, m)
        if padre:
            percorso = await _percorso(sessione, PADRE[pr.oggetto], padre)
        elif pr.oggetto == "PROCESSO" and d.area_id:
            percorso = await _percorso(sessione, "AREA", await _area_dell_ente(sessione, d.area_id))
        else:
            percorso = []
        pr.contesto = {"percorso": percorso, "codice": None, "titolo": _titolo(pr.oggetto, pr.dati)}
    else:
        el = await _elemento(sessione, pr.oggetto, pr.elemento_id)
        processo = await _processo_di(sessione, pr.oggetto, el)
        attuale = _json(await _istantanea(sessione, pr.oggetto, el, figli=pr.tipo == "ELIMINA"))
        if pr.tipo == "MODIFICA":
            d = _dati_proposta(pr.oggetto, "MODIFICA", dati if dati is not None else attuale)
            await _controlla_permesso(sessione, processo, [d.struttura_id] if pr.oggetto == "PROCESSO" else [])
            pr.dati, pr.prima = await _verifica_dati(sessione, d, m), _json(await _istantanea(sessione, pr.oggetto, el))
        else:
            await _controlla_permesso(sessione, processo, [])
            if pr.oggetto == "AREA":
                await _controlla_area_vuota(sessione, el)
            pr.dati = attuale
        padre = await _padre(sessione, pr.oggetto, el)
        pr.contesto = {"percorso": await _percorso(sessione, *padre) if padre else [], "codice": el.codice,
                       "titolo": _titolo(pr.oggetto, attuale)}  # fmt: skip
    pr.processo_id = processo.id if processo else None


# --- notifiche email delle proposte ----------------------------------------------------------
# Al RPCT quando arriva (o torna corretta) una proposta, al referente quando il RPCT decide.
# Si mettono in coda nella stessa transazione (common/posta.py); le invia il worker.

_TIPI_PROPOSTA = {"CREA": "Creazione", "MODIFICA": "Modifica", "ELIMINA": "Eliminazione"}
_OGGETTI_PROPOSTA = {"AREA": "area di rischio", "PROCESSO": "processo o procedimento", "ATTIVITA": "attività",
                     "RISCHIO": "rischio", "MISURA": "misura"}  # fmt: skip
_ESITI = {"APPROVATA": "approvata", "RESPINTA": "respinta", "RESTITUITA": "restituita per una correzione"}


def _descrizione_proposta(pr: AcProposta) -> str:
    c = pr.contesto or {}
    testo = f"{_TIPI_PROPOSTA.get(pr.tipo, pr.tipo)} - {_OGGETTI_PROPOSTA.get(pr.oggetto, pr.oggetto)}"
    if c.get("codice"):
        testo += f" {c['codice']}"
    if c.get("titolo"):
        testo += f": {c['titolo']}"
    return testo


async def _indirizzo_app(sessione, e: Ente) -> str | None:
    """Indirizzo dell'app per l'ente (il suo primo dominio), per i link nelle email."""
    dominio = await sessione.scalar(
        select(EnteDominio.dominio).where(EnteDominio.ente_id == e.id).order_by(EnteDominio.dominio).limit(1)
    )
    return f"https://{dominio}" if dominio else None


def _dettagli_proposta(pr: AcProposta) -> str:
    righe = [f"  {_descrizione_proposta(pr)}"]
    if percorso := (pr.contesto or {}).get("percorso"):
        righe.append(f"  Posizione nella mappatura: {' > '.join(percorso)}")
    return "\n".join(righe)


def _firma(e: Ente, link: str | None) -> str:
    accesso = f"Atti PA, Anticorruzione > Proposte:\n{link}\n" if link else "Atti PA, Anticorruzione > Proposte.\n"
    return f"\nLa proposta si consulta in {accesso}\n--\nEmail inviata automaticamente da Atti PA per {e.nome}.\n"


async def _notifica_rpct(sessione, pr: AcProposta, autore: User, reinviata: bool) -> None:
    e = await sessione.get(Ente, pr.ente_id)
    if posta.config_ente(e.smtp_json) is None:
        return
    utenti = await sessione.scalars(select(User).where(User.ente_id == e.id, User.attivo.is_(True)))
    destinatari = [u.email for u in utenti if u.ha_ruolo(Ruolo.ANTICORRUZIONE_RPCT) and u.id != autore.id]
    struttura = await sessione.get(Struttura, autore.struttura_id) if autore.struttura_id else None
    chi = autore.nome_completo or autore.username
    if struttura is not None:
        chi += f" ({struttura.codice} - {struttura.descrizione})"
    azione = "ha corretto e reinviato una proposta restituita" if reinviata else "ha inviato una proposta"
    testo = f"{chi} {azione}, da approvare:\n\n{_dettagli_proposta(pr)}\n"
    if pr.nota:
        testo += f"\nNota del referente:\n{pr.nota}\n"
    oggetto = f"[Anticorruzione] {'Proposta reinviata' if reinviata else 'Nuova proposta'} da approvare: {_descrizione_proposta(pr)}"
    posta.accoda(sessione, e, destinatari, oggetto, testo + _firma(e, await _indirizzo_app(sessione, e)),
                 origine=f"ac_proposta:{pr.id}")  # fmt: skip


async def _notifica_referente(sessione, pr: AcProposta) -> None:
    e = await sessione.get(Ente, pr.ente_id)
    if posta.config_ente(e.smtp_json) is None:
        return
    autore = await sessione.get(User, pr.utente_id)
    if autore is None or not autore.attivo:
        return
    esito = _ESITI.get(pr.stato, pr.stato.lower())
    testo = f"La tua proposta è stata {esito} dal RPCT:\n\n{_dettagli_proposta(pr)}\n"
    if pr.motivazione:
        testo += f"\nMotivazione:\n{pr.motivazione}\n"
    if pr.stato == "RESTITUITA":
        testo += "\nPuoi correggerla e reinviarla, oppure ritirarla.\n"
    oggetto = f"[Anticorruzione] Proposta {esito}: {_descrizione_proposta(pr)}"
    posta.accoda(sessione, e, [autore.email], oggetto, testo + _firma(e, await _indirizzo_app(sessione, e)),
                 origine=f"ac_proposta:{pr.id}")  # fmt: skip


@bp.post("/proposte")
@lettore
async def crea_proposta():
    """La proposta va subito al RPCT; finché non decide, il referente la corregge o la ritira."""
    dati = corpo(PropostaNuova)
    sessione = db()
    pr = AcProposta(ente_id=ente_id(), utente_id=utente().id, tipo=dati.tipo, oggetto=dati.oggetto, nota=dati.nota,
                    stato="INVIATA", inviata_il=datetime.now(), padre_id=dati.padre_id if dati.tipo == "CREA" else None,
                    elemento_id=dati.elemento_id if dati.tipo != "CREA" else None)  # fmt: skip
    await _prepara(sessione, pr, dati.dati)
    sessione.add(pr)
    await sessione.flush()
    audit(sessione, utente(), "ac_proposta", pr.id, "CREATA", {"tipo": pr.tipo, "oggetto": pr.oggetto})
    await _notifica_rpct(sessione, pr, utente(), reinviata=False)
    await sessione.commit()
    await sessione.refresh(pr)  # created_at: con MySQL il valore del database non torna con l'inserimento
    return _proposta(pr, utente(), dati=True), HTTPStatus.CREATED


class PropostaIn(BaseModel):
    dati: dict | None = None  # non per l'eliminazione
    nota: str | None = Field(default=None, max_length=5000)


@bp.put("/proposte/<proposta_id>")
@lettore
async def aggiorna_proposta(proposta_id: str):
    """Correzione di una proposta non ancora decisa; quella restituita torna al RPCT."""
    dati = corpo(PropostaIn)
    sessione = db()
    pr = await _proposta_propria(sessione, proposta_id)
    if dati.dati is not None and pr.tipo != "ELIMINA":
        await _prepara(sessione, pr, dati.dati)
    pr.nota = dati.nota
    if pr.stato == "RESTITUITA":
        pr.stato, pr.inviata_il = "INVIATA", datetime.now()
        audit(sessione, utente(), "ac_proposta", pr.id, "REINVIATA")
        await _notifica_rpct(sessione, pr, utente(), reinviata=True)
    await sessione.commit()
    return _proposta(pr, utente(), dati=True)


@bp.delete("/proposte/<proposta_id>")
@lettore
async def ritira_proposta(proposta_id: str):
    """Ritira una proposta non ancora decisa."""
    sessione = db()
    pr = await _proposta_propria(sessione, proposta_id)
    audit(sessione, utente(), "ac_proposta", pr.id, "RITIRATA")
    await sessione.delete(pr)
    await sessione.commit()
    return nessun_contenuto()


class DecisioneIn(BaseModel):
    motivazione: str | None = Field(default=None, max_length=5000)
    forza: bool = False  # approva anche se l'elemento è cambiato dopo la proposta


async def _proposta_inviata(sessione, proposta_id: str) -> AcProposta:
    pr = await _proposta_visibile(sessione, proposta_id)
    if pr.stato != "INVIATA":
        raise ErroreApi(HTTPStatus.CONFLICT, "Si decidono solo le proposte inviate")
    return pr


async def _applica(sessione, pr: AcProposta, forza: bool):
    """Applica la proposta alla mappatura; restituisce l'elemento creato o modificato."""
    m = await metodologia_ente()
    if pr.tipo == "CREA":
        d = _dati_proposta(pr.oggetto, "CREA", pr.dati)
        if pr.oggetto == "AREA":
            return await _crea_area(sessione, d)
        if pr.oggetto == "PROCESSO":
            return await _crea_processo_completo(sessione, d, m)
        try:
            padre = await _elemento(sessione, PADRE[pr.oggetto], pr.padre_id)
        except ErroreApi as e:
            raise ErroreApi(HTTPStatus.CONFLICT, "L'elemento a cui si aggiunge la proposta non esiste più") from e
        crea = {"ATTIVITA": _crea_attivita_completa, "RISCHIO": _crea_rischio_completo}.get(pr.oggetto)
        return await crea(sessione, padre, d, m) if crea else await _crea_misura(sessione, padre, d)
    try:
        el = await _elemento(sessione, pr.oggetto, pr.elemento_id)
    except ErroreApi as e:
        raise ErroreApi(HTTPStatus.CONFLICT, "L'elemento della proposta non esiste più") from e
    if pr.tipo == "ELIMINA":
        elimina = {"AREA": None, "PROCESSO": _elimina_processo, "ATTIVITA": _elimina_attivita,
                   "RISCHIO": _elimina_rischio, "MISURA": _elimina_misura}[pr.oggetto]  # fmt: skip
        if elimina is None:
            await _controlla_area_vuota(sessione, el)
            await sessione.delete(el)
        else:
            await elimina(sessione, el)
        return el
    if not forza and _json(await _istantanea(sessione, pr.oggetto, el)) != pr.prima:
        raise ErroreApi(HTTPStatus.CONFLICT, "L'elemento è stato modificato dopo la proposta: verifica le differenze e conferma")
    d = _dati_proposta(pr.oggetto, "MODIFICA", pr.dati)
    if pr.oggetto == "AREA":
        _modifica_area(el, d)
    elif pr.oggetto == "PROCESSO":
        await _modifica_processo(sessione, el, d)
    elif pr.oggetto == "ATTIVITA":
        await _modifica_attivita(sessione, el, d)
    elif pr.oggetto == "RISCHIO":
        await _modifica_rischio(sessione, el, d)
        _valuta(el, m, d.valutazione)
    else:
        await _modifica_misura(sessione, el, d)
    return el


@bp.post("/proposte/<proposta_id>/approva")
@rpct
async def approva_proposta(proposta_id: str):
    """Applica la proposta alla mappatura (con i codici assegnati ora)."""
    dati = corpo(DecisioneIn)
    sessione = db()
    pr = await _proposta_inviata(sessione, proposta_id)
    el = await _applica(sessione, pr, dati.forza)
    await sessione.flush()
    if pr.tipo == "CREA":
        pr.elemento_id = el.id
        if pr.oggetto == "PROCESSO":
            pr.processo_id = el.id
    pr.contesto = {**(pr.contesto or {}), "codice": el.codice}
    pr.stato, pr.motivazione = "APPROVATA", dati.motivazione
    pr.deciso_da, pr.decisa_il = utente().id, datetime.now()
    audit(sessione, utente(), "ac_proposta", pr.id, "APPROVATA",
          {"tipo": pr.tipo, "oggetto": pr.oggetto, "codice": el.codice})  # fmt: skip
    await _notifica_referente(sessione, pr)
    await sessione.commit()
    return _proposta(pr, await sessione.get(User, pr.utente_id))


async def _decidi(proposta_id: str, stato: str) -> dict:
    dati = corpo(DecisioneIn)
    if not (dati.motivazione or "").strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Serve la motivazione")
    sessione = db()
    pr = await _proposta_inviata(sessione, proposta_id)
    pr.stato, pr.motivazione = stato, dati.motivazione.strip()
    pr.deciso_da, pr.decisa_il = utente().id, datetime.now()
    audit(sessione, utente(), "ac_proposta", pr.id, stato)
    await _notifica_referente(sessione, pr)
    await sessione.commit()
    return _proposta(pr, await sessione.get(User, pr.utente_id))


@bp.post("/proposte/<proposta_id>/respingi")
@rpct
async def respingi_proposta(proposta_id: str):
    return await _decidi(proposta_id, "RESPINTA")


@bp.post("/proposte/<proposta_id>/restituisci")
@rpct
async def restituisci_proposta(proposta_id: str):
    """Torna al referente, che la corregge e la reinvia."""
    return await _decidi(proposta_id, "RESTITUITA")


# --- monitoraggio delle misure -------------------------------------------------------------

STATI_ATTUAZIONE = ("ATTUATA", "PARZIALE", "NON_ATTUATA")


async def _misure_con_contesto(sessione) -> list[dict]:
    """Tutte le misure dell'ente con rischio, attività, processo e la struttura responsabile
    (della misura o, se manca, del processo; nessuna: misura trasversale)."""
    processi = {p.id: p for p in await sessione.scalars(select(AcProcesso).where(AcProcesso.ente_id == ente_id()))}
    attivita = {a.id: a for a in await sessione.scalars(select(AcAttivita).where(AcAttivita.ente_id == ente_id()))}
    rischi = {r.id: r for r in await sessione.scalars(select(AcRischio).where(AcRischio.ente_id == ente_id()))}
    risultato = []
    for m in _per_codice(await sessione.scalars(select(AcMisura).where(AcMisura.ente_id == ente_id()))):
        r = rischi[m.rischio_id]
        a = attivita[r.attivita_id]
        p = processi[a.processo_id]
        risultato.append({"misura": m, "rischio": r, "attivita": a, "processo": p,
                          "responsabile": m.struttura_id or p.struttura_id})  # fmt: skip
    return risultato


def _contesto(voce: dict, struttura: Struttura) -> dict:
    m, r, a, p = voce["misura"], voce["rischio"], voce["attivita"], voce["processo"]
    return {
        "misura": {"codice": m.codice, "descrizione": m.descrizione, "tipo": m.tipo, "categoria": m.categoria,
                   "indicatore": m.indicatore, "target": m.target},
        "rischio": {"codice": r.codice, "evento": r.evento, "livello": r.livello},
        "attivita": {"codice": a.codice, "descrizione": a.descrizione},
        "processo": {"codice": p.codice, "denominazione": p.denominazione},
        "struttura": {"codice": struttura.codice, "descrizione": struttura.descrizione},
    }  # fmt: skip


def _dichiarazione(d: AcMonitoraggio) -> dict:
    return {
        "id": d.id, "anno": d.anno, "misura_id": d.misura_id, "struttura_id": d.struttura_id,
        "contesto": d.contesto, "stato_attuazione": d.stato_attuazione, "motivazione": d.motivazione,
        "indicatore_rilevato": d.indicatore_rilevato, "target": d.target, "evidenze": d.evidenze,
        "dichiarato_da": d.dichiarato_da, "dichiarato_il": d.dichiarato_il.isoformat() if d.dichiarato_il else None,
        "stato_verifica": d.stato_verifica, "note_rpct": d.note_rpct,
        "verificato_il": d.verificato_il.isoformat() if d.verificato_il else None,
    }  # fmt: skip


async def _strutture_dell_utente(sessione) -> set[str] | None:
    """Strutture su cui l'utente dichiara: la sua e le sottostanti; None per il RPCT (tutte)."""
    if _e_rpct():
        return None
    if not utente().struttura_id:
        return set()
    return _sottostanti(await _strutture_ente(sessione), utente().struttura_id)


def _anno_valido(anno: int) -> None:
    if not 2000 <= anno <= 2100:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Anno non valido")


@bp.get("/monitoraggio/anni")
@lettore
async def anni_monitoraggio():
    """Anni con dichiarazioni, dal più recente, più l'anno in corso."""
    anni = set(await db().scalars(select(AcMonitoraggio.anno).where(AcMonitoraggio.ente_id == ente_id()).distinct()))
    return sorted(anni | {datetime.now().year}, reverse=True)


class SceltaStruttura(BaseModel):
    struttura: str | None = None


@bp.get("/monitoraggio/<int:anno>/misure")
@lettore
async def misure_da_dichiarare(anno: int):
    """Misure che la struttura dichiara nell'anno (quelle di cui è responsabile, anche tramite
    le strutture sottostanti, e le trasversali) con la dichiarazione, se c'è. Di norma la
    struttura è quella dell'utente."""
    _anno_valido(anno)
    sessione = db()
    struttura_id = parametri(SceltaStruttura).struttura or utente().struttura_id
    if not struttura_id:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica la struttura (al tuo utente non ne è assegnata una)")
    strutture = await _strutture_ente(sessione)
    if struttura_id not in strutture:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Struttura non trovata")
    ammesse = await _strutture_dell_utente(sessione)
    if ammesse is not None and struttura_id not in ammesse:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "La struttura non è tra le tue")
    sotto = _sottostanti(strutture, struttura_id)
    dichiarazioni = {
        (d.misura_id, d.struttura_id): d
        for d in await sessione.scalars(select(AcMonitoraggio).where(AcMonitoraggio.ente_id == ente_id(), AcMonitoraggio.anno == anno))
    }  # fmt: skip
    risultato = []
    for voce in await _misure_con_contesto(sessione):
        responsabile = voce["responsabile"]
        if responsabile is not None and responsabile not in sotto:
            continue
        dichiarante = responsabile or struttura_id  # la trasversale la dichiara la struttura scelta
        d = dichiarazioni.get((voce["misura"].id, dichiarante))
        risultato.append({
            "misura_id": voce["misura"].id, "struttura_id": dichiarante, "trasversale": responsabile is None,
            "contesto": _contesto(voce, strutture[dichiarante]),
            "dichiarazione": _dichiarazione(d) if d else None,
        })  # fmt: skip
    return risultato


class DichiarazioneIn(BaseModel):
    struttura_id: str | None = None  # misure trasversali: chi dichiara (di norma la struttura dell'utente)
    stato_attuazione: Literal["ATTUATA", "PARZIALE", "NON_ATTUATA"]
    motivazione: str | None = Field(default=None, max_length=10_000)
    indicatore_rilevato: str | None = Field(default=None, max_length=2000)
    target: str | None = Field(default=None, max_length=2000)
    evidenze: str | None = Field(default=None, max_length=10_000)


@bp.put("/monitoraggio/<int:anno>/misure/<misura_id>")
@lettore
async def dichiara(anno: int, misura_id: str):
    """Dichiarazione (nuova o corretta) sull'attuazione della misura. Una dichiarazione
    verificata è chiusa; una contestata, corretta, torna da verificare."""
    _anno_valido(anno)
    dati = corpo(DichiarazioneIn)
    if dati.stato_attuazione != "ATTUATA" and not (dati.motivazione or "").strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "La motivazione è obbligatoria se la misura non è pienamente attuata")
    sessione = db()
    voce = next((v for v in await _misure_con_contesto(sessione) if v["misura"].id == misura_id), None)
    if voce is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Misura non trovata")
    struttura_id = voce["responsabile"] or dati.struttura_id or utente().struttura_id
    if not struttura_id:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Per una misura trasversale indica la struttura che dichiara")
    strutture = await _strutture_ente(sessione)
    if struttura_id not in strutture:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Struttura non trovata")
    ammesse = await _strutture_dell_utente(sessione)
    if ammesse is not None and struttura_id not in ammesse:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "La misura non è di una tua struttura")
    d = await sessione.scalar(select(AcMonitoraggio).where(
        AcMonitoraggio.ente_id == ente_id(), AcMonitoraggio.anno == anno,
        AcMonitoraggio.misura_id == misura_id, AcMonitoraggio.struttura_id == struttura_id,
    ))  # fmt: skip
    if d is not None and d.stato_verifica == "VERIFICATA":
        raise ErroreApi(HTTPStatus.CONFLICT, "La dichiarazione è già stata verificata e non si modifica più")
    if d is None:
        d = AcMonitoraggio(ente_id=ente_id(), anno=anno, misura_id=misura_id, struttura_id=struttura_id)
        sessione.add(d)
    d.contesto = _contesto(voce, strutture[struttura_id])
    d.stato_attuazione, d.motivazione = dati.stato_attuazione, (dati.motivazione or "").strip() or None
    d.indicatore_rilevato, d.target, d.evidenze = dati.indicatore_rilevato, dati.target, dati.evidenze
    d.dichiarato_da, d.dichiarato_il = utente().id, datetime.now()
    d.stato_verifica = "DA_VERIFICARE"
    await sessione.flush()
    audit(sessione, utente(), "ac_monitoraggio", d.id, "DICHIARATA",
          {"anno": anno, "misura": voce["misura"].codice, "stato": d.stato_attuazione})  # fmt: skip
    await sessione.commit()
    return _dichiarazione(d)


class FiltriDichiarazioni(BaseModel):
    struttura: str | None = None  # la struttura e le sottostanti
    stato_attuazione: Literal["ATTUATA", "PARZIALE", "NON_ATTUATA"] | None = None
    stato_verifica: Literal["DA_VERIFICARE", "VERIFICATA", "CONTESTATA"] | None = None


async def _dichiarazioni(sessione, anno: int, f: FiltriDichiarazioni) -> list[AcMonitoraggio]:
    """Dichiarazioni dell'anno visibili all'utente (il RPCT tutte, il referente quelle delle
    sue strutture), filtrate e ordinate per struttura e misura."""
    righe = list(await sessione.scalars(
        select(AcMonitoraggio).where(AcMonitoraggio.ente_id == ente_id(), AcMonitoraggio.anno == anno)))  # fmt: skip
    ammesse = await _strutture_dell_utente(sessione)
    if f.struttura:
        sotto = _sottostanti(await _strutture_ente(sessione), f.struttura)
        ammesse = sotto if ammesse is None else ammesse & sotto
    return sorted(
        (d for d in righe
         if (ammesse is None or d.struttura_id in ammesse)
         and (f.stato_attuazione is None or d.stato_attuazione == f.stato_attuazione)
         and (f.stato_verifica is None or d.stato_verifica == f.stato_verifica)),
        key=lambda d: (chiave_naturale(d.contesto["struttura"]["codice"]), chiave_naturale(d.contesto["misura"]["codice"])),
    )  # fmt: skip


@bp.get("/monitoraggio/<int:anno>")
@lettore
async def dichiarazioni(anno: int):
    _anno_valido(anno)
    return [_dichiarazione(d) for d in await _dichiarazioni(db(), anno, parametri(FiltriDichiarazioni))]


class VerificaIn(BaseModel):
    note: str | None = Field(default=None, max_length=10_000)


async def _verifica(dichiarazione_id: str, stato: str) -> dict:
    dati = corpo(VerificaIn)
    if stato == "CONTESTATA" and not (dati.note or "").strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Per contestare serve una nota")
    sessione = db()
    d = await sessione.get(AcMonitoraggio, dichiarazione_id)
    if d is None or d.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Dichiarazione non trovata")
    if d.stato_verifica == "VERIFICATA":
        raise ErroreApi(HTTPStatus.CONFLICT, "La dichiarazione è già verificata")
    d.stato_verifica, d.note_rpct = stato, (dati.note or "").strip() or None
    d.verificato_da, d.verificato_il = utente().id, datetime.now()
    audit(sessione, utente(), "ac_monitoraggio", d.id, stato)
    await sessione.commit()
    return _dichiarazione(d)


@bp.post("/monitoraggio/dichiarazioni/<dichiarazione_id>/verifica")
@rpct
async def verifica_dichiarazione(dichiarazione_id: str):
    return await _verifica(dichiarazione_id, "VERIFICATA")


@bp.post("/monitoraggio/dichiarazioni/<dichiarazione_id>/contesta")
@rpct
async def contesta_dichiarazione(dichiarazione_id: str):
    """La struttura corregge la dichiarazione, che torna da verificare."""
    return await _verifica(dichiarazione_id, "CONTESTATA")


def _conteggi(righe) -> dict:
    c = {"totale": 0, "attuate": 0, "parziali": 0, "non_attuate": 0, "verificate": 0, "contestate": 0}
    for d in righe:
        c["totale"] += 1
        c[{"ATTUATA": "attuate", "PARZIALE": "parziali", "NON_ATTUATA": "non_attuate"}[d.stato_attuazione]] += 1
        if d.stato_verifica == "VERIFICATA":
            c["verificate"] += 1
        elif d.stato_verifica == "CONTESTATA":
            c["contestate"] += 1
    c["percentuale_attuate"] = round(c["attuate"] / c["totale"] * 100, 1) if c["totale"] else 0
    return c


@bp.get("/monitoraggio/<int:anno>/cruscotto")
@lettore
async def cruscotto(anno: int):
    """Per struttura: misure attese (non trasversali), dichiarate, attuate, verificate...;
    totali dell'anno e confronto con gli altri anni."""
    _anno_valido(anno)
    sessione = db()
    righe = await _dichiarazioni(sessione, anno, FiltriDichiarazioni())
    strutture = await _strutture_ente(sessione)
    ammesse = await _strutture_dell_utente(sessione)
    attese: dict[str, int] = {}
    for voce in await _misure_con_contesto(sessione):
        if voce["responsabile"] is not None:
            attese[voce["responsabile"]] = attese.get(voce["responsabile"], 0) + 1
    per_struttura = []
    for sid in set(attese) | {d.struttura_id for d in righe if d.struttura_id}:
        if ammesse is not None and sid not in ammesse:
            continue
        s = strutture.get(sid)
        per_struttura.append({
            "struttura_id": sid, "codice": s.codice if s else "?", "descrizione": s.descrizione if s else "",
            "attese": attese.get(sid, 0), **_conteggi(d for d in righe if d.struttura_id == sid),
        })  # fmt: skip
    per_struttura.sort(key=lambda x: chiave_naturale(x["codice"]))
    anni = []
    for a in await anni_monitoraggio():
        anni.append({"anno": a, **_conteggi(await _dichiarazioni(sessione, a, FiltriDichiarazioni()))})
    return {"anno": anno, "totale": _conteggi(righe), "strutture": per_struttura, "anni": anni}


ETICHETTE_ATTUAZIONE = {"ATTUATA": "Attuata", "PARZIALE": "Parzialmente attuata", "NON_ATTUATA": "Non attuata"}
ETICHETTE_VERIFICA = {"DA_VERIFICARE": "Da verificare", "VERIFICATA": "Verificata", "CONTESTATA": "Contestata"}


@bp.get("/monitoraggio/<int:anno>/esporta")
@lettore
async def esporta_monitoraggio(anno: int):
    """Le dichiarazioni dell'anno visibili all'utente, in Excel."""
    _anno_valido(anno)
    sessione = db()
    righe = await _dichiarazioni(sessione, anno, parametri(FiltriDichiarazioni))
    nomi = {u.id: u.nome_completo or u.username
            for u in await sessione.scalars(select(User).where(User.ente_id == ente_id()))}  # fmt: skip
    intestazioni = [
        "Anno", "Struttura", "Descrizione struttura", "Processo", "Denominazione processo", "Attività",
        "Descrizione attività", "Rischio", "Evento rischioso", "Misura", "Descrizione misura",
        "Stato di attuazione", "Motivazione", "Indicatore rilevato", "Target", "Evidenze",
        "Stato della verifica", "Note del RPCT", "Dichiarata da", "Data della dichiarazione",
        "Verificata da", "Data della verifica",
    ]  # fmt: skip
    contenuto = excel.foglio(f"Monitoraggio {anno}", intestazioni, [
        [d.anno, c["struttura"]["codice"], c["struttura"]["descrizione"], c["processo"]["codice"],
         c["processo"]["denominazione"], c["attivita"]["codice"], c["attivita"]["descrizione"],
         c["rischio"]["codice"], c["rischio"]["evento"], c["misura"]["codice"], c["misura"]["descrizione"],
         ETICHETTE_ATTUAZIONE[d.stato_attuazione], d.motivazione, d.indicatore_rilevato, d.target, d.evidenze,
         ETICHETTE_VERIFICA.get(d.stato_verifica, d.stato_verifica), d.note_rpct, nomi.get(d.dichiarato_da),
         d.dichiarato_il.strftime("%d/%m/%Y %H:%M") if d.dichiarato_il else None, nomi.get(d.verificato_da),
         d.verificato_il.strftime("%d/%m/%Y %H:%M") if d.verificato_il else None]
        for d in righe for c in [d.contesto]
    ])  # fmt: skip
    return allegato(contenuto, excel.MIME, f"monitoraggio_{anno}.xlsx")


# --- riepilogo ed esportazione per il PTPCT -----------------------------------------------


@bp.get("/riepilogo")
@lettore
async def riepilogo():
    """Totali della mappatura e distribuzione dei rischi per livello, per area e per struttura
    responsabile del processo (livelli nell'ordine della metodologia)."""
    sessione = db()
    m = await metodologia_ente()
    processi = {p.id: p for p in await sessione.scalars(select(AcProcesso).where(AcProcesso.ente_id == ente_id()))}
    attivita = {a.id: a for a in await sessione.scalars(select(AcAttivita).where(AcAttivita.ente_id == ente_id()))}
    rischi = list(await sessione.scalars(select(AcRischio).where(AcRischio.ente_id == ente_id())))
    misure = list(await sessione.scalars(select(AcMisura).where(AcMisura.ente_id == ente_id())))
    aree = {a.id: a for a in await sessione.scalars(select(AcArea).where(AcArea.ente_id == ente_id()))}
    strutture = await _strutture_ente(sessione)
    livelli = [*reversed(m.livelli), None]  # dal più grave; None: non valutato

    def distribuzione(righe) -> dict:
        conteggi = {str(liv): 0 for liv in livelli}
        for r in righe:
            conteggi[str(r.livello if r.livello in m.livelli else None)] += 1
        return conteggi

    per_area: dict[str | None, list] = {}
    per_struttura: dict[str | None, list] = {}
    for r in rischi:
        p = processi[attivita[r.attivita_id].processo_id]
        per_area.setdefault(p.area_id, []).append(r)
        per_struttura.setdefault(p.struttura_id, []).append(r)
    return {
        "totali": {"processi": len(processi), "attivita": len(attivita), "rischi": len(rischi), "misure": len(misure),
                   "misure_generali": sum(x.tipo == "GENERALE" for x in misure),
                   "misure_trasparenza": sum(bool(x.obbligo_trasparenza) or x.categoria == "Trasparenza" for x in misure),
                   "rischi_non_valutati": sum(r.livello not in m.livelli for r in rischi)},
        "livelli": [str(liv) for liv in livelli],
        "per_livello": distribuzione(rischi),
        "per_area": sorted(
            ({"area_id": aid, "codice": aree[aid].codice if aid in aree else None,
              "descrizione": aree[aid].descrizione_breve or aree[aid].descrizione if aid in aree else "Senza area",
              "rischi": len(righe), "per_livello": distribuzione(righe)} for aid, righe in per_area.items()),
            key=lambda x: (x["area_id"] not in aree, chiave_area(aree[x["area_id"]]) if x["area_id"] in aree else ()),
        ),
        "per_struttura": sorted(
            ({"struttura_id": sid, "codice": strutture[sid].codice if sid in strutture else None,
              "descrizione": strutture[sid].descrizione if sid in strutture else "Trasversali",
              "rischi": len(righe), "per_livello": distribuzione(righe)} for sid, righe in per_struttura.items()),
            key=lambda x: (x["codice"] is None, chiave_naturale(x["codice"] or "")),
        ),
    }  # fmt: skip


@bp.get("/esporta/ptpct")
@lettore
async def esporta_ptpct():
    """Allegati al PTPCT in Excel: "Processi, rischi, valutazione e misure" (una riga per
    misura, come Si.Ge.Ri.Co., con le colonne nuove in fondo) e "Attuazione delle misure"
    (misure con fasi, tempi o struttura responsabile)."""
    sessione = db()
    aree = {a.id: a for a in await sessione.scalars(select(AcArea).where(AcArea.ente_id == ente_id()))}
    strutture = await _strutture_ente(sessione)
    processi = _per_codice(await sessione.scalars(select(AcProcesso).where(AcProcesso.ente_id == ente_id())))
    attivita = _per_codice(await sessione.scalars(select(AcAttivita).where(AcAttivita.ente_id == ente_id())))
    rischi = _per_codice(await sessione.scalars(select(AcRischio).where(AcRischio.ente_id == ente_id())))
    misure = _per_codice(await sessione.scalars(select(AcMisura).where(AcMisura.ente_id == ente_id())))

    def area(p: AcProcesso) -> str:
        a = aree.get(p.area_id)
        return f"{a.codice}) {a.descrizione}" if a else ""

    def struttura(sid: str | None, vuota: str = "") -> str:
        return f"{strutture[sid].codice} {strutture[sid].descrizione}" if sid in strutture else vuota

    righe, attuazione = [], []
    ordine_aree = {a.id: (0, chiave_area(a)) for a in aree.values()}  # senza area in fondo
    for p in sorted(processi, key=lambda p: (ordine_aree.get(p.area_id, (1, ())), chiave_naturale(p.codice))):
        base_p = [area(p), p.codice, p.denominazione]
        procedimento = ["Procedimento" if p.tipo == "PROCEDIMENTO" else "Processo", p.termine_conclusione,
                        p.norma_riferimento]  # fmt: skip
        responsabilita = struttura(p.struttura_id, "Tutti i servizi/settori")
        attivita_p = [a for a in attivita if a.processo_id == p.id] or [None]
        for a in attivita_p:
            base_a = [a.codice, a.descrizione] if a else ["", ""]
            rischi_a = [r for r in rischi if a and r.attivita_id == a.id] or [None]
            for r in rischi_a:
                base_r = [r.codice, r.evento, r.probabilita, r.impatto, r.livello] if r else ["", "", "", "", ""]
                misure_r = [x for x in misure if r and x.rischio_id == r.id] or [None]
                for x in misure_r:
                    base_m = [x.codice, x.descrizione] if x else ["", ""]
                    extra = ([x.tipo.capitalize(), x.categoria, x.obbligo_trasparenza, r.fattore_abilitante if r else None]
                             if x else ["", "", "", r.fattore_abilitante if r else None])  # fmt: skip
                    righe.append([*base_p, *base_a, *base_r, *base_m, responsabilita, *extra, *procedimento])
                    if x and (x.fasi or x.tempi or x.struttura_id):
                        attuazione.append([x.codice, x.descrizione, x.fasi, x.tempi,
                                           struttura(x.struttura_id) or responsabilita, x.indicatore, x.target])  # fmt: skip
    contenuto = excel.cartella([
        ("PTPC", ["AREA DI RISCHIO", "ID PROCESSO", "PROCESSI", "ID ATTIVITA'", "ATTIVITA'", "ID RISCHIO",
                  "EVENTO RISCHIOSO", "Valore moda indice probabilità", "Valore moda indice impatto",
                  "Valore complessivo del rischio", "ID MISURA", "MISURA", "RESPONSABILITA'", "TIPO DI MISURA",
                  "CATEGORIA", "OBBLIGO DI PUBBLICAZIONE", "FATTORE ABILITANTE", "TIPO", "TERMINE DI CONCLUSIONE",
                  "NORMA DI RIFERIMENTO"], righe),
        ("Attuazione misure", ["ID MISURA", "MISURA", "FASI DI ATTUAZIONE", "TEMPI", "UFFICIO RESPONSABILE",
                               "INDICATORE", "TARGET"], attuazione),
    ])  # fmt: skip
    return allegato(contenuto, excel.MIME, "allegato_ptpct.xlsx")
