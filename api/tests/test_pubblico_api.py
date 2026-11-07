"""Pagina pubblica della mappatura via HTTP: senza accesso, solo per l'ente del dominio con il
modulo anticorruzione e la pubblicazione accesa dal RPCT (altrimenti 404), solo i dati da
pubblicare (niente valori degli indicatori né correzioni), separazione tra enti.
    cd api/tests && python test_pubblico_api.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from auth import password as pw  # noqa: E402
from common.config import Settings  # noqa: E402
from common.models import Base, Ente, EnteDominio, Modulo, Ruolo, Struttura, User  # noqa: E402

PASSWORD = "Password-di-prova-1"
ENTE = "http://lucca.example.it"
ALTRO = "http://altro.example.it"
SENZA_MODULO = "http://atti.example.it"
API = "/api/v1/anticorruzione"
PUBBLICO = "/api/v1/pubblico"


class MappaturaPubblicaApi(unittest.TestCase):
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
                ente = Ente(codice="lucca", nome="Comune di Lucca", dati_json={}, moduli_json=[Modulo.ANTICORRUZIONE])
                altro = Ente(codice="altro", nome="Altro", dati_json={}, moduli_json=[Modulo.ANTICORRUZIONE],
                             mappatura_pubblica=True)  # fmt: skip
                senza = Ente(codice="atti", nome="Atti", dati_json={}, moduli_json=[Modulo.REDAZIONE],
                             mappatura_pubblica=True)  # fmt: skip
                db.add_all([ente, altro, senza])
                await db.flush()
                uo = Struttura(ente_id=ente.id, codice="U.O. 2.1", descrizione="Personale")
                db.add(uo)
                await db.flush()
                cls.uo = uo.id
                for dominio, e in [("lucca.example.it", ente), ("altro.example.it", altro), ("atti.example.it", senza)]:
                    db.add(EnteDominio(dominio=dominio, ente_id=e.id))
                for username, ruoli in [("rpct", [Ruolo.ANTICORRUZIONE_RPCT]),
                                        ("referente", [Ruolo.ANTICORRUZIONE_REFERENTE])]:  # fmt: skip
                    db.add(User(ente_id=ente.id, username=username, origine="LOCALE",
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

    def test_mappatura_pubblica(self):
        rpct = self._client("rpct")
        area = self._ok(rpct.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Personale"}), 201)
        p = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={
            "area_id": area["id"], "denominazione": "Concorsi pubblici", "struttura_id": self.uo}), 201)  # fmt: skip
        a = self._ok(rpct.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE,
                               json={"descrizione": "Nomina della commissione"}), 201)  # fmt: skip
        r = self._ok(rpct.post(f"{API}/attivita/{a['id']}/rischi", base_url=ENTE,
                               json={"evento": "Commissari in conflitto di interessi"}), 201)  # fmt: skip
        self._ok(rpct.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Dichiarazioni di assenza di conflitto", "tipo": "GENERALE", "struttura_id": self.uo}), 201)  # fmt: skip
        met = self._ok(rpct.get(f"{API}/metodologia", base_url=ENTE))
        prob = {i["id"]: "Alto" for i in met["indicatori_probabilita"]}
        imp = {i["id"]: "Medio" for i in met["indicatori_impatto"]}
        self._ok(rpct.put(f"{API}/rischi/{r['id']}/valutazione", base_url=ENTE, json={
            "valori_probabilita": prob, "valori_impatto": imp, "probabilita": "Medio",
            "motivazione_correzione": "Nota interna del RPCT"}))  # fmt: skip

        cittadino = self.app.test_client()
        # spenta di default: la pagina non esiste
        self.assertFalse(self._ok(rpct.get(f"{API}/pubblicazione", base_url=ENTE))["attiva"])
        for percorso in ("/mappatura", "/mappatura/processi", f"/mappatura/processi/{p['id']}", "/logo"):
            self.assertEqual(cittadino.get(PUBBLICO + percorso, base_url=ENTE).status_code, 404, percorso)

        # solo il RPCT la accende
        referente = self._client("referente")
        self.assertEqual(referente.put(f"{API}/pubblicazione", base_url=ENTE, json={"attiva": True}).status_code, 403)
        stato = self._ok(rpct.put(f"{API}/pubblicazione", base_url=ENTE, json={"attiva": True}))
        self.assertEqual((stato["attiva"], stato["percorso"], stato["procedimenti_attiva"]),
                         (True, "/pubblico/mappatura", False))  # fmt: skip

        dati = self._ok(cittadino.get(f"{PUBBLICO}/mappatura", base_url=ENTE))
        self.assertEqual(dati["ente"], {"nome": "Comune di Lucca", "logo": False})
        self.assertEqual([x["id"] for x in dati["aree"]], [area["id"]])
        self.assertEqual(dati["strutture"], [{"id": self.uo, "codice": "U.O. 2.1", "descrizione": "Personale"}])
        self.assertEqual(dati["livelli"], met["livelli"])
        self.assertEqual(cittadino.get(f"{PUBBLICO}/logo", base_url=ENTE).status_code, 404)

        elenco = self._ok(cittadino.get(f"{PUBBLICO}/mappatura/processi", base_url=ENTE))
        self.assertEqual(len(elenco), 1)
        self.assertEqual((elenco[0]["attivita"], elenco[0]["rischi"], elenco[0]["misure"]), (1, 1, 1))
        self.assertIsNotNone(elenco[0]["livello_massimo"])
        self.assertNotIn("pacchetto", elenco[0])
        self.assertNotIn("updated_at", elenco[0])
        filtrati = self._ok(cittadino.get(f"{PUBBLICO}/mappatura/processi?tipo=PROCEDIMENTO", base_url=ENTE))
        self.assertEqual(filtrati, [])

        albero = self._ok(cittadino.get(f"{PUBBLICO}/mappatura/processi/{p['id']}", base_url=ENTE))
        rischio = albero["attivita"][0]["rischi"][0]
        self.assertEqual(set(rischio), {"id", "codice", "evento", "fattore_abilitante", "livello", "misure"})
        self.assertEqual(rischio["livello"], elenco[0]["livello_massimo"])
        self.assertNotIn("Nota interna", str(albero))
        self.assertEqual(rischio["misure"][0]["descrizione"], "Dichiarazioni di assenza di conflitto")
        self.assertNotIn("proponibile", albero)

        # altri enti: il processo non si vede dal loro dominio; senza modulo nulla
        self.assertEqual(cittadino.get(f"{PUBBLICO}/mappatura/processi/{p['id']}", base_url=ALTRO).status_code, 404)
        self.assertEqual(self._ok(cittadino.get(f"{PUBBLICO}/mappatura/processi", base_url=ALTRO)), [])
        self.assertEqual(cittadino.get(f"{PUBBLICO}/mappatura", base_url=SENZA_MODULO).status_code, 404)
        self.assertEqual(cittadino.get(f"{PUBBLICO}/mappatura", base_url="http://ignoto.example.it").status_code, 404)

        # spenta di nuovo
        self._ok(rpct.put(f"{API}/pubblicazione", base_url=ENTE, json={"attiva": False}))
        self.assertEqual(cittadino.get(f"{PUBBLICO}/mappatura", base_url=ENTE).status_code, 404)


if __name__ == "__main__":
    unittest.main()
