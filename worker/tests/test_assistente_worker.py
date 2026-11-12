"""Azioni dell'assistente nel worker, su SQLite e con RAG e LLM simulati: presa in carico e
risultato, avanzamento salvato, sessione scaduta senza nuovi tentativi, errore temporaneo
ritentato poi chiuso, annullamento dell'utente, azioni ferme rimesse in coda, pulizia.
    cd worker/tests && python test_assistente_worker.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "worker" / "src")]

import httpx  # noqa: E402
from sqlalchemy import delete, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.orm import undefer  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from assistente import LavoriAssistente  # noqa: E402
from common.config import Settings  # noqa: E402
from common.llm import LlmError  # noqa: E402
from common.models import AssistenteLavoro, Base, Ente, Modulo, StatoVerifica, User  # noqa: E402
from common.rag import cifra  # noqa: E402

SEGRETO = "segreto-di-prova"


class RagFinto:
    def __init__(self):
        self.scaduta = False
        self.parti = [f"Parte {i}: testo della delibera" for i in range(3)]

    def __call__(self, r: httpx.Request) -> httpx.Response:
        if self.scaduta:
            return httpx.Response(404, json={"error": "Sessione non trovata"})
        da, quante = int(r.url.params["from"]), int(r.url.params["limit"])
        return httpx.Response(200, json={"total": len(self.parti), "sections": [
            {"index": i, "content": self.parti[i], "headings": {}} for i in range(da, min(da + quante, len(self.parti)))]})


class LlmFinto:
    modello = "finto"

    def __init__(self):
        self.errori = 0
        self.chiamate = 0
        self.prima_della_risposta = None  # azione da eseguire durante una chiamata

    async def elabora(self, sistema, testo):
        if self.prima_della_risposta:
            await self.prima_della_risposta()
        if self.errori:
            self.errori -= 1
            raise LlmError("Chiamata al modello fallita: HTTP 503")
        self.chiamate += 1
        return "Riassunto della delibera [d.pdf, parte 1]"


class LavoriWorker(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.motore = create_async_engine(f"sqlite+aiosqlite:///{self.cartella.name}/prova.db", poolclass=NullPool)
        self.sessioni = async_sessionmaker(self.motore, expire_on_commit=False)
        self.settings = Settings(
            _env_file=None, database_url="sqlite+aiosqlite://", llm_provider="ollama", llm_model="finto",
            worker_max_tentativi=2, chiave_cifratura=SEGRETO,
        )  # fmt: skip
        self.rag = RagFinto()
        self.llm = LlmFinto()
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.rag))
        self.lavori = LavoriAssistente(self.sessioni, self.llm, http, self.settings)

        async def prepara():
            async with self.motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(self.motore, expire_on_commit=False) as db:
                ente = Ente(codice="provincia", nome="Provincia", dati_json={}, moduli_json=[Modulo.ASSISTENTE],
                            rag_json={"url": "https://rag.example.it/api", "chiave_cifrata": cifra("k", SEGRETO)})  # fmt: skip
                db.add(ente)
                await db.flush()
                utente = User(ente_id=ente.id, username="utente", origine="LOCALE", ruoli=["REDATTORE"])
                db.add(utente)
                await db.commit()
                self.ente_id, self.utente_id = ente.id, utente.id

        asyncio.run(prepara())

    def tearDown(self):
        asyncio.run(self.motore.dispose())
        self.cartella.cleanup()

    def _lavoro(self) -> str:
        async def crea():
            async with self.sessioni() as db:
                lavoro = AssistenteLavoro(ente_id=self.ente_id, utente_id=self.utente_id, tipo="RIASSUNTO", richiesta={
                    "sessione": "a" * 32, "istruzioni": "", "documenti": [{"id": "d" * 32, "nome": "d.pdf"}]})  # fmt: skip
                db.add(lavoro)
                await db.commit()
                return lavoro.id

        return asyncio.run(crea())

    def _leggi(self, lavoro_id) -> AssistenteLavoro | None:
        async def leggi():
            async with self.sessioni() as db:
                return await db.get(AssistenteLavoro, lavoro_id, options=[undefer(AssistenteLavoro.risultato)])

        return asyncio.run(leggi())

    def _esegui(self, lavoro_id):
        async def esegui():
            if not await self.lavori.prendi_in_carico(lavoro_id):
                return "non preso"
            return await self.lavori.elabora(lavoro_id)

        return asyncio.run(esegui())

    def test_azione_completata(self):
        lavoro_id = self._lavoro()
        self.assertIsNone(self._esegui(lavoro_id))
        self.assertEqual(self._esegui(lavoro_id), "non preso")  # messaggio duplicato
        lavoro = self._leggi(lavoro_id)
        self.assertEqual(lavoro.stato, StatoVerifica.COMPLETATA)
        self.assertIn("[d.pdf, parte 1]", lavoro.risultato)
        self.assertEqual(lavoro.avanzamento, {"fatti": 1, "totale": 1})
        self.assertEqual(lavoro.modello_llm, "finto")
        self.assertIsNotNone(lavoro.completato_il)

    def test_sessione_scaduta_senza_nuovi_tentativi(self):
        self.rag.scaduta = True
        lavoro_id = self._lavoro()
        self.assertIsNone(self._esegui(lavoro_id))
        lavoro = self._leggi(lavoro_id)
        self.assertEqual(lavoro.stato, StatoVerifica.ERRORE)
        self.assertIn("scaduta", lavoro.errore)

    def test_errore_temporaneo_ritentato(self):
        self.llm.errori = 5
        lavoro_id = self._lavoro()
        self.assertEqual(self._esegui(lavoro_id), 30)
        self.assertEqual(self._leggi(lavoro_id).stato, StatoVerifica.IN_CODA)
        self.assertIsNone(self._esegui(lavoro_id))  # secondo e ultimo tentativo
        lavoro = self._leggi(lavoro_id)
        self.assertEqual(lavoro.stato, StatoVerifica.ERRORE)
        self.assertIn("503", lavoro.errore)

    def test_annullata_durante_l_esecuzione(self):
        lavoro_id = self._lavoro()

        async def annulla():
            async with self.sessioni() as db:
                await db.execute(delete(AssistenteLavoro).where(AssistenteLavoro.id == lavoro_id))
                await db.commit()

        self.llm.prima_della_risposta = annulla
        self.assertIsNone(self._esegui(lavoro_id))
        self.assertIsNone(self._leggi(lavoro_id))

    def test_ferme_rimesse_in_coda_e_pulizia(self):
        fermo, vecchio = self._lavoro(), self._lavoro()

        async def prepara():
            await self.lavori.prendi_in_carico(fermo)
            async with self.sessioni() as db:
                await db.execute(update(AssistenteLavoro).where(AssistenteLavoro.id == fermo)
                                 .values(aggiornato_il=datetime.now() - timedelta(minutes=30)))  # fmt: skip
                await db.execute(update(AssistenteLavoro).where(AssistenteLavoro.id == vecchio)
                                 .values(created_at=datetime.now() - timedelta(days=2)))  # fmt: skip
                await db.commit()
            return await self.lavori.recupera_bloccati(), await self.lavori.pulisci()

        self.assertEqual(asyncio.run(prepara()), (1, 1))
        self.assertEqual(self._leggi(fermo).stato, StatoVerifica.IN_CODA)
        self.assertIsNone(self._leggi(vecchio))


if __name__ == "__main__":
    unittest.main()
