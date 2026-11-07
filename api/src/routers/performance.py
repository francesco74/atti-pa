"""Modulo performance: PIAO triennali, obiettivi annuali delle strutture con azioni e misure,
percentuali di impegno e di completamento, scadenze e storico delle modifiche.

L'amministratore della performance (o l'amministratore dell'ente) crea, apre e chiude i PIAO e
vede e corregge tutto. Il responsabile (dirigente di un servizio o responsabile di un ufficio,
secondo la struttura assegnata al suo utente) dichiara e aggiorna gli obiettivi della propria
struttura e vede in sola lettura quelli delle strutture sottostanti. Con il PIAO chiuso nulla si
modifica.

Gli impegni degli obiettivi di una struttura in un anno, e quelli delle azioni e misure di un
obiettivo, non possono superare 100; il completamento si calcola (common/performance). Le misure
si scelgono tra quelle della mappatura dei rischi (modulo anticorruzione). Ogni creazione,
modifica ed eliminazione finisce nello storico (pf_modifiche), con i valori prima e dopo.
"""

from __future__ import annotations

from datetime import date
from http import HTTPStatus
from typing import Literal

from flask import Blueprint, request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from deps import audit, autenticato, db, ente, ente_id, utente
from web import ErroreApi, corpo, nessun_contenuto, parametri
from common.anticorruzione.metodologia import chiave_naturale
from common.models import (
    AcMisura, Modulo, PfElemento, PfModifica, PfObiettivo, PfPiao, Ruolo, Struttura,
)  # fmt: skip
from common.performance import AVVISO, TOTALE, controlli_obiettivo, disponibile, in_ritardo, media_pesata

bp = Blueprint("performance", __name__, url_prefix="/api/v1/performance")

lettore = autenticato(Ruolo.PERFORMANCE_RESPONSABILE, Ruolo.PERFORMANCE_AMMINISTRATORE, modulo=Modulo.PERFORMANCE)
amministratore = autenticato(Ruolo.PERFORMANCE_AMMINISTRATORE, modulo=Modulo.PERFORMANCE)

_ETICHETTE = {"PIAO": "PIAO", "OBIETTIVO": "Obiettivo", "AZIONE": "Azione", "MISURA": "Misura"}


# --- permessi -------------------------------------------------------------------------------


def _e_amministratore() -> bool:
    return utente().ha_ruolo(Ruolo.ADMIN, Ruolo.PERFORMANCE_AMMINISTRATORE)


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
    if _e_amministratore():
        return None
    if not utente().struttura_id:
        return set()
    return _sottostanti(await _strutture(), utente().struttura_id)


def _modificabile(o: PfObiettivo, piao: PfPiao) -> bool:
    return piao.stato == "APERTO" and (_e_amministratore() or o.struttura_id == utente().struttura_id)


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
    o, p = await _obiettivo_visibile(obiettivo_id)
    _aperto(p)
    if not _modificabile(o, p):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Puoi modificare solo gli obiettivi della tua struttura")
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
    """Cosa può fare l'utente: amministratore o responsabile, la sua struttura, le strutture
    visibili (None: tutte), se le misure della mappatura sono disponibili."""
    visibili = await _visibili()
    return {
        "amministratore": _e_amministratore(),
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
    """Solo un PIAO senza obiettivi."""
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
    struttura_id: str | None = None  # il responsabile: la sua struttura


def _campi_obiettivo(o: PfObiettivo) -> dict:
    return {"codice": o.codice, "titolo": o.titolo, "descrizione": o.descrizione, "tipo": o.tipo, "impegno": o.impegno}


def _imposta_obiettivo(o: PfObiettivo, d: ObiettivoDati) -> None:
    o.codice = (d.codice or "").strip() or None
    o.titolo, o.descrizione = d.titolo.strip(), (d.descrizione or "").strip() or None
    o.tipo, o.impegno = d.tipo, d.impegno


def _nome_obiettivo(o: PfObiettivo) -> str:
    return f"{o.codice} - {o.titolo}" if o.codice else o.titolo


async def _controlla_impegno_obiettivi(o: PfObiettivo) -> None:
    altri = await db().scalars(select(PfObiettivo.impegno).where(
        PfObiettivo.piao_id == o.piao_id, PfObiettivo.anno == o.anno, PfObiettivo.struttura_id == o.struttura_id,
        PfObiettivo.id != o.id))  # fmt: skip
    resta = disponibile(altri)
    if o.impegno > resta:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"Gli impegni degli obiettivi della struttura superano il 100%: disponibile {resta}%")  # fmt: skip


def _elemento(x: PfElemento, oggi: date) -> dict:
    return {
        "id": x.id, "obiettivo_id": x.obiettivo_id, "tipo": x.tipo, "descrizione": x.descrizione,
        "misura_id": x.misura_id, "misura_codice": x.misura_codice, "impegno": x.impegno,
        "completamento": x.completamento, "scadenza": x.scadenza.isoformat(),
        "in_ritardo": in_ritardo(x.scadenza, x.completamento, oggi),
    }  # fmt: skip


def _per_scadenza(elementi):
    return sorted(elementi, key=lambda x: (x.scadenza, x.ordine))


def _obiettivo(o: PfObiettivo, p: PfPiao, elementi: list[PfElemento], oggi: date) -> dict:
    impegno_elementi = sum(x.impegno for x in elementi)
    return {
        "id": o.id, "piao_id": o.piao_id, "anno": o.anno, "struttura_id": o.struttura_id, "codice": o.codice,
        "titolo": o.titolo, "descrizione": o.descrizione, "tipo": o.tipo, "impegno": o.impegno,
        "completamento": media_pesata((x.impegno, x.completamento) for x in elementi),
        "impegno_elementi": impegno_elementi, "completo": impegno_elementi == TOTALE,
        "azioni": sum(1 for x in elementi if x.tipo == "AZIONE"),
        "misure": sum(1 for x in elementi if x.tipo == "MISURA"),
        "ritardi": sum(1 for x in elementi if in_ritardo(x.scadenza, x.completamento, oggi)),
        "avvisi": sum(1 for c in _controlli(o, elementi) if c["livello"] == AVVISO),
        "modificabile": _modificabile(o, p),
    }  # fmt: skip


def _controlli(o: PfObiettivo, elementi: list[PfElemento], strutture_misure: dict | None = None) -> list[dict]:
    return controlli_obiettivo(
        o.impegno, o.anno, o.struttura_id,
        [{"tipo": x.tipo, "descrizione": x.descrizione, "impegno": x.impegno, "scadenza": x.scadenza,
          "misura_id": x.misura_id} for x in elementi],
        misure_attive=ente().modulo_attivo(Modulo.ANTICORRUZIONE), strutture_misure=strutture_misure,
    )  # fmt: skip


async def _elementi_di(ids: list[str]) -> dict[str, list[PfElemento]]:
    risultato: dict[str, list[PfElemento]] = {i: [] for i in ids}
    if ids:
        for x in await db().scalars(select(PfElemento).where(PfElemento.obiettivo_id.in_(ids))):
            risultato[x.obiettivo_id].append(x)
    return risultato


class FiltriObiettivi(BaseModel):
    piao_id: str
    anno: int | None = None
    struttura_id: str | None = None


@bp.get("/obiettivi")
@lettore
async def obiettivi():
    """Obiettivi del PIAO (dell'anno, della struttura) visibili all'utente, con il riepilogo
    della struttura nell'anno quando entrambi sono indicati."""
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
    oggi = date.today()
    elenco = [_obiettivo(o, p, _per_scadenza(elementi[o.id]), oggi) for o in righe]
    impegno = sum(o["impegno"] for o in elenco)
    return {
        "obiettivi": elenco,
        "impegno_totale": impegno,
        "completo": impegno == TOTALE,
        "completamento": media_pesata((o["impegno"], o["completamento"]) for o in elenco),
        # si possono aggiungere obiettivi: PIAO aperto e struttura dell'utente (o amministratore)
        "modificabile": p.stato == "APERTO" and bool(f.struttura_id)
        and (_e_amministratore() or f.struttura_id == utente().struttura_id),
    }


@bp.get("/obiettivi/<obiettivo_id>")
@lettore
async def obiettivo(obiettivo_id: str):
    """Obiettivo con le azioni e le misure (per scadenza)."""
    o, p = await _obiettivo_visibile(obiettivo_id)
    elementi = _per_scadenza((await _elementi_di([o.id]))[o.id])
    oggi = date.today()
    ids_misure = [x.misura_id for x in elementi if x.misura_id]
    strutture_misure = {
        m_id: s_id for m_id, s_id in await db().execute(select(AcMisura.id, AcMisura.struttura_id).where(AcMisura.id.in_(ids_misure)))
    } if ids_misure else {}  # fmt: skip
    return {**_obiettivo(o, p, elementi, oggi), "elementi": [_elemento(x, oggi) for x in elementi],
            "piao": _piao(p), "controlli": _controlli(o, elementi, strutture_misure)}  # fmt: skip


@bp.post("/obiettivi")
@lettore
async def crea_obiettivo():
    dati = corpo(ObiettivoNuovo)
    sessione = db()
    p = await _piao_dell_ente(dati.piao_id)
    _aperto(p)
    if dati.anno not in range(p.anno_inizio, p.anno_inizio + 3):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"L'anno deve essere nel triennio {p.anno_inizio}-{p.anno_inizio + 2}")  # fmt: skip
    struttura_id = dati.struttura_id or utente().struttura_id
    if not struttura_id:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica la struttura (o assegnala al tuo utente nel profilo)")
    s = await sessione.get(Struttura, struttura_id)
    if s is None or s.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Struttura non trovata")
    if not _e_amministratore() and struttura_id != utente().struttura_id:
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Puoi dichiarare obiettivi solo per la tua struttura")
    o = PfObiettivo(ente_id=ente_id(), piao_id=p.id, anno=dati.anno, struttura_id=struttura_id)
    _imposta_obiettivo(o, dati)
    await _controlla_impegno_obiettivi(o)
    sessione.add(o)
    await sessione.flush()
    _registra("OBIETTIVO", o.id, "CREATO", _nome_obiettivo(o), piao_id=p.id, obiettivo_id=o.id,
              campi=_differenze({}, {**_campi_obiettivo(o), "anno": o.anno, "struttura": s.codice}), nota=dati.nota)  # fmt: skip
    await sessione.commit()
    return _obiettivo(o, p, [], date.today()), HTTPStatus.CREATED


@bp.put("/obiettivi/<obiettivo_id>")
@lettore
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


@bp.delete("/obiettivi/<obiettivo_id>")
@lettore
async def elimina_obiettivo(obiettivo_id: str):
    """Elimina l'obiettivo con le sue azioni e misure (restano nello storico)."""
    sessione = db()
    o, p = await _obiettivo_modificabile(obiettivo_id)
    _registra("OBIETTIVO", o.id, "ELIMINATO", _nome_obiettivo(o), piao_id=p.id, obiettivo_id=o.id,
              campi=_differenze(_campi_obiettivo(o), {k: None for k in _campi_obiettivo(o)}), nota=_nota_richiesta())  # fmt: skip
    await sessione.execute(delete(PfElemento).where(PfElemento.obiettivo_id == o.id))
    await sessione.delete(o)
    await sessione.commit()
    return nessun_contenuto()


# --- azioni e misure ------------------------------------------------------------------------


class ElementoDati(BaseModel):
    descrizione: str | None = Field(default=None, max_length=10000)  # dell'azione
    impegno: int = Field(ge=0, le=TOTALE)
    completamento: int = Field(default=0, ge=0, le=TOTALE)
    scadenza: date
    nota: str | None = Field(default=None, max_length=5000)


class ElementoNuovo(ElementoDati):
    tipo: Literal["AZIONE", "MISURA"]
    misura_id: str | None = None


def _campi_elemento(x: PfElemento) -> dict:
    return {"descrizione": x.descrizione, "impegno": x.impegno, "completamento": x.completamento, "scadenza": x.scadenza}


def _nome_elemento(x: PfElemento) -> str:
    return f"{x.misura_codice} - {x.descrizione}" if x.misura_codice else x.descrizione


async def _controlla_impegno_elementi(x: PfElemento) -> None:
    altri = await db().scalars(select(PfElemento.impegno).where(
        PfElemento.obiettivo_id == x.obiettivo_id, PfElemento.id != x.id))  # fmt: skip
    resta = disponibile(altri)
    if x.impegno > resta:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY,
                        f"Gli impegni delle azioni e misure dell'obiettivo superano il 100%: disponibile {resta}%")  # fmt: skip


async def _elemento_modificabile(elemento_id: str) -> tuple[PfElemento, PfObiettivo, PfPiao]:
    x = await db().get(PfElemento, elemento_id)
    if x is None or x.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Azione o misura non trovata")
    o, p = await _obiettivo_modificabile(x.obiettivo_id)
    return x, o, p


@bp.post("/obiettivi/<obiettivo_id>/elementi")
@lettore
async def crea_elemento(obiettivo_id: str):
    """Nuova azione (con la descrizione) o misura (scelta dalla mappatura dei rischi)."""
    dati = corpo(ElementoNuovo)
    sessione = db()
    o, p = await _obiettivo_modificabile(obiettivo_id)
    x = PfElemento(ente_id=ente_id(), obiettivo_id=o.id, tipo=dati.tipo, impegno=dati.impegno,
                   completamento=dati.completamento, scadenza=dati.scadenza)  # fmt: skip
    if dati.tipo == "AZIONE":
        if not (dati.descrizione or "").strip():
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Descrivi l'azione")
        x.descrizione = dati.descrizione.strip()
    else:
        if not ente().modulo_attivo(Modulo.ANTICORRUZIONE):
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Le misure vengono dalla mappatura dei rischi: modulo non attivo")
        m = await sessione.get(AcMisura, dati.misura_id) if dati.misura_id else None
        if m is None or m.ente_id != ente_id():
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Scegli una misura della mappatura dei rischi")
        if await sessione.scalar(select(PfElemento.id).where(PfElemento.obiettivo_id == o.id, PfElemento.misura_id == m.id)):
            raise ErroreApi(HTTPStatus.CONFLICT, f"La misura {m.codice} è già nell'obiettivo")
        x.misura_id, x.misura_codice, x.descrizione = m.id, m.codice, m.descrizione
    await _controlla_impegno_elementi(x)
    x.ordine = (await sessione.scalar(select(func.count()).where(PfElemento.obiettivo_id == o.id))) or 0
    sessione.add(x)
    await sessione.flush()
    _registra(x.tipo, x.id, "CREATO", _nome_elemento(x), piao_id=p.id, obiettivo_id=o.id,
              campi=_differenze({}, _campi_elemento(x)), nota=dati.nota)  # fmt: skip
    await sessione.commit()
    return _elemento(x, date.today()), HTTPStatus.CREATED


@bp.put("/elementi/<elemento_id>")
@lettore
async def aggiorna_elemento(elemento_id: str):
    """Impegno, completamento, scadenza e, per le azioni, la descrizione."""
    dati = corpo(ElementoDati)
    sessione = db()
    x, o, p = await _elemento_modificabile(elemento_id)
    prima = _campi_elemento(x)
    if x.tipo == "AZIONE" and dati.descrizione is not None:
        if not dati.descrizione.strip():
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Descrivi l'azione")
        x.descrizione = dati.descrizione.strip()
    x.impegno, x.completamento, x.scadenza = dati.impegno, dati.completamento, dati.scadenza
    await _controlla_impegno_elementi(x)
    if campi := _differenze(prima, _campi_elemento(x)):
        _registra(x.tipo, x.id, "MODIFICATO", _nome_elemento(x), piao_id=p.id, obiettivo_id=o.id,
                  campi=campi, nota=dati.nota)  # fmt: skip
    await sessione.commit()
    return _elemento(x, date.today())


@bp.delete("/elementi/<elemento_id>")
@lettore
async def elimina_elemento(elemento_id: str):
    sessione = db()
    x, o, p = await _elemento_modificabile(elemento_id)
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
             "struttura_id": m.struttura_id, "tempi": m.tempi} for m in righe[:200]]  # fmt: skip


# --- storico e riepilogo --------------------------------------------------------------------


@bp.get("/obiettivi/<obiettivo_id>/storico")
@lettore
async def storico_obiettivo(obiettivo_id: str):
    """Modifiche all'obiettivo e alle sue azioni e misure, dalla più recente."""
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
    misure non al 100%, ritardi. Solo le strutture visibili all'utente."""
    f = parametri(FiltriRiepilogo)
    p = await _piao_dell_ente(f.piao_id)
    q = select(PfObiettivo).where(PfObiettivo.piao_id == p.id)
    if f.anno:
        q = q.where(PfObiettivo.anno == f.anno)
    visibili = await _visibili()
    if visibili is not None:
        q = q.where(PfObiettivo.struttura_id.in_(visibili or {""}))
    righe = list(await db().scalars(q))
    elementi = await _elementi_di([o.id for o in righe])
    oggi = date.today()
    gruppi: dict[tuple[str, int], list[dict]] = {}
    for o in righe:
        gruppi.setdefault((o.struttura_id, o.anno), []).append(_obiettivo(o, p, elementi[o.id], oggi))
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
        })  # fmt: skip
    ordine = {s.id: (s.ordine, chiave_naturale(s.codice)) for s in strutture.values()}
    risultato.sort(key=lambda r: (r["anno"], ordine.get(r["struttura_id"], (0, []))))
    return risultato
