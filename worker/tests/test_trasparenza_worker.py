"""Lavori della trasparenza nel worker, su SQLite e con LLM e converter simulati: presa in
carico, analisi completata con i file eliminati, errore della richiesta senza nuovi tentativi,
errore temporaneo ritentato, lavori bloccati rimessi in coda.
    cd worker/tests && python test_trasparenza_worker.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
import tempfile
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "worker" / "src")]

from sqlalchemy import update  # noqa: E402
from sqlalchemy.orm import undefer  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from common import archivio  # noqa: E402
from common.config import Settings  # noqa: E402
from common.llm import LlmError  # noqa: E402
from common.models import Base, Ente, Modulo, StatoVerifica, TrasparenzaLavoro, User  # noqa: E402
from trasparenza import LavoriTrasparenza  # noqa: E402

REPORT = '<p>Analisi</p><span class="esito-validazione">Non pubblicabile</span>'


class LlmFinto:
    modello = "finto"

    def __init__(self):
        self.errori = 0  # chiamate da far fallire prima di rispondere
        self.sistemi: list[str] = []

    async def genera(self, sistema, testo):
        if self.errori:
            self.errori -= 1
            raise LlmError("Chiamata al modello fallita: HTTP 503")
        self.sistemi.append(sistema)
        return REPORT


class ConverterFinto:
    async def markdown(self, contenuto, nome_file):
        return "Elenco dei provvedimenti dei dirigenti"


class LavoriWorker(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        # una connessione per richiesta: ogni asyncio.run ha il suo ciclo
        self.motore = create_async_engine(f"sqlite+aiosqlite:///{self.cartella.name}/prova.db", poolclass=NullPool)
        self.sessioni = async_sessionmaker(self.motore, expire_on_commit=False)
        self.settings = Settings(
            _env_file=None, database_url="sqlite+aiosqlite://", archivio_dir=self.cartella.name,
            llm_provider="ollama", llm_model="finto", worker_max_tentativi=2,
        )  # fmt: skip
        self.llm = LlmFinto()
        self.lavori = LavoriTrasparenza(self.sessioni, self.llm, ConverterFinto(), self.settings)

        async def prepara():
            async with self.motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(self.motore, expire_on_commit=False) as db:
                ente = Ente(codice="provincia", nome="Provincia di Prova", dati_json={}, moduli_json=[Modulo.TRASPARENZA],
                            caratteristiche="Provincia con 380.000 abitanti")  # fmt: skip
                db.add(ente)
                await db.flush()
                utente = User(ente_id=ente.id, username="operatore", origine="LOCALE", ruoli=["TRASPARENZA"])
                db.add(utente)
                await db.commit()
                self.ente_id, self.utente_id = ente.id, utente.id

        asyncio.run(prepara())

    def tearDown(self):
        asyncio.run(self.motore.dispose())
        self.cartella.cleanup()

    def _lavoro(self, richiesta: dict) -> str:
        async def crea():
            async with self.sessioni() as db:
                lavoro = TrasparenzaLavoro(ente_id=self.ente_id, utente_id=self.utente_id, tipo="ANALISI",
                                           richiesta=richiesta)  # fmt: skip
                db.add(lavoro)
                await db.commit()
                return lavoro.id

        return asyncio.run(crea())

    def _leggi(self, lavoro_id) -> TrasparenzaLavoro:
        async def leggi():
            async with self.sessioni() as db:
                return await db.get(TrasparenzaLavoro, lavoro_id, options=[undefer(TrasparenzaLavoro.risultato)])

        return asyncio.run(leggi())

    def _esegui(self, lavoro_id):
        async def esegui():
            if not await self.lavori.prendi_in_carico(lavoro_id):
                return "non preso"
            return await self.lavori.elabora(lavoro_id)

        return asyncio.run(esegui())

    def _file(self, nome: str, contenuto: bytes) -> dict:
        salvato = archivio.salva(self.cartella.name, contenuto, nome)
        return {"percorso": salvato.percorso, "nome": nome, "descrizione": ""}

    def test_analisi_completata_e_file_eliminati(self):
        file = self._file("elenco.pdf", b"%PDF")
        lavoro_id = self._lavoro({"controllo": "ART_23_DIRIGENTI", "file": [file], "note": "Primo semestre"})
        self.assertIsNone(self._esegui(lavoro_id))
        self.assertEqual(self._esegui(lavoro_id), "non preso")  # messaggio duplicato
        lavoro = self._leggi(lavoro_id)
        self.assertEqual(lavoro.stato, StatoVerifica.COMPLETATA)
        self.assertIn("Non pubblicabile", lavoro.risultato["html"])
        self.assertEqual(lavoro.modello_llm, "finto")
        self.assertIn("Provincia con 380.000 abitanti", self.llm.sistemi[0])
        self.assertIn("Primo semestre", self.llm.sistemi[0])
        self.assertFalse((Path(self.cartella.name) / file["percorso"]).exists())

    def test_errore_della_richiesta_senza_nuovi_tentativi(self):
        file = self._file("eseguibile.exe", b"MZ")
        lavoro_id = self._lavoro({"controllo": "ART_23_DIRIGENTI", "file": [file]})
        self.assertIsNone(self._esegui(lavoro_id))
        lavoro = self._leggi(lavoro_id)
        self.assertEqual((lavoro.stato, lavoro.tentativi), (StatoVerifica.ERRORE, 1))
        self.assertIn("Formato non ammesso", lavoro.errore)
        self.assertFalse((Path(self.cartella.name) / file["percorso"]).exists())

    def test_errore_temporaneo_ritentato_fino_al_massimo(self):
        file = self._file("elenco.pdf", b"%PDF")
        lavoro_id = self._lavoro({"controllo": "ART_23_DIRIGENTI", "file": [file]})
        self.llm.errori = 5
        self.assertEqual(self._esegui(lavoro_id), 30)  # di nuovo in coda dopo 30 s
        self.assertEqual(self._leggi(lavoro_id).stato, StatoVerifica.IN_CODA)
        self.assertTrue((Path(self.cartella.name) / file["percorso"]).exists())  # serve al nuovo tentativo
        self.assertIsNone(self._esegui(lavoro_id))  # secondo e ultimo tentativo
        lavoro = self._leggi(lavoro_id)
        self.assertEqual(lavoro.stato, StatoVerifica.ERRORE)
        self.assertIn("HTTP 503", lavoro.errore)

    def test_lavoro_abbandonato_rimesso_in_coda(self):
        lavoro_id = self._lavoro({"controllo": "ART_23_DIRIGENTI", "file": []})

        async def abbandona():
            async with self.sessioni() as db:
                await db.execute(update(TrasparenzaLavoro).values(
                    stato=StatoVerifica.IN_CORSO, avviato_il=datetime(2020, 1, 1), tentativi=1,
                ))  # fmt: skip
                await db.commit()
            return await self.lavori.recupera_bloccati()

        self.assertEqual(asyncio.run(abbandona()), 1)
        self.assertEqual(self._leggi(lavoro_id).stato, StatoVerifica.IN_CODA)


if __name__ == "__main__":
    unittest.main()
