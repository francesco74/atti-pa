"""Contenuti standard del modulo anticorruzione nei pacchetti (common/pacchetti.py):

    anticorruzione/metodologia.yaml       metodologia di valutazione del rischio
    anticorruzione/aree.yaml              aree di rischio (create se mancano, mai cancellate)
    anticorruzione/catalogo.yaml          voci standard di attività, rischi e misure (create se
                                          mancano, mai cancellate: common/anticorruzione/catalogo.py)
    anticorruzione/procedimenti.yaml      procedimenti standard (codici PRC-0001...): creati se
                                          mancano, con il codice P.n dell'ente, mai cancellati
    anticorruzione/processi/*.yaml        processi standard, un file per area

Un'attività di un processo standard nasce da una voce del catalogo oppure è un procedimento
standard (`procedimento: PRC-0012`), come nella mappatura dell'ente. Un processo può valere
solo per i comuni o solo per le province (`ambito`): l'importazione lo segnala e l'ente sceglie.

Un processo standard porta attività, rischi (con una valutazione proposta) e misure. Il
confronto a tre vie usa l'impronta del contenuto standard: codici e testi di processo,
attività, rischi e misure. Restano fuori, perché sono scelte dell'ente, le strutture
responsabili e le valutazioni: la valutazione proposta entra solo nei rischi nuovi.
Applicando un aggiornamento gli elementi si abbinano per codice: quelli con lo stesso codice
si aggiornano (conservano i monitoraggi), i nuovi si aggiungono e
quelli tolti dallo standard si eliminano. Gli elementi nuovi si collegano alla voce del
catalogo con lo stesso testo (o a una nuova dell'ente).
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import re

from common.anticorruzione.art35 import DatiArt35
from common.anticorruzione.catalogo import Catalogo, normalizza
from common.anticorruzione.metodologia import Metodologia, chiave_area, chiave_naturale, standard, valuta
from common.configurazione import impronta
from common.models import (
    AcArea, AcAttivita, AcContatore, AcMetodologia, AcMisura, AcProcedimento, AcProcesso, AcRischio, AcVoce,
    nuovo_id,
)  # fmt: skip

CARTELLA = "anticorruzione"
FILE_METODOLOGIA = f"{CARTELLA}/metodologia.yaml"
FILE_AREE = f"{CARTELLA}/aree.yaml"
FILE_PROCEDIMENTI = f"{CARTELLA}/procedimenti.yaml"
CARTELLA_PROCESSI = f"{CARTELLA}/processi"


class AreaStd(BaseModel):
    codice: str = Field(min_length=1, max_length=20)
    descrizione: str = Field(min_length=1, max_length=500)
    descrizione_breve: str | None = Field(default=None, max_length=255)


class ValutazioneStd(BaseModel):
    """Valutazione proposta: valori degli indicatori della metodologia standard."""

    probabilita: dict[str, str]
    impatto: dict[str, str]


# `voce`: codice della voce del catalogo, solo quando il testo dell'elemento è diverso da quello
# della voce (variante riunita nella stessa radice); senza, la voce è quella con lo stesso testo.


class MisuraStd(BaseModel):
    codice: str = Field(min_length=1, max_length=70)
    descrizione: str = Field(min_length=1)
    voce: str | None = Field(default=None, max_length=20)
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
    voce: str | None = Field(default=None, max_length=20)
    fattore_abilitante: str | None = None
    valutazione: ValutazioneStd | None = None
    misure: list[MisuraStd] = []


class AttivitaStd(BaseModel):
    codice: str = Field(min_length=1, max_length=50)
    descrizione: str = Field(min_length=1)
    voce: str | None = Field(default=None, max_length=20)
    procedimento: str | None = Field(default=None, max_length=20)  # procedimento standard (PRC-...), invece della voce
    rischi: list[RischioStd] = []


Ambito = Literal["COMUNE", "PROVINCIA"]
AMBITI = {"COMUNE": "solo comuni", "PROVINCIA": "solo province e città metropolitane"}


class ProcessoStd(BaseModel):
    codice: str = Field(min_length=1, max_length=50)
    # enti a cui serve (assente: a tutti); non entra nell'impronta, non è un dato dell'ente
    ambito: Ambito | None = None
    denominazione: str = Field(min_length=1, max_length=500)
    descrizione: str | None = None
    tempi: str | None = None
    attori_esterni: str | None = None
    attivita: list[AttivitaStd] = []


class ProcedimentoStd(BaseModel):
    """Procedimento standard: i dati che vengono dalla norma (uffici e recapiti li mette l'ente)."""

    codice: str = Field(pattern=r"^PRC-\d{4}$")
    ambito: Ambito | None = None
    denominazione: str = Field(min_length=1, max_length=500)
    descrizione: str | None = None
    norma_riferimento: str | None = None
    termine_conclusione: str | None = Field(default=None, max_length=255)
    art35: DatiArt35 | None = None


class FileProcedimenti(BaseModel):
    procedimenti: list[ProcedimentoStd]


def leggi_procedimenti(sorgente: str) -> list[ProcedimentoStd]:
    f = FileProcedimenti.model_validate(yaml.safe_load(sorgente) or {})
    codici = [p.codice for p in f.procedimenti]
    ripetuti = sorted({c for c in codici if codici.count(c) > 1})
    if ripetuti:
        raise ValueError(f"codici ripetuti: {', '.join(ripetuti)}")
    for p in f.procedimenti:
        if p.art35 is not None and any(getattr(p.art35, k) for k in ("uff_resp_struttura_id", "uff_finale_struttura_id",
                                                                      "ist_struttura_id", "sost_struttura_id")):  # fmt: skip
            raise ValueError(f"{p.codice}: gli uffici sono dell'ente, non del pacchetto")
    return f.procedimenti


async def crea_procedimenti(db: AsyncSession, ente_id: str, procedimenti: list[ProcedimentoStd], pacchetto: str) -> list[str]:
    """I procedimenti standard che l'ente non ha (per codice standard), con il codice P.n
    successivo; quelli che ha restano com'è (li ha potuti adattare)."""
    presenti = set(await db.scalars(select(AcProcedimento.standard).where(
        AcProcedimento.ente_id == ente_id, AcProcedimento.standard.is_not(None))))  # fmt: skip
    nuovi = [p for p in procedimenti if p.codice not in presenti]
    if not nuovi:
        return []
    contatore = await db.get(AcContatore, (ente_id, "P."))
    usati = [int(m.group(1)) for c in await db.scalars(select(AcProcedimento.codice).where(AcProcedimento.ente_id == ente_id))
             if (m := re.fullmatch(r"P\.(\d+)", c or ""))]  # fmt: skip
    n = max([contatore.ultimo if contatore else 0, *usati])
    for p in nuovi:
        n += 1
        db.add(AcProcedimento(
            id=nuovo_id(), ente_id=ente_id, codice=f"P.{n}", standard=p.codice, pacchetto=pacchetto,
            denominazione=p.denominazione, descrizione=p.descrizione, norma_riferimento=p.norma_riferimento,
            termine_conclusione=p.termine_conclusione,
            art35=p.art35.model_dump(exclude_none=True) or None if p.art35 is not None else None,
        ))  # fmt: skip
    if contatore is None:
        db.add(AcContatore(ente_id=ente_id, prefisso="P.", ultimo=n))
    else:
        contatore.ultimo = n
    await db.flush()
    return [p.codice for p in nuovi]


class FileProcessi(BaseModel):
    area: str | None = None  # codice dell'area di rischio dei processi del file
    processi: list[ProcessoStd]


def impronta_processo(p: ProcessoStd, area: str | None) -> str:
    """Impronta del contenuto standard (senza valutazioni, che sono dell'ente)."""
    dati = p.model_dump(mode="json", exclude={"ambito": True, "attivita": {"__all__": {"rischi": {"__all__": {"valutazione"}}}}})
    # la voce del catalogo entra solo se indicata: i processi senza mantengono l'impronta di prima
    for a in dati.get("attivita", []):
        for el in [a, *a.get("rischi", []), *(m for r in a.get("rischi", []) for m in r.get("misure", []))]:
            if el.get("voce") is None:
                el.pop("voce", None)
        if a.get("procedimento") is None:
            a.pop("procedimento", None)
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
        for a in p.attivita:
            if a.voce and a.procedimento:
                raise ValueError(f"{a.codice}: l'attività viene da una voce oppure è un procedimento, non entrambi")
    return f


def sorgente_processo(p: ProcessoStd, area: str | None) -> str:
    """Un processo come file a sé (sorgente dell'oggetto del pacchetto)."""
    dati = p.model_dump(mode="json", exclude_none=True)
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
    ids_voci = {x.voce_id for x in [*attivita, *rischi, *misure] if x.voce_id}
    voci = {v.id: v for v in await db.scalars(select(AcVoce).where(AcVoce.id.in_(ids_voci)))} if ids_voci else {}
    ids_proc = {a.procedimento_id for a in attivita if a.procedimento_id}
    standard = dict((await db.execute(select(AcProcedimento.id, AcProcedimento.standard).where(
        AcProcedimento.id.in_(ids_proc)))).all()) if ids_proc else {}  # fmt: skip

    def voce(el, testo: str) -> str | None:
        """Il codice della voce, se il testo dell'elemento è diverso dal suo."""
        v = voci.get(el.voce_id)
        return v.codice if v is not None and normalizza(v.descrizione) != normalizza(testo) else None

    std = ProcessoStd(
        codice=p.codice, denominazione=p.denominazione, descrizione=p.descrizione,
        tempi=p.tempi, attori_esterni=p.attori_esterni,
        attivita=[AttivitaStd(codice=a.codice, descrizione=a.descrizione, voce=voce(a, a.descrizione),
                              procedimento=standard.get(a.procedimento_id), rischi=[
            RischioStd(codice=r.codice, evento=r.evento, voce=voce(r, r.evento), fattore_abilitante=r.fattore_abilitante, misure=[
                MisuraStd(codice=m.codice, descrizione=m.descrizione, voce=voce(m, m.descrizione), tipo=m.tipo, categoria=m.categoria,
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

    catalogo = Catalogo(db, ente_id)
    for a_std in std.attivita:
        a = attivita.get(a_std.codice) or AcAttivita(id=nuovo_id(), ente_id=ente_id, codice=a_std.codice)
        a.processo_id, a.descrizione = p.id, a_std.descrizione
        proc = await db.scalar(select(AcProcedimento.id).where(
            AcProcedimento.ente_id == ente_id, AcProcedimento.standard == a_std.procedimento)) if a_std.procedimento else None  # fmt: skip
        if proc is not None:  # l'attività è il procedimento standard (l'adattamento dell'ente resta)
            if a.procedimento_id != proc:
                a.procedimento_adattato = None
            a.procedimento_id, a.voce_id = proc, None
        else:
            a.procedimento_id = a.procedimento_adattato = None
            await catalogo.collega("ATTIVITA", a, a_std.voce)
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
            await catalogo.collega("RISCHIO", r, r_std.voce)
            db.add(r)
            for x_std in r_std.misure:
                x = misure.get(x_std.codice) or AcMisura(id=nuovo_id(), ente_id=ente_id, codice=x_std.codice)
                x.rischio_id = r.id
                for campo, valore in x_std.model_dump(exclude={"codice", "voce"}).items():
                    setattr(x, campo, valore)
                await catalogo.collega("MISURA", x, x_std.voce)
                db.add(x)
    await db.flush()
    return p


async def esporta(db: AsyncSession, ente_id: str) -> dict[str, str]:
    """Metodologia (se adattata), aree, procedimenti standard e processi dell'ente come file di pacchetto."""
    file: dict[str, str] = {}
    riga = await db.get(AcMetodologia, ente_id)
    if riga is not None:
        file[FILE_METODOLOGIA] = yaml.safe_dump(riga.dati, allow_unicode=True, sort_keys=False, width=100)
    aree = sorted(await db.scalars(select(AcArea).where(AcArea.ente_id == ente_id)), key=chiave_area)
    if aree:
        file[FILE_AREE] = yaml.safe_dump(
            {"aree": [AreaStd.model_validate(a, from_attributes=True).model_dump(exclude_none=True) for a in aree]},
            allow_unicode=True, sort_keys=False, width=100)  # fmt: skip
    # i procedimenti venuti dal pacchetto, con il loro codice standard (le attività lo indicano)
    procedimenti = [p for p in await db.scalars(select(AcProcedimento).where(
        AcProcedimento.ente_id == ente_id, AcProcedimento.standard.is_not(None))) if re.fullmatch(r"PRC-\d{4}", p.standard)]  # fmt: skip
    if procedimenti:
        file[FILE_PROCEDIMENTI] = yaml.safe_dump({"procedimenti": [ProcedimentoStd(
            codice=p.standard, denominazione=p.denominazione, descrizione=p.descrizione, norma_riferimento=p.norma_riferimento,
            termine_conclusione=p.termine_conclusione,
            art35=DatiArt35.model_validate({k: v for k, v in (p.art35 or {}).items() if not k.endswith("struttura_id")}),
        ).model_dump(mode="json", exclude_none=True) for p in sorted(procedimenti, key=lambda p: p.standard)]},
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
