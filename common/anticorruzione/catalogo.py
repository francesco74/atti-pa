"""Catalogo della mappatura: le voci (radici) di attività, rischi e misure dell'ente, da cui
nascono gli elementi dei processi (common/models.AcVoce).

Le voci standard stanno nel pacchetto (anticorruzione/catalogo.yaml), si creano se mancano e
non si cancellano mai, come le aree. Un elemento senza voce si collega alla voce con lo stesso
testo (vedi `normalizza`) o ne fa nascere una dell'ente.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models import AcAttivita, AcContatore, AcMisura, AcRischio, AcVoce, nuovo_id

FILE_CATALOGO = "anticorruzione/catalogo.yaml"

Tipo = Literal["ATTIVITA", "RISCHIO", "MISURA"]
TIPI: tuple[Tipo, ...] = ("ATTIVITA", "RISCHIO", "MISURA")
PREFISSI: dict[str, str] = {"ATTIVITA": "ATT", "RISCHIO": "RIS", "MISURA": "MIS"}
ELEMENTI = {"ATTIVITA": AcAttivita, "RISCHIO": AcRischio, "MISURA": AcMisura}
CAMPI_MISURA = ("tipo_misura", "categoria", "indicatore", "target")


def normalizza(testo: str | None) -> str:
    """Il testo per riconoscere le voci uguali: senza differenze di maiuscole, spazi,
    apostrofi e virgolette tipografici e punteggiatura finale."""
    t = unicodedata.normalize("NFC", testo or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"\s+", " ", t).strip()
    return t.rstrip(" .;:,").strip()


def testo_elemento(tipo: str, el) -> str:
    """Il testo dell'elemento che corrisponde alla descrizione della voce."""
    return el.evento if tipo == "RISCHIO" else el.descrizione


# --- pacchetto ------------------------------------------------------------------------------


class VoceStd(BaseModel):
    codice: str = Field(min_length=1, max_length=20)
    descrizione: str = Field(min_length=1)
    tipo_misura: Literal["GENERALE", "SPECIFICA"] | None = None  # solo misure
    categoria: str | None = None
    indicatore: str | None = None
    target: str | None = None


class CatalogoStd(BaseModel):
    attivita: list[VoceStd] = []
    rischi: list[VoceStd] = []
    misure: list[VoceStd] = []

    def voci(self) -> list[tuple[Tipo, VoceStd]]:
        return [*(("ATTIVITA", v) for v in self.attivita), *(("RISCHIO", v) for v in self.rischi),
                *(("MISURA", v) for v in self.misure)]  # fmt: skip


def leggi_catalogo(sorgente: str) -> CatalogoStd:
    """Catalogo del pacchetto. Solleva ValueError (codici ripetuti o del tipo sbagliato)."""
    c = CatalogoStd.model_validate(yaml.safe_load(sorgente) or {})
    codici = [v.codice for _, v in c.voci()]
    ripetuti = sorted({x for x in codici if codici.count(x) > 1})
    if ripetuti:
        raise ValueError(f"codici ripetuti: {', '.join(ripetuti)}")
    for tipo, v in c.voci():
        if not v.codice.startswith(PREFISSI[tipo] + "-"):
            raise ValueError(f"{v.codice}: il codice di una voce {tipo.lower()} inizia con {PREFISSI[tipo]}-")
    return c


async def crea_voci(db: AsyncSession, ente_id: str, catalogo: CatalogoStd) -> list[str]:
    """Le voci del pacchetto che l'ente non ha (per codice); quelle che ha restano com'è."""
    esistenti = set(await db.scalars(select(AcVoce.codice).where(AcVoce.ente_id == ente_id)))
    nuove = []
    for tipo, v in catalogo.voci():
        if v.codice in esistenti:
            continue
        db.add(AcVoce(id=nuovo_id(), ente_id=ente_id, tipo=tipo, **v.model_dump()))
        nuove.append(v.codice)
    await db.flush()
    return nuove


async def esporta(db: AsyncSession, ente_id: str) -> dict[str, str]:
    """Il catalogo dell'ente come file di pacchetto (vuoto se non ha voci)."""
    voci = list(await db.scalars(select(AcVoce).where(AcVoce.ente_id == ente_id).order_by(AcVoce.codice)))
    if not voci:
        return {}
    chiavi = {"ATTIVITA": "attivita", "RISCHIO": "rischi", "MISURA": "misure"}
    dati: dict[str, list] = {"attivita": [], "rischi": [], "misure": []}
    for v in voci:
        campi = VoceStd(codice=v.codice, descrizione=v.descrizione,
                        **({k: getattr(v, k) for k in CAMPI_MISURA} if v.tipo == "MISURA" else {}))  # fmt: skip
        dati[chiavi[v.tipo]].append(campi.model_dump(exclude_none=True))
    return {FILE_CATALOGO: yaml.safe_dump(dati, allow_unicode=True, sort_keys=False, width=100)}


# --- voci dell'ente ---------------------------------------------------------------------------


async def nuovo_codice(db: AsyncSession, ente_id: str, tipo: str) -> str:
    """Codice di una voce nuova dell'ente (ATT-E001...): non si riusa, nemmeno dopo
    un'eliminazione (contatore della mappatura)."""
    prefisso = PREFISSI[tipo] + "-E"
    contatore = await db.get(AcContatore, (ente_id, prefisso), with_for_update=True)
    usati = []
    for codice in await db.scalars(select(AcVoce.codice).where(AcVoce.ente_id == ente_id, AcVoce.codice.startswith(prefisso))):
        if m := re.fullmatch(r"(\d+)", codice[len(prefisso):]):
            usati.append(int(m.group(1)))
    n = max([contatore.ultimo if contatore else 0, *usati]) + 1
    if contatore is None:
        db.add(AcContatore(ente_id=ente_id, prefisso=prefisso, ultimo=n))
    else:
        contatore.ultimo = n
    await db.flush()
    return f"{prefisso}{n:03d}"


class VoceDoppia(ValueError):
    """C'è già una voce dello stesso tipo con lo stesso testo."""

    def __init__(self, voce: AcVoce):
        self.voce = voce
        super().__init__(f"Nel catalogo c'è già la voce {voce.codice} con lo stesso testo")


async def voce_con_testo(db: AsyncSession, ente_id: str, tipo: str, testo: str, esclusa: str | None = None) -> AcVoce | None:
    chiave = normalizza(testo)
    for v in await db.scalars(select(AcVoce).where(AcVoce.ente_id == ente_id, AcVoce.tipo == tipo)):
        if v.id != esclusa and normalizza(v.descrizione) == chiave:
            return v
    return None


async def crea_voce(db: AsyncSession, ente_id: str, tipo: str, descrizione: str, **campi_misura) -> AcVoce:
    """Nuova voce dell'ente (codice ATT-E001...). Solleva VoceDoppia se il testo c'è già."""
    if (doppia := await voce_con_testo(db, ente_id, tipo, descrizione)) is not None:
        raise VoceDoppia(doppia)
    v = AcVoce(id=nuovo_id(), ente_id=ente_id, tipo=tipo, codice=await nuovo_codice(db, ente_id, tipo), descrizione=descrizione.strip())
    if tipo == "MISURA":
        for campo in CAMPI_MISURA:
            valore = campi_misura.get(campo)
            setattr(v, campo, valore.strip() or None if isinstance(valore, str) else valore)
        v.tipo_misura = v.tipo_misura or "SPECIFICA"
    db.add(v)
    await db.flush()
    return v


class Catalogo:
    """Le voci di un ente per tipo e testo normalizzato, per collegare gli elementi: trova la
    voce con lo stesso testo o ne crea una dell'ente. Si carica una volta per operazione."""

    def __init__(self, db: AsyncSession, ente_id: str):
        self.db, self.ente_id = db, ente_id
        self._per_testo: dict[tuple[str, str], AcVoce] | None = None

    async def _indice(self) -> dict[tuple[str, str], AcVoce]:
        if self._per_testo is None:
            self._per_testo = {}
            # a parità di testo vince la voce standard (codice senza E), poi la più vecchia
            voci = sorted(await self.db.scalars(select(AcVoce).where(AcVoce.ente_id == self.ente_id)),
                          key=lambda v: ("-E" in v.codice, v.codice))  # fmt: skip
            for v in voci:
                self._per_testo.setdefault((v.tipo, normalizza(v.descrizione)), v)
        return self._per_testo

    async def voce(self, tipo: str, testo: str, **campi_misura) -> tuple[AcVoce, bool]:
        """La voce con lo stesso testo, o una nuova dell'ente; True se è nuova."""
        indice = await self._indice()
        chiave = (tipo, normalizza(testo))
        if chiave in indice:
            return indice[chiave], False
        v = AcVoce(id=nuovo_id(), ente_id=self.ente_id, tipo=tipo, codice=await nuovo_codice(self.db, self.ente_id, tipo),
                   descrizione=testo.strip(), **({k: campi_misura.get(k) for k in CAMPI_MISURA} if tipo == "MISURA" else {}))  # fmt: skip
        self.db.add(v)
        await self.db.flush()  # la voce prima dell'elemento che la usa (chiave esterna)
        indice[chiave] = v
        return v, True

    async def collega(self, tipo: str, el, codice: str | None = None) -> bool:
        """Collega l'elemento senza voce alla voce indicata per codice (variante con un testo
        diverso, dal pacchetto) o a quella con lo stesso testo (o a una nuova); True se la voce
        è nuova."""
        if el.voce_id:
            return False
        if codice:
            v = await self.db.scalar(select(AcVoce).where(AcVoce.ente_id == self.ente_id, AcVoce.codice == codice))
            if v is not None and v.tipo == tipo:
                el.voce_id = v.id
                return False
        campi = {"tipo_misura": el.tipo, "categoria": el.categoria, "indicatore": el.indicatore,
                 "target": el.target} if tipo == "MISURA" else {}  # fmt: skip
        v, nuova = await self.voce(tipo, testo_elemento(tipo, el), **campi)
        el.voce_id = v.id
        return nuova


async def collega_mappatura(db: AsyncSession, ente_id: str) -> dict[str, dict[str, int]]:
    """Collega al catalogo tutti gli elementi della mappatura dell'ente che non hanno una voce:
    {tipo: {"collegati": n, "voci_nuove": n}}. Non fa il commit."""
    catalogo = Catalogo(db, ente_id)
    esito: dict[str, dict[str, int]] = {}
    for tipo, modello in ELEMENTI.items():
        conteggi = {"collegati": 0, "voci_nuove": 0}
        for el in await db.scalars(select(modello).where(modello.ente_id == ente_id, modello.voce_id.is_(None)).order_by(modello.codice)):
            conteggi["voci_nuove"] += await catalogo.collega(tipo, el)
            conteggi["collegati"] += 1
        await db.flush()
        esito[tipo] = conteggi
    return esito


def simili(voci: list[AcVoce], soglia: float = 0.9, massimo: int = 50) -> list[tuple[AcVoce, AcVoce, float]]:
    """Coppie di voci dello stesso tipo con testi molto somiglianti (da valutare se unire)."""
    coppie = []
    for tipo in TIPI:
        del_tipo = [(v, normalizza(v.descrizione)) for v in voci if v.tipo == tipo]
        for i, (a, ta) in enumerate(del_tipo):
            for b, tb in del_tipo[i + 1:]:
                if abs(len(ta) - len(tb)) > max(len(ta), len(tb)) * (1 - soglia):
                    continue
                r = difflib.SequenceMatcher(None, ta, tb).ratio()
                if r >= soglia:
                    coppie.append((a, b, r))
    return sorted(coppie, key=lambda c: -c[2])[:massimo]
