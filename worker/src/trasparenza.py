"""Lavori del modulo trasparenza (coda "trasparenza", tabella trasparenza_lavori): analisi con
l'LLM di pagine o documenti di Amministrazione Trasparente ed estrazione dei dati per il form
di uno schema. La logica è in common/trasparenza/analisi.py; qui stato, nuovi tentativi e
pulizia dei file caricati.

Come per le verifiche, la presa in carico usa SELECT ... FOR UPDATE SKIP LOCKED; gli errori
temporanei (LLM, converter, rete) si ritentano fino a WORKER_MAX_TENTATIVI, quelli della
richiesta (pagina non raggiungibile, formato, testo assente) chiudono subito il lavoro.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timedelta

from sqlalchemy import DateTime, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common import archivio
from common.config import Settings
from common.models import Ente, StatoVerifica, TrasparenzaLavoro
from common.trasparenza import analisi, fonti
from common.trasparenza.rete import UrlNonConsentito

log = logging.getLogger("worker.trasparenza")

# errori della richiesta: ritentare non serve
DEFINITIVI = (analisi.AnalisiNonRiuscita, UrlNonConsentito, ValueError, archivio.FileNonInArchivio)


def _ora() -> datetime:
    return datetime.now().replace(microsecond=0)


class LavoriTrasparenza:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        llm,
        documenti,
        settings: Settings,
    ):
        self.sessionmaker = sessionmaker
        self.llm = llm
        self.documenti = documenti
        self.settings = settings
        self.nome = socket.gethostname()

    async def prendi_in_carico(self, lavoro_id: str) -> bool:
        async with self.sessionmaker() as db:
            query = select(TrasparenzaLavoro).where(
                TrasparenzaLavoro.id == lavoro_id, TrasparenzaLavoro.stato == StatoVerifica.IN_CODA
            )
            if db.bind.dialect.name != "sqlite":
                query = query.with_for_update(skip_locked=True)
            lavoro = await db.scalar(query)
            if lavoro is None:
                log.debug("Lavoro %s non in coda (già preso o concluso): ignorato", lavoro_id)
                return False
            lavoro.stato = StatoVerifica.IN_CORSO
            lavoro.worker = self.nome
            lavoro.avviato_il = _ora()
            lavoro.tentativi += 1
            await db.commit()
            log.info("Lavoro %s (%s) preso in carico, tentativo %d", lavoro.id, lavoro.tipo, lavoro.tentativi)
            return True

    async def _file(self, richiesta: dict) -> list[analisi.File]:
        cartella = self.settings.archivio_dir
        return [
            analisi.File(f["nome"], await asyncio.to_thread(archivio.leggi, cartella, f["percorso"]), f.get("descrizione", ""))
            for f in richiesta.get("file") or []
        ]

    async def _esegui(self, lavoro: TrasparenzaLavoro, ente: Ente) -> dict:
        r = lavoro.richiesta
        contenuti = await analisi.contenuti(
            r.get("url") or "", await self._file(r), self.documenti,
            analizza_documenti=bool(r.get("analizza_documenti")),
            max_documenti=int(r.get("max_documenti") or fonti.MAX_DOCUMENTI),
            segui_link=bool(r.get("segui_link")), max_link=int(r.get("max_link") or fonti.MAX_LINK),
        )  # fmt: skip
        if lavoro.tipo == analisi.ANALISI:
            contesto = analisi.Contesto(
                ente=ente.nome, caratteristiche=ente.caratteristiche or "", note=r.get("note") or "",
                data_adozione=r.get("data_adozione") or "", data_pubblicazione=r.get("data_pubblicazione") or "",
            )  # fmt: skip
            return await analisi.analizza(r["controllo"], contenuti, contesto, self.llm)
        return await analisi.estrai_dati(r["schema_id"], r.get("variante") or "", contenuti, self.llm,
                                         r.get("sezione") or "")  # fmt: skip

    async def _elimina_file(self, richiesta: dict) -> None:
        for f in richiesta.get("file") or []:
            try:
                await asyncio.to_thread(archivio.elimina, self.settings.archivio_dir, f["percorso"])
            except Exception:  # noqa: BLE001 - un file rimasto non deve far fallire il lavoro
                log.warning("File %s del lavoro non eliminato", f["percorso"], exc_info=True)

    async def elabora(self, lavoro_id: str) -> int | None:
        """Esegue il lavoro; se va ritentato restituisce i secondi di attesa."""
        async with self.sessionmaker() as db:
            lavoro = await db.get(TrasparenzaLavoro, lavoro_id)
            if lavoro is None:  # tolto dall'utente mentre era in coda
                log.info("Lavoro %s non più presente: ignorato", lavoro_id)
                return None
            ente = await db.get(Ente, lavoro.ente_id)
            attesa = None
            try:
                lavoro.risultato = await self._esegui(lavoro, ente)
                lavoro.stato = StatoVerifica.COMPLETATA
                lavoro.errore = None
                lavoro.modello_llm = self.llm.modello
                log.info("Lavoro %s (%s) completato", lavoro.id, lavoro.tipo)
            except DEFINITIVI as e:
                log.warning("Lavoro %s non eseguibile: %s", lavoro_id, e)
                lavoro.stato, lavoro.errore = StatoVerifica.ERRORE, str(e)[:2000]
            except Exception as e:
                log.exception("Lavoro %s fallito", lavoro_id)
                ultimo = lavoro.tentativi >= self.settings.worker_max_tentativi
                lavoro.stato = StatoVerifica.ERRORE if ultimo else StatoVerifica.IN_CODA
                lavoro.errore = str(e)[:2000]
                attesa = None if ultimo else 30 * lavoro.tentativi
            if lavoro.stato != StatoVerifica.IN_CODA:
                lavoro.completato_il = _ora()
            if lavoro.stato == StatoVerifica.COMPLETATA:
                # un lavoro non riuscito tiene i file: l'utente può riprovarlo (API "riprova")
                await self._elimina_file(lavoro.richiesta)
            await db.commit()
            return attesa

    # --- manutenzione ---------------------------------------------------------------------

    async def recupera_bloccati(self) -> int:
        """Rimette in coda i lavori abbandonati da un worker terminato."""
        limite = _ora() - timedelta(minutes=self.settings.worker_timeout_minuti)
        async with self.sessionmaker() as db:
            in_errore = await db.execute(
                update(TrasparenzaLavoro)
                .where(
                    TrasparenzaLavoro.stato == StatoVerifica.IN_CORSO,
                    TrasparenzaLavoro.avviato_il < limite,
                    TrasparenzaLavoro.tentativi >= self.settings.worker_max_tentativi,
                )
                .values(stato=StatoVerifica.ERRORE, errore="Tempo massimo superato")
            )
            in_coda = await db.execute(
                update(TrasparenzaLavoro)
                .where(TrasparenzaLavoro.stato == StatoVerifica.IN_CORSO, TrasparenzaLavoro.avviato_il < limite)
                .values(stato=StatoVerifica.IN_CODA, worker=None)
            )
            await db.commit()
            return in_errore.rowcount + in_coda.rowcount

    async def pulisci_falliti(self, giorni: int = 30) -> int:
        """Elimina i lavori non riusciti più vecchi di `giorni` (non più nell'elenco dell'app)
        con i file caricati, che restavano per poterli riprovare."""
        limite = _ora() - timedelta(days=giorni)
        async with self.sessionmaker() as db:
            vecchi = (await db.scalars(select(TrasparenzaLavoro).where(
                TrasparenzaLavoro.stato == StatoVerifica.ERRORE, TrasparenzaLavoro.created_at < limite))).all()  # fmt: skip
            for lavoro in vecchi:
                await self._elimina_file(lavoro.richiesta)
                await db.delete(lavoro)
            await db.commit()
            return len(vecchi)

    async def fermi(self, attesa: timedelta) -> list[str]:
        """Lavori in coda da più di `attesa` (messaggio perso o RabbitMQ non raggiungibile)."""
        async with self.sessionmaker() as db:
            limite = await db.scalar(select(func.now(type_=DateTime))) - attesa
            return list(
                (
                    await db.scalars(
                        select(TrasparenzaLavoro.id).where(
                            TrasparenzaLavoro.stato == StatoVerifica.IN_CODA,
                            TrasparenzaLavoro.created_at < limite,
                        )
                    )
                ).all()
            )
