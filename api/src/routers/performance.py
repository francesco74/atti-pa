"""Modulo performance: PIAO triennali, obiettivi annuali delle strutture con azioni e misure,
percentuali di impegno e di completamento, scadenze, iter di approvazione e storico.

Gli obiettivi cambiano solo con l'approvazione. Il responsabile (dirigente di un servizio o
responsabile di un ufficio, secondo la struttura del suo utente) propone la creazione, la
modifica o l'eliminazione di un obiettivo della propria struttura: la proposta porta la versione
completa dell'obiettivo con le azioni e misure, si prepara in bozza e si invia. L'approvatore
(ruolo PERFORMANCE_APPROVATORE) la approva (e la modifica si applica), la respinge o la
restituisce per una correzione; modifica anche direttamente. Il completamento di azioni e misure
è monitoraggio, non programmazione: il responsabile lo aggiorna senza approvazione.

L'amministratore della performance (o l'amministratore dell'ente) crea, apre e chiude i PIAO,
vede tutto e propone come i responsabili, per qualsiasi struttura. Il responsabile vede in sola
lettura gli obiettivi delle strutture sottostanti. Con il PIAO chiuso nulla si modifica.

Gli impegni degli obiettivi di una struttura in un anno, e quelli delle azioni e misure di un
obiettivo, non possono superare 100; il completamento si calcola (common/performance). Le misure
si scelgono tra quelle della mappatura dei rischi (modulo anticorruzione). Ogni creazione,
modifica ed eliminazione finisce nello storico (pf_modifiche), con i valori prima e dopo.

Azioni e misure hanno degli indicatori (pf_indicatori): cosa si misura e il valore da
raggiungere fanno parte dell'obiettivo (proposte, approvazione); il valore rilevato è
avanzamento. Con almeno un indicatore il completamento dell'azione o misura si calcola dal loro
raggiungimento, altrimenti si inserisce a mano.
"""

from __future__ import annotations

from datetime import date, datetime
from http import HTTPStatus
from typing import Literal

from flask import Blueprint, request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, or_, select

from deps import audit, autenticato, db, ente, ente_id, utente
from web import ErroreApi, corpo, nessun_contenuto, parametri
from common import posta
from common.anticorruzione.metodologia import chiave_naturale
from common.models import (
    AcMisura, Ente, Modulo, PfElemento, PfIndicatore, PfModifica, PfObiettivo, PfPiao, PfProposta, Ruolo, Struttura, User,
    nuovo_id,
)  # fmt: skip
from common.performance import (
    AVVISO, TOTALE, completamento_indicatori, controlli_obiettivo, disponibile, errore_indicatore, in_ritardo, media_pesata,
    raggiungimento, testo_indicatore, valore_indicatore,
)  # fmt: skip

bp = Blueprint("performance", __name__, url_prefix="/api/v1/performance")

lettore = autenticato(Ruolo.PERFORMANCE_RESPONSABILE, Ruolo.PERFORMANCE_APPROVATORE, Ruolo.PERFORMANCE_AMMINISTRATORE,
                      modulo=Modulo.PERFORMANCE)  # fmt: skip
amministratore = autenticato(Ruolo.PERFORMANCE_AMMINISTRATORE, modulo=Modulo.PERFORMANCE)
approvatore = autenticato(Ruolo.PERFORMANCE_APPROVATORE, modulo=Modulo.PERFORMANCE)

APERTE = ("BOZZA", "INVIATA", "RESTITUITA")  # proposte non ancora decise


# --- permessi -------------------------------------------------------------------------------


def _e_amministratore() -> bool:
    return utente().ha_ruolo(Ruolo.ADMIN, Ruolo.PERFORMANCE_AMMINISTRATORE)


def _e_approvatore() -> bool:
    """Approvatore (anche l'amministratore dell'ente, come in tutti i controlli dei ruoli; le
    email delle proposte vanno però solo a chi ha il ruolo)."""
    return utente().ha_ruolo(Ruolo.ADMIN, Ruolo.PERFORMANCE_APPROVATORE)


async def _strutture() -> dict[str, Struttura]:
    return {s.id: s for s in await db().scalars(select(Struttura).where(Struttura.ente_id == ente_id()))}


def _sottostanti(strutture: dict[str, Struttura], radice: str) -> set[str]:
    risultato, cresciuto = {radice}, True
    while cresciuto:
        cresciuto = False
        for s in strutture.values():
            if s.padre_id in risultato and s.id not in risultato:
                risultato.add(s.id)
                cresciuto = True
    return risultato


async def _visibili() -> set[str] | None:
    """Strutture di cui l'utente vede gli obiettivi (None: tutte)."""
    if _e_amministratore() or _e_approvatore():
        return None
    if not utente().struttura_id:
        return set()
    return _sottostanti(await _strutture(), utente().struttura_id)


def _della_struttura(struttura_id: str | None) -> bool:
    """Gestisce le proposte della struttura: il responsabile per la sua, l'amministratore per
    tutte. L'approvatore modifica direttamente."""
    return not _e_approvatore() and (
        _e_amministratore() or (struttura_id is not None and struttura_id == utente().struttura_id))


def _proponibile(struttura_id: str | None, piao: PfPiao) -> bool:
    return piao.stato == "APERTO" and _della_struttura(struttura_id)


def _avanzamento(o: PfObiettivo, piao: PfPiao) -> bool:
    """Può aggiornare l'avanzamento di azioni e misure (completamento, valori rilevati)."""
    return piao.stato == "APERTO" and (_e_approvatore() or _e_amministratore() or o.struttura_id == utente().struttura_id)


async def _piao_dell_ente(piao_id: str) -> PfPiao:
    p = await db().get(PfPiao, piao_id)
    if p is None or p.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "PIAO non trovato")
    return p


def _aperto(p: PfPiao) -> None:
    if p.stato != "APERTO":
        raise ErroreApi(HTTPStatus.CONFLICT, "Il PIAO è chiuso: non si può modificare")


async def _obiettivo_visibile(obiettivo_id: str) -> tuple[PfObiettivo, PfPiao]:
    o = await db().get(PfObiettivo, obiettivo_id)
    visibili = await _visibili()
    if o is None or o.ente_id != ente_id() or (visibili is not None and o.struttura_id not in visibili):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Obiettivo non trovato")
    return o, await db().get(PfPiao, o.piao_id)


async def _obiettivo_modificabile(obiettivo_id: str) -> tuple[PfObiettivo, PfPiao]:
    """Modifica diretta: solo l'approvatore (route con @approvatore), PIAO aperto."""
    o, p = await _obiettivo_visibile(obiettivo_id)
    _aperto(p)
    return o, p


# --- storico --------------------------------------------------------------------------------


def _valore(v):
    return v.isoformat() if isinstance(v, date) else v


def _differenze(prima: dict, dopo: dict) -> dict:
    return {k: [_valore(prima.get(k)), _valore(v)] for k, v in dopo.items() if _valore(prima.get(k)) != _valore(v)}


def _registra(oggetto: str, oggetto_id: str, azione: str, descrizione: str, *, piao_id: str | None,
              obiettivo_id: str | None = None, campi: dict | None = None, nota: str | None = None) -> None:  # fmt: skip
    u = utente()
    db().add(PfModifica(
        ente_id=ente_id(), piao_id=piao_id, obiettivo_id=obiettivo_id, oggetto=oggetto, oggetto_id=oggetto_id,
        azione=azione, descrizione=descrizione[:500], campi=campi or None, nota=(nota or "").strip() or None,
        utente_id=u.id, utente_nome=u.nome_completo or u.username,
    ))  # fmt: skip


def _modifica(m: PfModifica) -> dict:
    return {
        "id": m.id, "oggetto": m.oggetto, "oggetto_id": m.oggetto_id, "obiettivo_id": m.obiettivo_id,
        "azione": m.azione, "descrizione": m.descrizione, "campi": m.campi or {}, "nota": m.nota,
        "utente": m.utente_nome, "quando": m.created_at.isoformat() if m.created_at else None,
    }  # fmt: skip


# --- PIAO -----------------------------------------------------------------------------------


class PiaoIn(BaseModel):
    anno_inizio: int = Field(ge=2000, le=2100)
    titolo: str = Field(min_length=1, max_length=255)
    atto: str | None = Field(default=None, max_length=255)


class PiaoModifica(BaseModel):
    titolo: str = Field(min_length=1, max_length=255)
    atto: str | None = Field(default=None, max_length=255)
    stato: Literal["APERTO", "CHIUSO"]
    nota: str | None = Field(default=None, max_length=5000)


def _piao(p: PfPiao) -> dict:
    return {"id": p.id, "anno_inizio": p.anno_inizio, "anni": [p.anno_inizio + i for i in range(3)],
            "titolo": p.titolo, "atto": p.atto, "stato": p.stato}  # fmt: skip


def _campi_piao(p: PfPiao) -> dict:
    return {"titolo": p.titolo, "atto": p.atto, "stato": p.stato}


@bp.get("/contesto")
@lettore
async def contesto():
    """Cosa può fare l'utente: amministratore, approvatore (con le proposte da decidere) o
    responsabile, la sua struttura, le strutture visibili (None: tutte), se le misure della
    mappatura sono disponibili."""
    visibili = await _visibili()
    da_decidere = 0
    if _e_approvatore():
        da_decidere = await db().scalar(select(func.count()).select_from(PfProposta).where(
            PfProposta.ente_id == ente_id(), PfProposta.stato == "INVIATA"))  # fmt: skip
    return {
        "amministratore": _e_amministratore(),
        "approvatore": _e_approvatore(),
        "da_decidere": da_decidere or 0,
        "struttura_id": utente().struttura_id,
        "visibili": sorted(visibili) if visibili is not None else None,
        "misure": ente().modulo_attivo(Modulo.ANTICORRUZIONE),
    }


@bp.get("/piao")
@lettore
async def elenco_piao():
    """PIAO dell'ente, dal più recente."""
    righe = await db().scalars(select(PfPiao).where(PfPiao.ente_id == ente_id()).order_by(PfPiao.anno_inizio.desc()))
    return [_piao(p) for p in righe]


@bp.post("/piao")
@amministratore
async def crea_piao():
    dati = corpo(PiaoIn)
    sessione = db()
    if await sessione.scalar(select(PfPiao.id).where(PfPiao.ente_id == ente_id(), PfPiao.anno_inizio == dati.anno_inizio)):
        raise ErroreApi(HTTPStatus.CONFLICT, f"Esiste già il PIAO {dati.anno_inizio}-{dati.anno_inizio + 2}")
    p = PfPiao(ente_id=ente_id(), anno_inizio=dati.anno_inizio, titolo=dati.titolo.strip(),
               atto=(dati.atto or "").strip() or None, stato="APERTO")  # fmt: skip
    sessione.add(p)
    await sessione.flush()
    _registra("PIAO", p.id, "CREATO", p.titolo, piao_id=p.id, campi=_differenze({}, _campi_piao(p)))
    audit(sessione, utente(), "pf_piao", p.id, "CREATO", {"anno_inizio": p.anno_inizio})
    await sessione.commit()
    return _piao(p), HTTPStatus.CREATED


@bp.put("/piao/<piao_id>")
@amministratore
async def aggiorna_piao(piao_id: str):
    """Titolo, atto e stato: CHIUSO rende il PIAO in sola lettura, APERTO lo riapre."""
    dati = corpo(PiaoModifica)
    sessione = db()
    p = await _piao_dell_ente(piao_id)
    prima = _campi_piao(p)
    p.titolo, p.atto, p.stato = dati.titolo.strip(), (dati.atto or "").strip() or None, dati.stato
    if campi := _differenze(prima, _campi_piao(p)):
        _registra("PIAO", p.id, "MODIFICATO", p.titolo, piao_id=p.id, campi=campi, nota=dati.nota)
        audit(sessione, utente(), "pf_piao", p.id, "MODIFICATO", {"campi": list(campi)})
    await sessione.commit()
    return _piao(p)


@bp.delete("/piao/<piao_id>")
@amministratore
async def elimina_piao(piao_id: str):
    """Solo un PIAO senza obiettivi (le proposte di creazione si perdono con il PIAO)."""
    sessione = db()
    p = await _piao_dell_ente(piao_id)
    if await sessione.scalar(select(PfObiettivo.id).where(PfObiettivo.piao_id == p.id).limit(1)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Il PIAO ha degli obiettivi: non si può eliminare")
    _registra("PIAO", p.id, "ELIMINATO", p.titolo, piao_id=p.id)
    audit(sessione, utente(), "pf_piao", p.id, "ELIMINATO", {"anno_inizio": p.anno_inizio})
    await sessione.delete(p)
    await sessione.commit()
    return nessun_contenuto()


# --- obiettivi ------------------------------------------------------------------------------


class ObiettivoDati(BaseModel):
    codice: str | None = Field(default=None, max_length=100)
    titolo: str = Field(min_length=1, max_length=500)
    descrizione: str | None = Field(default=None, max_length=10000)
    tipo: Literal["OPERATIVO", "FUNZIONAMENTO", "MIGLIORAMENTO"] = "OPERATIVO"
    impegno: int = Field(ge=0, le=TOTALE)
    nota: str | None = Field(default=None, max_length=5000)  # motivo della modifica (storico)


class ObiettivoNuovo(ObiettivoDati):
    piao_id: str
    anno: int
    struttura_id: str


def _campi_obiettivo(o: PfObiettivo) -> dict:
    return {"codice": o.codice, "titolo": o.titolo, "descrizione": o.descrizione, "tipo": o.tipo, "impegno": o.impegno}


def _imposta_obiettivo(o: PfObiettivo, d: ObiettivoDati | dict) -> None:
    d = d if isinstance(d, dict) else d.model_dump()
    o.codice = (d.get("codice") or "").strip() or None
    o.titolo, o.descrizione = d["titolo"].strip(), (d.get("descrizione") or "").strip() or None
    o.tipo, o.impegno = d["tipo"], d["impegno"]


def _nome(codice: str | None, titolo: str) -> str:
    return f"{codice} - {titolo}" if codice else titolo


def _nome_obiettivo(o: PfObiettivo) -> str:
    return _nome(o.codice, o.titolo)


async def _disponibile_obiettivi(piao_id: str, anno: int, struttura_id: str, escluso: str | None) -> int:
    """Impegno che resta agli obiettivi della struttura nell'anno, escluso l'obiettivo dato."""
    q = select(PfObiettivo.impegno).where(PfObiettivo.piao_id == piao_id, PfObiettivo.anno == anno,
                                          PfObiettivo.struttura_id == struttura_id)  # fmt: skip
    if escluso:
        q = q.where(PfObiettivo.id != escluso)
    return disponibile(await db().scalars(q))


async def _controlla_impegno_obiettivi(o: PfObiettivo) -> None:
    resta = await _disponibile_obiettivi(o.piao_id, o.anno, o.struttura_id, o.id)
    if o.impegno > resta:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"Gli impegni degli obiettivi della struttura superano il 100%: disponibile {resta}%")  # fmt: skip


async def _struttura_dell_ente(struttura_id: str | None) -> Struttura:
    s = await db().get(Struttura, struttura_id) if struttura_id else None
    if s is None or s.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Struttura non trovata")
    return s


def _nel_triennio(p: PfPiao, anno: int) -> None:
    if anno not in range(p.anno_inizio, p.anno_inizio + 3):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"L'anno deve essere nel triennio {p.anno_inizio}-{p.anno_inizio + 2}")  # fmt: skip


def _elemento(x: PfElemento, oggi: date, indicatori: list[PfIndicatore]) -> dict:
    return {
        "id": x.id, "obiettivo_id": x.obiettivo_id, "tipo": x.tipo, "descrizione": x.descrizione,
        "misura_id": x.misura_id, "misura_codice": x.misura_codice, "impegno": x.impegno,
        "completamento": x.completamento, "scadenza": x.scadenza.isoformat(),
        "in_ritardo": in_ritardo(x.scadenza, x.completamento, oggi),
        "indicatori": [_indicatore(i) for i in indicatori],
        "calcolato": bool(indicatori),  # completamento calcolato dagli indicatori
    }  # fmt: skip


def _per_scadenza(elementi):
    return sorted(elementi, key=lambda x: (x.scadenza, x.ordine))


def _riferimento(pr: PfProposta | None) -> dict | None:
    return {"id": pr.id, "tipo": pr.tipo, "stato": pr.stato} if pr else None


def _obiettivo(o: PfObiettivo, p: PfPiao, elementi: list[PfElemento], oggi: date, proposta: PfProposta | None = None,
               indicatori: dict[str, list[PfIndicatore]] | None = None) -> dict:  # fmt: skip
    impegno_elementi = sum(x.impegno for x in elementi)
    return {
        "id": o.id, "piao_id": o.piao_id, "anno": o.anno, "struttura_id": o.struttura_id, "codice": o.codice,
        "titolo": o.titolo, "descrizione": o.descrizione, "tipo": o.tipo, "impegno": o.impegno,
        "completamento": media_pesata((x.impegno, x.completamento) for x in elementi),
        "impegno_elementi": impegno_elementi, "completo": impegno_elementi == TOTALE,
        "azioni": sum(1 for x in elementi if x.tipo == "AZIONE"),
        "misure": sum(1 for x in elementi if x.tipo == "MISURA"),
        "ritardi": sum(1 for x in elementi if in_ritardo(x.scadenza, x.completamento, oggi)),
        "avvisi": sum(1 for c in _controlli(o.impegno, o.anno, o.struttura_id, elementi) if c["livello"] == AVVISO),
        "senza_indicatori": None if indicatori is None else sum(1 for x in elementi if not indicatori.get(x.id)),
        # modifica diretta (approvatore), proposta (responsabile, amministratore), avanzamento
        "modificabile": p.stato == "APERTO" and _e_approvatore(),
        "proponibile": _proponibile(o.struttura_id, p) and proposta is None,
        "avanzamento": _avanzamento(o, p),
        "proposta": _riferimento(proposta),  # proposta aperta sull'obiettivo
    }  # fmt: skip


def _controlli(impegno: int, anno: int, struttura_id: str, elementi: list, strutture_misure: dict | None = None,
               indicatori: dict[str, list] | None = None) -> list[dict]:  # fmt: skip
    """Controlli oggettivi; elementi: PfElemento (con i loro [indicatori], se noti) o dict delle
    proposte (scadenza ISO, con gli indicatori)."""
    voci = []
    for x in elementi:
        if not isinstance(x, dict):
            x = {"tipo": x.tipo, "descrizione": x.descrizione, "impegno": x.impegno, "scadenza": x.scadenza,
                 "misura_id": x.misura_id, **({} if indicatori is None else {"indicatori": indicatori.get(x.id, [])})}  # fmt: skip
        scadenza = date.fromisoformat(x["scadenza"]) if isinstance(x.get("scadenza"), str) else x.get("scadenza")
        voci.append({**x, "scadenza": scadenza})
    return controlli_obiettivo(impegno, anno, struttura_id, voci, misure_attive=ente().modulo_attivo(Modulo.ANTICORRUZIONE),
                               strutture_misure=strutture_misure)  # fmt: skip


async def _strutture_misure(ids: list[str | None]) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {m: s for m, s in await db().execute(select(AcMisura.id, AcMisura.struttura_id).where(AcMisura.id.in_(ids)))}


async def _elementi_di(ids: list[str]) -> dict[str, list[PfElemento]]:
    risultato: dict[str, list[PfElemento]] = {i: [] for i in ids}
    if ids:
        for x in await db().scalars(select(PfElemento).where(PfElemento.obiettivo_id.in_(ids))):
            risultato[x.obiettivo_id].append(x)
    return risultato


async def _indicatori_di(elementi_ids: list[str]) -> dict[str, list[PfIndicatore]]:
    """Indicatori delle azioni e misure date, nel loro ordine."""
    risultato: dict[str, list[PfIndicatore]] = {i: [] for i in elementi_ids}
    if elementi_ids:
        q = select(PfIndicatore).where(PfIndicatore.elemento_id.in_(elementi_ids)).order_by(PfIndicatore.ordine, PfIndicatore.created_at)
        for i in await db().scalars(q):
            risultato[i.elemento_id].append(i)
    return risultato


async def _proposte_aperte(obiettivi_ids: list[str]) -> dict[str, PfProposta]:
    if not obiettivi_ids:
        return {}
    righe = await db().scalars(select(PfProposta).where(PfProposta.obiettivo_id.in_(obiettivi_ids), PfProposta.stato.in_(APERTE)))
    return {pr.obiettivo_id: pr for pr in righe}


class FiltriObiettivi(BaseModel):
    piao_id: str
    anno: int | None = None
    struttura_id: str | None = None


@bp.get("/obiettivi")
@lettore
async def obiettivi():
    """Obiettivi del PIAO (dell'anno, della struttura) visibili all'utente, con il riepilogo
    della struttura nell'anno e le proposte di nuovi obiettivi quando entrambi sono indicati."""
    f = parametri(FiltriObiettivi)
    p = await _piao_dell_ente(f.piao_id)
    q = select(PfObiettivo).where(PfObiettivo.piao_id == p.id)
    if f.anno:
        q = q.where(PfObiettivo.anno == f.anno)
    if f.struttura_id:
        q = q.where(PfObiettivo.struttura_id == f.struttura_id)
    visibili = await _visibili()
    if visibili is not None:
        q = q.where(PfObiettivo.struttura_id.in_(visibili or {""}))
    righe = sorted(await db().scalars(q), key=lambda o: (o.anno, chiave_naturale(o.codice or ""), o.titolo))
    elementi = await _elementi_di([o.id for o in righe])
    aperte = await _proposte_aperte([o.id for o in righe])
    oggi = date.today()
    elenco = [_obiettivo(o, p, _per_scadenza(elementi[o.id]), oggi, aperte.get(o.id)) for o in righe]
    impegno = sum(o["impegno"] for o in elenco)
    nuovi, aggiunta = [], None
    if f.anno and f.struttura_id and (visibili is None or f.struttura_id in visibili):
        nuovi = [_sintesi(pr) for pr in await db().scalars(select(PfProposta).where(
            PfProposta.piao_id == p.id, PfProposta.anno == f.anno, PfProposta.struttura_id == f.struttura_id,
            PfProposta.tipo == "CREA", PfProposta.stato.in_(APERTE)).order_by(PfProposta.created_at))
            if pr.stato != "BOZZA" or _della_struttura(pr.struttura_id)]  # fmt: skip
        if p.stato == "APERTO" and _e_approvatore():
            aggiunta = "DIRETTA"
        elif _proponibile(f.struttura_id, p):
            aggiunta = "PROPOSTA"
    return {
        "obiettivi": elenco,
        "proposte": nuovi,  # nuovi obiettivi proposti, non ancora approvati
        "impegno_totale": impegno,
        "completo": impegno == TOTALE,
        "completamento": media_pesata((o["impegno"], o["completamento"]) for o in elenco),
        "aggiunta": aggiunta,  # come si aggiunge un obiettivo: DIRETTA, PROPOSTA o None
    }


@bp.get("/obiettivi/<obiettivo_id>")
@lettore
async def obiettivo(obiettivo_id: str):
    """Obiettivo con le azioni e le misure (per scadenza)."""
    o, p = await _obiettivo_visibile(obiettivo_id)
    elementi = _per_scadenza((await _elementi_di([o.id]))[o.id])
    indicatori = await _indicatori_di([x.id for x in elementi])
    oggi = date.today()
    strutture_misure = await _strutture_misure([x.misura_id for x in elementi])
    proposta = (await _proposte_aperte([o.id])).get(o.id)
    return {**_obiettivo(o, p, elementi, oggi, proposta, indicatori),
            "elementi": [_elemento(x, oggi, indicatori[x.id]) for x in elementi], "piao": _piao(p),
            "controlli": _controlli(o.impegno, o.anno, o.struttura_id, elementi, strutture_misure, indicatori)}  # fmt: skip


@bp.post("/obiettivi")
@approvatore
async def crea_obiettivo():
    """Creazione diretta (approvatore); il responsabile propone (POST /proposte)."""
    dati = corpo(ObiettivoNuovo)
    sessione = db()
    p = await _piao_dell_ente(dati.piao_id)
    _aperto(p)
    _nel_triennio(p, dati.anno)
    s = await _struttura_dell_ente(dati.struttura_id)
    o = PfObiettivo(ente_id=ente_id(), piao_id=p.id, anno=dati.anno, struttura_id=s.id)
    _imposta_obiettivo(o, dati)
    await _controlla_impegno_obiettivi(o)
    sessione.add(o)
    await sessione.flush()
    _registra("OBIETTIVO", o.id, "CREATO", _nome_obiettivo(o), piao_id=p.id, obiettivo_id=o.id,
              campi=_differenze({}, {**_campi_obiettivo(o), "anno": o.anno, "struttura": s.codice}), nota=dati.nota)  # fmt: skip
    await sessione.commit()
    return _obiettivo(o, p, [], date.today()), HTTPStatus.CREATED


@bp.put("/obiettivi/<obiettivo_id>")
@approvatore
async def aggiorna_obiettivo(obiettivo_id: str):
    """Codice, titolo, descrizione, tipo e impegno (anno e struttura restano)."""
    dati = corpo(ObiettivoDati)
    sessione = db()
    o, p = await _obiettivo_modificabile(obiettivo_id)
    prima = _campi_obiettivo(o)
    _imposta_obiettivo(o, dati)
    await _controlla_impegno_obiettivi(o)
    if campi := _differenze(prima, _campi_obiettivo(o)):
        _registra("OBIETTIVO", o.id, "MODIFICATO", _nome_obiettivo(o), piao_id=p.id, obiettivo_id=o.id,
                  campi=campi, nota=dati.nota)  # fmt: skip
    await sessione.commit()
    elementi = _per_scadenza((await _elementi_di([o.id]))[o.id])
    return _obiettivo(o, p, elementi, date.today())


def _nota_richiesta() -> str | None:
    """Nota facoltativa di un'eliminazione (corpo JSON {"nota": ...})."""
    dati = request.get_json(silent=True) or {}
    nota = dati.get("nota") if isinstance(dati, dict) else None
    return str(nota)[:5000] if nota else None


async def _elimina_obiettivo(o: PfObiettivo, nota: str | None) -> None:
    """Elimina l'obiettivo con le sue azioni e misure (restano nello storico)."""
    _registra("OBIETTIVO", o.id, "ELIMINATO", _nome_obiettivo(o), piao_id=o.piao_id, obiettivo_id=o.id,
              campi=_differenze(_campi_obiettivo(o), {k: None for k in _campi_obiettivo(o)}), nota=nota)  # fmt: skip
    await db().execute(delete(PfElemento).where(PfElemento.obiettivo_id == o.id))
    await db().delete(o)


@bp.delete("/obiettivi/<obiettivo_id>")
@approvatore
async def elimina_obiettivo(obiettivo_id: str):
    """Elimina l'obiettivo con le sue azioni e misure (restano nello storico)."""
    o, _ = await _obiettivo_modificabile(obiettivo_id)
    await _elimina_obiettivo(o, _nota_richiesta())
    await db().commit()
    return nessun_contenuto()


# --- indicatori -----------------------------------------------------------------------------


class IndicatoreIn(BaseModel):
    """Definizione di un indicatore: id di uno esistente (modifica) o nessuno (nuovo)."""

    id: str | None = Field(default=None, max_length=64)
    descrizione: str = Field(min_length=1, max_length=2000)
    tipo: Literal["NUMERO", "PERCENTUALE", "SI_NO", "DATA"] = "NUMERO"
    unita: str | None = Field(default=None, max_length=50)
    partenza: float | None = None
    target: float | None = None
    target_data: date | None = None
    verso: Literal["CRESCENTE", "DECRESCENTE"] = "CRESCENTE"
    fonte: str | None = Field(default=None, max_length=255)


_CAMPI_INDICATORE = ("descrizione", "tipo", "unita", "partenza", "target", "target_data", "verso", "fonte")


def _definizione(i: IndicatoreIn) -> dict:
    """Definizione controllata, con i soli campi che servono al tipo (date in ISO)."""
    numerico = i.tipo in ("NUMERO", "PERCENTUALE")
    d = {
        "id": i.id, "descrizione": i.descrizione.strip(), "tipo": i.tipo,
        "unita": ((i.unita or "").strip() or None) if i.tipo == "NUMERO" else None,
        "partenza": i.partenza if numerico else None, "target": i.target if numerico else None,
        "target_data": i.target_data.isoformat() if i.tipo == "DATA" and i.target_data else None,
        "verso": i.verso if numerico else "CRESCENTE", "fonte": (i.fonte or "").strip() or None,
    }  # fmt: skip
    if not d["descrizione"]:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Descrivi ogni indicatore")
    if errore := errore_indicatore(d):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Indicatore «{d['descrizione'][:60]}»: {errore}")
    return d


def _definizione_di(i: PfIndicatore) -> dict:
    return {"id": i.id, "descrizione": i.descrizione, "tipo": i.tipo, "unita": i.unita, "partenza": i.partenza,
            "target": i.target, "target_data": i.target_data.isoformat() if i.target_data else None,
            "verso": i.verso, "fonte": i.fonte}  # fmt: skip


def _con_rilevato(i: PfIndicatore) -> dict:
    return {**_definizione_di(i), "rilevato": i.rilevato, "rilevato_data": i.rilevato_data}


def _indicatore(i: PfIndicatore) -> dict:
    d = _con_rilevato(i)
    return {**d, "rilevato_data": i.rilevato_data.isoformat() if i.rilevato_data else None,
            "rilevato_il": i.rilevato_il.isoformat() if i.rilevato_il else None,
            "raggiungimento": raggiungimento(d), "testo": testo_indicatore(d)}  # fmt: skip


def _ricalcola(x: PfElemento, indicatori: list[PfIndicatore]) -> None:
    """Con degli indicatori il completamento dell'azione o misura si calcola da loro."""
    valore = completamento_indicatori(_con_rilevato(i) for i in indicatori)
    if valore is not None:
        x.completamento = valore


def _campi_indicatore(d: dict) -> dict:
    return {k: d.get(k) for k in _CAMPI_INDICATORE}


def _nome_indicatore(x: PfElemento, descrizione: str) -> str:
    return f"{_nome_elemento(x)[:240]} › {descrizione}"


async def _sincronizza_indicatori(x: PfElemento, esistenti: list[PfIndicatore], definizioni: list[dict], *,
                                  piao_id: str, nota: str | None) -> list[PfIndicatore]:  # fmt: skip
    """Porta gli indicatori dell'azione o misura alle [definizioni]: con l'id di uno esistente
    lo modificano (il rilevato resta, se il tipo non cambia), gli altri sono nuovi, quelli che
    mancano si eliminano. Tutto va nello storico; poi si ricalcola il completamento."""
    sessione = db()
    await sessione.flush()  # l'azione o misura nuova prima dei suoi indicatori
    per_id = {i.id: i for i in esistenti}
    tenuti = {d.get("id") for d in definizioni}
    for i in esistenti:
        if i.id not in tenuti:
            _registra("INDICATORE", i.id, "ELIMINATO", _nome_indicatore(x, i.descrizione), piao_id=piao_id,
                      obiettivo_id=x.obiettivo_id, nota=nota,
                      campi=_differenze(_campi_indicatore(_definizione_di(i)), dict.fromkeys(_CAMPI_INDICATORE)))  # fmt: skip
            await sessione.delete(i)
    risultato = []
    for ordine, d in enumerate(definizioni):
        i = per_id.get(d.get("id"))
        if i is None:
            i = PfIndicatore(id=nuovo_id(), ente_id=ente_id(), elemento_id=x.id)
            sessione.add(i)
            prima, azione = {}, "CREATO"
        else:
            prima, azione = _campi_indicatore(_definizione_di(i)), "MODIFICATO"
            if i.tipo != d["tipo"]:  # il valore rilevato non ha più senso
                i.rilevato = i.rilevato_data = i.rilevato_il = None
        i.descrizione, i.tipo, i.unita, i.verso, i.fonte = d["descrizione"], d["tipo"], d["unita"], d["verso"], d["fonte"]
        i.partenza, i.target, i.ordine = d["partenza"], d["target"], ordine
        i.target_data = date.fromisoformat(d["target_data"]) if d["target_data"] else None
        if campi := _differenze(prima, _campi_indicatore(_definizione_di(i))):
            _registra("INDICATORE", i.id, azione, _nome_indicatore(x, i.descrizione), piao_id=piao_id,
                      obiettivo_id=x.obiettivo_id, campi=campi, nota=nota)  # fmt: skip
        risultato.append(i)
    _ricalcola(x, risultato)
    return risultato


# --- azioni e misure ------------------------------------------------------------------------


class ElementoDati(BaseModel):
    descrizione: str | None = Field(default=None, max_length=10000)  # dell'azione
    impegno: int = Field(ge=0, le=TOTALE)
    completamento: int = Field(default=0, ge=0, le=TOTALE)  # con degli indicatori si calcola
    scadenza: date
    indicatori: list[IndicatoreIn] | None = Field(default=None, max_length=50)  # None: restano come sono
    nota: str | None = Field(default=None, max_length=5000)


class ElementoNuovo(ElementoDati):
    tipo: Literal["AZIONE", "MISURA"]
    misura_id: str | None = None


def _campi_elemento(x: PfElemento) -> dict:
    return {"descrizione": x.descrizione, "impegno": x.impegno, "completamento": x.completamento, "scadenza": x.scadenza}


def _nome_elemento(x: PfElemento) -> str:
    return _nome(x.misura_codice, x.descrizione)


async def _controlla_impegno_elementi(x: PfElemento) -> None:
    altri = await db().scalars(select(PfElemento.impegno).where(
        PfElemento.obiettivo_id == x.obiettivo_id, PfElemento.id != x.id))  # fmt: skip
    resta = disponibile(altri)
    if x.impegno > resta:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"Gli impegni delle azioni e misure dell'obiettivo superano il 100%: disponibile {resta}%")  # fmt: skip


async def _elemento_visibile(elemento_id: str) -> tuple[PfElemento, PfObiettivo, PfPiao]:
    x = await db().get(PfElemento, elemento_id)
    if x is None or x.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Azione o misura non trovata")
    o, p = await _obiettivo_visibile(x.obiettivo_id)
    _aperto(p)
    return x, o, p


async def _misura_dell_ente(misura_id: str | None) -> AcMisura:
    if not ente().modulo_attivo(Modulo.ANTICORRUZIONE):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Le misure vengono dalla mappatura dei rischi: modulo non attivo")
    m = await db().get(AcMisura, misura_id) if misura_id else None
    if m is None or m.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Scegli una misura della mappatura dei rischi")
    return m


@bp.post("/obiettivi/<obiettivo_id>/elementi")
@approvatore
async def crea_elemento(obiettivo_id: str):
    """Nuova azione (con la descrizione) o misura (scelta dalla mappatura dei rischi), con gli
    indicatori."""
    dati = corpo(ElementoNuovo)
    sessione = db()
    o, p = await _obiettivo_modificabile(obiettivo_id)
    definizioni = [_definizione(i) for i in dati.indicatori or []]
    x = PfElemento(id=nuovo_id(), ente_id=ente_id(), obiettivo_id=o.id, tipo=dati.tipo, impegno=dati.impegno,
                   completamento=dati.completamento, scadenza=dati.scadenza)  # fmt: skip
    if dati.tipo == "AZIONE":
        if not (dati.descrizione or "").strip():
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Descrivi l'azione")
        x.descrizione = dati.descrizione.strip()
    else:
        m = await _misura_dell_ente(dati.misura_id)
        if await sessione.scalar(select(PfElemento.id).where(PfElemento.obiettivo_id == o.id, PfElemento.misura_id == m.id)):
            raise ErroreApi(HTTPStatus.CONFLICT, f"La misura {m.codice} è già nell'obiettivo")
        x.misura_id, x.misura_codice, x.descrizione = m.id, m.codice, m.descrizione
    await _controlla_impegno_elementi(x)
    x.ordine = (await sessione.scalar(select(func.count()).where(PfElemento.obiettivo_id == o.id))) or 0
    sessione.add(x)
    indicatori = await _sincronizza_indicatori(x, [], definizioni, piao_id=p.id, nota=dati.nota)
    _registra(x.tipo, x.id, "CREATO", _nome_elemento(x), piao_id=p.id, obiettivo_id=o.id,
              campi=_differenze({}, _campi_elemento(x)), nota=dati.nota)  # fmt: skip
    await sessione.commit()
    return _elemento(x, date.today(), indicatori), HTTPStatus.CREATED


@bp.put("/elementi/<elemento_id>")
@approvatore
async def aggiorna_elemento(elemento_id: str):
    """Impegno, scadenza, indicatori (se indicati), completamento (senza indicatori) e, per le
    azioni, la descrizione."""
    dati = corpo(ElementoDati)
    sessione = db()
    x, o, p = await _elemento_visibile(elemento_id)
    prima = _campi_elemento(x)
    if x.tipo == "AZIONE" and dati.descrizione is not None:
        if not dati.descrizione.strip():
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Descrivi l'azione")
        x.descrizione = dati.descrizione.strip()
    x.impegno, x.completamento, x.scadenza = dati.impegno, dati.completamento, dati.scadenza
    await _controlla_impegno_elementi(x)
    indicatori = (await _indicatori_di([x.id]))[x.id]
    if dati.indicatori is not None:
        definizioni = [_definizione(i) for i in dati.indicatori]
        indicatori = await _sincronizza_indicatori(x, indicatori, definizioni, piao_id=p.id, nota=dati.nota)
    else:
        _ricalcola(x, indicatori)
    if campi := _differenze(prima, _campi_elemento(x)):
        _registra(x.tipo, x.id, "MODIFICATO", _nome_elemento(x), piao_id=p.id, obiettivo_id=o.id,
                  campi=campi, nota=dati.nota)  # fmt: skip
    await sessione.commit()
    return _elemento(x, date.today(), indicatori)


class RilevazioneIn(BaseModel):
    id: str
    rilevato: float | None = None  # numero, percentuale; sì/no: 1 o 0
    rilevato_data: date | None = None  # data: quando è stato raggiunto


class AvanzamentoIn(BaseModel):
    completamento: int | None = Field(default=None, ge=0, le=TOTALE)  # senza indicatori
    indicatori: list[RilevazioneIn] = Field(default_factory=list, max_length=50)  # valori rilevati
    nota: str | None = Field(default=None, max_length=5000)


def _rileva(i: PfIndicatore, r: RilevazioneIn) -> tuple[float | None, date | None]:
    """Valore rilevato controllato per il tipo dell'indicatore."""
    if i.tipo == "DATA":
        return None, r.rilevato_data
    if i.tipo == "SI_NO" and r.rilevato not in (None, 0, 1):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Indicatore «{i.descrizione[:60]}»: rilevato sì o no")
    if i.tipo == "PERCENTUALE" and r.rilevato is not None and not 0 <= r.rilevato <= 100:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Indicatore «{i.descrizione[:60]}»: percentuale da 0 a 100")
    return r.rilevato, None


@bp.put("/elementi/<elemento_id>/avanzamento")
@lettore
async def aggiorna_avanzamento(elemento_id: str):
    """Avanzamento di un'azione o misura, senza approvazione, per il responsabile della
    struttura, l'amministratore e l'approvatore: i valori rilevati degli indicatori (il
    completamento si calcola) o, senza indicatori, il completamento. Resta nello storico."""
    dati = corpo(AvanzamentoIn)
    sessione = db()
    x, o, p = await _elemento_visibile(elemento_id)
    if not _avanzamento(o, p):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Puoi aggiornare solo l'avanzamento degli obiettivi della tua struttura")
    prima = x.completamento
    indicatori = (await _indicatori_di([x.id]))[x.id]
    if indicatori:
        per_id = {i.id: i for i in indicatori}
        for r in dati.indicatori:
            i = per_id.get(r.id)
            if i is None:
                raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indicatore non trovato nell'azione o misura")
            rilevato, rilevato_data = _rileva(i, r)
            if (rilevato, rilevato_data) == (i.rilevato, i.rilevato_data):
                continue
            d = _definizione_di(i)
            vecchio = i.rilevato_data if i.tipo == "DATA" else i.rilevato
            nuovo = rilevato_data if i.tipo == "DATA" else rilevato
            _registra("INDICATORE", i.id, "MODIFICATO", _nome_indicatore(x, i.descrizione), piao_id=p.id, obiettivo_id=o.id,
                      campi={"rilevato": [_valore_rilevato(d, vecchio), _valore_rilevato(d, nuovo)]}, nota=dati.nota)  # fmt: skip
            i.rilevato, i.rilevato_data, i.rilevato_il = rilevato, rilevato_data, datetime.now()
        _ricalcola(x, indicatori)
    elif dati.completamento is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica il completamento")
    else:
        x.completamento = dati.completamento
    if x.completamento != prima:
        _registra(x.tipo, x.id, "MODIFICATO", _nome_elemento(x), piao_id=p.id, obiettivo_id=o.id,
                  campi={"completamento": [prima, x.completamento]}, nota=dati.nota)  # fmt: skip
    await sessione.commit()
    return _elemento(x, date.today(), indicatori)


def _valore_rilevato(d: dict, v) -> str | None:
    return None if v is None else valore_indicatore(d, v)


@bp.delete("/elementi/<elemento_id>")
@approvatore
async def elimina_elemento(elemento_id: str):
    sessione = db()
    x, o, p = await _elemento_visibile(elemento_id)
    _registra(x.tipo, x.id, "ELIMINATO", _nome_elemento(x), piao_id=p.id, obiettivo_id=o.id,
              campi=_differenze(_campi_elemento(x), {k: None for k in _campi_elemento(x)}), nota=_nota_richiesta())  # fmt: skip
    await sessione.delete(x)
    await sessione.commit()
    return nessun_contenuto()


class FiltriMisure(BaseModel):
    testo: str | None = Field(default=None, max_length=200)
    struttura_id: str | None = None  # le sue misure (e quelle trasversali) per prime


@bp.get("/misure")
@lettore
async def misure():
    """Misure della mappatura dei rischi da collegare agli obiettivi (al massimo 200)."""
    if not ente().modulo_attivo(Modulo.ANTICORRUZIONE):
        return []
    f = parametri(FiltriMisure)
    q = select(AcMisura).where(AcMisura.ente_id == ente_id())
    if testo := (f.testo or "").strip():
        q = q.where(or_(AcMisura.codice.ilike(f"%{testo}%"), AcMisura.descrizione.ilike(f"%{testo}%")))
    righe = list(await db().scalars(q))

    def priorita(m: AcMisura) -> int:
        return 0 if f.struttura_id and m.struttura_id == f.struttura_id else 1 if m.struttura_id is None else 2

    righe.sort(key=lambda m: (priorita(m), chiave_naturale(m.codice)))
    return [{"id": m.id, "codice": m.codice, "descrizione": m.descrizione, "tipo": m.tipo, "categoria": m.categoria,
             "struttura_id": m.struttura_id, "tempi": m.tempi, "indicatore": m.indicatore, "target": m.target}
            for m in righe[:200]]  # fmt: skip


# --- proposte -------------------------------------------------------------------------------
# La proposta di creazione o modifica porta l'obiettivo intero: {codice, titolo, descrizione,
# tipo, impegno, elementi: [{id, tipo, descrizione, misura_id, misura_codice, impegno,
# scadenza, indicatori: [{id, descrizione, tipo, unita, partenza, target, target_data, verso,
# fonte}]}]}. Gli elementi (e gli indicatori) con l'id di uno esistente lo modificano, gli altri
# sono nuovi (l'id si assegna all'approvazione), quelli che mancano si eliminano. L'avanzamento
# (completamento, valori rilevati) non fa parte della proposta: quello esistente resta, i nuovi
# partono da 0.


class ElementoProposto(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    tipo: Literal["AZIONE", "MISURA"]
    descrizione: str | None = Field(default=None, max_length=10000)
    misura_id: str | None = None
    impegno: int = Field(ge=0, le=TOTALE)
    scadenza: date
    indicatori: list[IndicatoreIn] = Field(default_factory=list, max_length=50)


class ObiettivoProposto(BaseModel):
    codice: str | None = Field(default=None, max_length=100)
    titolo: str = Field(min_length=1, max_length=500)
    descrizione: str | None = Field(default=None, max_length=10000)
    tipo: Literal["OPERATIVO", "FUNZIONAMENTO", "MIGLIORAMENTO"] = "OPERATIVO"
    impegno: int = Field(ge=0, le=TOTALE)
    elementi: list[ElementoProposto] = Field(default_factory=list, max_length=200)


_CAMPI_OBIETTIVO = ("codice", "titolo", "descrizione", "tipo", "impegno")
_CAMPI_ELEMENTO = ("descrizione", "misura_codice", "impegno", "scadenza", "indicatori")


def _elemento_proposto(x: PfElemento, indicatori: list[PfIndicatore]) -> dict:
    return {"id": x.id, "tipo": x.tipo, "descrizione": x.descrizione, "misura_id": x.misura_id,
            "misura_codice": x.misura_codice, "impegno": x.impegno, "scadenza": x.scadenza.isoformat(),
            "indicatori": [_definizione_di(i) for i in indicatori]}  # fmt: skip


def _istantanea(o: PfObiettivo, elementi: list[PfElemento], indicatori: dict[str, list[PfIndicatore]]) -> dict:
    """L'obiettivo com'è, nella forma dei dati delle proposte."""
    return {**_campi_obiettivo(o),
            "elementi": [_elemento_proposto(x, indicatori.get(x.id, [])) for x in _per_scadenza(elementi)]}  # fmt: skip


async def _stato_attuale(o: PfObiettivo) -> tuple[list[PfElemento], dict[str, list[PfIndicatore]]]:
    """Azioni e misure dell'obiettivo con i loro indicatori."""
    elementi = (await _elementi_di([o.id]))[o.id]
    return elementi, await _indicatori_di([x.id for x in elementi])


def _uguali(a: dict | None, b: dict | None) -> bool:
    def norma(d):
        return None if d is None else {**d, "elementi": sorted(d.get("elementi", []), key=lambda x: x.get("id") or "")}

    return norma(a) == norma(b)


async def _istantanea_di(obiettivo_id: str | None) -> dict | None:
    o = await db().get(PfObiettivo, obiettivo_id) if obiettivo_id else None
    if o is None or o.ente_id != ente_id():
        return None
    return _istantanea(o, *await _stato_attuale(o))


def _valida(dati: dict | None) -> ObiettivoProposto:
    try:
        return ObiettivoProposto.model_validate(dati or {})
    except ValidationError as e:
        errore = e.errors()[0]
        campo = ".".join(str(c) for c in errore["loc"])
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Dati dell'obiettivo non validi ({campo}): {errore['msg']}") from e


async def _normalizza(pr: PfProposta, dati: dict | None, base: dict | None) -> dict:
    """Controlla l'obiettivo proposto e lo restituisce nella forma dei dati delle proposte.
    [base]: l'obiettivo com'è (modifica), da cui vengono le misure esistenti già copiate."""
    d = _valida(dati)
    esistenti = {x["id"]: x for x in (base or {}).get("elementi", [])}
    elementi, visti, misure = [], set(), set()
    for x in d.elementi:
        e = {"id": x.id, "tipo": x.tipo, "impegno": x.impegno, "scadenza": x.scadenza.isoformat()}
        # id di un'azione o misura esistente, o provvisorio ("nuovo-...") di una nuova
        vecchio = esistenti.get(x.id) if x.id not in visti else None
        if vecchio is not None and vecchio["tipo"] != x.tipo:
            vecchio = None
        if vecchio is None and (not (x.id or "").startswith("nuovo-") or x.id in visti):
            e["id"] = f"nuovo-{nuovo_id()}"
        visti.add(e["id"])
        if x.tipo == "AZIONE":
            if not (x.descrizione or "").strip():
                raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Descrivi ogni azione")
            e.update(descrizione=x.descrizione.strip(), misura_id=None, misura_codice=None)
        elif vecchio is not None and x.misura_id == vecchio["misura_id"]:
            # misura già nell'obiettivo: la copia resta (anche se tolta dalla mappatura)
            e.update(descrizione=vecchio["descrizione"], misura_id=vecchio["misura_id"], misura_codice=vecchio["misura_codice"])
        else:
            m = await _misura_dell_ente(x.misura_id)
            e.update(descrizione=m.descrizione, misura_id=m.id, misura_codice=m.codice)
        # indicatori: l'id di uno esistente dell'azione o misura, o provvisorio di uno nuovo
        vecchi = {i["id"] for i in (vecchio or {}).get("indicatori", [])}
        e["indicatori"] = []
        for i in x.indicatori:
            definizione = _definizione(i)
            codice = definizione["id"]
            if codice in visti or not (codice in vecchi or (codice or "").startswith("nuovo-")):
                definizione["id"] = f"nuovo-{nuovo_id()}"
            visti.add(definizione["id"])
            e["indicatori"].append(definizione)
        if e["misura_id"]:
            if e["misura_id"] in misure:
                raise ErroreApi(HTTPStatus.CONFLICT, f"La misura {e['misura_codice']} è già nell'obiettivo")
            misure.add(e["misura_id"])
        elementi.append(e)
    if (somma := sum(e["impegno"] for e in elementi)) > TOTALE:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"Gli impegni delle azioni e misure dell'obiettivo superano il 100% ({somma}%)")  # fmt: skip
    resta = await _disponibile_obiettivi(pr.piao_id, pr.anno, pr.struttura_id, pr.obiettivo_id)
    if d.impegno > resta:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"Gli impegni degli obiettivi della struttura superano il 100%: disponibile {resta}%")  # fmt: skip
    elementi.sort(key=lambda e: e["scadenza"])
    return {"codice": (d.codice or "").strip() or None, "titolo": d.titolo.strip(),
            "descrizione": (d.descrizione or "").strip() or None, "tipo": d.tipo, "impegno": d.impegno,
            "elementi": elementi}  # fmt: skip


def _confronto(prima: dict | None, dati: dict | None) -> dict | None:
    """Differenze tra l'obiettivo com'era e quello proposto: campi dell'obiettivo
    {campo: [prima, dopo]} e per ogni azione o misura lo stato (NUOVO, MODIFICATO, INVARIATO,
    ELIMINATO) con i campi cambiati."""
    if prima is None or dati is None:
        return None
    obiettivo = {k: [prima.get(k), dati.get(k)] for k in _CAMPI_OBIETTIVO if prima.get(k) != dati.get(k)}
    vecchi = {x["id"]: x for x in prima.get("elementi", [])}
    elementi = []
    for x in dati.get("elementi", []):
        v = vecchi.pop(x["id"], None)
        if v is None:
            elementi.append({"id": x["id"], "stato": "NUOVO", "campi": {}})
        else:
            campi = {k: [_per_confronto(k, v.get(k)), _per_confronto(k, x.get(k))]
                     for k in _CAMPI_ELEMENTO if v.get(k, [] if k == "indicatori" else None) != x.get(k)}  # fmt: skip
            elementi.append({"id": x["id"], "stato": "MODIFICATO" if campi else "INVARIATO", "campi": campi})
    elementi += [{"id": i, "stato": "ELIMINATO", "campi": {}} for i in vecchi]
    return {"obiettivo": obiettivo, "elementi": elementi}


def _per_confronto(campo: str, valore):
    """Gli indicatori si confrontano come sintesi leggibili."""
    return [testo_indicatore(i) for i in valore or []] if campo == "indicatori" else valore


def _titolo(dati: dict | None) -> str:
    return _nome((dati or {}).get("codice"), (dati or {}).get("titolo") or "")[:600]


def _sintesi(pr: PfProposta, autore: User | None = None) -> dict:
    return {
        "id": pr.id, "tipo": pr.tipo, "stato": pr.stato, "piao_id": pr.piao_id, "anno": pr.anno,
        "struttura_id": pr.struttura_id, "obiettivo_id": pr.obiettivo_id, "titolo": pr.titolo,
        "impegno": (pr.dati or pr.prima or {}).get("impegno"),
        "nota": pr.nota, "motivazione": pr.motivazione,
        "autore": (autore.nome_completo or autore.username) if autore else None,
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "inviata_il": pr.inviata_il.isoformat() if pr.inviata_il else None,
        "decisa_il": pr.decisa_il.isoformat() if pr.decisa_il else None,
    }  # fmt: skip


async def _dettaglio(pr: PfProposta) -> dict:
    p = await db().get(PfPiao, pr.piao_id)
    attuale = await _istantanea_di(pr.obiettivo_id) if pr.tipo != "CREA" and pr.stato in APERTE else None
    versione = pr.dati or pr.prima or {}
    elementi = versione.get("elementi", [])
    aperta = pr.stato in APERTE and p.stato == "APERTO"
    proponibile = _proponibile(pr.struttura_id, p)
    resta = await _disponibile_obiettivi(pr.piao_id, pr.anno, pr.struttura_id, pr.obiettivo_id)
    return {
        **_sintesi(pr, await db().get(User, pr.utente_id) if pr.utente_id else None),
        "dati": pr.dati, "prima": pr.prima, "confronto": _confronto(pr.prima, pr.dati),
        "piao": _piao(p),
        "impegno_elementi": sum(x["impegno"] for x in elementi),
        "disponibile": resta,  # impegno che resta all'obiettivo nella struttura
        "controlli": _controlli(versione.get("impegno", 0), pr.anno, pr.struttura_id, elementi,
                                await _strutture_misure([x.get("misura_id") for x in elementi])) if versione else [],
        # l'obiettivo è cambiato (o è stato eliminato) dopo che la proposta è nata
        "cambiato": pr.tipo != "CREA" and pr.stato in APERTE and not _uguali(attuale, pr.prima),
        "eliminato": pr.tipo != "CREA" and pr.stato in APERTE and attuale is None,
        "modificabile": aperta and proponibile and pr.tipo != "ELIMINA" and pr.stato in ("BOZZA", "RESTITUITA"),
        "inviabile": aperta and proponibile and pr.stato in ("BOZZA", "RESTITUITA"),
        "ritirabile": aperta and proponibile and pr.stato == "INVIATA",
        "scartabile": pr.stato in ("BOZZA", "RESTITUITA") and _della_struttura(pr.struttura_id),
        "decidibile": aperta and pr.stato == "INVIATA" and _e_approvatore(),
    }  # fmt: skip


async def _proposta_visibile(proposta_id: str) -> PfProposta:
    pr = await db().get(PfProposta, proposta_id)
    visibili = await _visibili()
    if pr is None or pr.ente_id != ente_id() or (visibili is not None and pr.struttura_id not in visibili):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Proposta non trovata")
    return pr


async def _proposta_propria(proposta_id: str, stati: tuple[str, ...]) -> tuple[PfProposta, PfPiao]:
    """Proposta della struttura dell'utente (o, per l'amministratore, di qualsiasi struttura)
    in uno degli stati dati, con il PIAO aperto."""
    pr = await _proposta_visibile(proposta_id)
    p = await db().get(PfPiao, pr.piao_id)
    _aperto(p)
    if not _proponibile(pr.struttura_id, p):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Puoi gestire solo le proposte della tua struttura")
    if pr.stato not in stati:
        raise ErroreApi(HTTPStatus.CONFLICT, "Operazione non possibile nello stato attuale della proposta")
    return pr, p


class FiltriProposte(BaseModel):
    piao_id: str | None = None
    stato: Literal["BOZZA", "INVIATA", "APPROVATA", "RESPINTA", "RESTITUITA", "APERTE"] | None = None
    struttura_id: str | None = None


@bp.get("/proposte")
@lettore
async def proposte():
    """Proposte delle strutture visibili all'utente (l'approvatore le vede tutte), dalla più
    recente; le bozze solo a chi le può modificare (la sua struttura)."""
    f = parametri(FiltriProposte)
    q = (select(PfProposta, User).outerjoin(User, User.id == PfProposta.utente_id)
         .where(PfProposta.ente_id == ente_id()))  # fmt: skip
    if f.piao_id:
        q = q.where(PfProposta.piao_id == f.piao_id)
    if f.struttura_id:
        q = q.where(PfProposta.struttura_id == f.struttura_id)
    if f.stato == "APERTE":
        q = q.where(PfProposta.stato.in_(APERTE))
    elif f.stato:
        q = q.where(PfProposta.stato == f.stato)
    visibili = await _visibili()
    if visibili is not None:
        q = q.where(PfProposta.struttura_id.in_(visibili or {""}))
    righe = await db().execute(q.order_by(func.coalesce(PfProposta.decisa_il, PfProposta.inviata_il, PfProposta.created_at).desc()))
    return [_sintesi(pr, u) for pr, u in righe if pr.stato != "BOZZA" or _della_struttura(pr.struttura_id)]


@bp.get("/proposte/<proposta_id>")
@lettore
async def proposta(proposta_id: str):
    """Proposta con l'obiettivo proposto, com'era, le differenze, i controlli e cosa può fare
    l'utente."""
    return await _dettaglio(await _proposta_visibile(proposta_id))


class PropostaNuova(BaseModel):
    tipo: Literal["CREA", "MODIFICA", "ELIMINA"]
    obiettivo_id: str | None = None  # modifica, eliminazione
    piao_id: str | None = None  # creazione
    anno: int | None = None
    struttura_id: str | None = None  # creazione: la struttura dell'utente se manca
    dati: dict | None = None  # creazione: l'obiettivo (anche senza azioni e misure)
    nota: str | None = Field(default=None, max_length=5000)


@bp.post("/proposte")
@lettore
async def crea_proposta():
    """Creazione e modifica nascono in bozza (la modifica con l'obiettivo com'è, da
    cambiare); l'eliminazione va subito all'approvatore."""
    dati = corpo(PropostaNuova)
    sessione = db()
    if dati.tipo == "CREA":
        p = await _piao_dell_ente(dati.piao_id or "")
        _nel_triennio(p, dati.anno or 0)
        s = await _struttura_dell_ente(dati.struttura_id or utente().struttura_id)
        pr = PfProposta(ente_id=ente_id(), piao_id=p.id, anno=dati.anno, struttura_id=s.id, tipo="CREA")
    else:
        o, p = await _obiettivo_visibile(dati.obiettivo_id or "")
        if await _proposte_aperte([o.id]):
            raise ErroreApi(HTTPStatus.CONFLICT, "C'è già una proposta aperta su questo obiettivo")
        pr = PfProposta(ente_id=ente_id(), piao_id=p.id, anno=o.anno, struttura_id=o.struttura_id, obiettivo_id=o.id,
                        tipo=dati.tipo, prima=_istantanea(o, *await _stato_attuale(o)))  # fmt: skip
    _aperto(p)
    if not _proponibile(pr.struttura_id, p):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Puoi proporre solo per gli obiettivi della tua struttura")
    pr.nota = (dati.nota or "").strip() or None
    if dati.tipo == "CREA":
        pr.dati = await _normalizza(pr, dati.dati, None)
    elif dati.tipo == "MODIFICA":
        pr.dati = pr.prima
    pr.titolo = _titolo(pr.dati or pr.prima)
    if dati.tipo == "ELIMINA":
        pr.stato, pr.utente_id, pr.inviata_il = "INVIATA", utente().id, datetime.now()
    sessione.add(pr)
    await sessione.flush()
    audit(sessione, utente(), "pf_proposta", pr.id, "CREATA", {"tipo": pr.tipo})
    if pr.stato == "INVIATA":
        await _notifica_approvatori(pr, reinviata=False)
    await sessione.commit()
    await sessione.refresh(pr)  # created_at: con MySQL il valore del database non torna con l'inserimento
    return await _dettaglio(pr), HTTPStatus.CREATED


class PropostaIn(BaseModel):
    dati: dict | None = None
    nota: str | None = Field(default=None, max_length=5000)


@bp.put("/proposte/<proposta_id>")
@lettore
async def aggiorna_proposta(proposta_id: str):
    """Nuova versione dell'obiettivo proposto (intero) e nota, in bozza o restituita."""
    dati = corpo(PropostaIn)
    pr, _ = await _proposta_propria(proposta_id, ("BOZZA", "RESTITUITA"))
    if pr.tipo != "ELIMINA" and dati.dati is not None:
        pr.dati = await _normalizza(pr, dati.dati, pr.prima)
        pr.titolo = _titolo(pr.dati)
    pr.nota = (dati.nota or "").strip() or None
    await db().commit()
    return await _dettaglio(pr)


class InvioIn(BaseModel):
    nota: str | None = Field(default=None, max_length=5000)


@bp.post("/proposte/<proposta_id>/invia")
@lettore
async def invia_proposta(proposta_id: str):
    """Invia all'approvatore la bozza, o la restituita corretta."""
    dati = corpo(InvioIn)
    sessione = db()
    pr, _ = await _proposta_propria(proposta_id, ("BOZZA", "RESTITUITA"))
    if pr.tipo != "CREA" and await _istantanea_di(pr.obiettivo_id) is None:
        raise ErroreApi(HTTPStatus.CONFLICT, "L'obiettivo non esiste più: scarta la proposta")
    if pr.tipo != "ELIMINA":
        pr.dati = await _normalizza(pr, pr.dati, pr.prima)  # impegni: gli altri obiettivi possono essere cambiati
        if pr.tipo == "MODIFICA" and _uguali(pr.dati, pr.prima):
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "La proposta non cambia nulla dell'obiettivo")
    if dati.nota is not None:
        pr.nota = dati.nota.strip() or None
    reinviata = pr.stato == "RESTITUITA"
    pr.stato, pr.utente_id, pr.inviata_il = "INVIATA", utente().id, datetime.now()
    audit(sessione, utente(), "pf_proposta", pr.id, "REINVIATA" if reinviata else "INVIATA")
    await _notifica_approvatori(pr, reinviata=reinviata)
    await sessione.commit()
    return await _dettaglio(pr)


@bp.post("/proposte/<proposta_id>/ritira")
@lettore
async def ritira_proposta(proposta_id: str):
    """Ritira la proposta inviata e non ancora decisa: torna in bozza (l'eliminazione si
    annulla)."""
    sessione = db()
    pr, _ = await _proposta_propria(proposta_id, ("INVIATA",))
    audit(sessione, utente(), "pf_proposta", pr.id, "RITIRATA")
    if pr.tipo == "ELIMINA":
        await sessione.delete(pr)
        await sessione.commit()
        return nessun_contenuto()
    pr.stato, pr.inviata_il = "BOZZA", None
    await sessione.commit()
    return await _dettaglio(pr)


@bp.delete("/proposte/<proposta_id>")
@lettore
async def scarta_proposta(proposta_id: str):
    """Scarta una bozza o una proposta restituita."""
    sessione = db()
    pr = await _proposta_visibile(proposta_id)
    if not _della_struttura(pr.struttura_id):  # anche con il PIAO chiuso
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Puoi gestire solo le proposte della tua struttura")
    if pr.stato not in ("BOZZA", "RESTITUITA"):
        raise ErroreApi(HTTPStatus.CONFLICT, "Si scartano solo le bozze e le proposte restituite")
    audit(sessione, utente(), "pf_proposta", pr.id, "SCARTATA")
    await sessione.delete(pr)
    await sessione.commit()
    return nessun_contenuto()


class DecisioneIn(BaseModel):
    motivazione: str | None = Field(default=None, max_length=5000)
    forza: bool = False  # approva anche se l'obiettivo è cambiato dopo la proposta


async def _proposta_inviata(proposta_id: str) -> tuple[PfProposta, PfPiao]:
    pr = await _proposta_visibile(proposta_id)
    p = await db().get(PfPiao, pr.piao_id)
    _aperto(p)
    if pr.stato != "INVIATA":
        raise ErroreApi(HTTPStatus.CONFLICT, "Si decidono solo le proposte inviate")
    return pr, p


def _nota_approvazione(pr: PfProposta, autore: User | None, motivazione: str | None) -> str:
    righe = [f"Proposta di {(autore.nome_completo or autore.username) if autore else 'utente non più presente'} approvata"]
    if pr.nota:
        righe.append(f"Nota della proposta: {pr.nota}")
    if motivazione:
        righe.append(f"Motivazione: {motivazione}")
    return "\n".join(righe)


async def _applica(pr: PfProposta, p: PfPiao, nota: str, forza: bool) -> None:
    """Applica la proposta agli obiettivi, registrando ogni cambiamento nello storico."""
    sessione = db()
    if pr.tipo == "CREA":
        d = await _normalizza(pr, pr.dati, None)
        s = await sessione.get(Struttura, pr.struttura_id)
        o = PfObiettivo(ente_id=ente_id(), piao_id=p.id, anno=pr.anno, struttura_id=pr.struttura_id)
        _imposta_obiettivo(o, d)
        sessione.add(o)
        await sessione.flush()
        pr.obiettivo_id = o.id
        _registra("OBIETTIVO", o.id, "CREATO", _nome_obiettivo(o), piao_id=p.id, obiettivo_id=o.id, nota=nota,
                  campi=_differenze({}, {**_campi_obiettivo(o), "anno": o.anno, "struttura": s.codice if s else None}))  # fmt: skip
        await _applica_elementi(o, [], {}, d["elementi"], nota)
        return
    o = await sessione.get(PfObiettivo, pr.obiettivo_id) if pr.obiettivo_id else None
    if o is None:
        raise ErroreApi(HTTPStatus.CONFLICT, "L'obiettivo della proposta non esiste più: respingila")
    elementi, indicatori = await _stato_attuale(o)
    if not forza and not _uguali(_istantanea(o, elementi, indicatori), pr.prima):
        raise ErroreApi(HTTPStatus.CONFLICT, "L'obiettivo è stato modificato dopo la proposta: verifica le differenze e conferma")
    if pr.tipo == "ELIMINA":
        await _elimina_obiettivo(o, nota)
        return
    d = await _normalizza(pr, pr.dati, _istantanea(o, elementi, indicatori))
    prima = _campi_obiettivo(o)
    _imposta_obiettivo(o, d)
    if campi := _differenze(prima, _campi_obiettivo(o)):
        _registra("OBIETTIVO", o.id, "MODIFICATO", _nome_obiettivo(o), piao_id=p.id, obiettivo_id=o.id, campi=campi, nota=nota)
    await _applica_elementi(o, elementi, indicatori, d["elementi"], nota)


async def _applica_elementi(o: PfObiettivo, esistenti: list[PfElemento], indicatori: dict[str, list[PfIndicatore]],
                            proposti: list[dict], nota: str) -> None:  # fmt: skip
    sessione = db()
    per_id = {x.id: x for x in esistenti}
    for x in esistenti:
        if x.id not in {e["id"] for e in proposti}:
            _registra(x.tipo, x.id, "ELIMINATO", _nome_elemento(x), piao_id=o.piao_id, obiettivo_id=o.id, nota=nota,
                      campi=_differenze(_campi_elemento(x), {k: None for k in _campi_elemento(x)}))  # fmt: skip
            await sessione.delete(x)
    ordine = max((x.ordine for x in esistenti), default=-1) + 1
    for e in proposti:
        x = per_id.get(e["id"])
        if x is None:
            x = PfElemento(id=nuovo_id(), ente_id=ente_id(), obiettivo_id=o.id, tipo=e["tipo"], completamento=0, ordine=ordine)
            ordine += 1
            prima, azione = {}, "CREATO"
            sessione.add(x)
        else:
            prima, azione = _campi_elemento(x), "MODIFICATO"
        x.descrizione, x.misura_id, x.misura_codice = e["descrizione"], e["misura_id"], e["misura_codice"]
        x.impegno, x.scadenza = e["impegno"], date.fromisoformat(e["scadenza"])
        await _sincronizza_indicatori(x, indicatori.get(x.id, []), e.get("indicatori", []), piao_id=o.piao_id, nota=nota)
        if campi := _differenze(prima, _campi_elemento(x)):
            _registra(x.tipo, x.id, azione, _nome_elemento(x), piao_id=o.piao_id, obiettivo_id=o.id, campi=campi, nota=nota)


@bp.post("/proposte/<proposta_id>/approva")
@approvatore
async def approva_proposta(proposta_id: str):
    """Applica la proposta agli obiettivi; con `forza` anche se l'obiettivo è cambiato dopo."""
    dati = corpo(DecisioneIn)
    sessione = db()
    pr, p = await _proposta_inviata(proposta_id)
    motivazione = (dati.motivazione or "").strip() or None
    autore = await sessione.get(User, pr.utente_id) if pr.utente_id else None
    await _applica(pr, p, _nota_approvazione(pr, autore, motivazione), dati.forza)
    pr.stato, pr.motivazione = "APPROVATA", motivazione
    pr.deciso_da, pr.decisa_il = utente().id, datetime.now()
    audit(sessione, utente(), "pf_proposta", pr.id, "APPROVATA", {"tipo": pr.tipo, "obiettivo_id": pr.obiettivo_id})
    await _notifica_proponente(pr)
    await sessione.commit()
    return await _dettaglio(pr)


async def _decidi(proposta_id: str, stato: str) -> dict:
    dati = corpo(DecisioneIn)
    if not (dati.motivazione or "").strip():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Serve la motivazione")
    sessione = db()
    pr, _ = await _proposta_inviata(proposta_id)
    pr.stato, pr.motivazione = stato, dati.motivazione.strip()
    pr.deciso_da, pr.decisa_il = utente().id, datetime.now()
    audit(sessione, utente(), "pf_proposta", pr.id, stato)
    await _notifica_proponente(pr)
    await sessione.commit()
    return await _dettaglio(pr)


@bp.post("/proposte/<proposta_id>/respingi")
@approvatore
async def respingi_proposta(proposta_id: str):
    return await _decidi(proposta_id, "RESPINTA")


@bp.post("/proposte/<proposta_id>/restituisci")
@approvatore
async def restituisci_proposta(proposta_id: str):
    """Torna alla struttura, che la corregge e la reinvia (o la scarta)."""
    return await _decidi(proposta_id, "RESTITUITA")


# --- notifiche ------------------------------------------------------------------------------

_TIPI_PROPOSTA = {"CREA": "Nuovo obiettivo", "MODIFICA": "Modifica dell'obiettivo", "ELIMINA": "Eliminazione dell'obiettivo"}
_ESITI = {"APPROVATA": "approvata", "RESPINTA": "respinta", "RESTITUITA": "restituita per una correzione"}


async def _dettagli_email(pr: PfProposta) -> str:
    s = await db().get(Struttura, pr.struttura_id)
    p = await db().get(PfPiao, pr.piao_id)
    return (f"  {_TIPI_PROPOSTA.get(pr.tipo, pr.tipo)}: {pr.titolo}\n"
            f"  Struttura: {f'{s.codice} - {s.descrizione}' if s else '—'}\n"
            f"  {p.titolo if p else 'PIAO'}, anno {pr.anno}")  # fmt: skip


def _firma(e: Ente, link: str | None) -> str:
    accesso = f"Atti PA, Performance > Proposte:\n{link}\n" if link else "Atti PA, Performance > Proposte.\n"
    return f"\nLa proposta si consulta in {accesso}\n--\nEmail inviata automaticamente da Atti PA per {e.nome}.\n"


async def _notifica_approvatori(pr: PfProposta, reinviata: bool) -> None:
    sessione = db()
    e = await sessione.get(Ente, pr.ente_id)
    if posta.config_ente(e.smtp_json) is None:
        return
    autore = utente()
    utenti = await sessione.scalars(select(User).where(User.ente_id == e.id, User.attivo.is_(True)))
    destinatari = [u.email for u in utenti if u.ha_ruolo(Ruolo.PERFORMANCE_APPROVATORE) and u.id != autore.id]
    azione = "ha corretto e reinviato una proposta restituita" if reinviata else "ha inviato una proposta"
    testo = f"{autore.nome_completo or autore.username} {azione}, da approvare:\n\n{await _dettagli_email(pr)}\n"
    if pr.nota:
        testo += f"\nNota:\n{pr.nota}\n"
    oggetto = f"[Performance] {'Proposta reinviata' if reinviata else 'Nuova proposta'} da approvare: {pr.titolo}"
    posta.accoda(sessione, e, destinatari, oggetto, testo + _firma(e, await posta.indirizzo_app(sessione, e)),
                 origine=f"pf_proposta:{pr.id}")  # fmt: skip


async def _notifica_proponente(pr: PfProposta) -> None:
    sessione = db()
    e = await sessione.get(Ente, pr.ente_id)
    if posta.config_ente(e.smtp_json) is None:
        return
    autore = await sessione.get(User, pr.utente_id) if pr.utente_id else None
    if autore is None or not autore.attivo:
        return
    esito = _ESITI.get(pr.stato, pr.stato.lower())
    testo = f"La tua proposta è stata {esito}:\n\n{await _dettagli_email(pr)}\n"
    if pr.motivazione:
        testo += f"\nMotivazione:\n{pr.motivazione}\n"
    if pr.stato == "RESTITUITA":
        testo += "\nPuoi correggerla e reinviarla, oppure scartarla.\n"
    oggetto = f"[Performance] Proposta {esito}: {pr.titolo}"
    posta.accoda(sessione, e, [autore.email], oggetto, testo + _firma(e, await posta.indirizzo_app(sessione, e)),
                 origine=f"pf_proposta:{pr.id}")  # fmt: skip


# --- storico e riepilogo --------------------------------------------------------------------


@bp.get("/obiettivi/<obiettivo_id>/storico")
@lettore
async def storico_obiettivo(obiettivo_id: str):
    """Modifiche all'obiettivo, alle sue azioni e misure e ai loro indicatori, dalla più recente."""
    o, _ = await _obiettivo_visibile(obiettivo_id)
    righe = await db().scalars(select(PfModifica).where(PfModifica.ente_id == ente_id(), PfModifica.obiettivo_id == o.id)
                               .order_by(PfModifica.created_at.desc(), PfModifica.id.desc()))  # fmt: skip
    return [_modifica(m) for m in righe]


@bp.get("/piao/<piao_id>/storico")
@amministratore
async def storico_piao(piao_id: str):
    """Tutte le modifiche del PIAO, comprese quelle agli obiettivi eliminati (le ultime 1000)."""
    p = await _piao_dell_ente(piao_id)
    righe = await db().scalars(select(PfModifica).where(PfModifica.ente_id == ente_id(), PfModifica.piao_id == p.id)
                               .order_by(PfModifica.created_at.desc(), PfModifica.id.desc()).limit(1000))  # fmt: skip
    return [_modifica(m) for m in righe]


class FiltriRiepilogo(BaseModel):
    piao_id: str
    anno: int | None = None


@bp.get("/riepilogo")
@lettore
async def riepilogo():
    """Per struttura e anno: obiettivi, impegno totale, completamento, obiettivi con le azioni e
    misure non al 100%, ritardi, azioni e misure senza indicatori, proposte in attesa. Solo le strutture visibili all'utente."""
    f = parametri(FiltriRiepilogo)
    p = await _piao_dell_ente(f.piao_id)
    q = select(PfObiettivo).where(PfObiettivo.piao_id == p.id)
    qp = select(PfProposta.struttura_id, PfProposta.anno).where(PfProposta.piao_id == p.id, PfProposta.stato == "INVIATA")
    if f.anno:
        q, qp = q.where(PfObiettivo.anno == f.anno), qp.where(PfProposta.anno == f.anno)
    visibili = await _visibili()
    if visibili is not None:
        q = q.where(PfObiettivo.struttura_id.in_(visibili or {""}))
        qp = qp.where(PfProposta.struttura_id.in_(visibili or {""}))
    righe = list(await db().scalars(q))
    elementi = await _elementi_di([o.id for o in righe])
    indicatori = await _indicatori_di([x.id for v in elementi.values() for x in v])
    oggi = date.today()
    gruppi: dict[tuple[str, int], list[dict]] = {}
    for o in righe:
        gruppi.setdefault((o.struttura_id, o.anno), []).append(_obiettivo(o, p, elementi[o.id], oggi, indicatori=indicatori))
    in_attesa: dict[tuple[str, int], int] = {}
    for chiave in await db().execute(qp):
        in_attesa[tuple(chiave)] = in_attesa.get(tuple(chiave), 0) + 1
        gruppi.setdefault(tuple(chiave), [])
    strutture = await _strutture()
    risultato = []
    for (struttura_id, anno), elenco in gruppi.items():
        s = strutture.get(struttura_id)
        impegno = sum(o["impegno"] for o in elenco)
        risultato.append({
            "struttura_id": struttura_id, "struttura": f"{s.codice} - {s.descrizione}" if s else None, "anno": anno,
            "obiettivi": len(elenco), "impegno_totale": impegno, "completo": impegno == TOTALE,
            "completamento": media_pesata((o["impegno"], o["completamento"]) for o in elenco),
            "obiettivi_incompleti": sum(1 for o in elenco if not o["completo"]),
            "ritardi": sum(o["ritardi"] for o in elenco),
            "senza_indicatori": sum(o["senza_indicatori"] for o in elenco),  # azioni e misure
            "proposte": in_attesa.get((struttura_id, anno), 0),  # inviate, da decidere
        })  # fmt: skip
    ordine = {s.id: (s.ordine, chiave_naturale(s.codice)) for s in strutture.values()}
    risultato.sort(key=lambda r: (r["anno"], ordine.get(r["struttura_id"], (0, []))))
    return risultato
