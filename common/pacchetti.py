"""Pacchetti di modelli di atto, specificità e checklist: il database comanda.

L'ente modifica nell'app modelli, specificità (moduli di regole) e checklist. I contenuti
standard forniti dall'azienda arrivano come pacchetti: una cartella o uno zip con

    pacchetto.yaml          manifesto: nome, versione, descrizione, tipologie di atto
    modelli/*.yaml          modelli di atto
    modelli/regole/*.yaml   specificità
    checklist/*.json        schede di controllo

Al primo avvio, con il database vuoto, l'API importa il pacchetto incluso
nell'installazione (deploy/). Poi nessun file sovrascrive più nulla: i pacchetti successivi
si importano da Amministrazione dopo un'analisi che, per ogni oggetto, confronta tre
versioni con le impronte del contenuto:

    base     lo standard da cui deriva la versione dell'ente (impronta_base)
    ente     la versione attiva nel database (impronta)
    nuovo    lo standard del pacchetto

    base == nuovo            INVARIATO      lo standard non è cambiato: nulla da fare
    ente == nuovo            ALLINEATO      l'ente ha già il nuovo contenuto
    ente == base             AGGIORNABILE   l'ente non l'ha modificato: si aggiorna
    altrimenti               CONFLITTO      modificato da entrambi: decide l'ente
    non c'è nel database     NUOVO          si aggiunge
    l'ente l'ha disattivato  DISATTIVATO    resta disattivato, salvo scelta diversa
    tolto dallo standard     RIMOSSO        resta, salvo scelta di disattivarlo

Ogni aggiornamento crea una nuova versione: le bozze e le verifiche restano legate a
quella usata. Le specificità si compongono nei modelli: quando cambiano, i modelli che le
usano ricevono una nuova versione (ricomponi_modelli).
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import undefer

from common.configurazione import (
    ChecklistNuovaIn,
    checklist_in,
    controlla_coerenza,
    elementi_checklist,
    impronta,
    impronta_checklist,
    leggi_checklist,
    sorgente_checklist,
)
from common.models import (
    AuditLog,
    Checklist,
    ModelloAtto,
    ModuloDiRegole,
    PacchettoImportato,
    TipologiaAtto,
)
from common.modelli import (
    Modello,
    ModelloNonValido,
    ModuloRegole,
    componi,
    leggi_modello,
    leggi_modulo,
)

log = logging.getLogger("common.pacchetti")

MANIFESTO = "pacchetto.yaml"
LOCK = "atti_pa_configurazione"
MAX_FILE_ZIP = 500  # file in un pacchetto
MAX_BYTE_ZIP = 20 * 1024 * 1024  # contenuto decompresso

Tipo = Literal["modulo", "modello", "checklist"]
ORDINE_TIPI: tuple[Tipo, ...] = ("modulo", "modello", "checklist")


class PacchettoNonValido(ValueError):
    def __init__(self, errori: list[str]):
        self.errori = errori
        super().__init__("Pacchetto non valido:\n- " + "\n- ".join(errori))


# --- lettura -------------------------------------------------------------------------------


class TipologiaIn(BaseModel):
    codice: str = Field(min_length=1, max_length=50)
    descrizione: str
    ordine: int = 0


class Manifesto(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    versione: str = Field(min_length=1, max_length=50)
    descrizione: str | None = None
    tipologie: list[TipologiaIn] = []

    @property
    def etichetta(self) -> str:
        return f"{self.nome} {self.versione}"


@dataclass
class Oggetto:
    """Modello, specificità o checklist di un pacchetto."""

    tipo: Tipo
    codice: str
    titolo: str
    percorso: str
    sorgente: str
    impronta: str

    @property
    def chiave(self) -> str:
        return f"{self.tipo}:{self.codice}"


@dataclass
class Pacchetto:
    manifesto: Manifesto
    oggetti: list[Oggetto]

    def di_tipo(self, tipo: Tipo) -> list[Oggetto]:
        return [o for o in self.oggetti if o.tipo == tipo]


def impronta_modello(definizione: Modello) -> str:
    return impronta(definizione.model_dump(mode="json"))


def impronta_modulo(definizione: ModuloRegole) -> str:
    return impronta(definizione.model_dump(mode="json"))


def _modello_base(sorgente: str) -> Modello:
    """Il modello senza specificità. Solleva ModelloNonValido."""
    return leggi_modello(sorgente).d


def leggi_pacchetto(file: dict[str, str]) -> Pacchetto:
    """Pacchetto da {percorso: testo}: manifesto, modelli, specificità e checklist, tutti
    controllati; i modelli sono controllati anche composti con le specificità del pacchetto.
    Solleva PacchettoNonValido con l'elenco degli errori."""
    errori: list[str] = []
    if MANIFESTO not in file:
        raise PacchettoNonValido([f"manca il manifesto {MANIFESTO}"])
    try:
        manifesto = Manifesto.model_validate(yaml.safe_load(file[MANIFESTO]) or {})
    except (yaml.YAMLError, ValidationError) as e:
        raise PacchettoNonValido([f"{MANIFESTO}: {e}"]) from e
    oggetti: list[Oggetto] = []
    moduli: list[ModuloRegole] = []
    for percorso in sorted(file):
        p = PurePosixPath(percorso)
        sorgente = file[percorso]
        try:
            if p.parent == PurePosixPath("modelli/regole") and p.suffix == ".yaml":
                d = leggi_modulo(sorgente)
                moduli.append(d)
                oggetti.append(
                    Oggetto("modulo", d.codice, d.etichetta, percorso, sorgente, impronta_modulo(d))
                )
            elif p.parent == PurePosixPath("modelli") and p.suffix == ".yaml":
                d = _modello_base(sorgente)
                oggetti.append(
                    Oggetto("modello", d.codice, d.titolo, percorso, sorgente, impronta_modello(d))
                )
            elif p.parent == PurePosixPath("checklist") and p.suffix == ".json":
                d = leggi_checklist(sorgente)
                oggetti.append(
                    Oggetto(
                        "checklist", d.codice, d.titolo, percorso, sorgente, impronta_checklist(d)
                    )
                )
        except (ModelloNonValido, ValueError) as e:
            errori.append(f"{percorso}: {e}")
    for tipo in ORDINE_TIPI:
        codici = [o.codice for o in oggetti if o.tipo == tipo]
        for codice in sorted({c for c in codici if codici.count(c) > 1}):
            errori.append(f"{tipo} {codice}: codice usato da più file")
    for o in oggetti:  # i modelli composti con le specificità del pacchetto
        if o.tipo == "modello":
            try:
                leggi_modello(o.sorgente, moduli)
            except ModelloNonValido as e:
                errori.append(f"{o.percorso} con le specificità: {e}")
    if errori:
        raise PacchettoNonValido(errori)
    return Pacchetto(manifesto, oggetti)


def da_cartella(cartella: Path) -> dict[str, str]:
    """I file di un pacchetto in una cartella (es. deploy/)."""
    file: dict[str, str] = {}
    candidati = [
        cartella / MANIFESTO,
        *sorted((cartella / "modelli").glob("*.yaml")),
        *sorted((cartella / "modelli" / "regole").glob("*.yaml")),
        *sorted((cartella / "checklist").glob("*.json")),
    ]
    for f in candidati:
        if f.is_file():
            file[f.relative_to(cartella).as_posix()] = f.read_text(encoding="utf-8")
    return file


def da_zip(dati: bytes) -> dict[str, str]:
    """I file di un pacchetto zip; si accettano solo i percorsi previsti (con o senza una
    cartella iniziale comune). Solleva PacchettoNonValido."""
    try:
        archivio = zipfile.ZipFile(io.BytesIO(dati))
    except zipfile.BadZipFile as e:
        raise PacchettoNonValido(["il file non è uno zip valido"]) from e
    voci = [i for i in archivio.infolist() if not i.is_dir()]
    if len(voci) > MAX_FILE_ZIP or sum(i.file_size for i in voci) > MAX_BYTE_ZIP:
        raise PacchettoNonValido(["il pacchetto è troppo grande"])
    nomi = [i.filename for i in voci]
    radice = ""
    if MANIFESTO not in nomi:  # pacchetto con una cartella iniziale (es. modelli-2026.2/)
        manifesti = [n for n in nomi if PurePosixPath(n).name == MANIFESTO]
        if len(manifesti) == 1:
            radice = str(PurePosixPath(manifesti[0]).parent) + "/"
    file: dict[str, str] = {}
    for info in voci:
        nome = info.filename
        if not nome.startswith(radice):
            continue
        relativo = nome[len(radice) :]
        p = PurePosixPath(relativo)
        if ".." in p.parts or p.is_absolute():
            continue
        if relativo == MANIFESTO or (
            str(p.parent) in ("modelli", "modelli/regole", "checklist")
            and p.suffix in (".yaml", ".json")
        ):
            try:
                file[relativo] = archivio.read(info).decode("utf-8")
            except UnicodeDecodeError as e:
                raise PacchettoNonValido([f"{relativo}: non è un testo UTF-8"]) from e
    return file


def in_zip(file: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archivio:
        for percorso in sorted(file):
            archivio.writestr(percorso, file[percorso])
    return buffer.getvalue()


# --- versioni nel database ------------------------------------------------------------------


@dataclass
class Base:
    """Standard di riferimento di una versione: da quale pacchetto viene e il suo contenuto."""

    pacchetto: str | None
    impronta: str | None
    sorgente: str | None


MANTIENI_BASE = None  # nuova versione dell'ente: si conserva lo standard di riferimento


def _classe(tipo: Tipo):
    return {"modulo": ModuloDiRegole, "modello": ModelloAtto, "checklist": Checklist}[tipo]


def _attivo(classe):
    return classe.attiva if classe is Checklist else classe.attivo


async def versione_attiva(db: AsyncSession, tipo: Tipo, codice: str):
    classe = _classe(tipo)
    return await db.scalar(
        select(classe)
        .where(classe.codice == codice, _attivo(classe).is_(True))
        .options(undefer(classe.base_sorgente))
        .order_by(classe.versione.desc())
        .limit(1)
    )


async def _ultima(db: AsyncSession, tipo: Tipo, codice: str):
    classe = _classe(tipo)
    return await db.scalar(
        select(classe)
        .where(classe.codice == codice)
        .options(undefer(classe.base_sorgente))
        .order_by(classe.versione.desc())
        .limit(1)
    )


async def _nuova_versione(db: AsyncSession, tipo: Tipo, codice: str) -> int:
    classe = _classe(tipo)
    for vecchia in (await db.scalars(select(classe).where(classe.codice == codice))).all():
        if classe is Checklist:
            vecchia.attiva = False
        else:
            vecchia.attivo = False
    ultima = await db.scalar(select(func.max(classe.versione)).where(classe.codice == codice))
    return (ultima or 0) + 1


async def _base(db: AsyncSession, tipo: Tipo, codice: str, base: Base | None) -> Base:
    if base is not MANTIENI_BASE:
        return base
    precedente = await _ultima(db, tipo, codice)
    if precedente is None:
        return Base(None, None, None)
    return Base(precedente.pacchetto, precedente.impronta_base, precedente.base_sorgente)


def _audit(db: AsyncSession, utente_id: str | None, entita: str, oggetto, azione: str, **altro):
    db.add(
        AuditLog(
            user_id=utente_id,
            entita=entita,
            entita_id=oggetto.id,
            azione=azione,
            dettaglio={"codice": oggetto.codice, "versione": oggetto.versione, **altro},
        )
    )


async def moduli_attivi(db: AsyncSession) -> dict[str, tuple[ModuloRegole, str]]:
    """Specificità attive: {codice: (definizione, impronta)}."""
    righe = (
        await db.scalars(select(ModuloDiRegole).where(ModuloDiRegole.attivo.is_(True)))
    ).all()
    return {
        r.codice: (ModuloRegole.model_validate(r.definizione_json), r.impronta or "")
        for r in righe
    }


async def salva_modulo(
    db: AsyncSession, sorgente: str, base: Base | None, utente_id: str | None = None
) -> ModuloDiRegole:
    """Nuova versione di una specificità. Dopo, ricomporre i modelli (ricomponi_modelli)."""
    d = leggi_modulo(sorgente)
    base = await _base(db, "modulo", d.codice, base)
    nuovo = ModuloDiRegole(
        codice=d.codice,
        versione=await _nuova_versione(db, "modulo", d.codice),
        etichetta=d.etichetta,
        definizione_json=d.model_dump(mode="json"),
        sorgente=sorgente,
        impronta=impronta_modulo(d),
        pacchetto=base.pacchetto,
        impronta_base=base.impronta,
        base_sorgente=base.sorgente,
        attivo=True,
    )
    db.add(nuovo)
    await db.flush()
    _audit(db, utente_id, "modulo_regole", nuovo, "NUOVA_VERSIONE", pacchetto=base.pacchetto)
    return nuovo


async def salva_modello(
    db: AsyncSession, sorgente: str, base: Base | None, utente_id: str | None = None
) -> ModelloAtto:
    """Nuova versione di un modello, composta con le specificità attive."""
    d = _modello_base(sorgente)
    if await db.get(TipologiaAtto, d.tipologia_atto) is None:
        raise ValueError(f"tipologia di atto inesistente: {d.tipologia_atto}")
    moduli = await moduli_attivi(db)
    composto = leggi_modello(sorgente, [m for m, _ in moduli.values()]).d
    base = await _base(db, "modello", d.codice, base)
    nuovo = ModelloAtto(
        codice=d.codice,
        versione=await _nuova_versione(db, "modello", d.codice),
        titolo=d.titolo,
        provvedimento=d.provvedimento,
        tipologia_atto=d.tipologia_atto,
        descrizione=d.descrizione,
        definizione_json=composto.model_dump(mode="json"),
        sorgente=sorgente,
        moduli_json={r.codice: moduli[r.codice][1] for r in composto.regole},
        impronta=impronta_modello(d),
        pacchetto=base.pacchetto,
        impronta_base=base.impronta,
        base_sorgente=base.sorgente,
        attivo=True,
    )
    db.add(nuovo)
    await db.flush()
    _audit(db, utente_id, "modello_atto", nuovo, "NUOVA_VERSIONE", pacchetto=base.pacchetto)
    return nuovo


async def salva_checklist(
    db: AsyncSession, dati: ChecklistNuovaIn, base: Base | None, utente_id: str | None = None
) -> Checklist:
    """Nuova versione di una checklist (anche quelle modificate dall'app)."""
    if await db.get(TipologiaAtto, dati.tipologia_atto) is None:
        raise ValueError(f"tipologia di atto inesistente: {dati.tipologia_atto}")
    base = await _base(db, "checklist", dati.codice, base)
    nuova = Checklist(
        codice=dati.codice,
        versione=await _nuova_versione(db, "checklist", dati.codice),
        titolo=dati.titolo,
        tipologia_atto=dati.tipologia_atto,
        modello=dati.modello,
        modulo=dati.modulo,
        descrizione=dati.descrizione,
        attiva=True,
        impronta=impronta_checklist(dati),
        pacchetto=base.pacchetto,
        impronta_base=base.impronta,
        base_sorgente=base.sorgente,
        elementi=elementi_checklist(dati.elementi),
    )
    db.add(nuova)
    await db.flush()
    _audit(db, utente_id, "checklist", nuova, "NUOVA_VERSIONE", pacchetto=base.pacchetto)
    return nuova


async def ricomponi_modelli(db: AsyncSession, utente_id: str | None = None) -> list[str]:
    """Nuova versione dei modelli attivi le cui specificità sono cambiate (aggiunte, tolte
    o modificate). Restituisce gli errori: un modello che non si compone resta com'è."""
    moduli = await moduli_attivi(db)
    errori = []
    modelli = (
        await db.scalars(
            select(ModelloAtto)
            .where(ModelloAtto.attivo.is_(True))
            .options(undefer(ModelloAtto.sorgente), undefer(ModelloAtto.base_sorgente))
        )
    ).all()
    for m in modelli:
        try:
            composto = leggi_modello(m.sorgente, [d for d, _ in moduli.values()]).d
        except ModelloNonValido as e:
            errori.append(f"modello {m.codice}: {e}")
            log.error("Modello %s non ricomposto: %s", m.codice, e)
            continue
        usati = {r.codice: moduli[r.codice][1] for r in composto.regole}
        if usati == (m.moduli_json or {}):
            continue
        await salva_modello(
            db, m.sorgente, Base(m.pacchetto, m.impronta_base, m.base_sorgente), utente_id
        )
    return errori


# --- analisi e importazione ------------------------------------------------------------------

Stato = Literal[
    "NUOVO", "AGGIORNABILE", "INVARIATO", "ALLINEATO", "CONFLITTO", "DISATTIVATO", "RIMOSSO"
]
Azione = Literal["applica", "mantieni", "disattiva"]


@dataclass
class Voce:
    chiave: str
    tipo: Tipo
    codice: str
    titolo: str
    stato: Stato
    azione: Azione  # proposta
    azioni: list[Azione] = field(default_factory=list)  # ammesse
    nota: str = ""
    versione_ente: int | None = None

    def come_dict(self) -> dict:
        return asdict(self)


_NOTE: dict[Stato, str] = {
    "NUOVO": "Non presente nell'ente: si aggiunge.",
    "AGGIORNABILE": "L'ente non l'ha modificato: si aggiorna al nuovo standard.",
    "INVARIATO": "Lo standard non è cambiato.",
    "ALLINEATO": "L'ente ha già il contenuto del nuovo standard.",
    "CONFLITTO": (
        "Modificato sia dall'ente sia nello standard: si mantiene la versione dell'ente, "
        "salvo scelta di sostituirla con quella standard."
    ),
    "DISATTIVATO": "L'ente l'ha disattivato: resta disattivato, salvo scelta di riattivarlo.",
    "RIMOSSO": "Tolto dallo standard: resta nell'ente, salvo scelta di disattivarlo.",
}


def _voce(o, stato: Stato, azione: Azione, azioni: list[Azione], versione=None) -> Voce:
    return Voce(
        chiave=f"{o.tipo}:{o.codice}",
        tipo=o.tipo,
        codice=o.codice,
        titolo=o.titolo,
        stato=stato,
        azione=azione,
        azioni=azioni,
        nota=_NOTE[stato],
        versione_ente=versione,
    )


async def analizza(db: AsyncSession, pacchetto: Pacchetto) -> list[Voce]:
    """Cosa succede importando il pacchetto, oggetto per oggetto (confronto a tre vie)."""
    voci: list[Voce] = []
    for tipo in ORDINE_TIPI:
        nel_pacchetto = {o.codice for o in pacchetto.di_tipo(tipo)}
        for o in pacchetto.di_tipo(tipo):
            attivo = await versione_attiva(db, tipo, o.codice)
            if attivo is None:
                if await _ultima(db, tipo, o.codice) is not None:
                    voci.append(_voce(o, "DISATTIVATO", "mantieni", ["mantieni", "applica"]))
                else:
                    voci.append(_voce(o, "NUOVO", "applica", ["applica", "mantieni"]))
                continue
            ente, base, nuovo = attivo.impronta, attivo.impronta_base, o.impronta
            v = attivo.versione
            if base == nuovo:
                voci.append(_voce(o, "INVARIATO", "mantieni", ["mantieni", "applica"], v))
            elif ente == nuovo:
                voci.append(_voce(o, "ALLINEATO", "mantieni", ["mantieni"], v))
            elif base is not None and ente == base:
                voci.append(_voce(o, "AGGIORNABILE", "applica", ["applica", "mantieni"], v))
            else:
                voci.append(_voce(o, "CONFLITTO", "mantieni", ["mantieni", "applica"], v))
        # oggetti venuti da un pacchetto e non più nello standard
        classe = _classe(tipo)
        dal_pacchetto = (
            await db.scalars(
                select(classe).where(_attivo(classe).is_(True), classe.pacchetto.is_not(None))
            )
        ).all()
        for r in dal_pacchetto:
            if r.codice not in nel_pacchetto:
                titolo = getattr(r, "titolo", None) or getattr(r, "etichetta", r.codice)
                fittizio = Oggetto(tipo, r.codice, titolo, "", "", "")
                voci.append(
                    _voce(fittizio, "RIMOSSO", "mantieni", ["mantieni", "disattiva"], r.versione)
                )
    return voci


@dataclass
class Resoconto:
    pacchetto: str = ""
    applicati: list[str] = field(default_factory=list)
    mantenuti: list[str] = field(default_factory=list)
    disattivati: list[str] = field(default_factory=list)
    errori: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)  # incoerenze tra modelli e checklist

    def __str__(self) -> str:
        return (
            f"{self.pacchetto}: {len(self.applicati)} applicati, {len(self.mantenuti)} "
            f"mantenuti, {len(self.disattivati)} disattivati, {len(self.errori)} errori, "
            f"{len(self.avvisi)} avvisi"
        )

    def come_dict(self) -> dict:
        return asdict(self)


async def _tipologie(db: AsyncSession, manifesto: Manifesto) -> None:
    for t in manifesto.tipologie:
        if await db.get(TipologiaAtto, t.codice) is None:
            db.add(TipologiaAtto(codice=t.codice, descrizione=t.descrizione, ordine=t.ordine))
    await db.flush()


async def importa(
    db: AsyncSession,
    pacchetto: Pacchetto,
    decisioni: dict[str, str] | None = None,
    utente_id: str | None = None,
) -> Resoconto:
    """Importa il pacchetto con le decisioni dell'ente ({chiave: azione}); per le voci senza
    decisione vale l'azione proposta dall'analisi. Non fa il commit."""
    decisioni = decisioni or {}
    r = Resoconto(pacchetto=pacchetto.manifesto.etichetta)
    await _tipologie(db, pacchetto.manifesto)
    oggetti = {o.chiave: o for o in pacchetto.oggetti}
    for voce in await analizza(db, pacchetto):
        azione = decisioni.get(voce.chiave, voce.azione)
        if azione not in voce.azioni:
            r.errori.append(f"{voce.chiave}: azione {azione!r} non ammessa ({voce.stato})")
            continue
        o = oggetti.get(voce.chiave)
        if azione == "disattiva":
            attivo = await versione_attiva(db, voce.tipo, voce.codice)
            if attivo is not None:
                if voce.tipo == "checklist":
                    attivo.attiva = False
                else:
                    attivo.attivo = False
            r.disattivati.append(voce.chiave)
            continue
        base = Base(pacchetto.manifesto.etichetta, o.impronta, o.sorgente) if o else None
        if azione == "applica":
            try:
                async with db.begin_nested():  # un oggetto sbagliato non blocca gli altri
                    if voce.tipo == "modulo":
                        await salva_modulo(db, o.sorgente, base, utente_id)
                    elif voce.tipo == "modello":
                        await salva_modello(db, o.sorgente, base, utente_id)
                    else:
                        await salva_checklist(db, leggi_checklist(o.sorgente), base, utente_id)
                r.applicati.append(voce.chiave)
            except (ModelloNonValido, ValueError) as e:
                r.errori.append(f"{voce.chiave}: {e}")
            continue
        # mantieni: la versione dell'ente resta; se lo standard è cambiato, il nuovo diventa
        # il riferimento (le prossime analisi confrontano con questo)
        r.mantenuti.append(voce.chiave)
        if o is not None and voce.stato in ("AGGIORNABILE", "ALLINEATO", "CONFLITTO"):
            attivo = await versione_attiva(db, voce.tipo, voce.codice)
            attivo.pacchetto, attivo.impronta_base = base.pacchetto, base.impronta
            attivo.base_sorgente = base.sorgente
    if any(c.startswith("modulo:") for c in r.applicati + r.disattivati):
        r.errori += await ricomponi_modelli(db, utente_id)
    await db.flush()
    r.avvisi = await controlla_coerenza(db)
    return r


# --- esportazione ----------------------------------------------------------------------------


async def esporta(db: AsyncSession, nome: str, versione: str) -> dict[str, str]:
    """Tutto ciò che è attivo nell'ente come pacchetto: backup, passaggio ad altro ente,
    lavoro fuori dall'app. Si reimporta come qualsiasi pacchetto."""
    tipologie = (await db.scalars(select(TipologiaAtto).order_by(TipologiaAtto.ordine))).all()
    manifesto = {
        "nome": nome,
        "versione": versione,
        "descrizione": "Esportazione di modelli, specificità e checklist dell'ente",
        "tipologie": [
            {"codice": t.codice, "descrizione": t.descrizione, "ordine": t.ordine}
            for t in tipologie
        ],
    }
    file = {MANIFESTO: yaml.safe_dump(manifesto, allow_unicode=True, sort_keys=False)}
    for r in (
        await db.scalars(
            select(ModuloDiRegole)
            .where(ModuloDiRegole.attivo.is_(True))
            .options(undefer(ModuloDiRegole.sorgente))
        )
    ).all():
        file[f"modelli/regole/{r.codice.lower()}.yaml"] = r.sorgente
    for r in (
        await db.scalars(
            select(ModelloAtto)
            .where(ModelloAtto.attivo.is_(True))
            .options(undefer(ModelloAtto.sorgente))
        )
    ).all():
        file[f"modelli/{r.codice.lower()}.yaml"] = r.sorgente
    for r in (await db.scalars(select(Checklist).where(Checklist.attiva.is_(True)))).all():
        file[f"checklist/{r.codice.lower()}.json"] = sorgente_checklist(checklist_in(r))
    return file


# --- primo avvio -----------------------------------------------------------------------------


async def importa_pacchetto_iniziale(engine: AsyncEngine, cartella: Path) -> Resoconto | None:
    """Con il database vuoto (nessun modello né checklist) importa il pacchetto della
    cartella; altrimenti non fa nulla: comanda il database. Sotto lock: con più processi
    o più pod lo esegue uno solo. Restituisce None se il database era già configurato."""
    async with engine.connect() as conn:
        mysql = conn.dialect.name in ("mysql", "mariadb")
        if mysql:
            ottenuto = await conn.scalar(text("SELECT GET_LOCK(:n, 60)"), {"n": LOCK})
            await conn.commit()
            if ottenuto != 1:
                log.error("Importazione iniziale saltata: lock non ottenuto in 60 secondi")
                return None
        try:
            async with AsyncSession(bind=conn, expire_on_commit=False) as db:
                presenti = await db.scalar(select(func.count(ModelloAtto.id))) or 0
                presenti += await db.scalar(select(func.count(Checklist.id))) or 0
                if presenti:
                    return None
                pacchetto = leggi_pacchetto(da_cartella(cartella))
                r = await importa(db, pacchetto)
                db.add(
                    PacchettoImportato(
                        nome=pacchetto.manifesto.nome,
                        versione=pacchetto.manifesto.versione,
                        descrizione=pacchetto.manifesto.descrizione,
                        stato="IMPORTATO",
                        resoconto_json=r.come_dict(),
                        importato_il=func.now(),
                    )
                )
                await db.commit()
                return r
        finally:
            if mysql:
                await conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK})
                await conn.commit()
