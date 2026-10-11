"""Modulo Redazione: bozze personali di determinazione (ogni utente vede solo le proprie)."""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from atti_api.composizione import aggiorna_testo, data_riferimento, documento_odt
from atti_api.deps import (
    DbDep,
    RedattoreDep,
    SettingsDep,
    audit,
    get_documenti,
    get_llm,
    get_normattiva,
)
from atti_api.documenti import DocumentiClient, DocumentiError
from atti_api.schemas import Schema
from atti_common.dati_personali import come_dict, trova_dati_personali
from atti_common.llm import LlmClient, LlmError, espandi_appunti
from atti_common.models import Bozza, Template, TipologiaAtto
from atti_common.normattiva import NormattivaClient, Urn
from atti_common.normattiva.citazioni import citazione_riferimento
from atti_common.odt import segnaposto_non_compilati
from atti_common.verifica import verifica_riferimenti

router = APIRouter(prefix="/api/v1/bozze", tags=["redazione"])

NormattivaDep = Annotated[NormattivaClient, Depends(get_normattiva)]


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


async def _bozza_propria(db, bozza_id: str, user) -> Bozza:
    bozza = await db.get(Bozza, bozza_id)
    if bozza is None or bozza.owner_id != user.id:
        # stessa risposta per inesistente e altrui: non si rivela l'esistenza di atti di altri
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bozza non trovata")
    return bozza


async def _template(db, template_id: str | None, tipologia: str) -> Template | None:
    if not template_id:
        return None
    t = await db.scalar(
        select(Template).where(Template.id == template_id).options(undefer(Template.file_contenuto))
    )
    if t is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Template inesistente")
    if t.tipologia_atto != tipologia:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Il template è di un'altra tipologia di atto"
        )
    return t


def _riferimenti(dati: list[RiferimentoBozza]) -> list[dict]:
    risultato = []
    for r in dati:
        try:
            urn = Urn.parse(r.urn_atto).atto
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
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


async def _applica(db, bozza: Bozza, dati: BozzaIn) -> None:
    if await db.get(TipologiaAtto, dati.tipologia_atto) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")
    template = await _template(db, dati.template_id, dati.tipologia_atto)
    bozza.oggetto = dati.oggetto
    bozza.tipologia_atto = dati.tipologia_atto
    bozza.template_id = dati.template_id
    bozza.data_adozione_prevista = dati.data_adozione_prevista
    bozza.dati_json = dati.dati
    bozza.riferimenti_json = _riferimenti(dati.riferimenti)
    aggiorna_testo(bozza, template)


@router.get("", response_model=list[BozzaSintesi])
async def elenco(db: DbDep, user: RedattoreDep, q: str | None = None):
    query = select(Bozza).where(Bozza.owner_id == user.id).order_by(Bozza.updated_at.desc())
    if q:
        query = query.where(Bozza.oggetto.like(f"%{q}%"))
    return (await db.scalars(query)).all()


@router.post("", response_model=BozzaOut, status_code=status.HTTP_201_CREATED)
async def crea(dati: BozzaIn, db: DbDep, user: RedattoreDep):
    bozza = Bozza(owner_id=user.id)
    await _applica(db, bozza, dati)
    db.add(bozza)
    await db.flush()
    audit(db, user, "bozza", bozza.id, "CREATA")
    await db.commit()
    await db.refresh(bozza)
    return bozza


@router.get("/{bozza_id}", response_model=BozzaOut)
async def dettaglio(bozza_id: str, db: DbDep, user: RedattoreDep):
    return await _bozza_propria(db, bozza_id, user)


@router.put("/{bozza_id}", response_model=BozzaOut)
async def aggiorna(bozza_id: str, dati: BozzaIn, db: DbDep, user: RedattoreDep):
    bozza = await _bozza_propria(db, bozza_id, user)
    await _applica(db, bozza, dati)
    audit(db, user, "bozza", bozza.id, "MODIFICATA")
    await db.commit()
    await db.refresh(bozza)
    return bozza


@router.delete("/{bozza_id}", status_code=status.HTTP_204_NO_CONTENT)
async def elimina(bozza_id: str, db: DbDep, user: RedattoreDep) -> None:
    bozza = await _bozza_propria(db, bozza_id, user)
    await db.delete(bozza)
    audit(db, user, "bozza", bozza_id, "ELIMINATA")
    await db.commit()


@router.get("/{bozza_id}/controllo-rapido")
async def controllo_rapido(
    bozza_id: str, db: DbDep, user: RedattoreDep, normattiva: NormattivaDep, settings: SettingsDep
) -> dict:
    """Controlli deterministici immediati per il wizard (senza LLM)."""
    bozza = await _bozza_propria(db, bozza_id, user)
    testo = bozza.contenuto_testo or ""
    giorno = data_riferimento(bozza, datetime.now(settings.tz).date())

    mancanti = []
    if bozza.template_id:
        template = await db.get(Template, bozza.template_id)
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
        "riferimenti": await verifica_riferimenti(db, normattiva, testo, giorno),
        "dati_personali": come_dict(trova_dati_personali(testo)),
    }


MIME = {
    "odt": "application/vnd.oasis.opendocument.text",
    "pdf": "application/pdf",
    "pdfa": "application/pdf",
}


@router.get("/{bozza_id}/documento")
async def documento(
    bozza_id: str,
    db: DbDep,
    user: RedattoreDep,
    documenti: Annotated[DocumentiClient, Depends(get_documenti)],
    formato: Annotated[Literal["odt", "pdf", "pdfa"], Query()] = "odt",
    omissis: bool = False,
) -> Response:
    """Documento generato dal template; `omissis=true` oscura i dati personali rilevati."""
    bozza = await _bozza_propria(db, bozza_id, user)
    template = await _template(db, bozza.template_id, bozza.tipologia_atto)
    if template is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Scegliere un template per generare il documento"
        )
    odt = documento_odt(bozza, template, omissis=omissis)
    contenuto = odt
    if formato != "odt":
        try:
            contenuto = await documenti.converti(odt, "atto.odt", formato)
        except DocumentiError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    estensione = "odt" if formato == "odt" else "pdf"
    nome = f"determina{'-omissis' if omissis else ''}.{estensione}"
    audit(db, user, "bozza", bozza.id, "DOCUMENTO", {"formato": formato, "omissis": omissis})
    await db.commit()
    return Response(
        contenuto,
        media_type=MIME[formato],
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


class EspandiIn(BaseModel):
    sezione: str = Field(min_length=1, max_length=100)
    appunti: str = Field(min_length=3, max_length=5000)
    oggetto: str = ""


@router.post("/espandi")
async def espandi(
    dati: EspandiIn,
    _: RedattoreDep,
    llm: Annotated[LlmClient | None, Depends(get_llm)],
) -> dict:
    """Riscrive appunti sintetici in linguaggio amministrativo (LLM on-premise)."""
    if llm is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Modello linguistico non configurato"
        )
    try:
        testo = await espandi_appunti(llm, dati.sezione, dati.appunti, dati.oggetto)
    except LlmError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return {"testo": testo}
