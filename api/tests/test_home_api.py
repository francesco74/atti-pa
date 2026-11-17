"""Pagina iniziale (Home) via HTTP: il messaggio dell'amministratore dell'ente e le cose da fare
dell'utente secondo moduli e ruoli (proposte da decidere o da correggere, misure da dichiarare,
bozze), ognuna con la voce del menu.
    cd api/tests && python test_home_api.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from auth import password as pw  # noqa: E402
from common.config import Settings  # noqa: E402
from common.models import Base, Ente, EnteDominio, Modulo, Ruolo, Struttura, User  # noqa: E402

PASSWORD = "Password-di-prova-1"
ENTE = "http://lucca.example.it"
AC = "/api/v1/anticorruzione"
HOME = "/api/v1/home"


class HomeApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import create_app

        cls.cartella = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{cls.cartella.name}/prova.db"

        async def dati():
            motore = create_async_engine(url)
            async with motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(motore) as db:
                ente = Ente(codice="lucca", nome="Comune", dati_json={},
                            moduli_json=[Modulo.ANTICORRUZIONE, Modulo.PERFORMANCE, Modulo.REDAZIONE])  # fmt: skip
                db.add(ente)
                await db.flush()
                uo = Struttura(ente_id=ente.id, codice="U.O. 2.1", descrizione="Personale")
                db.add(uo)
                await db.flush()
                cls.uo = uo.id
                db.add(EnteDominio(dominio="lucca.example.it", ente_id=ente.id))
                for username, ruoli, struttura in [
                    ("admin", [Ruolo.ADMIN], None),
                    ("rpct", [Ruolo.ANTICORRUZIONE_RPCT], None),
                    ("referente", [Ruolo.ANTICORRUZIONE_REFERENTE], uo.id),
                    ("redattore", [Ruolo.REDATTORE], None),
                ]:
                    db.add(User(ente_id=ente.id, username=username, origine="LOCALE", struttura_id=struttura,
                                password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
                await db.commit()
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=url, jwt_secret="x" * 40, cookie_secure=False,
            llm_provider="ollama", llm_model="prova", archivio_dir=cls.cartella.name,
        )  # fmt: skip
        cls.app = create_app(settings)

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()

    def _client(self, username):
        c = self.app.test_client()
        r = c.post("/api/v1/auth/login", base_url=ENTE, json={"username": username, "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return c

    def _ok(self, r, codice=200):
        self.assertEqual(r.status_code, codice, r.get_data(as_text=True)[:500])
        return r.get_json()

    def _da_fare(self, c) -> dict[str, int]:
        return {f"{v['voce']}/{v['dove']}: {v['testo']}": v["numero"] for v in self._ok(c.get(HOME, base_url=ENTE))["da_fare"]}

    def test_home(self):
        admin, rpct, ref, red = self._client("admin"), self._client("rpct"), self._client("referente"), self._client("redattore")
        # niente da fare, niente messaggio
        self.assertEqual(self._ok(red.get(HOME, base_url=ENTE)), {"benvenuto": None, "da_fare": []})

        # il messaggio lo scrive l'amministratore e lo leggono tutti
        self._ok(admin.put("/api/v1/ente/profilo", base_url=ENTE, json={"benvenuto": "Entro il 31/01 il monitoraggio delle misure"}))
        self.assertEqual(self._ok(red.get(HOME, base_url=ENTE))["benvenuto"], "Entro il 31/01 il monitoraggio delle misure")
        self.assertEqual(rpct.put("/api/v1/ente/profilo", base_url=ENTE, json={"benvenuto": "x"}).status_code, 403)

        # una misura della U.O.: il referente la deve dichiarare quest'anno
        p = self._ok(rpct.post(f"{AC}/processi", base_url=ENTE, json={"denominazione": "Concorsi", "struttura_id": self.uo}), 201)
        a = self._ok(rpct.post(f"{AC}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "Bando"}), 201)
        r = self._ok(rpct.post(f"{AC}/attivita/{a['id']}/rischi", base_url=ENTE, json={"evento": "Bando su misura"}), 201)
        self._ok(rpct.post(f"{AC}/rischi/{r['id']}/misure", base_url=ENTE, json={"descrizione": "Doppia firma"}), 201)
        anno = date.today().year
        self.assertEqual(self._da_fare(ref), {f"Anticorruzione/Monitoraggio: 1 misura da dichiarare per il {anno}": 1})

        # la proposta del referente: da decidere per il RPCT; restituita, da correggere per il referente
        pr = self._ok(ref.post(f"{AC}/proposte", base_url=ENTE, json={
            "tipo": "MODIFICA", "oggetto": "ATTIVITA", "elemento_id": a["id"], "dati": {"descrizione": "Bando di concorso"}}), 201)  # fmt: skip
        self.assertEqual(self._da_fare(rpct), {"Anticorruzione/Proposte: 1 proposta da decidere": 1})
        self._ok(rpct.post(f"{AC}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={"motivazione": "Precisa"}))
        self.assertEqual(self._da_fare(rpct), {})
        self.assertIn("Anticorruzione/Proposte: 1 tua proposta restituita da correggere", self._da_fare(ref))


if __name__ == "__main__":
    unittest.main()
