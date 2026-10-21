"""Modelli di atto e checklist definiti nei file del repository, caricati nel database.

All'avvio dell'API (CARICA_CONFIGURAZIONE_ALL_AVVIO) si leggono MODELLI_DIR (*.yaml),
i moduli di regole in MODELLI_DIR/regole (*.yaml) e CHECKLIST_DIR (*.json). I file
comandano: per ogni file si confronta l'impronta SHA-256 con l'ultima versione caricata da
file e, solo se il file è cambiato, si crea una nuova versione attiva e si disattivano le
altre. L'impronta di un modello comprende i moduli di regole che gli si applicano: cambiare
un modulo crea una nuova versione dei modelli che lo usano. Una checklist modificata
dall'app resta attiva finché il suo file non cambia; quando cambia, la versione del file
la sostituisce.

Il caricamento avviene sotto un lock del database (GET_LOCK di MySQL): con più processi
gunicorn o più pod lo esegue uno solo, gli altri trovano tutto già caricato. Un file non
valido viene saltato con un errore nel log, senza bloccare l'avvio.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from common.models import AuditLog, Checklist, ChecklistElemento, ModelloAtto, TipologiaAtto
from common.modelli import ModelloNonValido, ModuloRegole, leggi_modello, leggi_modulo
from common.normattiva import Urn

log = logging.getLogger("common.configurazione")

LOCK = "atti_pa_configurazione"


# --- definizione di una checklist (stesso formato dell'API /checklists) ----------------------


class ElementoIn(BaseModel):
    titolo: str = Field(min_length=1, max_length=255)
    regola: str = Field(min_length=1)
    riferimenti: list[str] = []  # URN di articoli da passare all'LLM come contesto
    obbligatorio: bool = True


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
        )
        for i, e in enumerate(dati)
    ]


def leggi_checklist(sorgente: str) -> ChecklistNuovaIn:
    """Checklist da JSON, con le URN dei riferimenti controllate. Solleva ValueError."""
    try:
        dati = ChecklistNuovaIn.model_validate(json.loads(sorgente))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"Checklist non valida: {e}") from e
    for el in dati.elementi:
        for urn in el.riferimenti:
            if not Urn.parse(urn).articolo:
                raise ValueError(f"{el.titolo}: la URN {urn} non indica l'articolo (~artN)")
    return dati


def impronta(sorgente: str) -> str:
    return hashlib.sha256(sorgente.encode("utf-8")).hexdigest()


@dataclass
class FileModulo:
    nome: str
    sorgente: str
    modulo: ModuloRegole


def leggi_moduli(cartella: Path) -> tuple[list[FileModulo], list[str]]:
    """Moduli di regole della cartella, in ordine di nome; i file non validi sono errori."""
    moduli, errori = [], []
    if not cartella.is_dir():
        return moduli, errori
    for file in sorted(cartella.glob("*.yaml")):
        nome = f"{cartella.parent.name}/{cartella.name}/{file.name}"
        try:
            sorgente = file.read_text(encoding="utf-8")
            moduli.append(FileModulo(nome, sorgente, leggi_modulo(sorgente)))
        except (ModelloNonValido, OSError) as e:
            errori.append(f"{nome}: {e}")
    codici = [m.modulo.codice for m in moduli]
    for codice in sorted({c for c in codici if codici.count(c) > 1}):
        errori.append(f"modulo di regole {codice}: codice usato da più file")
    return moduli, errori


# --- salvataggio ----------------------------------------------------------------------------


async def salva_modello(
    db: AsyncSession,
    sorgente: str,
    file_nome: str | None = None,
    moduli: list[FileModulo] | None = None,
) -> tuple[ModelloAtto | None, str]:
    """Nuova versione del modello se il file o i suoi moduli di regole sono cambiati.
    Restituisce (modello, esito)."""
    modello = leggi_modello(sorgente, [m.modulo for m in moduli or []]).d
    composti = {r.codice for r in modello.regole}
    usati = [m for m in moduli or [] if m.modulo.codice in composti]
    hash_file = impronta("\n".join([sorgente, *(m.sorgente for m in usati)]))
    if await db.get(TipologiaAtto, modello.tipologia_atto) is None:
        raise ValueError(f"tipologia di atto inesistente: {modello.tipologia_atto}")
    ultimo_da_file = await db.scalar(
        select(ModelloAtto)
        .where(ModelloAtto.codice == modello.codice, ModelloAtto.hash_sorgente.is_not(None))
        .order_by(ModelloAtto.versione.desc())
        .limit(1)
    )
    if ultimo_da_file is not None and ultimo_da_file.hash_sorgente == hash_file:
        return ultimo_da_file, "invariato"
    ultima = await db.scalar(
        select(func.max(ModelloAtto.versione)).where(ModelloAtto.codice == modello.codice)
    )
    for vecchio in (
        await db.scalars(select(ModelloAtto).where(ModelloAtto.codice == modello.codice))
    ).all():
        vecchio.attivo = False
    nuovo = ModelloAtto(
        codice=modello.codice,
        versione=(ultima or 0) + 1,
        titolo=modello.titolo,
        provvedimento=modello.provvedimento,
        tipologia_atto=modello.tipologia_atto,
        descrizione=modello.descrizione,
        definizione_json=modello.model_dump(mode="json"),
        sorgente=sorgente,
        hash_sorgente=hash_file,
        file_sorgente=file_nome,
        attivo=True,
    )
    db.add(nuovo)
    await db.flush()
    db.add(
        AuditLog(
            user_id=None,
            entita="modello_atto",
            entita_id=nuovo.id,
            azione="CARICATO_DA_FILE",
            dettaglio={
                "codice": nuovo.codice,
                "versione": nuovo.versione,
                "file": file_nome,
                "regole": [m.nome for m in usati],
            },
        )
    )
    return nuovo, "caricato"


async def salva_checklist(
    db: AsyncSession, dati: ChecklistNuovaIn, hash_file: str, file_nome: str | None = None
) -> tuple[Checklist, str]:
    """Nuova versione della checklist se il file è cambiato. Restituisce (checklist, esito)."""
    if await db.get(TipologiaAtto, dati.tipologia_atto) is None:
        raise ValueError(f"tipologia di atto inesistente: {dati.tipologia_atto}")
    versioni = list(
        (
            await db.scalars(
                select(Checklist)
                .where(Checklist.codice == dati.codice)
                .order_by(Checklist.versione.desc())
            )
        ).all()
    )
    ultima_da_file = next((c for c in versioni if c.hash_sorgente), None)
    if ultima_da_file is not None and ultima_da_file.hash_sorgente == hash_file:
        return ultima_da_file, "invariato"
    superate = [c for c in versioni if c.attiva and not c.hash_sorgente]
    if superate:
        log.warning(
            "Checklist %s: la versione %d modificata dall'app è sostituita da quella del file %s",
            dati.codice,
            superate[0].versione,
            file_nome,
        )
    for c in versioni:
        c.attiva = False
    nuova = Checklist(
        codice=dati.codice,
        versione=(versioni[0].versione if versioni else 0) + 1,
        titolo=dati.titolo,
        tipologia_atto=dati.tipologia_atto,
        modello=dati.modello,
        modulo=dati.modulo,
        descrizione=dati.descrizione,
        attiva=True,
        hash_sorgente=hash_file,
        file_sorgente=file_nome,
        elementi=elementi_checklist(dati.elementi),
    )
    db.add(nuova)
    await db.flush()
    db.add(
        AuditLog(
            user_id=None,
            entita="checklist",
            entita_id=nuova.id,
            azione="CARICATA_DA_FILE",
            dettaglio={"codice": nuova.codice, "versione": nuova.versione, "file": file_nome},
        )
    )
    return nuova, "caricato"


# --- caricamento all'avvio --------------------------------------------------------------------


@dataclass
class Resoconto:
    caricati: list[str] = field(default_factory=list)
    invariati: list[str] = field(default_factory=list)
    errori: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)  # incoerenze tra modelli e checklist

    def __str__(self) -> str:
        return (
            f"{len(self.caricati)} nuove versioni, {len(self.invariati)} invariati, "
            f"{len(self.errori)} errori, {len(self.avvisi)} avvisi"
        )


async def controlla_coerenza(db: AsyncSession) -> list[str]:
    """Ogni tipologia con modelli ha la sua scheda generica, ogni modello e ogni specificità
    la propria; ogni scheda di modello o di specificità rimanda a qualcosa che esiste."""
    modelli = (await db.scalars(select(ModelloAtto).where(ModelloAtto.attivo.is_(True)))).all()
    schede = (await db.scalars(select(Checklist).where(Checklist.attiva.is_(True)))).all()
    generiche = {c.tipologia_atto for c in schede if not c.modello and not c.modulo}
    di_modello = {c.modello for c in schede if c.modello}
    di_modulo = {c.modulo for c in schede if c.modulo}
    specificita = {
        r["codice"] for m in modelli for r in (m.definizione_json or {}).get("regole", [])
    }
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


async def _carica_cartella(
    db: AsyncSession,
    cartella: Path,
    schema: str,
    r: Resoconto,
    moduli: list[FileModulo] | None = None,
) -> None:
    if not cartella.is_dir():
        log.warning("Cartella di configurazione assente: %s", cartella)
        return
    for file in sorted(cartella.glob(schema)):
        nome = f"{cartella.name}/{file.name}"
        try:
            sorgente = file.read_text(encoding="utf-8")
            async with db.begin_nested():  # un file sbagliato non annulla gli altri
                if file.suffix == ".json":
                    dati = leggi_checklist(sorgente)
                    oggetto, esito = await salva_checklist(db, dati, impronta(sorgente), nome)
                else:
                    oggetto, esito = await salva_modello(db, sorgente, nome, moduli)
            (r.caricati if esito == "caricato" else r.invariati).append(
                f"{nome} (v{oggetto.versione})"
            )
            if esito == "caricato":
                log.info("%s caricato: %s versione %d", nome, oggetto.codice, oggetto.versione)
        except (ModelloNonValido, ValueError, OSError) as e:
            r.errori.append(f"{nome}: {e}")
            log.error("Configurazione %s non caricata: %s", nome, e)


async def carica_configurazione(
    engine: AsyncEngine, dir_modelli: Path, dir_checklist: Path
) -> Resoconto:
    """Carica modelli e checklist dai file (solo quelli cambiati), sotto lock.

    Il lock di MySQL appartiene alla connessione: per questo la sessione lavora su una
    connessione dedicata, tenuta dall'acquisizione al rilascio del lock.
    """
    r = Resoconto()
    async with engine.connect() as conn:
        mysql = conn.dialect.name in ("mysql", "mariadb")
        if mysql:
            ottenuto = await conn.scalar(text("SELECT GET_LOCK(:n, 60)"), {"n": LOCK})
            await conn.commit()
            if ottenuto != 1:
                r.errori.append("lock di configurazione non ottenuto in 60 secondi")
                log.error("Caricamento della configurazione saltato: lock non ottenuto")
                return r
        try:
            moduli, errori = leggi_moduli(dir_modelli / "regole")
            for errore in errori:
                r.errori.append(errore)
                log.error("Modulo di regole non caricato: %s", errore)
            async with AsyncSession(bind=conn, expire_on_commit=False) as db:
                await _carica_cartella(db, dir_modelli, "*.yaml", r, moduli)
                await _carica_cartella(db, dir_checklist, "*.json", r)
                await db.commit()
                r.avvisi = await controlla_coerenza(db)
                for avviso in r.avvisi:
                    log.warning("Modelli e checklist non coerenti: %s", avviso)
        finally:
            if mysql:
                await conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK})
                await conn.commit()
    return r
