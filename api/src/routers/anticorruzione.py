"""Modulo anticorruzione (ripreso da Si.Ge.Ri.Co.): metodologia di valutazione del rischio,
aree di rischio, mappatura dei processi (processo -> attività -> rischio -> misura) con la
valutazione dei rischi, proposte dei referenti, monitoraggio annuale delle misure, PIAO e
obiettivi di performance collegati a processi e attività, riepilogo ed esportazione degli
allegati al PTPCT.

Tutti gli utenti del modulo leggono; il RPCT (e il suo staff) modifica direttamente, i
referenti propongono la creazione, la modifica o l'eliminazione di un processo intero e il
RPCT approva, respinge o restituisce. Nel monitoraggio i referenti dichiarano l'attuazione
delle misure della propria struttura (e delle sottostanti) e il RPCT verifica o contesta.
Logica comune in common/anticorruzione.
"""

from datetime import datetime
from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from deps import audit, autenticato, db, ente_id, utente
from web import ErroreApi, allegato, corpo, file_caricato, nessun_contenuto, parametri
from common.anticorruzione import excel
from common.anticorruzione import obiettivi as importazione_obiettivi
from common.anticorruzione.metodologia import (
    Metodologia, chiave_naturale, prossimo_codice, standard, valuta,
)  # fmt: skip
from common.models import (
    AcArea, AcAttivita, AcMetodologia, AcMisura, AcMonitoraggio, AcObiettivo, AcObiettivoCollegamento,
    AcPiao, AcProcesso, AcProposta, AcRischio, Modulo, Ruolo, Struttura, User, nuovo_id,
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


@bp.get("/obblighi")
@lettore
async def obblighi():
    """Obblighi di pubblicazione (schemi ANAC) a cui collegare le misure di trasparenza."""
    return sorted(
        ({"id": s.id, "articolo": s.articolo, "titolo": s.titolo} for s in SCHEMI.values()),
        key=lambda o: chiave_naturale(o["id"]),
    )


# --- aree di rischio -----------------------------------------------------------------------


class AreaIn(BaseModel):
    codice: str = Field(min_length=1, max_length=20)
    descrizione: str = Field(min_length=1, max_length=500)
    descrizione_breve: str | None = Field(default=None, max_length=255)
    ordine: int = 0


def _area(a: AcArea) -> dict:
    return {"id": a.id, "codice": a.codice, "descrizione": a.descrizione,
            "descrizione_breve": a.descrizione_breve, "ordine": a.ordine}  # fmt: skip


async def _area_dell_ente(sessione, area_id: str) -> AcArea:
    a = await sessione.get(AcArea, area_id)
    if a is None or a.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Area di rischio non trovata")
    return a


async def _codice_libero(sessione, modello, codice: str, escluso: str | None = None) -> None:
    trovato = await sessione.scalar(select(modello).where(modello.ente_id == ente_id(), modello.codice == codice))
    if trovato is not None and trovato.id != escluso:
        raise ErroreApi(HTTPStatus.CONFLICT, f"Codice già usato: {codice}")


@bp.get("/aree")
@lettore
async def aree():
    righe = await db().scalars(select(AcArea).where(AcArea.ente_id == ente_id()))
    return [_area(a) for a in sorted(righe, key=lambda a: (a.ordine, chiave_naturale(a.codice)))]


@bp.post("/aree")
@rpct
async def crea_area():
    dati = corpo(AreaIn)
    sessione = db()
    await _codice_libero(sessione, AcArea, dati.codice.strip())
    a = AcArea(ente_id=ente_id(), **{**dati.model_dump(), "codice": dati.codice.strip()})
    sessione.add(a)
    await sessione.flush()
    audit(sessione, utente(), "ac_area", a.id, "CREATA", {"codice": a.codice})
    await sessione.commit()
    return _area(a), HTTPStatus.CREATED


@bp.put("/aree/<area_id>")
@rpct
async def aggiorna_area(area_id: str):
    dati = corpo(AreaIn)
    sessione = db()
    a = await _area_dell_ente(sessione, area_id)
    await _codice_libero(sessione, AcArea, dati.codice.strip(), escluso=a.id)
    a.codice, a.descrizione = dati.codice.strip(), dati.descrizione
    a.descrizione_breve, a.ordine = dati.descrizione_breve, dati.ordine
    audit(sessione, utente(), "ac_area", a.id, "AGGIORNATA", {"codice": a.codice})
    await sessione.commit()
    return _area(a)


@bp.delete("/aree/<area_id>")
@rpct
async def elimina_area(area_id: str):
    sessione = db()
    a = await _area_dell_ente(sessione, area_id)
    if await sessione.scalar(select(AcProcesso.id).where(AcProcesso.area_id == a.id).limit(1)):
        raise ErroreApi(HTTPStatus.CONFLICT, "L'area ha dei processi: spostali prima di eliminarla")
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
        "id": p.id, "codice": p.codice, "area_id": p.area_id, "denominazione": p.denominazione,
        "descrizione": p.descrizione, "tempi": p.tempi, "attori_esterni": p.attori_esterni,
        "struttura_id": p.struttura_id, "pacchetto": p.pacchetto,
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
    testo: str | None = Field(default=None, max_length=200)


@bp.get("/processi")
@lettore
async def processi():
    """Processi con i conteggi e il livello di rischio più alto tra i loro rischi."""
    f = parametri(FiltriProcessi)
    sessione = db()
    m = await metodologia_ente()
    q = select(AcProcesso).where(AcProcesso.ente_id == ente_id())
    if f.area:
        q = q.where(AcProcesso.area_id == f.area)
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
    return risultato


async def _processo_dell_ente(sessione, processo_id: str) -> AcProcesso:
    p = await sessione.get(AcProcesso, processo_id)
    if p is None or p.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Processo non trovato")
    return p


@bp.get("/processi/<processo_id>")
@lettore
async def processo(processo_id: str):
    """Processo con l'albero delle attività, dei rischi e delle misure."""
    sessione = db()
    return await _albero(sessione, await _processo_dell_ente(sessione, processo_id))


async def _albero(sessione, p: AcProcesso) -> dict:
    attivita = _per_codice(await sessione.scalars(select(AcAttivita).where(AcAttivita.processo_id == p.id)))
    ids_attivita = [a.id for a in attivita]
    rischi = _per_codice(await sessione.scalars(select(AcRischio).where(AcRischio.attivita_id.in_(ids_attivita))))
    misure = _per_codice(await sessione.scalars(select(AcMisura).where(AcMisura.rischio_id.in_([r.id for r in rischi]))))
    collegati = await _obiettivi_collegati(sessione)
    return {
        **_processo(p),
        "obiettivi": collegati.processi.get(p.id, []),
        "attivita": [
            {**_attivita(a), "obiettivi": collegati.dell_attivita(a), "rischi": [
                {**_rischio(r), "misure": [_misura(x) for x in misure if x.rischio_id == r.id]}
                for r in rischi if r.attivita_id == a.id
            ]}
            for a in attivita
        ],
    }  # fmt: skip


# --- mappatura: modifiche (RPCT) ----------------------------------------------------------


async def _struttura_valida(sessione, struttura_id: str | None) -> None:
    if struttura_id is None:
        return
    s = await sessione.get(Struttura, struttura_id)
    if s is None or s.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Struttura non trovata")


async def _codici(sessione, modello) -> list[str]:
    return list(await sessione.scalars(select(modello.codice).where(modello.ente_id == ente_id())))


class ProcessoIn(BaseModel):
    codice: str | None = Field(default=None, max_length=50)  # se manca si assegna il successivo
    area_id: str | None = None
    denominazione: str = Field(min_length=1, max_length=500)
    descrizione: str | None = None
    tempi: str | None = None
    attori_esterni: str | None = None
    struttura_id: str | None = None  # vuota: processo trasversale


async def _applica_processo(sessione, p: AcProcesso, dati: ProcessoIn) -> None:
    area = await _area_dell_ente(sessione, dati.area_id) if dati.area_id else None
    await _struttura_valida(sessione, dati.struttura_id)
    codice = (dati.codice or "").strip() or prossimo_codice(f"{area.codice if area else 'P'}.", await _codici(sessione, AcProcesso))
    await _codice_libero(sessione, AcProcesso, codice, escluso=p.id)
    p.codice, p.area_id, p.denominazione = codice, dati.area_id, dati.denominazione
    p.descrizione, p.tempi, p.attori_esterni = dati.descrizione, dati.tempi, dati.attori_esterni
    p.struttura_id = dati.struttura_id


@bp.post("/processi")
@rpct
async def crea_processo():
    dati = corpo(ProcessoIn)
    sessione = db()
    p = AcProcesso(ente_id=ente_id())
    await _applica_processo(sessione, p, dati)
    sessione.add(p)
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
    p = await _processo_dell_ente(sessione, processo_id)
    await _applica_processo(sessione, p, dati)
    audit(sessione, utente(), "ac_processo", p.id, "AGGIORNATO", {"codice": p.codice})
    await sessione.commit()
    await sessione.refresh(p)
    return _processo(p)


async def _elimina_sotto_attivita(sessione, ids_attivita: list[str]) -> None:
    """Rischi, misure e collegamenti agli obiettivi delle attività (esplicito: SQLite non
    applica le cascade senza pragma)."""
    await sessione.execute(delete(AcObiettivoCollegamento).where(AcObiettivoCollegamento.attivita_id.in_(ids_attivita)))
    ids_rischi = list(await sessione.scalars(select(AcRischio.id).where(AcRischio.attivita_id.in_(ids_attivita))))
    await sessione.execute(delete(AcMisura).where(AcMisura.rischio_id.in_(ids_rischi)))
    await sessione.execute(delete(AcRischio).where(AcRischio.id.in_(ids_rischi)))


@bp.delete("/processi/<processo_id>")
@rpct
async def elimina_processo(processo_id: str):
    """Il processo con le sue attività, rischi e misure."""
    sessione = db()
    p = await _processo_dell_ente(sessione, processo_id)
    ids_attivita = list(await sessione.scalars(select(AcAttivita.id).where(AcAttivita.processo_id == p.id)))
    await _elimina_sotto_attivita(sessione, ids_attivita)
    await sessione.execute(delete(AcAttivita).where(AcAttivita.id.in_(ids_attivita)))
    await sessione.execute(delete(AcObiettivoCollegamento).where(AcObiettivoCollegamento.processo_id == p.id))
    audit(sessione, utente(), "ac_processo", p.id, "ELIMINATO", {"codice": p.codice})
    await sessione.delete(p)
    await sessione.commit()
    return nessun_contenuto()


async def _tocca(sessione, processo_id: str) -> None:
    """Data di modifica del processo quando cambia qualcosa al suo interno."""
    p = await sessione.get(AcProcesso, processo_id)
    if p is not None:
        p.updated_at = datetime.now()


class AttivitaIn(BaseModel):
    codice: str | None = Field(default=None, max_length=50)
    descrizione: str = Field(min_length=1)
    strutture_coinvolte: str | None = None


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
    p = await _processo_dell_ente(sessione, processo_id)
    codice = (dati.codice or "").strip() or prossimo_codice(f"{p.codice}.", await _codici(sessione, AcAttivita))
    await _codice_libero(sessione, AcAttivita, codice)
    a = AcAttivita(ente_id=ente_id(), processo_id=p.id, codice=codice, descrizione=dati.descrizione,
                   strutture_coinvolte=dati.strutture_coinvolte)  # fmt: skip
    sessione.add(a)
    await _tocca(sessione, p.id)
    await sessione.flush()
    audit(sessione, utente(), "ac_attivita", a.id, "CREATA", {"codice": a.codice})
    await sessione.commit()
    return _attivita(a), HTTPStatus.CREATED


@bp.put("/attivita/<attivita_id>")
@rpct
async def aggiorna_attivita(attivita_id: str):
    dati = corpo(AttivitaIn)
    sessione = db()
    a = await _attivita_dell_ente(sessione, attivita_id)
    codice = (dati.codice or "").strip() or a.codice
    await _codice_libero(sessione, AcAttivita, codice, escluso=a.id)
    a.codice, a.descrizione, a.strutture_coinvolte = codice, dati.descrizione, dati.strutture_coinvolte
    await _tocca(sessione, a.processo_id)
    audit(sessione, utente(), "ac_attivita", a.id, "AGGIORNATA", {"codice": a.codice})
    await sessione.commit()
    return _attivita(a)


@bp.delete("/attivita/<attivita_id>")
@rpct
async def elimina_attivita(attivita_id: str):
    sessione = db()
    a = await _attivita_dell_ente(sessione, attivita_id)
    await _elimina_sotto_attivita(sessione, [a.id])
    await _tocca(sessione, a.processo_id)
    audit(sessione, utente(), "ac_attivita", a.id, "ELIMINATA", {"codice": a.codice})
    await sessione.delete(a)
    await sessione.commit()
    return nessun_contenuto()


class RischioIn(BaseModel):
    codice: str | None = Field(default=None, max_length=60)
    evento: str = Field(min_length=1)
    fattore_abilitante: str | None = Field(default=None, max_length=500)


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
    a = await _attivita_dell_ente(sessione, attivita_id)
    codice = (dati.codice or "").strip() or prossimo_codice(f"{a.codice}_R.", await _codici(sessione, AcRischio))
    await _codice_libero(sessione, AcRischio, codice)
    r = AcRischio(ente_id=ente_id(), attivita_id=a.id, codice=codice, evento=dati.evento,
                  fattore_abilitante=dati.fattore_abilitante)  # fmt: skip
    sessione.add(r)
    await _tocca(sessione, a.processo_id)
    await sessione.flush()
    audit(sessione, utente(), "ac_rischio", r.id, "CREATO", {"codice": r.codice})
    await sessione.commit()
    return _rischio(r), HTTPStatus.CREATED


@bp.put("/rischi/<rischio_id>")
@rpct
async def aggiorna_rischio(rischio_id: str):
    dati = corpo(RischioIn)
    sessione = db()
    r = await _rischio_dell_ente(sessione, rischio_id)
    codice = (dati.codice or "").strip() or r.codice
    await _codice_libero(sessione, AcRischio, codice, escluso=r.id)
    r.codice, r.evento, r.fattore_abilitante = codice, dati.evento, dati.fattore_abilitante
    a = await sessione.get(AcAttivita, r.attivita_id)
    await _tocca(sessione, a.processo_id)
    audit(sessione, utente(), "ac_rischio", r.id, "AGGIORNATO", {"codice": r.codice})
    await sessione.commit()
    return _rischio(r)


@bp.delete("/rischi/<rischio_id>")
@rpct
async def elimina_rischio(rischio_id: str):
    sessione = db()
    r = await _rischio_dell_ente(sessione, rischio_id)
    await sessione.execute(delete(AcMisura).where(AcMisura.rischio_id == r.id))
    a = await sessione.get(AcAttivita, r.attivita_id)
    await _tocca(sessione, a.processo_id)
    audit(sessione, utente(), "ac_rischio", r.id, "ELIMINATO", {"codice": r.codice})
    await sessione.delete(r)
    await sessione.commit()
    return nessun_contenuto()


class ValutazioneIn(BaseModel):
    valori_probabilita: dict[str, str]
    valori_impatto: dict[str, str]
    fattore_abilitante: str | None = Field(default=None, max_length=500)
    # correzione dei valori calcolati (es. parità nella moda), con motivazione obbligatoria
    probabilita: str | None = None
    impatto: str | None = None
    motivazione_correzione: str | None = Field(default=None, max_length=5000)


@bp.put("/rischi/<rischio_id>/valutazione")
@rpct
async def valuta_rischio(rischio_id: str):
    """Valutazione del rischio: moda degli indicatori (a parità il più alto) e matrice della
    metodologia dell'ente; probabilità e impatto si possono correggere con una motivazione."""
    dati = corpo(ValutazioneIn)
    sessione = db()
    r = await _rischio_dell_ente(sessione, rischio_id)
    m = await metodologia_ente()
    try:
        v = valuta(m, dati.valori_probabilita, dati.valori_impatto,
                   probabilita=dati.probabilita, impatto=dati.impatto)  # fmt: skip
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    corretta = (v.probabilita, v.impatto) != (v.probabilita_calcolata, v.impatto_calcolato)
    motivazione = (dati.motivazione_correzione or "").strip()
    if corretta and not motivazione:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Per correggere probabilità o impatto serve la motivazione")
    r.valori_probabilita, r.valori_impatto = dati.valori_probabilita, dati.valori_impatto
    r.probabilita_calcolata, r.impatto_calcolato = v.probabilita_calcolata, v.impatto_calcolato
    r.probabilita, r.impatto, r.livello = v.probabilita, v.impatto, v.livello
    r.motivazione_correzione = motivazione if corretta else None
    if dati.fattore_abilitante is not None:
        r.fattore_abilitante = dati.fattore_abilitante or None
    r.valutato_il = datetime.now()
    a = await sessione.get(AcAttivita, r.attivita_id)
    await _tocca(sessione, a.processo_id)
    audit(sessione, utente(), "ac_rischio", r.id, "VALUTATO", {"livello": r.livello, "corretta": corretta})
    await sessione.commit()
    return _rischio(r)


class MisuraIn(BaseModel):
    codice: str | None = Field(default=None, max_length=70)
    descrizione: str = Field(min_length=1)
    tipo: Literal["GENERALE", "SPECIFICA"] = "SPECIFICA"
    categoria: str | None = Field(default=None, max_length=255)
    obbligo_trasparenza: str | None = Field(default=None, max_length=100)
    fasi: str | None = None
    tempi: str | None = None
    struttura_id: str | None = None
    indicatore: str | None = None
    target: str | None = None


async def _misura_dell_ente(sessione, misura_id: str) -> AcMisura:
    m = await sessione.get(AcMisura, misura_id)
    if m is None or m.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Misura non trovata")
    return m


async def _applica_misura(sessione, m: AcMisura, dati: MisuraIn) -> None:
    if dati.obbligo_trasparenza and dati.obbligo_trasparenza not in SCHEMI:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Obbligo di pubblicazione non previsto: {dati.obbligo_trasparenza}")
    await _struttura_valida(sessione, dati.struttura_id)
    for campo, valore in dati.model_dump(exclude={"codice"}).items():
        setattr(m, campo, valore)


async def _processo_del_rischio(sessione, rischio: AcRischio) -> str:
    return (await sessione.get(AcAttivita, rischio.attivita_id)).processo_id


@bp.post("/rischi/<rischio_id>/misure")
@rpct
async def crea_misura(rischio_id: str):
    dati = corpo(MisuraIn)
    sessione = db()
    r = await _rischio_dell_ente(sessione, rischio_id)
    codice = (dati.codice or "").strip() or prossimo_codice(f"{r.codice}_M.", await _codici(sessione, AcMisura))
    await _codice_libero(sessione, AcMisura, codice)
    m = AcMisura(ente_id=ente_id(), rischio_id=r.id, codice=codice)
    await _applica_misura(sessione, m, dati)
    sessione.add(m)
    await _tocca(sessione, await _processo_del_rischio(sessione, r))
    await sessione.flush()
    audit(sessione, utente(), "ac_misura", m.id, "CREATA", {"codice": m.codice})
    await sessione.commit()
    return _misura(m), HTTPStatus.CREATED


@bp.put("/misure/<misura_id>")
@rpct
async def aggiorna_misura(misura_id: str):
    dati = corpo(MisuraIn)
    sessione = db()
    m = await _misura_dell_ente(sessione, misura_id)
    codice = (dati.codice or "").strip() or m.codice
    await _codice_libero(sessione, AcMisura, codice, escluso=m.id)
    m.codice = codice
    await _applica_misura(sessione, m, dati)
    await _tocca(sessione, await _processo_del_rischio(sessione, await sessione.get(AcRischio, m.rischio_id)))
    audit(sessione, utente(), "ac_misura", m.id, "AGGIORNATA", {"codice": m.codice})
    await sessione.commit()
    return _misura(m)


@bp.delete("/misure/<misura_id>")
@rpct
async def elimina_misura(misura_id: str):
    sessione = db()
    m = await _misura_dell_ente(sessione, misura_id)
    await _tocca(sessione, await _processo_del_rischio(sessione, await sessione.get(AcRischio, m.rischio_id)))
    audit(sessione, utente(), "ac_misura", m.id, "ELIMINATA", {"codice": m.codice})
    await sessione.delete(m)
    await sessione.commit()
    return nessun_contenuto()



# --- proposte ------------------------------------------------------------------------------


class ValutazioneProposta(BaseModel):
    valori_probabilita: dict[str, str]
    valori_impatto: dict[str, str]
    probabilita: str | None = None
    impatto: str | None = None
    motivazione_correzione: str | None = Field(default=None, max_length=5000)


class MisuraProposta(MisuraIn):
    id: str | None = None  # misura esistente (modifica di un processo)


class RischioProposta(RischioIn):
    id: str | None = None
    valutazione: ValutazioneProposta | None = None
    misure: list[MisuraProposta] = []


class AttivitaProposta(AttivitaIn):
    id: str | None = None
    rischi: list[RischioProposta] = []


class DatiProposta(BaseModel):
    """Processo intero proposto: nella modifica gli elementi con id sono quelli esistenti,
    quelli senza id si aggiungono, quelli esistenti che mancano si eliminano."""

    processo: ProcessoIn
    attivita: list[AttivitaProposta] = []


def _da_albero(albero: dict) -> dict:
    """Dati di una proposta dal processo com'è (per modificarlo o eliminarlo)."""
    def valutazione(r: dict) -> dict | None:
        if not r.get("valori_probabilita"):
            return None
        return {k: r[k] for k in ("valori_probabilita", "valori_impatto", "probabilita", "impatto",
                                  "motivazione_correzione", "probabilita_calcolata", "impatto_calcolato", "livello")}  # fmt: skip

    return {
        "processo": {k: albero[k] for k in ProcessoIn.model_fields},
        "attivita": [
            {**{k: a[k] for k in ("id", "codice", "descrizione", "strutture_coinvolte")}, "rischi": [
                {**{k: r[k] for k in ("id", "codice", "evento", "fattore_abilitante")},
                 "valutazione": valutazione(r),
                 "misure": [{k: x[k] for k in ("id", *MisuraIn.model_fields)} for x in r["misure"]]}
                for r in a["rischi"]
            ]}
            for a in albero["attivita"]
        ],
    }  # fmt: skip


def _esito(m: Metodologia, v: ValutazioneProposta):
    try:
        esito = valuta(m, v.valori_probabilita, v.valori_impatto, probabilita=v.probabilita, impatto=v.impatto)
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    corretta = (esito.probabilita, esito.impatto) != (esito.probabilita_calcolata, esito.impatto_calcolato)
    if corretta and not (v.motivazione_correzione or "").strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Per correggere probabilità o impatto serve la motivazione")
    return esito, corretta


async def _controlla_dati(sessione, dati: DatiProposta, m: Metodologia) -> dict:
    """Dati validi (aree, strutture, obblighi, valutazioni) con l'esito delle valutazioni,
    da mostrare nella proposta; i codici si controllano all'approvazione."""
    if dati.processo.area_id:
        await _area_dell_ente(sessione, dati.processo.area_id)
    await _struttura_valida(sessione, dati.processo.struttura_id)
    risultato = dati.model_dump()
    for a_in, a_out in zip(dati.attivita, risultato["attivita"], strict=True):
        for r_in, r_out in zip(a_in.rischi, a_out["rischi"], strict=True):
            if r_in.valutazione is not None:
                esito, _ = _esito(m, r_in.valutazione)
                r_out["valutazione"].update(esito.model_dump())
            for x in r_in.misure:
                if x.obbligo_trasparenza and x.obbligo_trasparenza not in SCHEMI:
                    raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Obbligo di pubblicazione non previsto: {x.obbligo_trasparenza}")
                await _struttura_valida(sessione, x.struttura_id)
    return risultato


async def _applica_dati(sessione, p: AcProcesso, dati: DatiProposta, m: Metodologia) -> None:
    """Porta il processo (nuovo o esistente) a coincidere con i dati della proposta."""
    await _applica_processo(sessione, p, dati.processo)
    sessione.add(p)
    esistenti_a = {a.id: a for a in await sessione.scalars(select(AcAttivita).where(AcAttivita.processo_id == p.id))}
    esistenti_r = {r.id: r for r in await sessione.scalars(
        select(AcRischio).where(AcRischio.attivita_id.in_(list(esistenti_a))))}  # fmt: skip
    esistenti_m = {x.id: x for x in await sessione.scalars(
        select(AcMisura).where(AcMisura.rischio_id.in_(list(esistenti_r))))}  # fmt: skip
    for oggetti, elementi in (
        (esistenti_a, dati.attivita),
        (esistenti_r, [r for a in dati.attivita for r in a.rischi]),
        (esistenti_m, [x for a in dati.attivita for r in a.rischi for x in r.misure]),
    ):
        estranei = {e.id for e in elementi if e.id} - set(oggetti)
        if estranei:
            raise ErroreApi(HTTPStatus.CONFLICT, "La proposta richiama elementi che non sono più nel processo: riaprila")
    # prima si tolgono gli elementi che la proposta non contiene più (liberano i loro codici)
    tenute_a = {a.id for a in dati.attivita if a.id}
    tenuti_r = {r.id for a in dati.attivita for r in a.rischi if r.id}
    tenute_m = {x.id for a in dati.attivita for r in a.rischi for x in r.misure if x.id}
    await sessione.execute(delete(AcMisura).where(AcMisura.id.in_(set(esistenti_m) - tenute_m)))
    await sessione.execute(delete(AcMisura).where(AcMisura.rischio_id.in_(set(esistenti_r) - tenuti_r)))
    await sessione.execute(delete(AcRischio).where(AcRischio.id.in_(set(esistenti_r) - tenuti_r)))
    await _elimina_sotto_attivita(sessione, list(set(esistenti_a) - tenute_a))
    await sessione.execute(delete(AcAttivita).where(AcAttivita.id.in_(set(esistenti_a) - tenute_a)))
    codici = {modello: await _codici(sessione, modello) for modello in (AcAttivita, AcRischio, AcMisura)}

    async def codice(modello, scelto: str | None, prefisso: str, oggetto) -> str:
        valore = (scelto or "").strip() or oggetto.codice or prossimo_codice(prefisso, codici[modello])
        await _codice_libero(sessione, modello, valore, escluso=oggetto.id)
        codici[modello].append(valore)
        return valore

    for a_in in dati.attivita:
        a = esistenti_a.get(a_in.id) or AcAttivita(id=nuovo_id(), ente_id=ente_id(), processo_id=p.id, codice="")
        a.codice = await codice(AcAttivita, a_in.codice, f"{p.codice}.", a)
        a.descrizione, a.strutture_coinvolte = a_in.descrizione, a_in.strutture_coinvolte
        sessione.add(a)
        for r_in in a_in.rischi:
            r = esistenti_r.get(r_in.id) or AcRischio(id=nuovo_id(), ente_id=ente_id(), codice="")
            r.attivita_id = a.id
            r.codice = await codice(AcRischio, r_in.codice, f"{a.codice}_R.", r)
            r.evento, r.fattore_abilitante = r_in.evento, r_in.fattore_abilitante
            if r_in.valutazione is None:
                r.valori_probabilita = r.valori_impatto = r.probabilita_calcolata = r.impatto_calcolato = None
                r.probabilita = r.impatto = r.livello = r.motivazione_correzione = r.valutato_il = None
            else:
                v, corretta = _esito(m, r_in.valutazione)
                nuova = (r.valori_probabilita, r.valori_impatto, r.probabilita, r.impatto) != (
                    r_in.valutazione.valori_probabilita, r_in.valutazione.valori_impatto, v.probabilita, v.impatto)
                r.valori_probabilita, r.valori_impatto = r_in.valutazione.valori_probabilita, r_in.valutazione.valori_impatto
                r.probabilita_calcolata, r.impatto_calcolato = v.probabilita_calcolata, v.impatto_calcolato
                r.probabilita, r.impatto, r.livello = v.probabilita, v.impatto, v.livello
                r.motivazione_correzione = r_in.valutazione.motivazione_correzione if corretta else None
                if nuova or r.valutato_il is None:
                    r.valutato_il = datetime.now()
            sessione.add(r)
            for x_in in r_in.misure:
                x = esistenti_m.get(x_in.id) or AcMisura(id=nuovo_id(), ente_id=ente_id(), codice="")
                x.rischio_id = r.id
                x.codice = await codice(AcMisura, x_in.codice, f"{r.codice}_M.", x)
                await _applica_misura(sessione, x, MisuraIn.model_validate(x_in.model_dump(exclude={"id"})))
                sessione.add(x)
    p.updated_at = datetime.now()


def _proposta(pr: AcProposta, autore: User | None, *, dati: bool = False) -> dict:
    processo = (pr.dati or {}).get("processo") or {}
    risultato = {
        "id": pr.id, "tipo": pr.tipo, "stato": pr.stato, "processo_id": pr.processo_id,
        "codice": processo.get("codice"), "denominazione": processo.get("denominazione"),
        "nota": pr.nota, "motivazione": pr.motivazione, "utente_id": pr.utente_id,
        "autore": (autore.nome_completo or autore.username) if autore else None,
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "inviata_il": pr.inviata_il.isoformat() if pr.inviata_il else None,
        "decisa_il": pr.decisa_il.isoformat() if pr.decisa_il else None,
    }  # fmt: skip
    if dati:
        risultato["dati"] = pr.dati
    return risultato


def _e_rpct() -> bool:
    return utente().ha_ruolo(Ruolo.ADMIN, Ruolo.ANTICORRUZIONE_RPCT)


async def _proposta_visibile(sessione, proposta_id: str) -> AcProposta:
    """Proposta dell'utente; il RPCT vede anche quelle inviate degli altri."""
    pr = await sessione.get(AcProposta, proposta_id)
    if pr is None or pr.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Proposta non trovata")
    if pr.utente_id != utente().id and not (_e_rpct() and pr.stato != "BOZZA"):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Proposta non trovata")
    return pr


async def _proposta_propria(sessione, proposta_id: str) -> AcProposta:
    """Proposta dell'utente ancora modificabile (bozza o restituita)."""
    pr = await _proposta_visibile(sessione, proposta_id)
    if pr.utente_id != utente().id:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "La proposta è di un altro utente")
    if pr.stato not in ("BOZZA", "RESTITUITA"):
        raise ErroreApi(HTTPStatus.CONFLICT, "La proposta è già stata inviata o decisa")
    return pr


class FiltriProposte(BaseModel):
    stato: Literal["BOZZA", "INVIATA", "APPROVATA", "RESPINTA", "RESTITUITA"] | None = None


@bp.get("/proposte")
@lettore
async def proposte():
    """Proposte dell'utente; per il RPCT anche quelle inviate (o decise) degli altri."""
    f = parametri(FiltriProposte)
    sessione = db()
    q = select(AcProposta, User).join(User, User.id == AcProposta.utente_id).where(AcProposta.ente_id == ente_id())
    if f.stato:
        q = q.where(AcProposta.stato == f.stato)
    righe = (await sessione.execute(q.order_by(AcProposta.created_at.desc()))).all()
    return [_proposta(pr, u) for pr, u in righe if pr.utente_id == utente().id or (_e_rpct() and pr.stato != "BOZZA")]


@bp.get("/proposte/<proposta_id>")
@lettore
async def proposta(proposta_id: str):
    """Proposta con i dati; per una modifica dice se il processo è cambiato dopo."""
    sessione = db()
    pr = await _proposta_visibile(sessione, proposta_id)
    risultato = _proposta(pr, await sessione.get(User, pr.utente_id), dati=True)
    p = await sessione.get(AcProcesso, pr.processo_id) if pr.processo_id else None
    risultato["processo_cambiato"] = bool(
        pr.tipo != "CREA" and pr.stato == "INVIATA" and (p is None or (pr.base_aggiornamento and p.updated_at > pr.base_aggiornamento))
    )  # fmt: skip
    return risultato


class PropostaNuova(BaseModel):
    tipo: Literal["CREA", "MODIFICA", "ELIMINA"]
    processo_id: str | None = None  # per MODIFICA ed ELIMINA
    dati: DatiProposta | None = None  # per CREA; per MODIFICA se manca è il processo com'è
    nota: str | None = Field(default=None, max_length=5000)


@bp.post("/proposte")
@lettore
async def crea_proposta():
    dati = corpo(PropostaNuova)
    sessione = db()
    m = await metodologia_ente()
    pr = AcProposta(ente_id=ente_id(), utente_id=utente().id, tipo=dati.tipo, nota=dati.nota, stato="BOZZA")
    if dati.tipo == "CREA":
        if dati.dati is None:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica il processo da creare")
        pr.dati = await _controlla_dati(sessione, dati.dati, m)
    else:
        if not dati.processo_id:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica il processo")
        p = await _processo_dell_ente(sessione, dati.processo_id)
        pr.processo_id, pr.base_aggiornamento = p.id, p.updated_at
        attuali = _da_albero(await _albero(sessione, p))
        pr.dati = attuali if dati.tipo == "ELIMINA" or dati.dati is None else await _controlla_dati(sessione, dati.dati, m)
    sessione.add(pr)
    await sessione.flush()
    audit(sessione, utente(), "ac_proposta", pr.id, "CREATA", {"tipo": pr.tipo, "processo_id": pr.processo_id})
    await sessione.commit()
    return _proposta(pr, utente(), dati=True), HTTPStatus.CREATED


class PropostaIn(BaseModel):
    dati: DatiProposta | None = None  # non per ELIMINA
    nota: str | None = Field(default=None, max_length=5000)


@bp.put("/proposte/<proposta_id>")
@lettore
async def aggiorna_proposta(proposta_id: str):
    dati = corpo(PropostaIn)
    sessione = db()
    pr = await _proposta_propria(sessione, proposta_id)
    if dati.dati is not None and pr.tipo != "ELIMINA":
        pr.dati = await _controlla_dati(sessione, dati.dati, await metodologia_ente())
    pr.nota = dati.nota
    await sessione.commit()
    return _proposta(pr, utente(), dati=True)


@bp.post("/proposte/<proposta_id>/invia")
@lettore
async def invia_proposta(proposta_id: str):
    sessione = db()
    pr = await _proposta_propria(sessione, proposta_id)
    pr.stato, pr.inviata_il = "INVIATA", datetime.now()
    audit(sessione, utente(), "ac_proposta", pr.id, "INVIATA")
    await sessione.commit()
    return _proposta(pr, utente())


@bp.delete("/proposte/<proposta_id>")
@lettore
async def ritira_proposta(proposta_id: str):
    """Ritira una proposta non ancora inviata (o restituita)."""
    sessione = db()
    pr = await _proposta_propria(sessione, proposta_id)
    audit(sessione, utente(), "ac_proposta", pr.id, "RITIRATA")
    await sessione.delete(pr)
    await sessione.commit()
    return nessun_contenuto()


class DecisioneIn(BaseModel):
    motivazione: str | None = Field(default=None, max_length=5000)
    forza: bool = False  # approva anche se il processo è cambiato dopo la proposta


async def _proposta_inviata(sessione, proposta_id: str) -> AcProposta:
    pr = await _proposta_visibile(sessione, proposta_id)
    if pr.stato != "INVIATA":
        raise ErroreApi(HTTPStatus.CONFLICT, "Si decidono solo le proposte inviate")
    return pr


@bp.post("/proposte/<proposta_id>/approva")
@rpct
async def approva_proposta(proposta_id: str):
    """Applica la proposta alla mappatura, tutta insieme."""
    dati = corpo(DecisioneIn)
    sessione = db()
    pr = await _proposta_inviata(sessione, proposta_id)
    p = await sessione.get(AcProcesso, pr.processo_id) if pr.processo_id else None
    if pr.tipo != "CREA":
        if p is None or p.ente_id != ente_id():
            raise ErroreApi(HTTPStatus.CONFLICT, "Il processo non esiste più")
        if pr.base_aggiornamento and p.updated_at > pr.base_aggiornamento and not dati.forza:
            raise ErroreApi(HTTPStatus.CONFLICT, "Il processo è stato modificato dopo la proposta: verifica le differenze e conferma")
    if pr.tipo == "ELIMINA":
        ids_attivita = list(await sessione.scalars(select(AcAttivita.id).where(AcAttivita.processo_id == p.id)))
        await _elimina_sotto_attivita(sessione, ids_attivita)
        await sessione.execute(delete(AcAttivita).where(AcAttivita.id.in_(ids_attivita)))
        await sessione.execute(delete(AcObiettivoCollegamento).where(AcObiettivoCollegamento.processo_id == p.id))
        await sessione.delete(p)
        pr.processo_id = None
    else:
        if p is None:
            p = AcProcesso(id=nuovo_id(), ente_id=ente_id())  # entra nella sessione con i dati
        await _applica_dati(sessione, p, DatiProposta.model_validate(pr.dati), await metodologia_ente())
        pr.processo_id = p.id
    pr.stato, pr.motivazione = "APPROVATA", dati.motivazione
    pr.deciso_da, pr.decisa_il = utente().id, datetime.now()
    audit(sessione, utente(), "ac_proposta", pr.id, "APPROVATA", {"tipo": pr.tipo, "processo_id": pr.processo_id})
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
    collegati = await _obiettivi_collegati(sessione)
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
            "obiettivi": collegati.dell_attivita(voce["attivita"]),
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


# --- PIAO e obiettivi di performance -------------------------------------------------------


class _Collegati:
    """Obiettivi collegati per processo e per attività (quelli del processo valgono anche per
    le sue attività, rischi e misure)."""

    def __init__(self, processi: dict[str, list[dict]], attivita: dict[str, list[dict]]):
        self.processi, self.attivita = processi, attivita

    def dell_attivita(self, a: AcAttivita) -> list[dict]:
        """Obiettivi dell'attività: quelli del suo processo (ereditati) e i suoi."""
        visti, risultato = set(), []
        ereditati = [{**o, "ereditato": True} for o in self.processi.get(a.processo_id, [])]
        for o in ereditati + self.attivita.get(a.id, []):
            if o["id"] not in visti:
                visti.add(o["id"])
                risultato.append(o)
        return risultato


async def _obiettivi_collegati(sessione) -> _Collegati:
    righe = (await sessione.execute(
        select(AcObiettivoCollegamento, AcObiettivo)
        .join(AcObiettivo, AcObiettivo.id == AcObiettivoCollegamento.obiettivo_id)
        .where(AcObiettivoCollegamento.ente_id == ente_id())
    )).all()  # fmt: skip
    processi: dict[str, list[dict]] = {}
    attivita: dict[str, list[dict]] = {}
    for c, o in righe:
        voce = {"id": o.id, "codice": o.codice, "titolo": o.titolo, "anno": o.anno, "collegamento_id": c.id,
                "ereditato": False}  # fmt: skip
        if c.processo_id:
            processi.setdefault(c.processo_id, []).append(voce)
        elif c.attivita_id:
            attivita.setdefault(c.attivita_id, []).append(voce)
    return _Collegati(processi, attivita)


class PiaoIn(BaseModel):
    anno_inizio: int = Field(ge=2000, le=2100)
    anno_fine: int = Field(ge=2000, le=2100)
    descrizione: str = Field(min_length=1, max_length=255)
    atto: str | None = Field(default=None, max_length=255)


def _piao(p: AcPiao) -> dict:
    return {"id": p.id, "anno_inizio": p.anno_inizio, "anno_fine": p.anno_fine,
            "descrizione": p.descrizione, "atto": p.atto}  # fmt: skip


async def _piao_dell_ente(sessione, piao_id: str) -> AcPiao:
    p = await sessione.get(AcPiao, piao_id)
    if p is None or p.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "PIAO non trovato")
    return p


async def _applica_piao(sessione, p: AcPiao, dati: PiaoIn) -> None:
    if dati.anno_fine < dati.anno_inizio:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "L'anno finale precede quello iniziale")
    altro = await sessione.scalar(select(AcPiao).where(AcPiao.ente_id == ente_id(), AcPiao.anno_inizio == dati.anno_inizio))
    if altro is not None and altro.id != p.id:
        raise ErroreApi(HTTPStatus.CONFLICT, f"C'è già un PIAO che inizia nel {dati.anno_inizio}")
    for campo, valore in dati.model_dump().items():
        setattr(p, campo, valore)


@bp.get("/piao")
@lettore
async def elenco_piao():
    righe = await db().scalars(select(AcPiao).where(AcPiao.ente_id == ente_id()).order_by(AcPiao.anno_inizio.desc()))
    return [_piao(p) for p in righe]


@bp.post("/piao")
@rpct
async def crea_piao():
    dati = corpo(PiaoIn)
    sessione = db()
    p = AcPiao(ente_id=ente_id())
    await _applica_piao(sessione, p, dati)
    sessione.add(p)
    await sessione.flush()
    audit(sessione, utente(), "ac_piao", p.id, "CREATO", {"anni": f"{p.anno_inizio}-{p.anno_fine}"})
    await sessione.commit()
    return _piao(p), HTTPStatus.CREATED


@bp.put("/piao/<piao_id>")
@rpct
async def aggiorna_piao(piao_id: str):
    dati = corpo(PiaoIn)
    sessione = db()
    p = await _piao_dell_ente(sessione, piao_id)
    await _applica_piao(sessione, p, dati)
    audit(sessione, utente(), "ac_piao", p.id, "AGGIORNATO")
    await sessione.commit()
    return _piao(p)


async def _elimina_obiettivi(sessione, ids: list[str]) -> None:
    await sessione.execute(delete(AcObiettivoCollegamento).where(AcObiettivoCollegamento.obiettivo_id.in_(ids)))
    await sessione.execute(delete(AcObiettivo).where(AcObiettivo.id.in_(ids)))


@bp.delete("/piao/<piao_id>")
@rpct
async def elimina_piao(piao_id: str):
    """Il PIAO con i suoi obiettivi e i loro collegamenti."""
    sessione = db()
    p = await _piao_dell_ente(sessione, piao_id)
    await _elimina_obiettivi(sessione, list(await sessione.scalars(select(AcObiettivo.id).where(AcObiettivo.piao_id == p.id))))
    audit(sessione, utente(), "ac_piao", p.id, "ELIMINATO", {"anni": f"{p.anno_inizio}-{p.anno_fine}"})
    await sessione.delete(p)
    await sessione.commit()
    return nessun_contenuto()


def _obiettivo(o: AcObiettivo) -> dict:
    return {
        "id": o.id, "piao_id": o.piao_id, "codice": o.codice, "anno": o.anno, "titolo": o.titolo,
        "tipo": o.tipo, "struttura_id": o.struttura_id, "centro_piano": o.centro_piano,
        "centro_descrizione": o.centro_descrizione, "responsabile": o.responsabile, "fonte": o.fonte,
    }  # fmt: skip


class FiltriObiettivi(BaseModel):
    anno: int | None = None
    tipo: str | None = None
    struttura: str | None = None  # assegnati alla struttura, a una superiore o a una sottostante
    testo: str | None = Field(default=None, max_length=200)


@bp.get("/piao/<piao_id>/obiettivi")
@lettore
async def obiettivi(piao_id: str):
    """Obiettivi del PIAO con il numero di processi e attività collegati."""
    f = parametri(FiltriObiettivi)
    sessione = db()
    p = await _piao_dell_ente(sessione, piao_id)
    righe = list(await sessione.scalars(select(AcObiettivo).where(AcObiettivo.piao_id == p.id)))
    if f.struttura:
        strutture = await _strutture_ente(sessione)
        sotto = _sottostanti(strutture, f.struttura)
        sopra, corrente = set(), f.struttura
        while corrente is not None and corrente not in sopra:
            sopra.add(corrente)
            corrente = strutture[corrente].padre_id if corrente in strutture else None
        righe = [o for o in righe if o.struttura_id in sotto | sopra]
    testo = (f.testo or "").strip().lower()
    righe = [o for o in righe
             if (f.anno is None or o.anno == f.anno) and (f.tipo is None or o.tipo == f.tipo)
             and (not testo or testo in f"{o.codice} {o.titolo or ''}".lower())]  # fmt: skip
    conteggi: dict[str, int] = {}
    for obiettivo_id in await sessione.scalars(select(AcObiettivoCollegamento.obiettivo_id).where(
            AcObiettivoCollegamento.obiettivo_id.in_([o.id for o in righe]))):  # fmt: skip
        conteggi[obiettivo_id] = conteggi.get(obiettivo_id, 0) + 1
    return [{**_obiettivo(o), "collegamenti": conteggi.get(o.id, 0)}
            for o in sorted(righe, key=lambda o: (o.anno, chiave_naturale(o.codice)))]  # fmt: skip


class ObiettivoIn(BaseModel):
    codice: str = Field(min_length=1, max_length=100)
    anno: int = Field(ge=2000, le=2100)
    titolo: str | None = None
    tipo: str | None = Field(default=None, max_length=100)
    struttura_id: str | None = None
    centro_piano: str | None = Field(default=None, max_length=255)
    centro_descrizione: str | None = Field(default=None, max_length=500)
    responsabile: str | None = Field(default=None, max_length=255)


async def _obiettivo_dell_ente(sessione, obiettivo_id: str) -> AcObiettivo:
    o = await sessione.get(AcObiettivo, obiettivo_id)
    if o is None or o.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Obiettivo non trovato")
    return o


async def _applica_obiettivo(sessione, o: AcObiettivo, dati: ObiettivoIn) -> None:
    await _struttura_valida(sessione, dati.struttura_id)
    altro = await sessione.scalar(select(AcObiettivo).where(
        AcObiettivo.piao_id == o.piao_id, AcObiettivo.codice == dati.codice.strip(), AcObiettivo.anno == dati.anno))  # fmt: skip
    if altro is not None and altro.id != o.id:
        raise ErroreApi(HTTPStatus.CONFLICT, f"Obiettivo già presente: {dati.codice} ({dati.anno})")
    for campo, valore in dati.model_dump().items():
        setattr(o, campo, valore.strip() if isinstance(valore, str) else valore)


@bp.post("/piao/<piao_id>/obiettivi")
@rpct
async def crea_obiettivo(piao_id: str):
    dati = corpo(ObiettivoIn)
    sessione = db()
    p = await _piao_dell_ente(sessione, piao_id)
    o = AcObiettivo(ente_id=ente_id(), piao_id=p.id)
    await _applica_obiettivo(sessione, o, dati)
    sessione.add(o)
    await sessione.flush()
    audit(sessione, utente(), "ac_obiettivo", o.id, "CREATO", {"codice": o.codice, "anno": o.anno})
    await sessione.commit()
    return _obiettivo(o), HTTPStatus.CREATED


@bp.put("/obiettivi/<obiettivo_id>")
@rpct
async def aggiorna_obiettivo(obiettivo_id: str):
    dati = corpo(ObiettivoIn)
    sessione = db()
    o = await _obiettivo_dell_ente(sessione, obiettivo_id)
    await _applica_obiettivo(sessione, o, dati)
    audit(sessione, utente(), "ac_obiettivo", o.id, "AGGIORNATO", {"codice": o.codice})
    await sessione.commit()
    return _obiettivo(o)


@bp.delete("/obiettivi/<obiettivo_id>")
@rpct
async def elimina_obiettivo(obiettivo_id: str):
    sessione = db()
    o = await _obiettivo_dell_ente(sessione, obiettivo_id)
    audit(sessione, utente(), "ac_obiettivo", o.id, "ELIMINATO", {"codice": o.codice})
    await _elimina_obiettivi(sessione, [o.id])
    await sessione.commit()
    return nessun_contenuto()


@bp.post("/piao/<piao_id>/obiettivi/importa")
@rpct
async def importa_obiettivi(piao_id: str):
    """Obiettivi dal file del Piano della performance: nuovi o aggiornati (per codice e anno);
    la struttura si abbina dal centro del Piano, e quella scelta a mano non si tocca."""
    sessione = db()
    p = await _piao_dell_ente(sessione, piao_id)
    file = file_caricato()
    contenuto = file.read(5 * 1024 * 1024 + 1)
    if len(contenuto) > 5 * 1024 * 1024:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande (massimo 5 MB)")
    try:
        righe = importazione_obiettivi.leggi(contenuto, file.filename or "")
    except importazione_obiettivi.FileNonLeggibile as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    if not righe:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Nel file non ci sono obiettivi (servono codice e anno nelle colonne 1 e 4)")
    fuori = sorted({r["anno"] for r in righe if not p.anno_inizio <= r["anno"] <= p.anno_fine})
    strutture = {sid: s.codice for sid, s in (await _strutture_ente(sessione)).items()}
    esistenti = {(o.codice, o.anno): o for o in await sessione.scalars(select(AcObiettivo).where(AcObiettivo.piao_id == p.id))}
    creati = aggiornati = 0
    non_abbinati: set[str] = set()
    for r in righe:
        if r["codice"] and len(r["codice"]) > 100:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Codice troppo lungo: {r['codice'][:40]}...")
        o = esistenti.get((r["codice"], r["anno"]))
        if o is None:
            o = AcObiettivo(ente_id=ente_id(), piao_id=p.id, codice=r["codice"], anno=r["anno"])
            o.struttura_id = importazione_obiettivi.abbina_struttura(r["centro"], strutture)
            sessione.add(o)
            esistenti[(o.codice, o.anno)] = o
            creati += 1
        else:
            if o.struttura_id is None:
                o.struttura_id = importazione_obiettivi.abbina_struttura(r["centro"], strutture)
            aggiornati += 1
        o.titolo, o.tipo, o.responsabile = r["titolo"], (r["tipo"] or "")[:100] or None, (r["responsabile"] or "")[:255] or None
        o.centro_piano, o.centro_descrizione = (r["centro"] or "")[:255] or None, (r["centro_descrizione"] or "")[:500] or None
        o.fonte = (file.filename or "")[:255]
        if r["centro"] and o.struttura_id is None:
            non_abbinati.add(r["centro"])
    audit(sessione, utente(), "ac_piao", p.id, "OBIETTIVI_IMPORTATI", {"creati": creati, "aggiornati": aggiornati})
    await sessione.commit()
    return {"creati": creati, "aggiornati": aggiornati, "centri_non_abbinati": sorted(non_abbinati),
            "anni_fuori_dal_piao": fuori}  # fmt: skip


@bp.get("/obiettivi/<obiettivo_id>")
@lettore
async def obiettivo(obiettivo_id: str):
    """Obiettivo con i processi e le attività collegati (e quanti rischi e misure ne seguono)."""
    sessione = db()
    o = await _obiettivo_dell_ente(sessione, obiettivo_id)
    collegamenti = list(await sessione.scalars(select(AcObiettivoCollegamento).where(AcObiettivoCollegamento.obiettivo_id == o.id)))
    processi = {p.id: p for p in await sessione.scalars(
        select(AcProcesso).where(AcProcesso.id.in_([c.processo_id for c in collegamenti if c.processo_id])))}  # fmt: skip
    attivita = {a.id: a for a in await sessione.scalars(
        select(AcAttivita).where(AcAttivita.id.in_([c.attivita_id for c in collegamenti if c.attivita_id])))}  # fmt: skip
    processi_attivita = {a.processo_id for a in attivita.values()}
    processi |= {p.id: p for p in await sessione.scalars(select(AcProcesso).where(AcProcesso.id.in_(processi_attivita)))}
    voci = []
    for c in collegamenti:
        if c.processo_id in processi:
            p = processi[c.processo_id]
            voci.append({"id": c.id, "tipo": "processo", "elemento_id": p.id, "codice": p.codice,
                         "descrizione": p.denominazione, "processo_id": p.id, "note": c.note})  # fmt: skip
        elif c.attivita_id in attivita:
            a = attivita[c.attivita_id]
            voci.append({"id": c.id, "tipo": "attivita", "elemento_id": a.id, "codice": a.codice,
                         "descrizione": a.descrizione, "processo_id": a.processo_id,
                         "processo": processi[a.processo_id].codice, "note": c.note})  # fmt: skip
    voci.sort(key=lambda v: chiave_naturale(v["codice"]))
    return {**_obiettivo(o), "collegamenti": voci}


class CollegamentoIn(BaseModel):
    processo_id: str | None = None
    attivita_id: str | None = None
    note: str | None = Field(default=None, max_length=5000)


@bp.post("/obiettivi/<obiettivo_id>/collegamenti")
@lettore
async def collega(obiettivo_id: str):
    """Collega un processo (con tutte le sue attività, anche future) o una singola attività.
    Collegando il processo, i collegamenti delle sue attività diventano superflui e si tolgono."""
    dati = corpo(CollegamentoIn)
    if bool(dati.processo_id) == bool(dati.attivita_id):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica un processo oppure un'attività")
    sessione = db()
    o = await _obiettivo_dell_ente(sessione, obiettivo_id)
    gia = select(AcObiettivoCollegamento.id).where(AcObiettivoCollegamento.obiettivo_id == o.id)
    if dati.processo_id:
        p = await _processo_dell_ente(sessione, dati.processo_id)
        if await sessione.scalar(gia.where(AcObiettivoCollegamento.processo_id == p.id)):
            raise ErroreApi(HTTPStatus.CONFLICT, "Il processo è già collegato all'obiettivo")
        ids_attivita = list(await sessione.scalars(select(AcAttivita.id).where(AcAttivita.processo_id == p.id)))
        await sessione.execute(delete(AcObiettivoCollegamento).where(
            AcObiettivoCollegamento.obiettivo_id == o.id, AcObiettivoCollegamento.attivita_id.in_(ids_attivita)))  # fmt: skip
        c = AcObiettivoCollegamento(ente_id=ente_id(), obiettivo_id=o.id, processo_id=p.id)
    else:
        a = await _attivita_dell_ente(sessione, dati.attivita_id)
        if await sessione.scalar(gia.where(AcObiettivoCollegamento.processo_id == a.processo_id)):
            raise ErroreApi(HTTPStatus.CONFLICT, "L'attività è già compresa: il suo processo è collegato all'obiettivo")
        if await sessione.scalar(gia.where(AcObiettivoCollegamento.attivita_id == a.id)):
            raise ErroreApi(HTTPStatus.CONFLICT, "L'attività è già collegata all'obiettivo")
        c = AcObiettivoCollegamento(ente_id=ente_id(), obiettivo_id=o.id, attivita_id=a.id)
    c.note, c.utente_id = dati.note, utente().id
    sessione.add(c)
    await sessione.flush()
    audit(sessione, utente(), "ac_obiettivo", o.id, "COLLEGATO",
          {"processo_id": c.processo_id, "attivita_id": c.attivita_id})  # fmt: skip
    await sessione.commit()
    return {"id": c.id, "obiettivo_id": o.id, "processo_id": c.processo_id, "attivita_id": c.attivita_id,
            "note": c.note}, HTTPStatus.CREATED  # fmt: skip


@bp.delete("/collegamenti/<collegamento_id>")
@lettore
async def scollega(collegamento_id: str):
    sessione = db()
    c = await sessione.get(AcObiettivoCollegamento, collegamento_id)
    if c is None or c.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Collegamento non trovato")
    audit(sessione, utente(), "ac_obiettivo", c.obiettivo_id, "SCOLLEGATO",
          {"processo_id": c.processo_id, "attivita_id": c.attivita_id})  # fmt: skip
    await sessione.delete(c)
    await sessione.commit()
    return nessun_contenuto()


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
            key=lambda x: (x["codice"] is None, chiave_naturale(x["codice"] or "")),
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
    ordine_aree = {a.id: (a.ordine, chiave_naturale(a.codice)) for a in aree.values()}
    for p in sorted(processi, key=lambda p: (ordine_aree.get(p.area_id, (1_000_000, [])), chiave_naturale(p.codice))):
        base_p = [area(p), p.codice, p.denominazione]
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
                    righe.append([*base_p, *base_a, *base_r, *base_m, responsabilita, *extra])
                    if x and (x.fasi or x.tempi or x.struttura_id):
                        attuazione.append([x.codice, x.descrizione, x.fasi, x.tempi,
                                           struttura(x.struttura_id) or responsabilita, x.indicatore, x.target])  # fmt: skip
    contenuto = excel.cartella([
        ("PTPC", ["AREA DI RISCHIO", "ID PROCESSO", "PROCESSI", "ID ATTIVITA'", "ATTIVITA'", "ID RISCHIO",
                  "EVENTO RISCHIOSO", "Valore moda indice probabilità", "Valore moda indice impatto",
                  "Valore complessivo del rischio", "ID MISURA", "MISURA", "RESPONSABILITA'", "TIPO DI MISURA",
                  "CATEGORIA", "OBBLIGO DI PUBBLICAZIONE", "FATTORE ABILITANTE"], righe),
        ("Attuazione misure", ["ID MISURA", "MISURA", "FASI DI ATTUAZIONE", "TEMPI", "UFFICIO RESPONSABILE",
                               "INDICATORE", "TARGET"], attuazione),
    ])  # fmt: skip
    return allegato(contenuto, excel.MIME, "allegato_ptpct.xlsx")
