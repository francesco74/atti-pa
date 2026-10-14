"""Norme inserite manualmente: regolamenti interni, leggi regionali, altre fonti.

Il file caricato è convertito in Markdown dal converter (come gli atti da controllare);
qui il testo viene scomposto in articoli, commi e lettere con la stessa struttura delle
norme di Normattiva, così verifica, coerenza e checklist le usano allo stesso modo.

Ogni testo caricato vale dalla sua data di inizio vigenza fino al giorno prima del testo
successivo: le versioni degli articoli (norme_articoli_versioni) sono ricostruite da tutti
i testi confermati della norma a ogni conferma, modifica o eliminazione.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from common.models import (
    FonteNorma,
    NormaArticoloVersione,
    NormaAtto,
    NormaTestoCaricato,
    StatoTestoNorma,
)
from common.normattiva.parser import INIZIO_COMMA, Articolo, Comma, commi_da_righe
from common.normattiva.urn import articolo_canonico

_SUFFISSI = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)"

# "Art. 1", "Articolo 3-bis - Oggetto", "ART. 2 (Definizioni)", "Art. 4. Ambito"; non
# "Art. 5 del regolamento ..." (dopo il numero serve un separatore o una maiuscola)
_TITOLO_ARTICOLO = re.compile(
    rf"^(?i:art(?:icolo|\.)?)\s*(?P<num>\d+(?:\s*-?\s*(?i:{_SUFFISSI}))?)\b\s*"
    r"(?P<resto>(?:[.:°º)\-–—(]|$|[A-ZÀ-Ý]).*)$"
)
# Partizioni superiori all'articolo: chiudono l'articolo in corso e non fanno parte del testo
_PARTIZIONE = re.compile(
    r"^(?:titolo|capo|sezione|parte|allegato)\s+(?:[IVXLCDM]+|\d+|[A-Z]|unico|primo|secondo)\b",
    re.IGNORECASE,
)
_MARCATORI_MD = re.compile(r"\*\*|__|`")
# Più titoli di articolo sulla stessa riga: è una riga dell'indice, non un articolo
_ALTRO_ARTICOLO = re.compile(r"(?<!\w)(?i:art(?:icolo|\.)?)\s*\d+\b")


@dataclass
class Scomposizione:
    articoli: list[Articolo]
    # nessun titolo "Art. N" riconosciuto: tutto il testo è trattato come articolo 1
    senza_articoli: bool = False

    def to_dict(self) -> dict:
        return {
            "senza_articoli": self.senza_articoli,
            "articoli": [a.to_dict() for a in self.articoli],
        }


def _righe(markdown: str) -> list[str]:
    """Righe di testo senza la formattazione Markdown e senza i numeri di pagina."""
    righe = []
    for riga in markdown.splitlines():
        riga = _MARCATORI_MD.sub("", riga)
        riga = re.sub(r"^\s*(?:#{1,6}|>)\s*", "", riga)
        riga = re.sub(r"^\s*[-*+]\s+", "", riga)  # elenchi puntati del Markdown
        riga = re.sub(r"(?<!\w)_(\S.*?\S|\S)_(?!\w)", r"\1", riga)  # corsivo
        riga = " ".join(riga.split())
        if riga and not re.fullmatch(r"(?:pag(?:ina)?\.?\s*)?\d{1,4}(?:\s*(?:di|/)\s*\d+)?", riga, re.I):
            righe.append(riga)
    return righe


def _rubrica(resto: str) -> str | None:
    rubrica = re.sub(r"^[\s.:°º)\-–—]+", "", resto).strip()
    if rubrica.startswith("(") and rubrica.endswith(")"):
        rubrica = rubrica[1:-1]
    return rubrica.strip(" .") or None


def _articolo(numero: str, rubrica: str | None, corpo: list[str]) -> Articolo:
    primo = next((i for i, r in enumerate(corpo) if INIZIO_COMMA.match(r)), None)
    if primo is None:
        # articolo senza commi numerati: un solo comma, come fa Normattiva
        commi = [Comma(numero="1", testo=" ".join(corpo))] if corpo else []
    else:
        commi = commi_da_righe(corpo[primo:])
        if primo and commi:  # testo prima del comma 1: non va perso
            commi[0].testo = f"{' '.join(corpo[:primo])} {commi[0].testo}"
    return Articolo(numero=numero, rubrica=rubrica, commi=commi, rinvii=[])


def scomponi(markdown: str) -> Scomposizione:
    """Articoli, commi e lettere di un testo normativo in Markdown."""
    righe = _righe(markdown or "")
    # numero -> (posizione nel testo, articolo)
    trovati: dict[str, tuple[int, Articolo]] = {}
    corrente: tuple[str, str | None, int] | None = None
    corpo: list[str] = []

    def chiudi() -> None:
        if corrente is None:
            return
        art = _articolo(corrente[0], corrente[1], corpo)
        precedente = trovati.get(art.numero)
        # lo stesso articolo due volte (es. nell'indice e nel testo): vale il più lungo,
        # nella posizione in cui si trova
        if precedente is None or len(art.testo()) > len(precedente[1].testo()):
            trovati[art.numero] = (corrente[2], art)

    i = 0
    while i < len(righe):
        riga = righe[i]
        if (m := _TITOLO_ARTICOLO.match(riga)) and _ALTRO_ARTICOLO.search(m["resto"]):
            chiudi()  # riga dell'indice ("Art. 1 Oggetto Art. 2 Definizioni ...")
            corrente, corpo = None, []
        elif m:
            chiudi()
            rubrica = _rubrica(m["resto"])
            # rubrica sulla riga successiva: breve e non un comma o una lettera
            if (
                rubrica is None
                and i + 1 < len(righe)
                and len(righe[i + 1]) <= 200
                and not INIZIO_COMMA.match(righe[i + 1])
                and not _TITOLO_ARTICOLO.match(righe[i + 1])
                and not _PARTIZIONE.match(righe[i + 1])
            ):
                i += 1
                rubrica = _rubrica(righe[i])
            corrente, corpo = (articolo_canonico(m["num"]), rubrica, i), []
        elif _PARTIZIONE.match(riga):
            chiudi()
            corrente, corpo = None, []
        elif corrente is not None:
            corpo.append(riga)
        i += 1
    chiudi()

    articoli = [a for _, a in sorted(trovati.values(), key=lambda t: t[0]) if a.commi]
    if articoli:
        return Scomposizione(articoli=articoli)
    if not righe:
        return Scomposizione(articoli=[], senza_articoli=True)
    return Scomposizione(articoli=[_articolo("1", None, righe)], senza_articoli=True)


def testo_articolo(articolo: Articolo) -> str:
    """Testo leggibile dell'articolo, salvato con la versione."""
    intestazione = f"Art. {articolo.numero}" + (f" - {articolo.rubrica}" if articolo.rubrica else "")
    return f"{intestazione}\n{articolo.testo()}"


async def ricostruisci_versioni(db: AsyncSession, urn_atto: str) -> int:
    """Rigenera le versioni degli articoli della norma dai suoi testi confermati.

    Ogni testo vale dalla sua data fino al giorno prima del testo successivo; un articolo
    che manca in un testo successivo risulta non più vigente da quella data.
    Restituisce il numero di versioni create.
    """
    testi = (
        await db.scalars(
            select(NormaTestoCaricato)
            .where(
                NormaTestoCaricato.urn_atto == urn_atto,
                NormaTestoCaricato.stato == StatoTestoNorma.ATTIVO,
            )
            .order_by(NormaTestoCaricato.vigenza_inizio)
            .options(undefer(NormaTestoCaricato.testo))
        )
    ).all()
    await db.execute(delete(NormaArticoloVersione).where(NormaArticoloVersione.urn_atto == urn_atto))
    create = 0
    for n, testo in enumerate(testi):
        fine = testi[n + 1].vigenza_inizio - timedelta(days=1) if n + 1 < len(testi) else None
        for art in scomponi(testo.testo or "").articoli:
            db.add(
                NormaArticoloVersione(
                    urn_atto=urn_atto,
                    articolo=art.numero,
                    rubrica=art.rubrica,
                    vigenza_inizio=testo.vigenza_inizio,
                    vigenza_fine=fine,
                    struttura_json=art.to_dict(),
                    testo_html=testo_articolo(art),
                    hash_testo=art.hash(),
                    rinvii_json=[],
                )
            )
            create += 1
    await db.flush()
    return create


async def norme_manuali(db: AsyncSession) -> list[NormaAtto]:
    return list(
        (await db.scalars(select(NormaAtto).where(NormaAtto.fonte == FonteNorma.MANUALE))).all()
    )
