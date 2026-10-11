"""Worker che elabora la coda delle verifiche (tabella `verifiche`).

Più repliche possono girare insieme: ogni verifica viene presa in carico con
SELECT ... FOR UPDATE SKIP LOCKED, quindi da un solo worker. Le verifiche rimaste
"IN_CORSO" troppo a lungo (worker terminato) tornano in coda o vanno in errore dopo
il numero massimo di tentativi.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from atti_common.config import Settings
from atti_common.llm import LlmClient
from atti_common.models import AttoControllato, Bozza, Checklist, StatoVerifica, Verifica
from atti_common.normattiva import NormattivaClient
from atti_common.verifica import analizza

log = logging.getLogger("verifica_worker")


def _ora() -> datetime:
    return datetime.now().replace(microsecond=0)


class Worker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        normattiva: NormattivaClient,
        llm: LlmClient | None,
        settings: Settings,
        heartbeat: Path | None = None,
    ):
        self.sessionmaker = sessionmaker
        self.normattiva = normattiva
        self.llm = llm
        self.settings = settings
        self.heartbeat = heartbeat
        self.nome = socket.gethostname()
        self._stop = asyncio.Event()

    def ferma(self) -> None:
        self._stop.set()

    def _battito(self) -> None:
        if self.heartbeat:
            self.heartbeat.touch()

    async def recupera_bloccate(self) -> int:
        """Rimette in coda le verifiche abbandonate da un worker terminato."""
        limite = _ora() - timedelta(minutes=self.settings.worker_timeout_minuti)
        async with self.sessionmaker() as db:
            in_errore = await db.execute(
                update(Verifica)
                .where(
                    Verifica.stato == StatoVerifica.IN_CORSO,
                    Verifica.avviata_il < limite,
                    Verifica.tentativi >= self.settings.worker_max_tentativi,
                )
                .values(stato=StatoVerifica.ERRORE, errore="Tempo massimo superato")
            )
            in_coda = await db.execute(
                update(Verifica)
                .where(Verifica.stato == StatoVerifica.IN_CORSO, Verifica.avviata_il < limite)
                .values(stato=StatoVerifica.IN_CODA, worker=None)
            )
            await db.commit()
            return in_errore.rowcount + in_coda.rowcount

    async def prendi_in_carico(self) -> str | None:
        async with self.sessionmaker() as db:
            query = (
                select(Verifica)
                .where(Verifica.stato == StatoVerifica.IN_CODA)
                .order_by(Verifica.created_at)
                .limit(1)
            )
            if db.bind.dialect.name != "sqlite":
                query = query.with_for_update(skip_locked=True)
            verifica = await db.scalar(query)
            if verifica is None:
                return None
            verifica.stato = StatoVerifica.IN_CORSO
            verifica.worker = self.nome
            verifica.avviata_il = _ora()
            verifica.tentativi += 1
            await db.commit()
            return verifica.id

    async def _testo(self, db: AsyncSession, verifica: Verifica) -> str:
        if verifica.bozza_id:
            bozza = await db.get(Bozza, verifica.bozza_id)
            return (bozza.contenuto_testo or "") if bozza else ""
        atto = await db.scalar(
            select(AttoControllato)
            .where(AttoControllato.id == verifica.atto_controllato_id)
            .options(undefer(AttoControllato.contenuto_testo))
        )
        return (atto.contenuto_testo or "") if atto else ""

    async def elabora(self, verifica_id: str) -> None:
        async with self.sessionmaker() as db:
            verifica = await db.get(Verifica, verifica_id)
            try:
                testo = await self._testo(db, verifica)
                if not testo.strip():
                    raise ValueError("L'atto non contiene testo analizzabile")
                checklist = (
                    await db.get(Checklist, verifica.checklist_id)
                    if verifica.checklist_id
                    else None
                )
                risultato = await analizza(
                    db, self.normattiva, self.llm, testo, verifica.data_riferimento, checklist
                )
                verifica.esito_riferimenti = risultato.esito_riferimenti()
                verifica.esito_automatico = risultato.checklist
                verifica.modello_llm = risultato.modello_llm
                verifica.stato = StatoVerifica.COMPLETATA
                verifica.errore = None
                verifica.completata_il = _ora()
                if verifica.atto_controllato_id:
                    await db.execute(
                        update(AttoControllato)
                        .where(
                            AttoControllato.id == verifica.atto_controllato_id,
                            or_(
                                AttoControllato.stato == "DA_ANALIZZARE",
                                AttoControllato.stato == "IN_ANALISI",
                            ),
                        )
                        .values(stato="ANALIZZATO")
                    )
                log.info("Verifica %s completata", verifica_id)
            except Exception as e:
                log.exception("Verifica %s fallita", verifica_id)
                await db.rollback()
                verifica = await db.get(Verifica, verifica_id)
                ultimo = verifica.tentativi >= self.settings.worker_max_tentativi
                verifica.stato = StatoVerifica.ERRORE if ultimo else StatoVerifica.IN_CODA
                verifica.errore = str(e)[:2000]
            await db.commit()

    async def esegui_una(self) -> bool:
        verifica_id = await self.prendi_in_carico()
        if verifica_id is None:
            return False
        await self.elabora(verifica_id)
        return True

    async def esegui(self) -> None:
        log.info("Worker %s avviato", self.nome)
        ultimo_recupero = datetime.min
        while not self._stop.is_set():
            self._battito()
            if datetime.now() - ultimo_recupero > timedelta(minutes=1):
                if recuperate := await self.recupera_bloccate():
                    log.warning("%d verifiche bloccate rimesse in coda", recuperate)
                ultimo_recupero = datetime.now()
            try:
                lavorato = await self.esegui_una()
            except Exception:
                log.exception("Errore nel ciclo del worker")
                lavorato = False
            if not lavorato:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.worker_intervallo_secondi
                    )
                except TimeoutError:
                    pass
        log.info("Worker %s fermato", self.nome)
