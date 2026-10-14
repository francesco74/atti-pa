"""Template ODT per la redazione guidata.

I campi del wizard sono ricavati dai segnaposto `{{ nome_campo }}` del documento;
l'amministratore può poi rinominarli, descriverli e indicarne il tipo.
"""

from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from deps import audit, autenticato, db, impostazioni, solo_admin, utente
from schemas import Schema
from web import (
    ErroreApi,
    allegato,
    corpo,
    file_caricato,
    modulo,
    nessun_contenuto,
    out,
    parametri,
)
from common.models import Template, TipologiaAtto
from common.odt import OdtNonValido, estrai_segnaposto

bp = Blueprint("templates", __name__, url_prefix="/api/v1/templates")

MIME_ODT = "application/vnd.oasis.opendocument.text"

# Campi gestiti dal sistema, non chiesti nel wizard
CAMPI_DI_SISTEMA = {"riferimenti_normativi", "oggetto", "data_adozione"}


class CampoTemplate(BaseModel):
    nome: str
    etichetta: str
    tipo: Literal["testo", "testo_lungo", "data", "importo", "numero"] = "testo"
    obbligatorio: bool = True
    aiuto: str | None = None


class TemplateOut(Schema):
    id: str
    nome: str
    tipologia_atto: str
    versione: int
    attivo: bool
    file_nome: str
    campi_json: list[CampoTemplate]


class FiltroTemplate(BaseModel):
    tipologia: str | None = None
    tutti: bool = False


class TemplateIn(BaseModel):
    nome: str = Field(min_length=1, max_length=255)
    tipologia_atto: str


def _etichetta(nome: str) -> str:
    return nome.replace("_", " ").capitalize()


def campi_da_segnaposto(nomi: list[str]) -> list[dict]:
    return [
        CampoTemplate(
            nome=n,
            etichetta=_etichetta(n),
            tipo="testo_lungo"
            if n.startswith(("premesse", "motivazione", "dispositivo"))
            else "testo",
        ).model_dump()
        for n in nomi
        if n not in CAMPI_DI_SISTEMA
    ]


@bp.get("")
@autenticato()
async def elenco():
    filtro = parametri(FiltroTemplate)
    query = select(Template).order_by(
        Template.tipologia_atto, Template.nome, Template.versione.desc()
    )
    if not filtro.tutti:
        query = query.where(Template.attivo.is_(True))
    if filtro.tipologia:
        query = query.where(Template.tipologia_atto == filtro.tipologia)
    return out(TemplateOut, (await db().scalars(query)).all())


@bp.get("/<template_id>")
@autenticato()
async def dettaglio(template_id: str):
    t = await db().get(Template, template_id)
    if t is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    return out(TemplateOut, t)


@bp.post("")
@solo_admin
async def carica():
    """Carica un template (.odt con segnaposto {{ campo }}).

    Se esiste già un template con lo stesso nome ne crea una nuova versione.
    """
    dati = modulo(TemplateIn)
    file = file_caricato()
    sessione = db()
    if await sessione.get(TipologiaAtto, dati.tipologia_atto) is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")
    limite = impostazioni().upload_max_mb * 1024 * 1024
    contenuto = file.read(limite + 1)
    if len(contenuto) > limite:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
    try:
        segnaposto = estrai_segnaposto(contenuto)
    except OdtNonValido as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from e
    if not segnaposto:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Il template non contiene segnaposto {{ campo }}"
        )

    stesso = (Template.nome == dati.nome, Template.tipologia_atto == dati.tipologia_atto)
    ultima = await sessione.scalar(select(func.max(Template.versione)).where(*stesso))
    if ultima:
        for t in (await sessione.scalars(select(Template).where(*stesso))).all():
            t.attivo = False
    t = Template(
        nome=dati.nome,
        tipologia_atto=dati.tipologia_atto,
        versione=(ultima or 0) + 1,
        attivo=True,
        file_nome=file.filename or "template.odt",
        file_contenuto=contenuto,
        campi_json=campi_da_segnaposto(segnaposto),
    )
    sessione.add(t)
    await sessione.flush()
    audit(
        sessione,
        utente(),
        "template",
        t.id,
        "CARICATO",
        {"nome": dati.nome, "versione": t.versione},
    )
    await sessione.commit()
    return out(TemplateOut, t), HTTPStatus.CREATED


class CampiIn(BaseModel):
    campi: list[CampoTemplate] = Field(min_length=1)


@bp.put("/<template_id>/campi")
@solo_admin
async def aggiorna_campi(template_id: str):
    """Etichette, tipi e testi di aiuto dei campi del wizard."""
    dati = corpo(CampiIn)
    sessione = db()
    t = await sessione.get(Template, template_id)
    if t is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    esistenti = {c["nome"] for c in t.campi_json}
    sconosciuti = {c.nome for c in dati.campi} - esistenti
    if sconosciuti:
        raise ErroreApi(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"Campi non presenti nel template: {', '.join(sorted(sconosciuti))}",
        )
    t.campi_json = [c.model_dump() for c in dati.campi]
    audit(sessione, utente(), "template", t.id, "CAMPI_AGGIORNATI")
    await sessione.commit()
    return out(TemplateOut, t)


@bp.get("/<template_id>/file")
@autenticato()
async def scarica(template_id: str):
    t = await db().scalar(
        select(Template).where(Template.id == template_id).options(undefer(Template.file_contenuto))
    )
    if t is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    return allegato(t.file_contenuto, MIME_ODT, t.file_nome)


@bp.delete("/<template_id>")
@solo_admin
async def disattiva(template_id: str):
    sessione = db()
    t = await sessione.get(Template, template_id)
    if t is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND)
    t.attivo = False
    audit(sessione, utente(), "template", t.id, "DISATTIVATO")
    await sessione.commit()
    return nessun_contenuto()
