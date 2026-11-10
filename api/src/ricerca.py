"""Ricerca in linguaggio naturale (common/ricerca.py) con i vettori di embedding dei record.

I vettori si calcolano alla ricerca, solo per i record nuovi o con il testo cambiato
(impronta), e si conservano nel database (ricerca_vettori) e in memoria. Se il modello di
embedding non è configurato, non risponde o (nelle pagine pubbliche) l'indirizzo ha superato il
limite di ricerche, la ricerca è solo lessicale: non fallisce mai per colpa del modello.
"""

from __future__ import annotations

import logging
import time
from array import array
from collections import deque

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from deps import risorse
from common import ricerca
from common.embedding import EmbeddingError
from common.models import RicercaVettore

log = logging.getLogger("atti_api.ricerca")

# vettori per ricerca da calcolare al massimo (i restanti alle ricerche successive), per non
# far attendere troppo la prima ricerca di un ente con molti record
MAX_NUOVI = 512

# (modello, oggetto_id) -> (impronta, vettore normalizzato)
_memoria: dict[tuple[str, str], tuple[str, list[float]]] = {}


def _in_binario(v: list[float]) -> bytes:
    return array("f", v).tobytes()


def _da_binario(b: bytes) -> list[float]:
    a = array("f")
    a.frombytes(b)
    return a.tolist()


async def _togli_orfani(ente_id: str, modello: str, validi: set[str]) -> None:
    """Elimina i vettori dei record che non ci sono più (solo gli id, senza i vettori)."""
    async with risorse().sessionmaker() as s:
        ids = await s.scalars(select(RicercaVettore.oggetto_id).where(RicercaVettore.ente_id == ente_id,
                                                                      RicercaVettore.modello == modello))  # fmt: skip
        orfani = [i for i in ids if i not in validi]
        if orfani:
            await s.execute(delete(RicercaVettore).where(RicercaVettore.ente_id == ente_id, RicercaVettore.oggetto_id.in_(orfani)))
            await s.commit()


async def _vettori(client, ente_id: str, documenti: list[ricerca.Documento], validi: set[str] | None) -> dict[str, list[float]]:
    """Vettori dei documenti: dalla memoria, dal database o calcolati ora (e salvati). Con
    [validi] si eliminano i vettori dei record che non ci sono più."""
    modello = client.modello
    impronte = {d.id: d.impronta for d in documenti}
    trovati: dict[str, list[float]] = {}
    for d in documenti:
        m = _memoria.get((modello, d.id))
        if m and m[0] == impronte[d.id]:
            trovati[d.id] = m[1]
    mancanti = [d for d in documenti if d.id not in trovati]
    if not mancanti:
        if validi is not None:
            await _togli_orfani(ente_id, modello, validi)
        return trovati
    async with risorse().sessionmaker() as s:
        righe = {r.oggetto_id: r for r in await s.scalars(
            select(RicercaVettore).where(RicercaVettore.ente_id == ente_id, RicercaVettore.modello == modello)
        )}  # fmt: skip
        da_calcolare = []
        for d in mancanti:
            r = righe.get(d.id)
            if r is not None and r.impronta == impronte[d.id]:
                trovati[d.id] = _da_binario(r.vettore)
                _memoria[(modello, d.id)] = (r.impronta, trovati[d.id])
            else:
                da_calcolare.append(d)
        da_calcolare = da_calcolare[:MAX_NUOVI]
        if da_calcolare:
            vettori = await client.vettori([d.per_embedding for d in da_calcolare])
            for d, v in zip(da_calcolare, vettori):
                v = ricerca.unitario(v)
                trovati[d.id] = v
                _memoria[(modello, d.id)] = (impronte[d.id], v)
                r = righe.get(d.id)
                if r is None:
                    s.add(RicercaVettore(ente_id=ente_id, oggetto_id=d.id, modello=modello,
                                         impronta=impronte[d.id], vettore=_in_binario(v)))  # fmt: skip
                else:
                    r.impronta, r.vettore = impronte[d.id], _in_binario(v)
        # vettori di record eliminati: solo se il chiamante conosce tutti i record dell'ente che
        # hanno un vettore (una ricerca sui soli procedimenti non deve cancellare gli altri)
        orfani = [i for i in righe if validi is not None and i not in validi and i not in impronte]
        if orfani:
            await s.execute(delete(RicercaVettore).where(RicercaVettore.ente_id == ente_id,
                                                         RicercaVettore.oggetto_id.in_(orfani)))  # fmt: skip
        try:
            await s.commit()
        except IntegrityError:  # un'altra richiesta li ha appena salvati: restano in memoria
            await s.rollback()
    return trovati


async def cerca(domanda: str, documenti: list[ricerca.Documento], *, ente_id: str, semantica: bool = True,
                validi: set[str] | None = None) -> dict:  # fmt: skip
    """Risultati in ordine di pertinenza: [{id, parole, semantica}] e se la parte semantica è
    stata usata. [validi]: id di tutti i record dell'ente che possono avere un vettore (oggi la
    mappatura); i vettori degli altri si eliminano."""
    lessicali = ricerca.lessicale(domanda, documenti)
    semantici: list[ricerca.Risultato] = []
    client = risorse().embedding
    usata = False
    if semantica and client is not None and documenti and len(domanda.strip()) >= 3:
        try:
            vettori = await _vettori(client, ente_id, documenti, validi)
            [q] = await client.vettori([domanda], domanda=True)
            semantici = ricerca.semantica(ricerca.unitario(q), vettori, risorse().settings.ricerca_soglia_semantica)
            usata = True
        except EmbeddingError as e:
            log.warning("Ricerca solo per parole: %s", e)
    return {
        "semantica": usata,
        "risultati": [
            {"id": r.id, "parole": r.parole, "semantica": r.semantica and not r.parole}
            for r in ricerca.fondi(lessicali, semantici)
        ],
    }


class LimiteRichieste:
    """Al più [massimo] richieste al minuto per chiave (indirizzo IP), in memoria."""

    def __init__(self, massimo: int, finestra: float = 60.0):
        self.massimo, self.finestra = massimo, finestra
        self._richieste: dict[str, deque[float]] = {}

    def consenti(self, chiave: str) -> bool:
        ora = time.monotonic()
        if len(self._richieste) > 10_000:  # pulizia delle chiavi inattive
            self._richieste = {k: v for k, v in self._richieste.items() if v and ora - v[-1] < self.finestra}
        coda = self._richieste.setdefault(chiave, deque())
        while coda and ora - coda[0] >= self.finestra:
            coda.popleft()
        if len(coda) >= self.massimo:
            return False
        coda.append(ora)
        return True
