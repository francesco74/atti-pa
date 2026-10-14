"""Worker delle verifiche: riceve il lavoro dalle code RabbitMQ (common/coda.py).

- coda "convertiti": il converter ha trasformato in Markdown il file di un atto; il
  worker salva il testo e avvia la verifica (o registra l'errore di conversione). Lo
  stesso per il testo di una norma inserita manualmente, che resta da confermare;
- coda "verifica": rianalisi di un atto o verifica di una bozza.

Lo stato resta nel database: la presa in carico usa SELECT ... FOR UPDATE SKIP LOCKED,
quindi un messaggio duplicato o più repliche del worker non elaborano due volte la stessa
verifica. Ogni minuto il worker:
- rimette in coda le verifiche "IN_CORSO" abbandonate (worker terminato);
- reinvia sulle code i lavori fermi da più di WORKER_REINVIO_MINUTI (messaggio perso o
  RabbitMQ non raggiungibile quando l'API ha provato a inviarlo).
"""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from common import coda
from common.coda import Coda
from common.config import Settings
from common.llm import LlmClient
from common.models import (
    AttoControllato,
    Bozza,
    Checklist,
    NormaTestoCaricato,
    StatoTestoNorma,
    StatoVerifica,
    Verifica,
)
from common.normattiva import NormattivaClient
from common.verifica import analizza

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
        coda: Coda,
        heartbeat: Path | None = None,
    ):
        self.sessionmaker = sessionmaker
        self.normattiva = normattiva
        self.llm = llm
        self.settings = settings
        self.coda = coda
        self.heartbeat = heartbeat
        self.nome = socket.gethostname()
        self._stop = asyncio.Event()
        # una verifica alla volta per processo (chiamate all'LLM, memoria)
        self._in_lavorazione = asyncio.Lock()
        self._reinviati: dict[str, datetime] = {}
        self._ritardati: set[asyncio.Task] = set()  # nuovi tentativi in attesa

    def ferma(self) -> None:
        self._stop.set()

    def _battito(self) -> None:
        if self.heartbeat:
            self.heartbeat.touch()

    # --- messaggi ------------------------------------------------------------------------

    async def gestisci_convertito(self, dati: dict[str, Any]) -> None:
        """Esito del converter: salva il Markdown e avvia la verifica."""
        if dati.get("testo_norma_id"):
            await self.gestisci_norma_convertita(dati)
            return
        async with self.sessionmaker() as db:
            atto = await db.get(AttoControllato, dati["atto_id"])
            if atto is None or atto.stato != "IN_CONVERSIONE":
                log.debug("Conversione di %s già registrata: ignorata", dati["atto_id"])
                return
            verifica = (
                await db.get(Verifica, dati["verifica_id"]) if dati.get("verifica_id") else None
            )
            if dati.get("errore"):
                atto.stato = "ERRORE_CONVERSIONE"
                if verifica is not None and verifica.stato == StatoVerifica.IN_CODA:
                    verifica.stato = StatoVerifica.ERRORE
                    verifica.errore = f"Conversione del file non riuscita: {dati['errore']}"
                await db.commit()
                log.warning("Atto %s non convertito: %s", atto.id, dati["errore"])
                return
            atto.contenuto_testo = dati["markdown"]
            atto.stato = "IN_ANALISI"
            await db.commit()
            log.info(
                "Atto %s convertito in Markdown (%d caratteri)", atto.id, len(dati["markdown"])
            )
        if dati.get("verifica_id"):
            await self.gestisci_verifica({"verifica_id": dati["verifica_id"]})

    async def gestisci_norma_convertita(self, dati: dict[str, Any]) -> None:
        """Testo di una norma manuale convertito: resta da rivedere e confermare nell'app."""
        async with self.sessionmaker() as db:
            testo = await db.get(NormaTestoCaricato, dati["testo_norma_id"])
            if testo is None or testo.stato != StatoTestoNorma.IN_CONVERSIONE:
                log.debug("Conversione del testo %s già registrata: ignorata", dati["testo_norma_id"])
                return
            if dati.get("errore"):
                testo.stato = StatoTestoNorma.ERRORE_CONVERSIONE
                testo.errore = dati["errore"]
                log.warning("Testo della norma %s non convertito: %s", testo.urn_atto, dati["errore"])
            else:
                testo.testo = dati["markdown"]
                testo.stato = StatoTestoNorma.DA_CONFERMARE
                log.info(
                    "Testo della norma %s convertito (%d caratteri): da confermare",
                    testo.urn_atto,
                    len(dati["markdown"]),
                )
            await db.commit()

    async def gestisci_verifica(self, dati: dict[str, Any]) -> None:
        async with self._in_lavorazione:
            if not await self.prendi_in_carico(dati["verifica_id"]):
                return
            battito = asyncio.create_task(self._battito_continuo())
            try:
                attesa = await self.elabora(dati["verifica_id"])
            finally:
                battito.cancel()
        if attesa is not None:  # errore temporaneo: nuovo tentativo dopo un'attesa crescente
            log.info("Nuovo tentativo della verifica %s tra %d s", dati["verifica_id"], attesa)
            task = asyncio.create_task(self._ripubblica(dati["verifica_id"], attesa))
            self._ritardati.add(task)
            task.add_done_callback(self._ritardati.discard)

    async def _ripubblica(self, verifica_id: str, attesa: int) -> None:
        await asyncio.sleep(attesa)
        await self.coda.pubblica(coda.VERIFICA, {"verifica_id": verifica_id})

    # --- verifica --------------------------------------------------------------------------

    async def _battito_continuo(self) -> None:
        """Durante una verifica lunga il processo è vivo: la liveness probe non deve fermarlo."""
        while True:
            self._battito()
            await asyncio.sleep(30)

    async def prendi_in_carico(self, verifica_id: str) -> bool:
        async with self.sessionmaker() as db:
            query = select(Verifica).where(
                Verifica.id == verifica_id, Verifica.stato == StatoVerifica.IN_CODA
            )
            if db.bind.dialect.name != "sqlite":
                query = query.with_for_update(skip_locked=True)
            verifica = await db.scalar(query)
            if verifica is None:
                log.debug("Verifica %s non in coda (già presa o conclusa): ignorata", verifica_id)
                return False
            verifica.stato = StatoVerifica.IN_CORSO
            verifica.worker = self.nome
            verifica.avviata_il = _ora()
            verifica.tentativi += 1
            await db.commit()
            log.info("Verifica %s presa in carico (tentativo %d)", verifica.id, verifica.tentativi)
            return True

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

    async def elabora(self, verifica_id: str) -> int | None:
        """Esegue la verifica; se fallisce e va ritentata restituisce i secondi di attesa."""
        async with self.sessionmaker() as db:
            verifica = await db.get(Verifica, verifica_id)
            try:
                testo = await self._testo(db, verifica)
                if not testo.strip():
                    raise ValueError("L'atto non contiene testo analizzabile")
                log.debug(
                    "Verifica %s: %s, checklist %s, data di riferimento %s",
                    verifica_id,
                    f"bozza {verifica.bozza_id}"
                    if verifica.bozza_id
                    else f"atto {verifica.atto_controllato_id}",
                    verifica.checklist_id or "nessuna",
                    verifica.data_riferimento,
                )
                checklist = (
                    await db.get(Checklist, verifica.checklist_id)
                    if verifica.checklist_id
                    else None
                )
                risultato = await analizza(
                    db,
                    self.normattiva,
                    self.llm,
                    testo,
                    verifica.data_riferimento,
                    checklist,
                    self.settings,
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
                log.info(
                    "Verifica %s completata: %d riferimenti, %d elementi di checklist",
                    verifica_id,
                    len(risultato.riferimenti),
                    len(risultato.checklist),
                )
                attesa = None
            except Exception as e:
                log.exception("Verifica %s fallita", verifica_id)
                await db.rollback()
                verifica = await db.get(Verifica, verifica_id)
                ultimo = verifica.tentativi >= self.settings.worker_max_tentativi
                verifica.stato = StatoVerifica.ERRORE if ultimo else StatoVerifica.IN_CODA
                verifica.errore = str(e)[:2000]
                attesa = None if ultimo else 30 * verifica.tentativi
            await db.commit()
            return attesa

    # --- manutenzione ---------------------------------------------------------------------

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

    def _da_reinviare(self, chiave: str, adesso: datetime, attesa: timedelta) -> bool:
        ultimo = self._reinviati.get(chiave)
        if ultimo is not None and adesso - ultimo < attesa:
            return False
        self._reinviati[chiave] = adesso
        return True

    async def reinvia_fermi(self) -> int:
        """Reinvia sulle code i lavori fermi: conversioni (atti e norme manuali) e verifiche."""
        attesa = timedelta(minutes=self.settings.worker_reinvio_minuti)
        adesso = _ora()
        reinviati = 0
        async with self.sessionmaker() as db:
            # created_at è scritto dal database (CURRENT_TIMESTAMP): il confronto usa il suo
            # orologio, che può avere un fuso diverso da quello del worker
            limite = await db.scalar(select(func.now(type_=DateTime))) - attesa
            righe = await db.execute(
                select(Verifica, AttoControllato)
                .outerjoin(AttoControllato, AttoControllato.id == Verifica.atto_controllato_id)
                .where(Verifica.stato == StatoVerifica.IN_CODA, Verifica.created_at < limite)
            )
            lavori = righe.all()
            testi_norme = (
                await db.scalars(
                    select(NormaTestoCaricato).where(
                        NormaTestoCaricato.stato == StatoTestoNorma.IN_CONVERSIONE,
                        NormaTestoCaricato.created_at < limite,
                    )
                )
            ).all()
        for testo in testi_norme:
            if self._da_reinviare(f"norma:{testo.id}", adesso, attesa):
                await self.coda.pubblica(
                    coda.CONVERSIONE,
                    {
                        "testo_norma_id": testo.id,
                        "percorso": testo.file_percorso,
                        "nome_file": testo.file_nome,
                    },
                )
                reinviati += 1
        for verifica, atto in lavori:
            if atto is not None and atto.stato == "IN_CONVERSIONE":
                if self._da_reinviare(f"conversione:{atto.id}", adesso, attesa):
                    await self.coda.pubblica(
                        coda.CONVERSIONE,
                        {
                            "atto_id": atto.id,
                            "verifica_id": verifica.id,
                            "percorso": atto.file_percorso,
                            "nome_file": atto.file_nome,
                        },
                    )
                    reinviati += 1
            elif self._da_reinviare(f"verifica:{verifica.id}", adesso, attesa):
                await self.coda.pubblica(coda.VERIFICA, {"verifica_id": verifica.id})
                reinviati += 1
        return reinviati

    async def manutenzione(self) -> None:
        try:
            if recuperate := await self.recupera_bloccate():
                log.warning("%d verifiche bloccate rimesse in coda", recuperate)
            if reinviati := await self.reinvia_fermi():
                log.warning("%d lavori fermi reinviati sulle code", reinviati)
        except Exception:
            log.exception("Errore nella manutenzione della coda")

    # --- ciclo principale -------------------------------------------------------------------

    async def esegui(self) -> None:
        await self.coda.connetti()
        await self.coda.consuma(coda.CONVERTITI, self.gestisci_convertito)
        await self.coda.consuma(coda.VERIFICA, self.gestisci_verifica)
        log.info(
            "Worker %s avviato: code %s e %s, modello %s",
            self.nome,
            self.coda.nome(coda.CONVERTITI),
            self.coda.nome(coda.VERIFICA),
            self.llm.modello if self.llm else "nessuno",
        )
        ultima_manutenzione = datetime.min
        while not self._stop.is_set():
            self._battito()
            if datetime.now() - ultima_manutenzione > timedelta(minutes=1):
                await self.manutenzione()
                ultima_manutenzione = datetime.now()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
            except TimeoutError:
                pass
        # arresto: nessun nuovo messaggio, si attende la verifica in corso
        await self.coda.smetti_di_consumare()
        for task in self._ritardati:  # restano IN_CODA: li reinvierà la manutenzione
            task.cancel()
        async with self._in_lavorazione:
            pass
        log.info("Worker %s fermato", self.nome)
