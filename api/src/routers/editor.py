"""Editor di modelli, specificità e checklist (common/editor.py) e proposte di modifica.

Il gestore dei modelli modifica in bozza; la bozza non cambia gli atti finché un
amministratore non la pubblica come nuova versione. Chi scrive un atto può proporre la
modifica di un capoverso: la proposta arriva al gestore.
"""

from datetime import datetime
from http import HTTPStatus
from typing import Any, Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from deps import audit, db, gestore_modelli, redattore, solo_admin, utente
from schemas import Schema
from web import ErroreApi, corpo, nessun_contenuto, out, parametri
from common.configurazione import ChecklistNuovaIn, checklist_in
from common.editor import (
    TIPI,
    anteprima,
    capoversi_del_modello,
    capoversi_del_modulo,
    confronta,
    controlla,
    definizione_da_sorgente,
    punti_di_innesto,
    sorgente_da_definizione,
    sorgente_grezzo,
)
from common.models import (
    AuditLog,
    BozzaConfigurazione,
    Checklist,
    ModelloAtto,
    ModuloDiRegole,
    PropostaModello,
    TipologiaAtto,
    User,
)
from common.modelli import ModelloNonValido
from common.pacchetti import (
    MANTIENI_BASE,
    ricomponi_modelli,
    salva_checklist,
    salva_modello,
    salva_modulo,
    versione_attiva,
)

bp = Blueprint("editor", __name__, url_prefix="/api/v1")

Tipo = Literal["modello", "modulo", "checklist"]


def _tipo(tipo: str) -> Tipo:
    if tipo not in TIPI:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Tipo inesistente")
    return tipo  # type: ignore[return-value]


def _classe(tipo: Tipo):
    return {"modulo": ModuloDiRegole, "modello": ModelloAtto, "checklist": Checklist}[tipo]


async def _bozza(sessione, tipo: Tipo, codice: str) -> BozzaConfigurazione | None:
    return await sessione.scalar(
        select(BozzaConfigurazione).where(
            BozzaConfigurazione.tipo == tipo, BozzaConfigurazione.codice == codice
        )
    )


async def _definizione_pubblicata(sessione, tipo: Tipo, attivo) -> dict:
    if tipo == "checklist":
        return checklist_in(attivo).model_dump(mode="json")
    classe = _classe(tipo)
    sorgente = await sessione.scalar(select(classe.sorgente).where(classe.id == attivo.id))
    return definizione_da_sorgente(tipo, sorgente)


def _modificato(o) -> bool | None:
    return None if o.pacchetto is None else o.impronta != o.impronta_base


# --- elenco ------------------------------------------------------------------------------------


@bp.get("/configurazione")
@gestore_modelli
async def elenco():
    """Modelli, specificità e checklist attivi, con la bozza in corso e le proposte aperte."""
    sessione = db()
    bozze = {
        (b.tipo, b.codice): b
        for b in (await sessione.scalars(select(BozzaConfigurazione))).all()
    }
    proposte = dict(
        (
            await sessione.execute(
                select(PropostaModello.modello, func.count())
                .where(PropostaModello.stato == "APERTA")
                .group_by(PropostaModello.modello)
            )
        ).all()
    )

    def voce(tipo: Tipo, o, titolo: str, **altro) -> dict:
        b = bozze.pop((tipo, o.codice), None)
        return {
            "tipo": tipo,
            "codice": o.codice,
            "titolo": titolo,
            "versione": o.versione,
            "pacchetto": o.pacchetto,
            "modificato": _modificato(o),
            "bozza": b.updated_at.isoformat() if b and b.updated_at else (True if b else None),
            **altro,
        }

    modelli = (
        await sessione.scalars(
            select(ModelloAtto).where(ModelloAtto.attivo.is_(True)).order_by(ModelloAtto.titolo)
        )
    ).all()
    moduli = (
        await sessione.scalars(
            select(ModuloDiRegole)
            .where(ModuloDiRegole.attivo.is_(True))
            .order_by(ModuloDiRegole.etichetta)
        )
    ).all()
    schede = (
        await sessione.scalars(
            select(Checklist).where(Checklist.attiva.is_(True)).order_by(Checklist.titolo)
        )
    ).all()
    risultato = {
        "modelli": [
            voce("modello", m, m.titolo, proposte=proposte.get(m.codice, 0)) for m in modelli
        ],
        "moduli": [voce("modulo", m, m.etichetta) for m in moduli],
        "checklist": [
            voce("checklist", c, c.titolo, modello=c.modello, modulo=c.modulo) for c in schede
        ],
    }
    # bozze di oggetti nuovi, non ancora pubblicati
    for (tipo, codice), b in bozze.items():
        d = b.definizione_json or {}
        chiave = {"modello": "modelli", "modulo": "moduli", "checklist": "checklist"}[tipo]
        risultato[chiave].append(
            {
                "tipo": tipo,
                "codice": codice,
                "titolo": d.get("titolo") or d.get("etichetta") or codice,
                "versione": None,
                "pacchetto": None,
                "modificato": None,
                "bozza": b.updated_at.isoformat() if b.updated_at else True,
                "nuovo": True,
            }
        )
    return risultato


# --- oggetto -----------------------------------------------------------------------------------


async def _contesto(sessione, tipo: Tipo) -> dict:
    """Ciò che serve all'editor per le scelte: tipologie, modelli con punti di innesto e
    capoversi, specificità con i loro capoversi."""
    tipologie = [
        {"codice": t.codice, "descrizione": t.descrizione}
        for t in (await sessione.scalars(select(TipologiaAtto).order_by(TipologiaAtto.ordine)))
    ]
    modelli = []
    for m in (
        await sessione.scalars(
            select(ModelloAtto)
            .where(ModelloAtto.attivo.is_(True))
            .options(undefer(ModelloAtto.sorgente))
        )
    ).all():
        d = definizione_da_sorgente("modello", m.sorgente)
        modelli.append(
            {
                "codice": m.codice,
                "titolo": m.titolo,
                "innesti": punti_di_innesto(d),
                "capoversi": capoversi_del_modello(d),
                "domande": d.get("domande", []),
                "derivati": list((d.get("derivati") or {}).keys()),
                "campi": {n: c.get("etichetta") for n, c in (d.get("campi") or {}).items()},
            }
        )
    moduli = [
        {
            "codice": m.codice,
            "etichetta": m.etichetta,
            "fattore": (m.definizione_json or {}).get("fattore"),
            "modelli": (m.definizione_json or {}).get("modelli", []),
            "capoversi": capoversi_del_modulo(m.definizione_json or {}),
        }
        for m in (
            await sessione.scalars(select(ModuloDiRegole).where(ModuloDiRegole.attivo.is_(True)))
        ).all()
    ]
    return {"tipologie": tipologie, "modelli": modelli, "moduli": moduli}


@bp.get("/configurazione/<tipo>/<codice>")
@gestore_modelli
async def dettaglio(tipo: str, codice: str):
    """Versione pubblicata, bozza in corso, standard di riferimento e contesto dell'editor."""
    tipo = _tipo(tipo)
    sessione = db()
    attivo = await versione_attiva(sessione, tipo, codice)
    bozza = await _bozza(sessione, tipo, codice)
    if attivo is None and bozza is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Oggetto non trovato")
    standard = None
    if attivo is not None and attivo.base_sorgente:
        try:
            standard = {
                "pacchetto": attivo.pacchetto,
                "definizione": definizione_da_sorgente(tipo, attivo.base_sorgente),
            }
        except (ModelloNonValido, ValueError):
            standard = None
    autore = await sessione.get(User, bozza.autore_id) if bozza and bozza.autore_id else None
    return {
        "tipo": tipo,
        "codice": codice,
        "pubblicata": None
        if attivo is None
        else {
            "versione": attivo.versione,
            "pacchetto": attivo.pacchetto,
            "modificato": _modificato(attivo),
            "definizione": await _definizione_pubblicata(sessione, tipo, attivo),
        },
        "bozza": None
        if bozza is None
        else {
            "definizione": bozza.definizione_json,
            "versione_partenza": bozza.versione_partenza,
            "aggiornata_il": bozza.updated_at.isoformat() if bozza.updated_at else None,
            "autore": autore.nome_completo if autore else None,
        },
        "standard": standard,
        "contesto": await _contesto(sessione, tipo),
    }


class DefinizioneIn(BaseModel):
    definizione: dict[str, Any]


class AnteprimaIn(DefinizioneIn):
    risposte: dict[str, Any] = {}
    modello: str | None = None  # per le specificità: il modello in cui comporle


class ConfrontoIn(DefinizioneIn):
    con: Literal["pubblicata", "standard"] = "pubblicata"


class SorgenteIn(BaseModel):
    tipo: Tipo
    sorgente: str = Field(max_length=2_000_000)


class NuovoIn(BaseModel):
    codice: str = Field(min_length=2, max_length=100, pattern=r"^[A-Z0-9_-]+$")
    copia_da: str | None = None  # codice di un oggetto dello stesso tipo da copiare


@bp.put("/configurazione/<tipo>/<codice>/bozza")
@gestore_modelli
async def salva_bozza(tipo: str, codice: str):
    """Salva la bozza anche se non è ancora valida; risponde con errori e avvisi."""
    tipo = _tipo(tipo)
    dati = corpo(DefinizioneIn)
    sessione = db()
    bozza = await _bozza(sessione, tipo, codice)
    if bozza is None:
        attivo = await versione_attiva(sessione, tipo, codice)
        bozza = BozzaConfigurazione(
            tipo=tipo,
            codice=codice,
            versione_partenza=attivo.versione if attivo else None,
            definizione_json={},
        )
        sessione.add(bozza)
    bozza.definizione_json = dati.definizione
    bozza.autore_id = utente().id
    esito = await controlla(sessione, tipo, codice, dati.definizione)
    await sessione.commit()
    return esito


@bp.post("/configurazione/<tipo>/nuovo")
@gestore_modelli
async def nuovo(tipo: str):
    """Bozza di un oggetto nuovo: vuota o copia di uno esistente dello stesso tipo."""
    tipo = _tipo(tipo)
    dati = corpo(NuovoIn)
    sessione = db()
    esiste = await versione_attiva(sessione, tipo, dati.codice)
    if esiste or await _bozza(sessione, tipo, dati.codice):
        raise ErroreApi(HTTPStatus.CONFLICT, "Codice già usato")
    if dati.copia_da:
        origine = await versione_attiva(sessione, tipo, dati.copia_da)
        if origine is None:
            raise ErroreApi(HTTPStatus.NOT_FOUND, "Oggetto da copiare non trovato")
        definizione = await _definizione_pubblicata(sessione, tipo, origine)
    else:
        definizione = _vuoto(tipo)
    definizione["codice"] = dati.codice
    sessione.add(
        BozzaConfigurazione(
            tipo=tipo, codice=dati.codice, definizione_json=definizione, autore_id=utente().id
        )
    )
    await sessione.commit()
    return {"codice": dati.codice}, HTTPStatus.CREATED


def _vuoto(tipo: Tipo) -> dict:
    if tipo == "checklist":
        return {
            "titolo": "Nuova checklist",
            "tipologia_atto": "DETERMINA",
            "elementi": [{"titolo": "Primo controllo", "regola": "Verifica che ..."}],
        }
    if tipo == "modulo":
        return {
            "fattore": "nuova_specificita",
            "etichetta": "Nuova specificità",
            "modelli": [],
            "inserti": [],
        }
    return {
        "titolo": "Nuovo modello",
        "tipologia_atto": "DETERMINA",
        "provvedimento": "Determinazione dirigenziale",
        "organo": "Dirigente",
        "formula_dispositivo": "DETERMINA",
        "domande": [],
        "campi": {},
        "fasi": [
            {"numero": 1, "titolo": "Intestazione e identificazione dell'atto", "sezioni": []},
            {"numero": 2, "titolo": "Preambolo e motivazione", "sezioni": []},
            {"numero": 3, "titolo": "Dispositivo", "formula": "DETERMINA",
             "numerazione": "automatica", "sezioni": []},
            {"numero": 4, "titolo": "Luogo, data e sottoscrizione", "sezioni": []},
        ],
    }  # fmt: skip


@bp.delete("/configurazione/<tipo>/<codice>/bozza")
@gestore_modelli
async def scarta_bozza(tipo: str, codice: str):
    tipo = _tipo(tipo)
    sessione = db()
    bozza = await _bozza(sessione, tipo, codice)
    if bozza is not None:
        await sessione.delete(bozza)
        await sessione.commit()
    return nessun_contenuto()


@bp.post("/configurazione/<tipo>/<codice>/controlla")
@gestore_modelli
async def controlla_definizione(tipo: str, codice: str):
    tipo = _tipo(tipo)
    return await controlla(db(), tipo, codice, corpo(DefinizioneIn).definizione)


@bp.post("/configurazione/<tipo>/<codice>/anteprima")
@gestore_modelli
async def anteprima_definizione(tipo: str, codice: str):
    tipo = _tipo(tipo)
    if tipo == "checklist":
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Anteprima disponibile per modelli e specificità"
        )
    dati = corpo(AnteprimaIn)
    try:
        return await anteprima(db(), tipo, dati.definizione, dati.risposte, dati.modello)
    except ModelloNonValido as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "; ".join(e.errori[:5])) from e
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e


@bp.post("/configurazione/<tipo>/<codice>/confronta")
@gestore_modelli
async def confronta_definizione(tipo: str, codice: str):
    """Differenze della definizione rispetto alla versione pubblicata o allo standard."""
    tipo = _tipo(tipo)
    dati = corpo(ConfrontoIn)
    sessione = db()
    attivo = await versione_attiva(sessione, tipo, codice)
    prima = None
    if attivo is not None:
        if dati.con == "pubblicata":
            prima = await _definizione_pubblicata(sessione, tipo, attivo)
        elif attivo.base_sorgente:
            prima = definizione_da_sorgente(tipo, attivo.base_sorgente)
    return {"differenze": confronta(tipo, prima, dati.definizione)}


@bp.post("/configurazione/sorgente")
@gestore_modelli
async def da_sorgente():
    """Scheda "Sorgente": dal testo YAML/JSON alla definizione (con gli errori)."""
    dati = corpo(SorgenteIn)
    try:
        return {"definizione": definizione_da_sorgente(dati.tipo, dati.sorgente)}
    except ModelloNonValido as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "\n".join(e.errori)) from e
    except ValueError as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e


@bp.post("/configurazione/<tipo>/sorgente")
@gestore_modelli
async def a_sorgente(tipo: str):
    """Il sorgente YAML/JSON della definizione, anche se non è ancora valida."""
    tipo = _tipo(tipo)
    return {"sorgente": sorgente_grezzo(tipo, corpo(DefinizioneIn).definizione)}


@bp.post("/configurazione/<tipo>/<codice>/pubblica")
@solo_admin
async def pubblica(tipo: str, codice: str):
    """La bozza diventa una nuova versione. Le specificità ricompongono i modelli che le
    usano; bozze di atto e verifiche già fatte restano sulla versione usata."""
    tipo = _tipo(tipo)
    sessione = db()
    bozza = await _bozza(sessione, tipo, codice)
    if bozza is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Nessuna bozza da pubblicare")
    esito = await controlla(sessione, tipo, codice, bozza.definizione_json)
    if esito["errori"]:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La bozza contiene errori: " + "; ".join(esito["errori"][:5]),
        )
    attivo = await versione_attiva(sessione, tipo, codice)
    partenza = bozza.versione_partenza
    if attivo is not None and partenza and attivo.versione != partenza:
        raise ErroreApi(
            HTTPStatus.CONFLICT,
            f"Nel frattempo è stata pubblicata la versione {attivo.versione}: confronta la "
            "bozza con la versione pubblicata prima di pubblicarla",
        )
    sorgente = sorgente_da_definizione(tipo, bozza.definizione_json)
    base = MANTIENI_BASE  # resta lo standard di riferimento della versione precedente
    user = utente()
    try:
        if tipo == "modello":
            nuovo_obj = await salva_modello(sessione, sorgente, base, user.id)
        elif tipo == "modulo":
            nuovo_obj = await salva_modulo(sessione, sorgente, base, user.id)
            esito["avvisi"] += await ricomponi_modelli(sessione, user.id)
        else:
            nuovo_obj = await salva_checklist(
                sessione, ChecklistNuovaIn.model_validate(bozza.definizione_json), base, user.id
            )
    except (ModelloNonValido, ValueError) as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    await sessione.delete(bozza)
    audit(
        sessione, user, tipo, nuovo_obj.id, "PUBBLICATA",
        {"codice": codice, "versione": nuovo_obj.versione},
    )  # fmt: skip
    await sessione.commit()
    return {"versione": nuovo_obj.versione, "avvisi": esito["avvisi"]}


class VersioneOut(BaseModel):
    versione: int
    created_at: str | None
    pacchetto: str | None
    autore: str | None


@bp.get("/configurazione/<tipo>/<codice>/storico")
@gestore_modelli
async def storico(tipo: str, codice: str):
    """Versioni dell'oggetto con chi le ha create (dal registro delle operazioni)."""
    tipo = _tipo(tipo)
    sessione = db()
    classe = _classe(tipo)
    versioni = (
        await sessione.scalars(
            select(classe).where(classe.codice == codice).order_by(classe.versione.desc())
        )
    ).all()
    autori = {}
    for riga in (
        await sessione.execute(
            select(AuditLog.entita_id, User.nome_completo)
            .join(User, User.id == AuditLog.user_id, isouter=True)
            .where(AuditLog.entita_id.in_([v.id for v in versioni]))
        )
    ).all():
        autori[riga[0]] = riga[1]
    return [
        VersioneOut(
            versione=v.versione,
            created_at=v.created_at.isoformat() if v.created_at else None,
            pacchetto=v.pacchetto,
            autore=autori.get(v.id) or ("importazione del pacchetto" if v.pacchetto else None),
        ).model_dump()
        for v in versioni
    ]


# --- proposte di modifica ------------------------------------------------------------------------


class PropostaIn(BaseModel):
    modello: str
    versione: int
    capoverso: str
    testo_attuale: str
    testo_proposto: str = Field(min_length=1)
    motivazione: str | None = None


class GestioneIn(BaseModel):
    stato: Literal["ACCOLTA", "RESPINTA"]
    nota: str | None = None


class FiltroProposte(BaseModel):
    modello: str | None = None
    stato: str | None = "APERTA"


class PropostaOut(Schema):
    id: str
    modello: str
    versione: int
    capoverso: str
    testo_attuale: str
    testo_proposto: str
    motivazione: str | None
    stato: str
    nota_gestione: str | None
    created_at: datetime | None
    gestita_il: datetime | None


@bp.post("/proposte")
@redattore
async def proponi():
    """Chi scrive un atto propone la modifica di un capoverso del modello."""
    dati = corpo(PropostaIn)
    sessione = db()
    p = PropostaModello(**dati.model_dump(), autore_id=utente().id)
    sessione.add(p)
    await sessione.flush()
    audit(
        sessione, utente(), "proposta_modello", p.id, "PROPOSTA",
        {"modello": p.modello, "capoverso": p.capoverso},
    )  # fmt: skip
    await sessione.commit()
    await sessione.refresh(p)
    return out(PropostaOut, p), HTTPStatus.CREATED


@bp.get("/proposte")
@gestore_modelli
async def elenco_proposte():
    filtro = parametri(FiltroProposte)
    query = select(PropostaModello).order_by(PropostaModello.created_at.desc())
    if filtro.modello:
        query = query.where(PropostaModello.modello == filtro.modello)
    if filtro.stato:
        query = query.where(PropostaModello.stato == filtro.stato)
    sessione = db()
    proposte = (await sessione.scalars(query)).all()
    autori = {
        u.id: u.nome_completo
        for u in (
            await sessione.scalars(select(User).where(User.id.in_({p.autore_id for p in proposte})))
        ).all()
    }
    return [
        {**PropostaOut.model_validate(p).model_dump(mode="json"), "autore": autori.get(p.autore_id)}
        for p in proposte
    ]


@bp.put("/proposte/<proposta_id>")
@gestore_modelli
async def gestisci_proposta(proposta_id: str):
    dati = corpo(GestioneIn)
    sessione = db()
    p = await sessione.get(PropostaModello, proposta_id)
    if p is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Proposta non trovata")
    p.stato = dati.stato
    p.nota_gestione = dati.nota
    p.gestita_da = utente().id
    p.gestita_il = func.now()
    audit(sessione, utente(), "proposta_modello", p.id, dati.stato)
    await sessione.commit()
    await sessione.refresh(p)
    return out(PropostaOut, p)
