"""Catalogo della mappatura anticorruzione: le voci (radici) di attività, rischi e misure da
cui nascono gli elementi dei processi (common/anticorruzione/catalogo.py).

Lo vede chi vede la mappatura; il RPCT crea le voci, le modifica, le disattiva, le elimina se
non usate e unisce due voci che sono la stessa (gli elementi della seconda passano alla
prima). Modificare, disattivare o unire una voce già usata richiede la conferma (`conferma`):
l'interfaccia mostra prima dove è usata. Gli elementi dei processi non cambiano: hanno il loro
testo, copiato dalla voce quando sono nati.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from deps import audit, db, ente_id, utente
from routers.anticorruzione import lettore, rpct
from web import ErroreApi, corpo, nessun_contenuto, parametri
from common.anticorruzione.catalogo import (
    CAMPI_MISURA, ELEMENTI, TIPI, VoceDoppia, normalizza, testo_elemento, voce_con_testo,
)  # fmt: skip
from common.anticorruzione.catalogo import crea_voce as nuova_voce_ente  # l'endpoint si chiama crea_voce
from common.anticorruzione.metodologia import chiave_naturale
from common.models import AcAttivita, AcProcesso, AcRischio, AcVoce

bp = Blueprint("catalogo", __name__, url_prefix="/api/v1/anticorruzione/catalogo")

TipoVoce = Literal["ATTIVITA", "RISCHIO", "MISURA"]


def _voce(v: AcVoce, usi: int | None = None) -> dict:
    return {
        "id": v.id, "tipo": v.tipo, "codice": v.codice, "descrizione": v.descrizione,
        "tipo_misura": v.tipo_misura, "categoria": v.categoria, "indicatore": v.indicatore, "target": v.target,
        "attiva": v.attiva, "standard": "-E" not in v.codice, **({} if usi is None else {"usi": usi}),
    }  # fmt: skip


async def _voce_dell_ente(voce_id: str) -> AcVoce:
    v = await db().get(AcVoce, voce_id)
    if v is None or v.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Voce del catalogo non trovata")
    return v


async def _conteggi(tipo: str | None = None) -> dict[str, int]:
    """Quanti elementi della mappatura usano ogni voce."""
    esito: dict[str, int] = {}
    for t, modello in ELEMENTI.items():
        if tipo and t != tipo:
            continue
        righe = await db().execute(select(modello.voce_id, func.count()).where(
            modello.ente_id == ente_id(), modello.voce_id.is_not(None)).group_by(modello.voce_id))  # fmt: skip
        esito.update(dict(righe.all()))
    return esito


async def usi_della_voce(v: AcVoce) -> list[dict]:
    """Gli elementi della mappatura che vengono dalla voce, con il loro processo."""
    sessione = db()
    modello = ELEMENTI[v.tipo]
    elementi = list(await sessione.scalars(select(modello).where(modello.voce_id == v.id)))
    if not elementi:
        return []
    # risale al processo: misura -> rischio -> attività -> processo
    rischi = {}
    if v.tipo == "MISURA":
        rischi = {r.id: r for r in await sessione.scalars(select(AcRischio).where(AcRischio.id.in_({e.rischio_id for e in elementi})))}
    ids_attivita = {e.attivita_id for e in elementi} if v.tipo == "RISCHIO" else {r.attivita_id for r in rischi.values()}
    if v.tipo == "ATTIVITA":
        ids_attivita = {e.id for e in elementi}
    attivita = {a.id: a for a in await sessione.scalars(select(AcAttivita).where(AcAttivita.id.in_(ids_attivita)))}
    processi = {p.id: p for p in await sessione.scalars(select(AcProcesso).where(AcProcesso.id.in_({a.processo_id for a in attivita.values()})))}
    usi = []
    for e in elementi:
        attivita_id = e.id if v.tipo == "ATTIVITA" else (e.attivita_id if v.tipo == "RISCHIO" else rischi[e.rischio_id].attivita_id)
        p = processi[attivita[attivita_id].processo_id]
        usi.append({"id": e.id, "codice": e.codice, "testo": testo_elemento(v.tipo, e),
                    "diverso": normalizza(testo_elemento(v.tipo, e)) != normalizza(v.descrizione),
                    "attivita_id": attivita_id,
                    "processo": {"id": p.id, "codice": p.codice, "denominazione": p.denominazione}})  # fmt: skip
    return sorted(usi, key=lambda u: chiave_naturale(u["codice"]))


class FiltriCatalogo(BaseModel):
    tipo: TipoVoce | None = None
    testo: str | None = Field(default=None, max_length=200)
    attive: bool | None = None  # true: solo le attive (per la scelta)


@bp.get("")
@lettore
async def catalogo():
    """Le voci del catalogo (per tipo e codice), con quanti elementi le usano."""
    f = parametri(FiltriCatalogo)
    q = select(AcVoce).where(AcVoce.ente_id == ente_id())
    if f.tipo:
        q = q.where(AcVoce.tipo == f.tipo)
    if f.attive:
        q = q.where(AcVoce.attiva.is_(True))
    voci = list(await db().scalars(q))
    if testo := normalizza(f.testo):
        voci = [v for v in voci if testo in normalizza(v.descrizione) or testo in v.codice.lower()]
    usi = await _conteggi(f.tipo)
    voci.sort(key=lambda v: (TIPI.index(v.tipo), "-E" in v.codice, chiave_naturale(v.codice)))
    return [_voce(v, usi.get(v.id, 0)) for v in voci]


@bp.get("/<voce_id>")
@lettore
async def voce(voce_id: str):
    """La voce con gli elementi della mappatura che la usano."""
    v = await _voce_dell_ente(voce_id)
    usi = await usi_della_voce(v)
    return {**_voce(v, len(usi)), "elementi": usi}


class VoceIn(BaseModel):
    descrizione: str = Field(min_length=1, max_length=10000)
    tipo_misura: Literal["GENERALE", "SPECIFICA"] | None = None  # solo misure
    categoria: str | None = Field(default=None, max_length=255)
    indicatore: str | None = None
    target: str | None = None


class VoceNuova(VoceIn):
    tipo: TipoVoce


class VoceModifica(VoceIn):
    attiva: bool = True
    conferma: bool = False  # la voce è usata: si modifica lo stesso


async def _testo_libero(tipo: str, descrizione: str, esclusa: str | None = None) -> None:
    """Due voci dello stesso tipo non hanno lo stesso testo."""
    if (v := await voce_con_testo(db(), ente_id(), tipo, descrizione, esclusa)) is not None:
        raise ErroreApi(HTTPStatus.CONFLICT, str(VoceDoppia(v)))


def _imposta(v: AcVoce, d: VoceIn) -> None:
    """Testo e, solo per le misure, tipo (di partenza specifica), categoria, indicatore e target."""
    v.descrizione = d.descrizione.strip()
    for campo in CAMPI_MISURA:
        valore = getattr(d, campo) if v.tipo == "MISURA" else None
        setattr(v, campo, valore.strip() or None if isinstance(valore, str) else valore)
    if v.tipo == "MISURA" and v.tipo_misura is None:
        v.tipo_misura = "SPECIFICA"


@bp.post("")
@rpct
async def crea_voce():
    """Nuova voce dell'ente (codice ATT-E001...)."""
    d = corpo(VoceNuova)
    sessione = db()
    try:
        v = await nuova_voce_ente(sessione, ente_id(), d.tipo, d.descrizione, **d.model_dump(include=set(CAMPI_MISURA)))
    except VoceDoppia as e:
        raise ErroreApi(HTTPStatus.CONFLICT, str(e)) from e
    audit(sessione, utente(), "ac_catalogo", v.id, "CREATA", {"codice": v.codice})
    await sessione.commit()
    return _voce(v, 0), HTTPStatus.CREATED


def _serve_conferma(n: int, d) -> None:
    if n and not d.conferma:
        raise ErroreApi(HTTPStatus.CONFLICT, f"La voce è usata in {n} elementi della mappatura: conferma per procedere")


@bp.put("/<voce_id>")
@rpct
async def modifica_voce(voce_id: str):
    """Testo e dati della voce, attiva o no. Gli elementi che la usano restano come sono; se ce
    ne sono serve la conferma."""
    d = corpo(VoceModifica)
    sessione = db()
    v = await _voce_dell_ente(voce_id)
    prima = _voce(v)
    _serve_conferma(len(await usi_della_voce(v)), d)
    await _testo_libero(v.tipo, d.descrizione, esclusa=v.id)
    _imposta(v, d)
    v.attiva = d.attiva
    cambi = {k: [prima[k], valore] for k, valore in _voce(v).items() if prima[k] != valore}
    if cambi:
        audit(sessione, utente(), "ac_catalogo", v.id, "MODIFICATA", {"codice": v.codice, "campi": cambi})
    await sessione.commit()
    return _voce(v, len(await usi_della_voce(v)))


@bp.delete("/<voce_id>")
@rpct
async def elimina_voce(voce_id: str):
    """Solo se nessun elemento la usa (altrimenti si disattiva)."""
    sessione = db()
    v = await _voce_dell_ente(voce_id)
    if await usi_della_voce(v):
        raise ErroreApi(HTTPStatus.CONFLICT, "La voce è usata nella mappatura: si può solo disattivare")
    audit(sessione, utente(), "ac_catalogo", v.id, "ELIMINATA", {"codice": v.codice})
    await sessione.delete(v)
    await sessione.commit()
    return nessun_contenuto()


class UnioneIn(BaseModel):
    in_voce: str  # la voce che resta
    conferma: bool = False


@bp.post("/<voce_id>/unisci")
@rpct
async def unisci_voce(voce_id: str):
    """La voce è la stessa di un'altra dello stesso tipo: i suoi elementi passano all'altra e
    la voce si elimina (il testo degli elementi resta com'è)."""
    d = corpo(UnioneIn)
    sessione = db()
    v = await _voce_dell_ente(voce_id)
    resta = await _voce_dell_ente(d.in_voce)
    if resta.id == v.id or resta.tipo != v.tipo:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Si unisce a un'altra voce dello stesso tipo")
    usi = await usi_della_voce(v)
    _serve_conferma(len(usi), d)
    modello = ELEMENTI[v.tipo]
    await sessione.execute(update(modello).where(modello.voce_id == v.id).values(voce_id=resta.id))
    audit(sessione, utente(), "ac_catalogo", resta.id, "UNITA", {"codice": resta.codice, "unita": v.codice, "elementi": len(usi)})
    await sessione.delete(v)
    await sessione.commit()
    return _voce(resta, len(await usi_della_voce(resta)))
