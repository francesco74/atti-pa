"""Contenuti standard del modulo anticorruzione nei pacchetti (common/pacchetti.py):

    anticorruzione/metodologia.yaml       metodologia di valutazione del rischio
    anticorruzione/aree.yaml              aree di rischio (create se mancano, mai cancellate)
    anticorruzione/processi/*.yaml        processi standard, un file per area

Un processo standard porta attività, rischi (con una valutazione proposta) e misure. Il
confronto a tre vie usa l'impronta del contenuto standard: codici e testi di processo,
attività, rischi e misure. Restano fuori, perché sono scelte dell'ente, le strutture
responsabili e le valutazioni: la valutazione proposta entra solo nei rischi nuovi.
Applicando un aggiornamento gli elementi si abbinano per codice: quelli con lo stesso codice
si aggiornano (conservano i monitoraggi), i nuovi si aggiungono e
quelli tolti dallo standard si eliminano.
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.anticorruzione.metodologia import Metodologia, chiave_area, chiave_naturale, standard, valuta
from common.configurazione import impronta
from common.models import (
    AcArea, AcAttivita, AcMetodologia, AcMisura, AcProcesso, AcRischio, nuovo_id,
)  # fmt: skip

CARTELLA = "anticorruzione"
FILE_METODOLOGIA = f"{CARTELLA}/metodologia.yaml"
FILE_AREE = f"{CARTELLA}/aree.yaml"
CARTELLA_PROCESSI = f"{CARTELLA}/processi"


class AreaStd(BaseModel):
    codice: str = Field(min_length=1, max_length=20)
    descrizione: str = Field(min_length=1, max_length=500)
    descrizione_breve: str | None = Field(default=None, max_length=255)


class ValutazioneStd(BaseModel):
    """Valutazione proposta: valori degli indicatori della metodologia standard."""

    probabilita: dict[str, str]
    impatto: dict[str, str]


class MisuraStd(BaseModel):
    codice: str = Field(min_length=1, max_length=70)
    descrizione: str = Field(min_length=1)
    tipo: Literal["GENERALE", "SPECIFICA"] = "SPECIFICA"
    categoria: str | None = None
    obbligo_trasparenza: str | None = None
    fasi: str | None = None
    tempi: str | None = None
    indicatore: str | None = None
    target: str | None = None


class RischioStd(BaseModel):
    codice: str = Field(min_length=1, max_length=60)
    evento: str = Field(min_length=1)
    fattore_abilitante: str | None = None
    valutazione: ValutazioneStd | None = None
    misure: list[MisuraStd] = []


class AttivitaStd(BaseModel):
    codice: str = Field(min_length=1, max_length=50)
    descrizione: str = Field(min_length=1)
    rischi: list[RischioStd] = []


class ProcessoStd(BaseModel):
    codice: str = Field(min_length=1, max_length=50)
    tipo: Literal["PROCESSO", "PROCEDIMENTO"] = "PROCESSO"
    denominazione: str = Field(min_length=1, max_length=500)
    descrizione: str | None = None
    tempi: str | None = None
    attori_esterni: str | None = None
    termine_conclusione: str | None = None  # procedimento
    norma_riferimento: str | None = None  # procedimento
    attivita: list[AttivitaStd] = []


class FileProcessi(BaseModel):
    area: str | None = None  # codice dell'area di rischio dei processi del file
    processi: list[ProcessoStd]


def impronta_processo(p: ProcessoStd, area: str | None) -> str:
    """Impronta del contenuto standard (senza valutazioni, che sono dell'ente). Tipo, termine e
    norma entrano solo se diversi dal valore predefinito: i processi già distribuiti, che non li
    hanno, mantengono l'impronta di prima."""
    dati = p.model_dump(mode="json", exclude={"attivita": {"__all__": {"rischi": {"__all__": {"valutazione"}}}}})
    for campo, predefinito in (("tipo", "PROCESSO"), ("termine_conclusione", None), ("norma_riferimento", None)):
        if dati.get(campo) == predefinito:
            del dati[campo]
    return impronta({"area": area, **dati})


def impronta_metodologia(m: Metodologia) -> str:
    return impronta(m.model_dump(mode="json"))


def leggi_metodologia(sorgente: str) -> Metodologia:
    return Metodologia.model_validate(yaml.safe_load(sorgente) or {})


def leggi_aree(sorgente: str) -> list[AreaStd]:
    return [AreaStd.model_validate(a) for a in (yaml.safe_load(sorgente) or {}).get("aree") or []]


def leggi_processi(sorgente: str) -> FileProcessi:
    f = FileProcessi.model_validate(yaml.safe_load(sorgente) or {})
    for p in f.processi:
        codici = [a.codice for a in p.attivita] + [r.codice for a in p.attivita for r in a.rischi]
        codici += [m.codice for a in p.attivita for r in a.rischi for m in r.misure]
        doppi = sorted({c for c in codici if codici.count(c) > 1})
        if doppi:
            raise ValueError(f"processo {p.codice}: codici ripetuti {', '.join(doppi)}")
    return f


def sorgente_processo(p: ProcessoStd, area: str | None) -> str:
    """Un processo come file a sé (sorgente dell'oggetto del pacchetto)."""
    dati = p.model_dump(mode="json", exclude_none=True)
    if dati.get("tipo") == "PROCESSO":
        del dati["tipo"]  # predefinito: i processi senza tipo restano scritti come prima
    return yaml.safe_dump({"area": area, "processi": [dati]}, allow_unicode=True, sort_keys=False, width=100)


# --- stato nell'ente -------------------------------------------------------------------------


async def processo_ente(db: AsyncSession, ente_id: str, codice: str) -> tuple[AcProcesso, ProcessoStd, str | None] | None:
    """Il processo dell'ente con quel codice, nella forma standard (per l'impronta)."""
    p = await db.scalar(select(AcProcesso).where(AcProcesso.ente_id == ente_id, AcProcesso.codice == codice))
    if p is None:
        return None
    area = await db.get(AcArea, p.area_id) if p.area_id else None
    attivita = sorted(await db.scalars(select(AcAttivita).where(AcAttivita.processo_id == p.id)),
                      key=lambda x: chiave_naturale(x.codice))  # fmt: skip
    rischi = sorted(await db.scalars(select(AcRischio).where(AcRischio.attivita_id.in_([a.id for a in attivita]))),
                    key=lambda x: chiave_naturale(x.codice))  # fmt: skip
    misure = sorted(await db.scalars(select(AcMisura).where(AcMisura.rischio_id.in_([r.id for r in rischi]))),
                    key=lambda x: chiave_naturale(x.codice))  # fmt: skip
    std = ProcessoStd(
        codice=p.codice, tipo=p.tipo or "PROCESSO", denominazione=p.denominazione, descrizione=p.descrizione,
        tempi=p.tempi, attori_esterni=p.attori_esterni, termine_conclusione=p.termine_conclusione,
        norma_riferimento=p.norma_riferimento,
        attivita=[AttivitaStd(codice=a.codice, descrizione=a.descrizione, rischi=[
            RischioStd(codice=r.codice, evento=r.evento, fattore_abilitante=r.fattore_abilitante, misure=[
                MisuraStd(codice=m.codice, descrizione=m.descrizione, tipo=m.tipo, categoria=m.categoria,
                          obbligo_trasparenza=m.obbligo_trasparenza, fasi=m.fasi, tempi=m.tempi,
                          indicatore=m.indicatore, target=m.target)
                for m in misure if m.rischio_id == r.id])
            for r in rischi if r.attivita_id == a.id])
            for a in attivita],
    )  # fmt: skip
    return p, std, area.codice if area else None


async def crea_aree(db: AsyncSession, ente_id: str, aree: list[AreaStd]) -> list[str]:
    """Aree del pacchetto che l'ente non ha (per codice); quelle esistenti restano come sono."""
    esistenti = set(await db.scalars(select(AcArea.codice).where(AcArea.ente_id == ente_id)))
    nuove = []
    for a in aree:
        if a.codice not in esistenti:
            db.add(AcArea(ente_id=ente_id, **a.model_dump()))
            nuove.append(a.codice)
    await db.flush()
    return nuove


async def metodologia_ente(db: AsyncSession, ente_id: str) -> tuple[AcMetodologia | None, Metodologia]:
    riga = await db.get(AcMetodologia, ente_id)
    return riga, Metodologia.model_validate(riga.dati) if riga else standard()


async def applica_metodologia(db: AsyncSession, ente_id: str, m: Metodologia, pacchetto: str, impronta_std: str) -> None:
    """Metodologia standard nell'ente. Le valutazioni esistenti non si ricalcolano qui: lo fa
    il RPCT salvando la metodologia o rivalutando i rischi."""
    riga = await db.get(AcMetodologia, ente_id)
    if riga is None:
        riga = AcMetodologia(ente_id=ente_id)
        db.add(riga)
    riga.dati = m.model_dump(mode="json")
    riga.impronta = riga.impronta_base = impronta_std
    riga.pacchetto = pacchetto
    await db.flush()


async def applica_processo(
    db: AsyncSession, ente_id: str, std: ProcessoStd, area: str | None, pacchetto: str, impronta_std: str
) -> AcProcesso:
    """Il processo standard nell'ente: nuovo o aggiornato abbinando gli elementi per codice."""
    _, m = await metodologia_ente(db, ente_id)
    area_id = await db.scalar(select(AcArea.id).where(AcArea.ente_id == ente_id, AcArea.codice == area)) if area else None
    p = await db.scalar(select(AcProcesso).where(AcProcesso.ente_id == ente_id, AcProcesso.codice == std.codice))
    if p is None:
        p = AcProcesso(id=nuovo_id(), ente_id=ente_id, codice=std.codice)
        db.add(p)
    p.area_id = area_id
    p.denominazione, p.descrizione, p.tempi, p.attori_esterni = std.denominazione, std.descrizione, std.tempi, std.attori_esterni
    p.tipo, p.termine_conclusione, p.norma_riferimento = std.tipo, std.termine_conclusione, std.norma_riferimento
    p.impronta = p.impronta_base = impronta_std
    p.pacchetto = pacchetto

    attivita = {a.codice: a for a in await db.scalars(select(AcAttivita).where(AcAttivita.processo_id == p.id))}
    rischi = {r.codice: r for r in await db.scalars(
        select(AcRischio).where(AcRischio.attivita_id.in_([a.id for a in attivita.values()])))}  # fmt: skip
    misure = {x.codice: x for x in await db.scalars(
        select(AcMisura).where(AcMisura.rischio_id.in_([r.id for r in rischi.values()])))}  # fmt: skip
    tenute_a = {a.codice for a in std.attivita}
    tenuti_r = {r.codice for a in std.attivita for r in a.rischi}
    tenute_m = {x.codice for a in std.attivita for r in a.rischi for x in r.misure}
    via_a = [a.id for c, a in attivita.items() if c not in tenute_a]
    via_r = [r.id for c, r in rischi.items() if c not in tenuti_r]
    via_m = [x.id for c, x in misure.items() if c not in tenute_m]
    await db.execute(delete(AcMisura).where(AcMisura.id.in_(via_m) | AcMisura.rischio_id.in_(via_r)))
    await db.execute(delete(AcRischio).where(AcRischio.id.in_(via_r)))
    await db.execute(delete(AcAttivita).where(AcAttivita.id.in_(via_a)))

    for a_std in std.attivita:
        a = attivita.get(a_std.codice) or AcAttivita(id=nuovo_id(), ente_id=ente_id, codice=a_std.codice)
        a.processo_id, a.descrizione = p.id, a_std.descrizione
        db.add(a)
        for r_std in a_std.rischi:
            r = rischi.get(r_std.codice)
            if r is None:
                r = AcRischio(id=nuovo_id(), ente_id=ente_id, codice=r_std.codice)
                if r_std.valutazione is not None:  # valutazione proposta, solo per i rischi nuovi
                    try:
                        v = valuta(m, r_std.valutazione.probabilita, r_std.valutazione.impatto)
                    except ValueError:
                        v = None  # indicatori diversi da quelli dell'ente: si valuta a mano
                    if v is not None:
                        r.valori_probabilita, r.valori_impatto = r_std.valutazione.probabilita, r_std.valutazione.impatto
                        r.probabilita_calcolata, r.impatto_calcolato = v.probabilita_calcolata, v.impatto_calcolato
                        r.probabilita, r.impatto, r.livello = v.probabilita, v.impatto, v.livello
            r.attivita_id, r.evento, r.fattore_abilitante = a.id, r_std.evento, r_std.fattore_abilitante
            db.add(r)
            for x_std in r_std.misure:
                x = misure.get(x_std.codice) or AcMisura(id=nuovo_id(), ente_id=ente_id, codice=x_std.codice)
                x.rischio_id = r.id
                for campo, valore in x_std.model_dump(exclude={"codice"}).items():
                    setattr(x, campo, valore)
                db.add(x)
    await db.flush()
    return p


async def esporta(db: AsyncSession, ente_id: str) -> dict[str, str]:
    """Metodologia (se adattata), aree e processi dell'ente come file di pacchetto."""
    file: dict[str, str] = {}
    riga = await db.get(AcMetodologia, ente_id)
    if riga is not None:
        file[FILE_METODOLOGIA] = yaml.safe_dump(riga.dati, allow_unicode=True, sort_keys=False, width=100)
    aree = sorted(await db.scalars(select(AcArea).where(AcArea.ente_id == ente_id)), key=chiave_area)
    if aree:
        file[FILE_AREE] = yaml.safe_dump(
            {"aree": [AreaStd.model_validate(a, from_attributes=True).model_dump(exclude_none=True) for a in aree]},
            allow_unicode=True, sort_keys=False, width=100)  # fmt: skip
    per_area: dict[str | None, list[ProcessoStd]] = {}
    for codice in sorted(await db.scalars(select(AcProcesso.codice).where(AcProcesso.ente_id == ente_id)), key=chiave_naturale):
        _, std, area = await processo_ente(db, ente_id, codice)
        per_area.setdefault(area, []).append(std)
    for area, processi in per_area.items():
        nome = (area or "senza_area").lower()
        file[f"{CARTELLA_PROCESSI}/{nome}.yaml"] = yaml.safe_dump(
            {"area": area, "processi": [p.model_dump(mode="json", exclude_none=True) for p in processi]},
            allow_unicode=True, sort_keys=False, width=100)  # fmt: skip
    return file
