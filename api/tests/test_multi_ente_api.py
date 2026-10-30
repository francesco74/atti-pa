"""Installazione multi ente: l'ente si riconosce dal dominio prima del login e dal token
dopo; utenti locali e Active Directory (simulata) per ente; dati separati; revoca delle
sessioni; blocco dopo troppi tentativi; hash delle password di rag e PApuntozeroIA accettati
e rigenerati; enti creati con deploy/enti.py, con l'admin che deve cambiare la password.
    cd api/tests && python test_multi_ente_api.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

import bcrypt  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from auth import password as pw  # noqa: E402
from auth.ldap import UtenteAD  # noqa: E402
from common.config import Settings  # noqa: E402
from common.models import Base, Ente, EnteDominio, Modulo, Ruolo, User  # noqa: E402
from common.pacchetti import da_cartella, importa, leggi_pacchetto  # noqa: E402

A = "http://atti.provincia.example.it"
B = "http://atti.comune.example.it"
SCONOSCIUTO = "http://altro.example.it"
PASSWORD = "Password-di-prova-1"


class AdFinto:
    """Active Directory simulata: accetta solo la password "ad-ok"."""

    def __init__(self, config):
        self.config = config

    def autentica(self, username, password):
        if password != "ad-ok":
            return None
        return UtenteAD(
            username=username.lower(),
            nome_completo="Mario Rossi",
            gruppi=["CN=ATTI-PA-Redattori,OU=Gruppi,DC=prova,DC=local"],
        )


class MultiEnte(unittest.TestCase):
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
                a = Ente(codice="provincia", nome="Provincia", moduli_json=list(Modulo.TUTTI), dati_json={})
                b = Ente(
                    codice="comune", nome="Comune", moduli_json=list(Modulo.TUTTI), dati_json={},
                    ldap_json={"url": "ldaps://dc.prova.local", "dominio": "prova.local",
                               "base_dn": "DC=prova,DC=local"},
                )  # fmt: skip
                db.add_all([a, b])
                await db.flush()
                db.add_all([
                    EnteDominio(dominio="atti.provincia.example.it", ente_id=a.id),
                    EnteDominio(dominio="atti.comune.example.it", ente_id=b.id),
                    User(ente_id=a.id, username="admin", origine="LOCALE",
                         password_hash=pw.calcola(PASSWORD), ruoli=[Ruolo.ADMIN]),
                    # hash ereditati: Werkzeug pbkdf2 (rag) e bcrypt (PApuntozeroIA)
                    User(ente_id=a.id, username="revisore", origine="LOCALE",
                         password_hash=generate_password_hash(PASSWORD, method="pbkdf2:sha256"),
                         ruoli=[Ruolo.REDATTORE]),
                    User(ente_id=a.id, username="trasparenza", origine="LOCALE",
                         password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode(),
                         ruoli=[Ruolo.REDATTORE]),
                ])  # fmt: skip
                await importa(db, a.id, leggi_pacchetto(da_cartella(RADICE / "pacchetto")))
                await db.commit()
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=url, auth_enabled=True, jwt_secret="x" * 40,
            cookie_secure=False, llm_provider="ollama", llm_model="prova",
            archivio_dir=cls.cartella.name, login_tentativi=3,
        )  # fmt: skip
        cls.app = create_app(settings, authenticator=AdFinto)
        cls.url = url

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()

    def _client(self, base):
        c = self.app.test_client()
        c.base = base
        return c

    def _login(self, base, username, password=PASSWORD, modo="locale", atteso=200):
        c = self._client(base)
        r = c.post("/api/v1/auth/login", base_url=base,
                   json={"username": username, "password": password, "modo": modo})  # fmt: skip
        self.assertEqual(r.status_code, atteso, r.get_data(as_text=True)[:300])
        return c, r.get_json()

    def _hash(self, username):
        async def leggi():
            motore = create_async_engine(self.url)
            async with AsyncSession(motore) as db:
                h = await db.scalar(select(User.password_hash).where(User.username == username))
            await motore.dispose()
            return h

        return asyncio.run(leggi())

    def test_ente_dal_dominio(self):
        c = self.app.test_client()
        a = c.get("/api/v1/auth/ente", base_url=A).get_json()
        self.assertEqual(a["ente"]["codice"], "provincia")
        self.assertTrue(a["accesso_locale"])
        self.assertFalse(a["accesso_ldap"])
        b = c.get("/api/v1/auth/ente", base_url=B).get_json()
        self.assertTrue(b["accesso_ldap"])
        self.assertEqual(b["dominio_ldap"], "prova.local")
        self.assertIsNone(c.get("/api/v1/auth/ente", base_url=SCONOSCIUTO).get_json()["ente"])

    def test_dati_separati_e_token_legato_al_dominio(self):
        c, dati = self._login(A, "admin")
        self.assertEqual(dati["utente"]["ente"]["codice"], "provincia")
        modelli = c.get("/api/v1/modelli", base_url=A)
        self.assertEqual(modelli.status_code, 200)
        self.assertEqual(len(modelli.get_json()), 4)
        # lo stesso token sul dominio di un altro ente non vale
        r = c.get(
            "/api/v1/modelli", base_url=B, headers={"Authorization": f"Bearer {dati['token']}"}
        )
        self.assertEqual(r.status_code, 401)
        # l'utente della Provincia non esiste nel Comune
        self._login(B, "admin", atteso=401)

    def test_active_directory_per_ente(self):
        c, dati = self._login(B, "mrossi", "ad-ok", modo="ldap")
        self.assertEqual(dati["utente"]["ruoli"], [Ruolo.REDATTORE])
        self.assertEqual(dati["utente"]["origine"], "LDAP")
        self.assertEqual(c.get("/api/v1/modelli", base_url=B).get_json(), [])  # Comune vuoto
        # la Provincia non ha Active Directory
        self._login(A, "mrossi", "ad-ok", modo="ldap", atteso=400)

    def test_hash_ereditati_rigenerati(self):
        for username in ("revisore", "trasparenza"):
            self.assertFalse(self._hash(username).startswith("scrypt:"))
            self._login(A, username)
            self.assertTrue(self._hash(username).startswith("scrypt:"))
            self._login(A, username)  # e la password resta quella

    def test_cambio_password_revoca_le_sessioni(self):
        async def crea():
            motore = create_async_engine(self.url)
            async with AsyncSession(motore) as db:
                ente = await db.scalar(select(Ente).where(Ente.codice == "provincia"))
                db.add(User(ente_id=ente.id, username="cambia", origine="LOCALE",
                            password_hash=pw.calcola(PASSWORD), ruoli=[Ruolo.REDATTORE]))  # fmt: skip
                await db.commit()
            await motore.dispose()

        asyncio.run(crea())
        _, vecchia = self._login(A, "cambia")
        c, _ = self._login(A, "cambia")
        r = c.put("/api/v1/auth/password", base_url=A,
                  json={"attuale": PASSWORD, "nuova": "Nuova-password-2"})  # fmt: skip
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        h = {"Authorization": f"Bearer {vecchia['token']}"}
        self.assertEqual(c.get("/api/v1/auth/me", base_url=A, headers=h).status_code, 401)
        self.assertEqual(c.get("/api/v1/auth/me", base_url=A).status_code, 200)  # nuovo cookie

    def test_troppi_tentativi(self):
        for _ in range(3):
            self._login(A, "bersaglio", "sbagliata", atteso=401)
        self._login(A, "bersaglio", "sbagliata", atteso=429)

    def _enti(self, *argomenti, esito=0):
        r = subprocess.run(
            [sys.executable, str(RADICE / "deploy" / "enti.py"), *argomenti],
            env={**os.environ, "DATABASE_URL": self.url, "PASSWORD_INIZIALE": "Iniziale-di-prova-1"},
            capture_output=True, text=True, cwd=self.cartella.name,
        )  # fmt: skip
        self.assertEqual(r.returncode, esito, r.stderr)
        return r.stdout

    def _cambia(self, c, base, attuale, nuova, atteso=200):
        r = c.put("/api/v1/auth/password", base_url=base, json={"attuale": attuale, "nuova": nuova})
        self.assertEqual(r.status_code, atteso, r.get_data(as_text=True))

    def test_ente_da_riga_di_comando_e_primo_accesso(self):
        g = "http://greenlees.example.it"
        self._enti("crea", "greenlees", "Archivio Greenlees", "greenlees.example.it", "--moduli", "")
        self._enti("crea", "doppio", "Doppio", "greenlees.example.it", esito=1)  # dominio già usato
        self.assertIn("password da cambiare", self._enti("mostra", "greenlees"))
        c, dati = self._login(g, "admin", "Iniziale-di-prova-1")
        self.assertTrue(dati["utente"]["cambio_password"])
        self.assertEqual(dati["utente"]["ente"]["moduli"], [])
        # finché non cambia la password può solo cambiarla
        self.assertEqual(c.get("/api/v1/ente/utenti", base_url=g).status_code, 403)
        self.assertEqual(c.get("/api/v1/auth/me", base_url=g).status_code, 200)
        self._cambia(c, g, "Iniziale-di-prova-1", "Iniziale-di-prova-1", atteso=422)
        self._cambia(c, g, "Iniziale-di-prova-1", PASSWORD)
        self.assertEqual(c.get("/api/v1/ente/utenti", base_url=g).status_code, 200)
        # senza il modulo redazione i modelli non si vedono, l'amministrazione sì
        self.assertEqual(c.get("/api/v1/modelli", base_url=g).status_code, 403)
        self._enti("moduli", "greenlees", "redazione")
        self.assertEqual(c.get("/api/v1/modelli", base_url=g).status_code, 200)
        # password dimenticata: torna quella iniziale e le sessioni si chiudono
        self._enti("reimposta", "greenlees")
        self.assertEqual(c.get("/api/v1/auth/me", base_url=g).status_code, 401)
        _, dati = self._login(g, "admin", "Iniziale-di-prova-1")
        self.assertTrue(dati["utente"]["cambio_password"])
        # ente disattivato: il dominio non apre più nulla
        self._enti("disattiva", "greenlees")
        self._login(g, "admin", "Iniziale-di-prova-1", atteso=404)
        self._enti("attiva", "greenlees")
        self.assertIn("greenlees", self._enti("elenco"))
        self._enti("reimposta", "inesistente", esito=1)

    def test_dominio_senza_ente(self):
        self._login(SCONOSCIUTO, "admin", atteso=404)
        a, _ = self._login(A, "admin")
        self.assertEqual(a.get("/api/v1/enti", base_url=A).status_code, 404)  # nessuna API degli enti

    def test_profilo_e_logo(self):
        import io

        c, _ = self._login(A, "admin")
        r = c.put("/api/v1/ente/profilo", base_url=A, json={"caratteristiche": " Provincia, 380.000 abitanti "})
        self.assertEqual(r.get_json()["caratteristiche"], "Provincia, 380.000 abitanti")
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
        carica = lambda dati, nome: c.post(  # noqa: E731
            "/api/v1/ente/logo", base_url=A, data={"file": (io.BytesIO(dati), nome)},
            content_type="multipart/form-data",
        )  # fmt: skip
        self.assertEqual(carica(b"<svg onload=alert(1)>", "logo.svg").status_code, 415)
        self.assertTrue(carica(png, "logo.png").get_json()["logo"])
        r = c.get("/api/v1/ente/logo", base_url=A)
        self.assertEqual((r.status_code, r.mimetype, r.data), (200, "image/png", png))
        # gli altri utenti leggono il profilo ma non lo modificano
        a, _ = self._login(A, "revisore")
        self.assertTrue(a.get("/api/v1/ente/profilo", base_url=A).get_json()["logo"])
        self.assertEqual(a.put("/api/v1/ente/profilo", base_url=A, json={}).status_code, 403)
        self.assertEqual(c.delete("/api/v1/ente/logo", base_url=A).status_code, 204)
        self.assertEqual(c.get("/api/v1/ente/logo", base_url=A).status_code, 404)

    def test_utenti_locali_dell_ente(self):
        c, _ = self._login(A, "admin")
        r = c.post("/api/v1/ente/utenti", base_url=A, json={
            "username": "Nuovo", "nome_completo": "Utente nuovo", "ruoli": ["CONTROLLORE"],
            "password": "corta",
        })  # fmt: skip
        self.assertEqual(r.status_code, 422)
        r = c.post("/api/v1/ente/utenti", base_url=A, json={
            "username": "Nuovo", "nome_completo": "Utente nuovo", "ruoli": ["CONTROLLORE"],
            "password": PASSWORD,
        })  # fmt: skip
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        nuovo = r.get_json()
        n, dati = self._login(A, "nuovo")
        self.assertTrue(dati["utente"]["cambio_password"])  # password scelta dall'amministratore
        self._cambia(n, A, PASSWORD, "Scelta-da-me-3")
        r = c.put(f"/api/v1/ente/utenti/{nuovo['id']}", base_url=A,
                  json={"ruoli": ["CONTROLLORE"], "attivo": False})  # fmt: skip
        self.assertEqual(r.status_code, 200)
        self._login(A, "nuovo", "Scelta-da-me-3", atteso=403)  # utente disattivato

    def test_strutture_organizzative(self):
        import io

        c, _ = self._login(A, "admin")
        csv = "codice;descrizione;padre\nU.O. 2.1;Servizi di personale;SETTORE 2\nSETTORE 2;Risorse umane;\n"
        r = c.post("/api/v1/ente/strutture/importa", base_url=A, content_type="multipart/form-data",
                   data={"file": (io.BytesIO(csv.encode()), "strutture.csv")})  # fmt: skip
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json(), {"create": 2, "aggiornate": 0})
        strutture = {s["codice"]: s for s in c.get("/api/v1/ente/strutture", base_url=A).get_json()}
        settore, uo = strutture["SETTORE 2"], strutture["U.O. 2.1"]
        self.assertEqual(uo["padre_id"], settore["id"])  # il padre può venire dopo nel file

        # nuova U.O. sotto il settore; codice doppio e gerarchia circolare rifiutati
        r = c.post("/api/v1/ente/strutture", base_url=A,
                   json={"codice": "U.O. 2.2", "descrizione": "Trattamento economico", "padre_id": settore["id"]})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        uo2 = r.get_json()
        self.assertEqual(c.post("/api/v1/ente/strutture", base_url=A,
                                json={"codice": "U.O. 2.2", "descrizione": "x"}).status_code, 409)  # fmt: skip
        r = c.put(f"/api/v1/ente/strutture/{settore['id']}", base_url=A,
                  json={"codice": "SETTORE 2", "descrizione": "Risorse umane", "padre_id": uo["id"]})
        self.assertEqual(r.status_code, 422)

        # struttura dell'utente; una struttura con utenti non si elimina, si disattiva
        r = c.post("/api/v1/ente/utenti", base_url=A, json={
            "username": "referente", "ruoli": ["ANTICORRUZIONE_REFERENTE"], "password": PASSWORD,
            "struttura_id": uo2["id"],
        })  # fmt: skip
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["struttura_id"], uo2["id"])
        self.assertEqual(c.delete(f"/api/v1/ente/strutture/{uo2['id']}", base_url=A).status_code, 409)
        self.assertEqual(c.delete(f"/api/v1/ente/strutture/{settore['id']}", base_url=A).status_code, 409)
        r = c.put(f"/api/v1/ente/strutture/{uo2['id']}", base_url=A, json={
            "codice": "U.O. 2.2", "descrizione": "Trattamento economico", "padre_id": settore["id"], "attiva": False,
        })  # fmt: skip
        self.assertFalse(r.get_json()["attiva"])

        # le strutture si leggono da tutti gli utenti dell'ente, ma le gestisce solo l'admin
        u, _ = self._login(A, "referente")
        self._cambia(u, A, PASSWORD, "Scelta-da-me-4")
        self.assertEqual(len(u.get("/api/v1/ente/strutture", base_url=A).get_json()), 3)
        self.assertEqual(u.post("/api/v1/ente/strutture", base_url=A,
                                json={"codice": "X", "descrizione": "x"}).status_code, 403)  # fmt: skip

        # importazione con una struttura superiore inesistente: nulla viene creato
        r = c.post("/api/v1/ente/strutture/importa", base_url=A, content_type="multipart/form-data",
                   data={"file": (io.BytesIO(b"codice;descrizione;padre\nU.O. 9;Nove;MANCA\n"), "s.csv")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("MANCA", r.get_data(as_text=True))
        self.assertEqual(len(c.get("/api/v1/ente/strutture", base_url=A).get_json()), 3)


if __name__ == "__main__":
    unittest.main()
