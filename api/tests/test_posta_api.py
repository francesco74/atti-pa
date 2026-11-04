"""Posta in uscita via HTTP: configurazione SMTP dell'ente (password cifrata che non esce mai,
prova dell'invio) e notifiche delle proposte dell'anticorruzione messe in coda per il worker:
al RPCT quando arriva o torna corretta una proposta, al referente quando il RPCT decide.
Senza posta configurata o senza indirizzo del destinatario non si accoda nulla.
    cd api/tests && python test_posta_api.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from auth import password as pw  # noqa: E402
from common import posta  # noqa: E402
from common.cifratura import decifra  # noqa: E402
from common.config import Settings  # noqa: E402
from common.models import Base, Ente, EnteDominio, Modulo, NotificaEmail, Ruolo, Struttura, User  # noqa: E402

PASSWORD = "Password-di-prova-1"
ENTE = "http://lucca.example.it"
API = "/api/v1/anticorruzione"
SEGRETO = "segreto-di-prova"


class PostaApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import create_app

        cls.cartella = tempfile.TemporaryDirectory()
        cls.url = f"sqlite+aiosqlite:///{cls.cartella.name}/prova.db"

        async def dati():
            motore = create_async_engine(cls.url)
            async with motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(motore) as db:
                ente = Ente(codice="lucca", nome="Comune di Lucca", dati_json={}, moduli_json=[Modulo.ANTICORRUZIONE])
                db.add(ente)
                await db.flush()
                cls.ente_id = ente.id
                uo = Struttura(ente_id=ente.id, codice="U.O. 2.1", descrizione="Personale")
                db.add(uo)
                await db.flush()
                cls.uo = uo.id
                db.add(EnteDominio(dominio="lucca.example.it", ente_id=ente.id))
                for username, ruoli, email, struttura in [
                    ("admin", [Ruolo.ADMIN], "admin@lucca.example.it", None),
                    ("rpct", [Ruolo.ANTICORRUZIONE_RPCT], "rpct@lucca.example.it", None),
                    ("staff", [Ruolo.ANTICORRUZIONE_RPCT], "Staff@Lucca.example.it", None),
                    ("senzaemail", [Ruolo.ANTICORRUZIONE_RPCT], None, None),
                    ("referente", [Ruolo.ANTICORRUZIONE_REFERENTE], "referente@lucca.example.it", uo.id),
                ]:
                    db.add(User(ente_id=ente.id, username=username, origine="LOCALE", email=email,
                                struttura_id=struttura, nome_completo=username.title(),
                                password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
                await db.commit()
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=cls.url, jwt_secret="x" * 40, cookie_secure=False,
            llm_provider="ollama", llm_model="prova", archivio_dir=cls.cartella.name, chiave_cifratura=SEGRETO,
        )  # fmt: skip
        cls.app = create_app(settings)
        cls.inviate = []
        cls.app.state.posta_invio = lambda config, segreto, a, oggetto, testo, timeout: cls.inviate.append(
            (config.host, decifra(config.password_cifrata, segreto), a, oggetto))  # fmt: skip

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

    def _db(self, funzione):
        async def esegui():
            motore = create_async_engine(self.url)
            try:
                async with AsyncSession(motore) as db:
                    risultato = await funzione(db)
                    await db.commit()
                    return risultato
            finally:
                await motore.dispose()

        return asyncio.run(esegui())

    def _notifiche(self):
        async def leggi(db):
            righe = await db.scalars(select(NotificaEmail).order_by(NotificaEmail.created_at, NotificaEmail.destinatario))
            return [(n.destinatario, n.oggetto, n.testo) for n in righe]

        return self._db(leggi)

    def _svuota(self):
        self._db(lambda db: db.execute(delete(NotificaEmail)))

    def test_configurazione_e_prova(self):
        admin = self._client("admin")
        self.assertEqual(self._ok(admin.get("/api/v1/ente/posta", base_url=ENTE)), {"configurata": False})
        self.assertEqual(self._ok(admin.post("/api/v1/ente/posta/prova", base_url=ENTE, json={}))["esito"], "ERRORE")
        self.assertEqual(self._client("rpct").get("/api/v1/ente/posta", base_url=ENTE).status_code, 403)
        corpo = {"host": "smtp.lucca.example.it", "porta": 587, "sicurezza": "STARTTLS", "utente": "atti",
                 "password": "segretissima", "mittente": "Comune di Lucca <atti@lucca.example.it>"}  # fmt: skip
        self.assertEqual(admin.put("/api/v1/ente/posta", base_url=ENTE, json={**corpo, "mittente": "nessuno"}).status_code, 422)
        p = self._ok(admin.put("/api/v1/ente/posta", base_url=ENTE, json=corpo))
        self.assertTrue(p["password_impostata"])
        self.assertNotIn("segretissima", str(p))
        self.assertNotIn("password_cifrata", p)
        # senza password nuova resta quella salvata
        p = self._ok(admin.put("/api/v1/ente/posta", base_url=ENTE, json={**corpo, "password": None, "porta": 2525}))
        self.assertEqual((p["porta"], p["password_impostata"]), (2525, True))
        self.assertNotIn("segretissima", admin.get("/api/v1/ente/posta", base_url=ENTE).get_data(as_text=True))

        esito = self._ok(admin.post("/api/v1/ente/posta/prova", base_url=ENTE, json={}))
        self.assertEqual(esito["esito"], "OK", esito)
        self.assertEqual(self.inviate[-1][:3], ("smtp.lucca.example.it", "segretissima", "admin@lucca.example.it"))

        self._ok(admin.delete("/api/v1/ente/posta", base_url=ENTE), 204)
        self.assertEqual(self._ok(admin.get("/api/v1/ente/posta", base_url=ENTE)), {"configurata": False})

    def test_notifiche_delle_proposte(self):
        admin, rpct, ref = self._client("admin"), self._client("rpct"), self._client("referente")
        area = self._ok(rpct.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Personale"}), 201)
        processo = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={
            "area_id": area["id"], "denominazione": "Concorsi", "struttura_id": self.uo}), 201)  # fmt: skip
        proposta = {"tipo": "CREA", "oggetto": "ATTIVITA", "padre_id": processo["id"],
                    "dati": {"descrizione": "Nomina della commissione"}, "nota": "Manca questa fase"}  # fmt: skip

        # senza posta configurata non si accoda nulla
        self._ok(ref.post(f"{API}/proposte", base_url=ENTE, json=proposta), 201)
        self.assertEqual(self._notifiche(), [])

        self._ok(admin.put("/api/v1/ente/posta", base_url=ENTE, json={
            "host": "smtp.lucca.example.it", "mittente": "atti@lucca.example.it"}))  # fmt: skip
        self._svuota()
        pr = self._ok(ref.post(f"{API}/proposte", base_url=ENTE, json=proposta), 201)
        notifiche = self._notifiche()
        # ai due RPCT con l'indirizzo (non a quello senza, non all'amministratore)
        self.assertEqual(sorted(n[0].lower() for n in notifiche), ["rpct@lucca.example.it", "staff@lucca.example.it"])
        destinatario, oggetto, testo = notifiche[0]
        self.assertIn("Nuova proposta da approvare", oggetto)
        self.assertIn("Creazione - attività: Nomina della commissione", oggetto)
        self.assertIn("Referente (U.O. 2.1 - Personale) ha inviato una proposta", testo)
        self.assertIn("Manca questa fase", testo)
        self.assertIn("https://lucca.example.it", testo)
        self.assertIn(f"{area['codice']} Personale > {processo['codice']} Concorsi", testo)

        # restituita: al referente, con la motivazione; reinviata: di nuovo ai RPCT
        self._svuota()
        self._ok(rpct.post(f"{API}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={"motivazione": "Indica i tempi"}))
        [(destinatario, oggetto, testo)] = self._notifiche()
        self.assertEqual(destinatario, "referente@lucca.example.it")
        self.assertIn("Proposta restituita per una correzione", oggetto)
        self.assertIn("Indica i tempi", testo)
        self._svuota()
        self._ok(ref.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": proposta["dati"], "nota": "Corretta"}))
        notifiche = self._notifiche()
        self.assertEqual(len(notifiche), 2)
        self.assertIn("Proposta reinviata da approvare", notifiche[0][1])
        self.assertIn("ha corretto e reinviato", notifiche[0][2])
        # correggere una proposta ancora in attesa non notifica di nuovo
        self._svuota()
        self._ok(ref.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": proposta["dati"], "nota": "Ancora"}))
        self.assertEqual(self._notifiche(), [])

        # approvata: al referente, con il codice assegnato
        self._ok(rpct.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}))
        [(destinatario, oggetto, testo)] = self._notifiche()
        self.assertEqual(destinatario, "referente@lucca.example.it")
        self.assertIn(f"Proposta approvata: Creazione - attività {processo['codice']}.1", oggetto)

        # la coda la svuota il worker (invio simulato)
        inviate = []

        async def invia():
            motore = create_async_engine(self.url)
            from sqlalchemy.ext.asyncio import async_sessionmaker

            try:
                return await posta.invia_in_sospeso(
                    async_sessionmaker(motore), SEGRETO, invio=lambda c, s, a, o, t, tm: inviate.append(a))
            finally:
                await motore.dispose()

        self.assertEqual(asyncio.run(invia()), (1, 0))
        self.assertEqual(inviate, ["referente@lucca.example.it"])
        self._ok(admin.delete("/api/v1/ente/posta", base_url=ENTE), 204)


if __name__ == "__main__":
    unittest.main()
