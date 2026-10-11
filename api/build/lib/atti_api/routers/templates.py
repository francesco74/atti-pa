"""Template ODT per la redazione guidata.

I campi del wizard sono ricavati dai segnaposto `{{ nome_campo }}` del documento;
l'amministratore può poi rinominarli, descriverli e indicarne il tipo.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from atti_api.deps import AdminDep, DbDep, SettingsDep, UtenteDep, audit
from atti_api.schemas import Schema
from atti_common.models import Template, TipologiaAtto
from atti_common.odt import OdtNonValido, estrai_segnaposto

router = APIRouter(prefix="/api/v1/templates", tags=["template"])

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


@router.get("", response_model=list[TemplateOut])
async def elenco(db: DbDep, _: UtenteDep, tipologia: str | None = None, tutti: bool = False):
    query = select(Template).order_by(
        Template.tipologia_atto, Template.nome, Template.versione.desc()
    )
    if not tutti:
        query = query.where(Template.attivo.is_(True))
    if tipologia:
        query = query.where(Template.tipologia_atto == tipologia)
    return (await db.scalars(query)).all()


@router.get("/{template_id}", response_model=TemplateOut)
async def dettaglio(template_id: str, db: DbDep, _: UtenteDep):
    t = await db.get(Template, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return t


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def carica(
    db: DbDep,
    user: AdminDep,
    settings: SettingsDep,
    nome: Annotated[str, Form(min_length=1, max_length=255)],
    tipologia_atto: Annotated[str, Form()],
    file: Annotated[UploadFile, File(description="Documento .odt con segnaposto {{ campo }}")],
):
    """Carica un template; se esiste già un template con lo stesso nome ne crea una nuova versione."""
    if await db.get(TipologiaAtto, tipologia_atto) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipologia di atto inesistente")
    contenuto = await file.read(settings.upload_max_mb * 1024 * 1024 + 1)
    if len(contenuto) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File troppo grande")
    try:
        segnaposto = estrai_segnaposto(contenuto)
    except OdtNonValido as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    if not segnaposto:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Il template non contiene segnaposto {{ campo }}"
        )

    ultima = await db.scalar(
        select(func.max(Template.versione)).where(
            Template.nome == nome, Template.tipologia_atto == tipologia_atto
        )
    )
    if ultima:
        precedenti = await db.scalars(
            select(Template).where(Template.nome == nome, Template.tipologia_atto == tipologia_atto)
        )
        for t in precedenti.all():
            t.attivo = False
    t = Template(
        nome=nome,
        tipologia_atto=tipologia_atto,
        versione=(ultima or 0) + 1,
        attivo=True,
        file_nome=file.filename or "template.odt",
        file_contenuto=contenuto,
        campi_json=campi_da_segnaposto(segnaposto),
    )
    db.add(t)
    await db.flush()
    audit(db, user, "template", t.id, "CARICATO", {"nome": nome, "versione": t.versione})
    await db.commit()
    return t


class CampiIn(BaseModel):
    campi: list[CampoTemplate] = Field(min_length=1)


@router.put("/{template_id}/campi", response_model=TemplateOut)
async def aggiorna_campi(template_id: str, dati: CampiIn, db: DbDep, user: AdminDep):
    """Etichette, tipi e testi di aiuto dei campi del wizard."""
    t = await db.get(Template, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    esistenti = {c["nome"] for c in t.campi_json}
    sconosciuti = {c.nome for c in dati.campi} - esistenti
    if sconosciuti:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Campi non presenti nel template: {', '.join(sorted(sconosciuti))}",
        )
    t.campi_json = [c.model_dump() for c in dati.campi]
    audit(db, user, "template", t.id, "CAMPI_AGGIORNATI")
    await db.commit()
    return t


@router.get("/{template_id}/file")
async def scarica(template_id: str, db: DbDep, _: UtenteDep) -> Response:
    t = await db.scalar(
        select(Template).where(Template.id == template_id).options(undefer(Template.file_contenuto))
    )
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return Response(
        t.file_contenuto,
        media_type=MIME_ODT,
        headers={"Content-Disposition": f'attachment; filename="{t.file_nome}"'},
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disattiva(template_id: str, db: DbDep, user: AdminDep) -> None:
    t = await db.get(Template, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    t.attivo = False
    audit(db, user, "template", t.id, "DISATTIVATO")
    await db.commit()
