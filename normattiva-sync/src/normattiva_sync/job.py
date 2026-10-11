"""Aggiornamento quotidiano della libreria normativa.

1. Determina l'intervallo da controllare: dall'ultima esecuzione riuscita a ora.
2. Chiede a Normattiva gli atti modificati nell'intervallo (`ricerca/aggiornati`),
   in finestre di ampiezza limitata.
3. Riscarica gli articoli monitorati che appartengono ad atti modificati, più quelli
   presenti in libreria ma mai scaricati.
4. Salva una nuova versione solo se il testo è cambiato (confronto hash).
5. Registra l'esito. Un'esecuzione non "OK" non fa avanzare l'intervallo:
   il giro successivo ricontrolla lo stesso periodo.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from atti_common.normattiva import (
    AttoNonTrovato,
    NormattivaClient,
    NormattivaError,
    RisultatoAmbiguo,
    Urn,
    testo_principale,
)
from normattiva_sync.repository import ArticoloMonitorato, Repository

log = logging.getLogger("normattiva_sync")


@dataclass
class Esito:
    da: datetime
    a: datetime
    atti_modificati: int = 0
    articoli_controllati: int = 0
    articoli_aggiornati: int = 0
    errori: list[str] = field(default_factory=list)

    @property
    def stato(self) -> str:
        return "OK" if not self.errori else "PARZIALE"


def finestre(da: datetime, a: datetime, giorni: int) -> list[tuple[datetime, datetime]]:
    """Divide [da, a] in intervalli di al massimo `giorni` giorni."""
    risultato = []
    inizio = da
    while inizio < a:
        fine = min(inizio + timedelta(days=giorni), a)
        risultato.append((inizio, fine))
        inizio = fine
    return risultato


class SyncJob:
    def __init__(
        self,
        repo: Repository,
        client: NormattivaClient,
        oggi: date,
        ora: datetime | None = None,
        giorni_iniziali: int = 7,
        finestra_giorni: int = 7,
        pausa_secondi: float = 0.0,
    ):
        self.repo = repo
        self.client = client
        self.oggi = oggi
        self.ora = ora or datetime.now(UTC).replace(tzinfo=None)
        self.giorni_iniziali = giorni_iniziali
        self.finestra_giorni = finestra_giorni
        self.pausa = pausa_secondi

    async def _atti_modificati(self, da: datetime, a: datetime) -> set[str]:
        urn_atti: set[str] = set()
        for inizio, fine in finestre(da, a, self.finestra_giorni):
            for atto in await self.client.atti_aggiornati(inizio, fine):
                urn = Urn.da_metadati(atto)
                if urn:
                    urn_atti.add(urn.atto)
            await asyncio.sleep(self.pausa)
        return urn_atti

    async def _aggiorna_articolo(self, art: ArticoloMonitorato, esito: Esito) -> None:
        urn = Urn.parse(art.urn_atto).con_articolo(art.articolo)
        try:
            testo = await self.client.articolo(urn, vigenza=self.oggi)
        except RisultatoAmbiguo as e:
            testo = testo_principale(e)
            if testo is None:
                esito.errori.append(f"{urn}: {len(e.candidati)} testi, scelta manuale necessaria")
                return
        except AttoNonTrovato:
            esito.errori.append(f"{urn}: non trovato su Normattiva")
            return
        except NormattivaError as e:
            esito.errori.append(f"{urn}: {e}")
            return

        esito.articoli_controllati += 1
        corrente = await self.repo.versione_corrente(art)
        if corrente and corrente.hash_testo == testo.articolo.hash():
            return
        await self.repo.salva_versione(art, testo)
        esito.articoli_aggiornati += 1
        log.info("Aggiornato %s (vigente dal %s)", urn, testo.vigenza_inizio)

    async def esegui(self) -> Esito:
        ultima = await self.repo.ultima_sincronizzazione_ok()
        da = ultima or self.ora - timedelta(days=self.giorni_iniziali)
        esito = Esito(da=da, a=self.ora)
        log.info("Controllo modifiche dal %s al %s", da, self.ora)

        try:
            modificati = await self._atti_modificati(da, self.ora)
            esito.atti_modificati = len(modificati)

            monitorati = await self.repo.articoli_monitorati()
            da_aggiornare = {a for a in monitorati if a.urn_atto in modificati}
            da_aggiornare |= set(await self.repo.articoli_senza_versione())
            log.info(
                "%d atti modificati, %d articoli monitorati, %d da riscaricare",
                len(modificati),
                len(monitorati),
                len(da_aggiornare),
            )

            for art in sorted(da_aggiornare, key=lambda x: (x.urn_atto, x.articolo)):
                await self._aggiorna_articolo(art, esito)
                await asyncio.sleep(self.pausa)
        except NormattivaError as e:
            esito.errori.append(f"Interrogazione atti aggiornati fallita: {e}")
            await self._registra(esito, "ERRORE")
            raise

        await self._registra(esito, esito.stato)
        return esito

    async def _registra(self, esito: Esito, stato: str) -> None:
        await self.repo.registra_esecuzione(
            esito.da,
            esito.a,
            esito.atti_modificati,
            esito.articoli_aggiornati,
            stato,
            "\n".join(esito.errori) or None,
        )
