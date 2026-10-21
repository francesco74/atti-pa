"""Schede di controllo (checklist): formato, controllo e coerenza con modelli e specificità.

Il database comanda: modelli di atto, specificità e checklist si modificano nell'app; i
contenuti standard arrivano con i pacchetti (common/pacchetti.py).
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models import Checklist, ChecklistElemento, ModelloAtto, ModuloDiRegole
from common.normattiva import Urn

# --- definizione di una checklist (stesso formato dell'API /checklists) ----------------------


class ElementoIn(BaseModel):
    titolo: str = Field(min_length=1, max_length=255)
    regola: str = Field(min_length=1)
    riferimenti: list[str] = []  # URN di articoli da passare all'LLM come contesto
    obbligatorio: bool = True
    capoversi: list[str] = []  # capoversi del modello o della specificità che lo soddisfano


class ChecklistIn(BaseModel):
    """Scheda di controllo: generica della tipologia di atto oppure, in aggiunta, di un
    modello di atto (modello) o di una specificità (modulo di regole)."""

    titolo: str = Field(min_length=1, max_length=255)
    tipologia_atto: str
    modello: str | None = None
    modulo: str | None = None
    descrizione: str | None = None
    elementi: list[ElementoIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _un_livello(self):
        self.modello = (self.modello or "").strip() or None
        self.modulo = (self.modulo or "").strip() or None
        if self.modello and self.modulo:
            raise ValueError(
                "Una checklist è di un modello oppure di una specificità, non di entrambi"
            )
        return self


class ChecklistNuovaIn(ChecklistIn):
    codice: str = Field(min_length=2, max_length=100)

    @field_validator("codice")
    @classmethod
    def _codice(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]+", v):
            raise ValueError("Il codice può contenere solo lettere, numeri, '_' e '-'")
        return v


def elementi_checklist(dati: list[ElementoIn]) -> list[ChecklistElemento]:
    return [
        ChecklistElemento(
            ordine=i,
            titolo=e.titolo,
            regola=e.regola,
            riferimenti_json=e.riferimenti or None,
            obbligatorio=e.obbligatorio,
            capoversi_json=e.capoversi or None,
        )
        for i, e in enumerate(dati)
    ]


def controlla_checklist(dati: ChecklistNuovaIn) -> ChecklistNuovaIn:
    """Le URN dei riferimenti indicano l'articolo. Solleva ValueError."""
    for el in dati.elementi:
        for urn in el.riferimenti:
            if not Urn.parse(urn).articolo:
                raise ValueError(f"{el.titolo}: la URN {urn} non indica l'articolo (~artN)")
    return dati


def leggi_checklist(sorgente: str) -> ChecklistNuovaIn:
    """Checklist da JSON, con le URN dei riferimenti controllate. Solleva ValueError."""
    try:
        dati = ChecklistNuovaIn.model_validate(json.loads(sorgente))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"Checklist non valida: {e}") from e
    return controlla_checklist(dati)


def checklist_in(cl: Checklist) -> ChecklistNuovaIn:
    """Contenuto di una checklist del database nel formato dei file."""
    return ChecklistNuovaIn(
        codice=cl.codice,
        titolo=cl.titolo,
        tipologia_atto=cl.tipologia_atto,
        modello=cl.modello,
        modulo=cl.modulo,
        descrizione=cl.descrizione,
        elementi=[
            ElementoIn(
                titolo=e.titolo,
                regola=e.regola,
                riferimenti=e.riferimenti_json or [],
                obbligatorio=e.obbligatorio,
                capoversi=e.capoversi_json or [],
            )
            for e in cl.elementi
        ],
    )


def sorgente_checklist(dati: ChecklistNuovaIn) -> str:
    """Il file JSON della checklist (esportazione e confronto con lo standard)."""
    ordine = ["codice", "titolo", "tipologia_atto", "modello", "modulo", "descrizione"]
    d = dati.model_dump(mode="json")
    elementi = [{k: v for k, v in e.items() if v != []} for e in d["elementi"]]
    contenuto = {k: d[k] for k in ordine if d.get(k) is not None} | {"elementi": elementi}
    return json.dumps(contenuto, ensure_ascii=False, indent=2) + "\n"


def impronta(contenuto: str | dict | list) -> str:
    """SHA-256 di un testo o, per i dati strutturati, della loro forma canonica: due
    contenuti uguali hanno la stessa impronta anche se i file sono formattati diversamente."""
    if not isinstance(contenuto, str):
        contenuto = json.dumps(contenuto, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(contenuto.encode("utf-8")).hexdigest()


def impronta_checklist(dati: ChecklistNuovaIn) -> str:
    return impronta(dati.model_dump(mode="json"))


# --- coerenza --------------------------------------------------------------------------------


async def controlla_coerenza(db: AsyncSession) -> list[str]:
    """Ogni tipologia con modelli ha la sua scheda generica, ogni modello e ogni specificità
    la propria; ogni scheda di modello o di specificità rimanda a qualcosa che esiste."""
    modelli = (await db.scalars(select(ModelloAtto).where(ModelloAtto.attivo.is_(True)))).all()
    moduli = (
        await db.scalars(select(ModuloDiRegole).where(ModuloDiRegole.attivo.is_(True)))
    ).all()
    schede = (await db.scalars(select(Checklist).where(Checklist.attiva.is_(True)))).all()
    generiche = {c.tipologia_atto for c in schede if not c.modello and not c.modulo}
    di_modello = {c.modello for c in schede if c.modello}
    di_modulo = {c.modulo for c in schede if c.modulo}
    specificita = {m.codice for m in moduli}
    avvisi = []
    for tipologia in sorted({m.tipologia_atto for m in modelli} - generiche):
        avvisi.append(f"tipologia {tipologia}: manca la checklist generica")
    for m in modelli:
        if m.codice not in di_modello:
            avvisi.append(f"modello {m.codice}: manca la checklist del modello")
    for codice in sorted(specificita - di_modulo):
        avvisi.append(f"specificità {codice}: manca la checklist della specificità")
    for c in schede:
        if c.modello and c.modello not in {m.codice for m in modelli}:
            avvisi.append(f"checklist {c.codice}: il modello {c.modello} non esiste")
        if c.modulo and c.modulo not in specificita:
            avvisi.append(f"checklist {c.codice}: la specificità {c.modulo} non esiste")
    return avvisi
