"""Modulo Redazione: bozze personali di determinazione (ogni utente vede solo le proprie)."""

from datetime import date, datetime
from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from composizione import (
    aggiorna_testo,
    data_riferimento,
    documento_odt,
    documento_odt_con_omissis,
)
from deps import audit, db, impostazioni, redattore, risorse, utente
from documenti import DocumentiError
from schemas import Schema
from web import ErroreApi, allegato, corpo, nessun_contenuto, out, parametri
from common.dati_personali import DatiPersonaliNonDisponibili, StatoDatiPersonali
from common.llm import LlmError, espandi_appunti
from common.models import Bozza, Template, TipologiaAtto
from common.normattiva import Urn
from common.normattiva.citazioni import citazione_riferimento
from common.odt import segnaposto_non_compilati
from common.verifica import verifica_riferimenti

bp = Blueprint("bozze", __name__, url_prefix="/api/v1/bozze")


class RiferimentoBozza(BaseModel):
    urn_atto: str
    articolo: str
    comma: str | None = None
    lettera: str | None = None
    citazione: str | None = None


class BozzaIn(BaseModel):
    oggetto: str = Field(min_length=3)
    tipologia_atto: str
    template_id: str | None = None
    data_adozione_prevista: date | None = None
    dati: dict[str, str | None] = {}
    riferimenti: list[RiferimentoBozza] = []


class BozzaSintesi(Schema):
    id: str
    oggetto: str
    tipologia_atto: str
    template_id: str | None
    data_adozione_prevista: date | None
    updated_at: datetime | None


class BozzaOut(BozzaSintesi):
    dati_json: dict
    riferimenti_json: list[dict]
    contenuto_testo: str | None


class FiltroBozze(BaseModel):
    q: str | None = None


async def _bozza_propria(sessione, bozza_id: str) -> Bozza:
    bozza = await sessione.get(Bozza, bozza_id)
    if bozza is None or bozza.owner_id != utente().id:
        # stessa risposta per inesistente e altrui: non si rivela l'esistenza di atti di altri
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Bozza non trovata")
    return bozza


async def _template(sessione, template_id: str | None, tipologia: str) -> Template | None:
    if not template_id:
        return None
    t = await sessione.scalar(
        select(Template).where(Template.id == template_id).options(undefer(Template.file_contenuto))
    )
    if t is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Template inesistente")
    if t.tipologia_atto != tipologia:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Il template è di un'altra tipologia di atto"
        )
    return t


def _riferimenti(dati: list[RiferimentoBozza]) -> list[dict]:
    risultato = []
    for r in dati:
        try:
            urn = Urn.parse(r.urn_atto).atto
        except ValueError as e:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
        risultato.append(
            {
                "urn_atto": urn,
                "articolo": r.articolo,
                "comma": r.comma,
                "lettera": r.lettera,
                "citazione": r.citazione
                or citazione_riferimento(urn, r.articolo, r.comma, r.lettera),
            }
        )
    return risultato


async def _applica(sessione, bozza: Bozza, dati: BozzaIn) -> None:
    if await sessione.get(TipologiaAtto, dati.tipologia_atto) is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")
    template = await _template(sessione, dati.template_id, dati.tipologia_atto)
    bozza.oggetto = dati.oggetto
    bozza.tipologia_atto = dati.tipologia_atto
    bozza.template_id = dati.template_id
    bozza.data_adozione_prevista = dati.data_adozione_prevista
    bozza.dati_json = dati.dati
    bozza.riferimenti_json = _riferimenti(dati.riferimenti)
    aggiorna_testo(bozza, template)


@bp.get("")
@redattore
async def elenco():
    q = parametri(FiltroBozze).q
    query = select(Bozza).where(Bozza.owner_id == utente().id).order_by(Bozza.updated_at.desc())
    if q:
        query = query.where(Bozza.oggetto.like(f"%{q}%"))
    return out(BozzaSintesi, (await db().scalars(query)).all())


@bp.post("")
@redattore
async def crea():
    dati = corpo(BozzaIn)
    sessione = db()
    bozza = Bozza(owner_id=utente().id)
    await _applica(sessione, bozza, dati)
    sessione.add(bozza)
    await sessione.flush()
    audit(sessione, utente(), "bozza", bozza.id, "CREATA")
    await sessione.commit()
    await sessione.refresh(bozza)
    return out(BozzaOut, bozza), HTTPStatus.CREATED


@bp.get("/<bozza_id>")
@redattore
async def dettaglio(bozza_id: str):
    return out(BozzaOut, await _bozza_propria(db(), bozza_id))


@bp.put("/<bozza_id>")
@redattore
async def aggiorna(bozza_id: str):
    dati = corpo(BozzaIn)
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    await _applica(sessione, bozza, dati)
    audit(sessione, utente(), "bozza", bozza.id, "MODIFICATA")
    await sessione.commit()
    await sessione.refresh(bozza)
    return out(BozzaOut, bozza)


@bp.delete("/<bozza_id>")
@redattore
async def elimina(bozza_id: str):
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    await sessione.delete(bozza)
    audit(sessione, utente(), "bozza", bozza_id, "ELIMINATA")
    await sessione.commit()
    return nessun_contenuto()


@bp.get("/<bozza_id>/controllo-rapido")
@redattore
async def controllo_rapido(bozza_id: str):
    """Controlli deterministici immediati per il wizard (senza LLM)."""
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    testo = bozza.contenuto_testo or ""
    giorno = data_riferimento(bozza, datetime.now(impostazioni().tz).date())

    mancanti = []
    if bozza.template_id:
        template = await sessione.get(Template, bozza.template_id)
        if template:
            mancanti = [
                c["etichetta"]
                for c in template.campi_json
                if c.get("obbligatorio") and not (bozza.dati_json or {}).get(c["nome"])
            ]
    return {
        "data_riferimento": giorno,
        "campi_obbligatori_mancanti": mancanti,
        "segnaposto": segnaposto_non_compilati(testo),
        "riferimenti": await verifica_riferimenti(sessione, risorse().normattiva, testo, giorno),
        # i dati personali li rileva il modello: nella verifica completa, non qui
        "dati_personali": [],
        "dati_personali_stato": StatoDatiPersonali.NON_VALUTATI,
    }


MIME = {
    "odt": "application/vnd.oasis.opendocument.text",
    "pdf": "application/pdf",
    "pdfa": "application/pdf",
}


class DocumentoQuery(BaseModel):
    formato: Literal["odt", "pdf", "pdfa"] = "odt"
    omissis: bool = False


@bp.get("/<bozza_id>/documento")
@redattore
async def documento(bozza_id: str):
    """Documento generato dal template; `omissis=true` oscura i dati personali rilevati."""
    q = parametri(DocumentoQuery)
    sessione = db()
    bozza = await _bozza_propria(sessione, bozza_id)
    template = await _template(sessione, bozza.template_id, bozza.tipologia_atto)
    if template is None:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Scegliere un template per generare il documento"
        )
    try:
        odt = (
            await documento_odt_con_omissis(
                bozza,
                template,
                risorse().llm if impostazioni().llm_dati_personali else None,
            )
            if q.omissis
            else documento_odt(bozza, template)
        )
    except DatiPersonaliNonDisponibili as e:
        # mai un documento "con omissis" con i dati in chiaro
        raise ErroreApi(
            HTTPStatus.SERVICE_UNAVAILABLE,
            f"Documento con omissis non disponibile: rilevamento dei dati personali non "
            f"riuscito ({e}). Riprovare più tardi.",
        ) from e
    contenuto = odt
    if q.formato != "odt":
        try:
            contenuto = await risorse().documenti.converti(odt, "atto.odt", q.formato)
        except DocumentiError as e:
            raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    estensione = "odt" if q.formato == "odt" else "pdf"
    nome = f"determina{'-omissis' if q.omissis else ''}.{estensione}"
    audit(
        sessione,
        utente(),
        "bozza",
        bozza.id,
        "DOCUMENTO",
        {"formato": q.formato, "omissis": q.omissis},
    )
    await sessione.commit()
    return allegato(contenuto, MIME[q.formato], nome)


class EspandiIn(BaseModel):
    sezione: str = Field(min_length=1, max_length=100)
    appunti: str = Field(min_length=3, max_length=5000)
    oggetto: str = ""


@bp.post("/espandi")
@redattore
async def espandi():
    """Riscrive appunti sintetici in linguaggio amministrativo (LLM on-premise)."""
    dati = corpo(EspandiIn)
    llm = risorse().llm
    if llm is None:
        raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, "Modello linguistico non configurato")
    try:
        testo = await espandi_appunti(llm, dati.sezione, dati.appunti, dati.oggetto)
    except LlmError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    return {"testo": testo}
