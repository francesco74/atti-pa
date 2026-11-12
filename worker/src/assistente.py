"""Azioni dell'assistente sui documenti della conversazione (coda "assistente", tabella
assistente_lavori): Riassumi, Confronta, Estrai sulla sessione del RAG dell'ente. La logica
è in common/assistente_azioni.py; qui stato, avanzamento, nuovi tentativi e pulizia.

Come per la trasparenza, la presa in carico usa SELECT ... FOR UPDATE SKIP LOCKED. Gli errori
temporanei (LLM, RAG non raggiungibile) si ritentano fino a WORKER_MAX_TENTATIVI, quelli della
richiesta (sessione scaduta, documenti troppo lunghi) chiudono subito il lavoro. Se l'utente
annulla, la riga sparisce e l'azione si ferma al passo successivo. I lavori si cancellano dopo
un giorno: il risultato contiene testo dei documenti.
"""

from __future__ import annotations

import logging
import socket
from datetime import datetime, timedelta

import httpx
from sqlalchemy import DateTime, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common import assistente_azioni as azioni
from common.config import Settings
from common.models import AssistenteLavoro, Ente, StatoVerifica
from common.rag import RagClient, RagError

log = logging.getLogger("worker.assistente")

CONSERVAZIONE = timedelta(days=1)


def _ora() -> datetime:
    return datetime.now().replace(microsecond=0)


class LavoriAssistente:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        llm,
        rag_http: httpx.AsyncClient,
        settings: Settings,
    ):
        self.sessionmaker = sessionmaker
        self.llm = llm
        self.rag_http = rag_http
        self.settings = settings
        self.nome = socket.gethostname()

    async def prendi_in_carico(self, lavoro_id: str) -> bool:
        async with self.sessionmaker() as db:
            query = select(AssistenteLavoro).where(
                AssistenteLavoro.id == lavoro_id, AssistenteLavoro.stato == StatoVerifica.IN_CODA
            )
            if db.bind.dialect.name != "sqlite":
                query = query.with_for_update(skip_locked=True)
            lavoro = await db.scalar(query)
            if lavoro is None:
                log.debug("Azione %s non in coda (già presa, conclusa o annullata): ignorata", lavoro_id)
                return False
            lavoro.stato = StatoVerifica.IN_CORSO
            lavoro.worker = self.nome
            lavoro.avviato_il = lavoro.aggiornato_il = _ora()
            lavoro.tentativi += 1
            await db.commit()
            log.info("Azione %s (%s) presa in carico, tentativo %d", lavoro.id, lavoro.tipo, lavoro.tentativi)
            return True

    async def _avanza(self, lavoro_id: str, fatti: int, totale: int) -> bool:
        """Salva l'avanzamento; False se il lavoro non c'è più (annullato)."""
        async with self.sessionmaker() as db:
            r = await db.execute(
                update(AssistenteLavoro)
                .where(AssistenteLavoro.id == lavoro_id, AssistenteLavoro.stato == StatoVerifica.IN_CORSO)
                .values(avanzamento={"fatti": fatti, "totale": totale}, aggiornato_il=_ora())
            )
            await db.commit()
            return r.rowcount > 0

    async def elabora(self, lavoro_id: str) -> int | None:
        """Esegue l'azione; se va ritentata restituisce i secondi di attesa."""
        async with self.sessionmaker() as db:
            lavoro = await db.get(AssistenteLavoro, lavoro_id)
            if lavoro is None:
                return None
            ente = await db.get(Ente, lavoro.ente_id)
            r = dict(lavoro.richiesta)
            tipo = lavoro.tipo
        risultato, errore, temporaneo = None, None, False
        try:
            rag = RagClient.dell_ente(self.rag_http, ente.rag_json, self.settings.chiave_cifratura)
            if rag is None:
                raise azioni.AzioneNonEseguibile("Il collegamento al RAG non è configurato")
            risultato = await azioni.esegui(
                tipo, rag, r["sessione"], [azioni.Documento(d["id"], d["nome"]) for d in r["documenti"]],
                r.get("istruzioni") or "", self.llm, lambda f, t: self._avanza(lavoro_id, f, t),
                caratteri_blocco=self.settings.assistente_caratteri_blocco,
                caratteri_unione=self.settings.assistente_caratteri_passaggi,
                max_blocchi=self.settings.assistente_max_blocchi,
            )  # fmt: skip
            log.info("Azione %s (%s) completata", lavoro_id, tipo)
        except azioni.AzioneInterrotta:
            log.info("Azione %s annullata dall'utente", lavoro_id)
            return None
        except azioni.AzioneNonEseguibile as e:
            log.warning("Azione %s non eseguibile: %s", lavoro_id, e)
            errore = str(e)
        except RagError as e:
            if e.stato_http == 404:
                errore = "La sessione dei documenti è scaduta: caricali di nuovo"
            elif e.stato_http == 409:
                errore = str(e)
            else:
                log.warning("Azione %s: RAG non disponibile: %s", lavoro_id, e)
                errore, temporaneo = str(e), True
        except Exception as e:  # noqa: BLE001 - LLM o rete: si ritenta
            log.exception("Azione %s fallita", lavoro_id)
            errore, temporaneo = str(e) or type(e).__name__, True
        attesa = None
        async with self.sessionmaker() as db:
            lavoro = await db.get(AssistenteLavoro, lavoro_id)
            if lavoro is None:  # annullata durante l'ultimo passo
                return None
            if errore is None:
                lavoro.stato, lavoro.errore = StatoVerifica.COMPLETATA, None
                lavoro.risultato = risultato
                lavoro.modello_llm = self.llm.modello
            elif temporaneo and lavoro.tentativi < self.settings.worker_max_tentativi:
                lavoro.stato, lavoro.errore = StatoVerifica.IN_CODA, errore[:2000]
                attesa = 30 * lavoro.tentativi
            else:
                lavoro.stato, lavoro.errore = StatoVerifica.ERRORE, errore[:2000]
            if lavoro.stato != StatoVerifica.IN_CODA:
                lavoro.completato_il = _ora()
            await db.commit()
        return attesa

    # --- manutenzione ---------------------------------------------------------------------

    async def recupera_bloccati(self) -> int:
        """Rimette in coda le azioni senza avanzamenti da troppo tempo (worker terminato);
        oltre i tentativi le chiude in errore."""
        limite = _ora() - timedelta(minutes=self.settings.assistente_minuti_senza_avanzamento)
        fermo = (AssistenteLavoro.stato == StatoVerifica.IN_CORSO, AssistenteLavoro.aggiornato_il < limite)
        async with self.sessionmaker() as db:
            in_errore = await db.execute(
                update(AssistenteLavoro)
                .where(*fermo, AssistenteLavoro.tentativi >= self.settings.worker_max_tentativi)
                .values(stato=StatoVerifica.ERRORE, errore="L'azione si è interrotta: riprova", completato_il=_ora())
            )
            in_coda = await db.execute(
                update(AssistenteLavoro).where(*fermo).values(stato=StatoVerifica.IN_CODA, worker=None)
            )
            await db.commit()
            return in_errore.rowcount + in_coda.rowcount

    async def pulisci(self) -> int:
        """Cancella le azioni più vecchie di un giorno, concluse o no."""
        async with self.sessionmaker() as db:
            limite = await db.scalar(select(func.now(type_=DateTime))) - CONSERVAZIONE
            r = await db.execute(delete(AssistenteLavoro).where(AssistenteLavoro.created_at < limite))
            await db.commit()
            return r.rowcount

    async def fermi(self, attesa: timedelta) -> list[str]:
        """Azioni in coda da più di `attesa` (messaggio perso o RabbitMQ non raggiungibile)."""
        async with self.sessionmaker() as db:
            # created_at lo scrive il database: si confronta con la sua ora
            limite = await db.scalar(select(func.now(type_=DateTime))) - attesa
            return list((await db.scalars(select(AssistenteLavoro.id).where(
                AssistenteLavoro.stato == StatoVerifica.IN_CODA, AssistenteLavoro.created_at < limite))).all())  # fmt: skip
