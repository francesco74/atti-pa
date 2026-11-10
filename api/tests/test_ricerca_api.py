"""Ricerca in linguaggio naturale nella mappatura via HTTP: parole con radici e sinonimi, parte
semantica con il modello di embedding (simulato), vettori salvati e ricalcolati solo quando il
testo cambia, ricaduta sulla sola ricerca per parole se il modello non risponde o se nelle
pagine pubbliche si supera il limite di richieste.
    cd api/tests && python test_ricerca_api.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from auth import password as pw  # noqa: E402
from common.config import Settings  # noqa: E402
from common.embedding import EmbeddingError  # noqa: E402
from common.models import Base, Ente, EnteDominio, Modulo, RicercaVettore, Ruolo, Struttura, User  # noqa: E402

PASSWORD = "Password-di-prova-1"
ENTE = "http://lucca.example.it"
API = "/api/v1/anticorruzione"
PUBBLICO = "/api/v1/pubblico"

# concetti del modello finto: un testo che contiene una di queste parole ha 1 su quella
# dimensione (così "immondizia" e "igiene urbana" sono vicini senza parole in comune)
_CONCETTI = [("igiene urbana", "immondizia", "pattume"), ("locazion", "affitt"), ("concors", "assunzion")]


class EmbeddingFinto:
    modello = "finto"

    def __init__(self):
        self.testi: list[str] = []  # testi dei documenti calcolati
        self.guasto = False

    async def vettori(self, testi, *, domanda=False):
        if self.guasto:
            raise EmbeddingError("spento")
        if not domanda:
            self.testi += testi
        return [[0.05] + [1.0 if any(p in t.lower() for p in gruppo) else 0.0 for gruppo in _CONCETTI] for t in testi]

    async def close(self):
        pass


class RicercaApi(unittest.TestCase):
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
                uo = Struttura(ente_id=ente.id, codice="U.O. 1", descrizione="Servizi sociali")
                db.add(uo)
                await db.flush()
                cls.uo = uo.id
                db.add(EnteDominio(dominio="lucca.example.it", ente_id=ente.id))
                for username, ruoli in [("rpct", [Ruolo.ANTICORRUZIONE_RPCT]),
                                        ("referente", [Ruolo.ANTICORRUZIONE_REFERENTE])]:  # fmt: skip
                    db.add(User(ente_id=ente.id, username=username, origine="LOCALE",
                                password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
                await db.commit()
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=cls.url, jwt_secret="x" * 40, cookie_secure=False,
            llm_provider="ollama", llm_model="prova", archivio_dir=cls.cartella.name,
            ricerca_limite_pubblico=2,
        )  # fmt: skip
        cls.app = create_app(settings)
        cls.embedding = EmbeddingFinto()
        cls.app.state.embedding = cls.embedding

        rpct = cls._client(cls, "rpct")
        area = rpct.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Servizi alla persona"}).get_json()
        cls.processi = {}
        for chiave, tipo, denominazione, descrizione in [
            ("affitto", "PROCEDIMENTO", "Contributi per il sostegno alla locazione", "Contributo per il pagamento del canone"),
            ("rifiuti", "PROCEDIMENTO", "Servizio di igiene urbana", "Segnalazioni sul servizio"),
            ("concorsi", "PROCESSO", "Reclutamento del personale", "Concorsi pubblici"),
            ("sport", "PROCEDIMENTO", "Contributi alle associazioni sportive", "Sostegno alle attività sportive"),
        ]:
            r = rpct.post(f"{API}/processi", base_url=ENTE, json={
                "area_id": area["id"], "tipo": tipo, "denominazione": denominazione, "descrizione": descrizione,
                "struttura_id": cls.uo})  # fmt: skip
            assert r.status_code == 201, r.get_data(as_text=True)
            cls.processi[chiave] = r.get_json()["id"]

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()

    def setUp(self):
        self.embedding.guasto = False

    def _client(self, username):
        c = self.app.test_client()
        r = c.post("/api/v1/auth/login", base_url=ENTE, json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.get_data(as_text=True)
        return c

    def _ok(self, r, codice=200):
        self.assertEqual(r.status_code, codice, r.get_data(as_text=True)[:500])
        return r.get_json()

    def _vettori(self, solo_processi: bool = True) -> int:
        """Vettori salvati: dei soli processi (gli altri test cercano anche negli altri livelli)."""
        async def conta():
            motore = create_async_engine(self.url)
            async with AsyncSession(motore) as db:
                q = select(func.count()).select_from(RicercaVettore)
                if solo_processi:
                    q = q.where(RicercaVettore.oggetto_id.in_(list(self.processi.values())))
                n = await db.scalar(q)
            await motore.dispose()
            return n

        return asyncio.run(conta())

    def test_ricerca_interna(self):
        referente = self._client("referente")
        r = self._ok(referente.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "come chiedo il contributo per l'affitto?"}))
        self.assertTrue(r["semantica"])
        ids = [x["id"] for x in r["risultati"]]
        self.assertEqual(ids[0], self.processi["affitto"])  # parole, sinonimi e significato
        self.assertNotIn(self.processi["concorsi"], ids)
        self.assertIn("locazion", r["risultati"][0]["parole"])  # affitto ~ locazione

        # solo per significato: "immondizia" non compare nel testo del servizio di igiene urbana
        r = self._ok(referente.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "pattume"}))
        self.assertEqual(r["risultati"], [{"id": self.processi["rifiuti"], "parole": [], "semantica": True}])

        # filtro per tipo; il codice trova il processo
        r = self._ok(referente.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "concorsi", "tipo": "PROCEDIMENTO"}))
        self.assertEqual(r["risultati"], [])
        self.assertEqual(self._ok(referente.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "a"}))["risultati"], [])
        self.assertEqual(referente.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": ""}).status_code, 422)
        self.assertEqual(self.app.test_client().get(f"{API}/ricerca?testo=x", base_url=ENTE).status_code, 401)

    def test_vettori_salvati_e_ricalcolati(self):
        rpct = self._client("rpct")
        self._ok(rpct.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "affitto casa"}))
        self.assertEqual(self._vettori(), len(self.processi))
        calcolati = len(self.embedding.testi)
        self._ok(rpct.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "concorso"}))
        self.assertEqual(len(self.embedding.testi), calcolati)  # niente da ricalcolare

        # cambia una denominazione: si ricalcola solo quel processo
        p = self.processi["sport"]
        self._ok(rpct.put(f"{API}/processi/{p}", base_url=ENTE, json={
            "denominazione": "Contributi alle società sportive", "tipo": "PROCEDIMENTO",
            "descrizione": "Sostegno alle attività sportive", "struttura_id": self.uo}))  # fmt: skip
        self._ok(rpct.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "palestra"}))
        self.assertEqual(len(self.embedding.testi), calcolati + 1)
        self.assertIn("società sportive", self.embedding.testi[-1])
        self.assertEqual(self._vettori(), len(self.processi))

    def test_ricerca_elenco(self):
        """Elenco piatto della mappatura e ricerca su ogni livello, con il percorso; i vettori
        degli altri livelli restano, quelli degli elementi eliminati si tolgono."""
        rpct, referente = self._client("rpct"), self._client("referente")
        p = self.processi["concorsi"]
        a = self._ok(rpct.post(f"{API}/processi/{p}/attivita", base_url=ENTE, json={"descrizione": "Nomina della commissione di concorso"}), 201)
        r = self._ok(rpct.post(f"{API}/attivita/{a['id']}/rischi", base_url=ENTE, json={"evento": "Commissari compiacenti"}), 201)
        m = self._ok(rpct.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Rotazione dei componenti", "struttura_id": self.uo}), 201)  # fmt: skip

        elenco = self._ok(referente.get(f"{API}/elenco", base_url=ENTE))
        self.assertEqual({k: len(v) for k, v in elenco.items()}, {"aree": 1, "processi": 4, "attivita": 1, "rischi": 1, "misure": 1})
        self.assertEqual((elenco["misure"][0]["rischio_id"], elenco["rischi"][0]["attivita_id"], elenco["attivita"][0]["processo_id"]),
                         (r["id"], a["id"], p))  # fmt: skip

        def cerca(testo, livello):
            return self._ok(referente.get(f"{API}/elenco/ricerca", base_url=ENTE, query_string={"testo": testo, "livello": livello}))

        # per parole, anche nel percorso: la misura si trova con il nome del processo
        self.assertEqual([x["id"] for x in cerca("rotazione", "MISURA")["risultati"]], [m["id"]])
        self.assertEqual([x["id"] for x in cerca("reclutamento", "MISURA")["risultati"]], [m["id"]])
        self.assertEqual([x["id"] for x in cerca("compiacenti", "RISCHIO")["risultati"]], [r["id"]])
        self.assertEqual([x["id"] for x in cerca("commissione", "ATTIVITA")["risultati"]], [a["id"]])
        self.assertEqual(cerca("persona", "AREA")["risultati"][0]["parole"] != [], True)
        # "assunzioni" non compare: sinonimi e significato (l'attività parla di concorso)
        trovata = cerca("assunzioni", "MISURA")
        self.assertTrue(trovata["semantica"])
        self.assertEqual([x["id"] for x in trovata["risultati"]], [m["id"]])
        self.assertEqual([x["id"] for x in cerca("affitto", "PROCESSO")["risultati"]][0], self.processi["affitto"])
        self.assertEqual(referente.get(f"{API}/elenco/ricerca", base_url=ENTE, query_string={"testo": "x", "livello": "ALTRO"}).status_code, 422)

        # esportazione dell'elenco come appare a video
        r = referente.post(f"{API}/elenco/esporta", base_url=ENTE, json={
            "titolo": "Misure", "intestazioni": ["Codice", "Misura"], "righe": [[m["codice"], m["descrizione"]]]})  # fmt: skip
        self.assertEqual(r.status_code, 200)
        self.assertIn("elenco_misure.xlsx", r.headers["Content-Disposition"])
        self.assertTrue(r.data.startswith(b"PK"))

        # la ricerca nei procedimenti non cancella i vettori degli altri livelli
        vettori = self._vettori(solo_processi=False)
        self.assertEqual(vettori, len(self.processi) + 4)  # area, attività, rischio, misura
        self._ok(rpct.get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "concorso", "tipo": "PROCEDIMENTO"}))
        self.assertEqual(self._vettori(solo_processi=False), vettori)
        # eliminati attività, rischio e misura, la ricerca nell'elenco toglie i loro vettori
        self._ok(rpct.delete(f"{API}/attivita/{a['id']}", base_url=ENTE), 204)
        cerca("concorso", "PROCESSO")
        self.assertEqual(self._vettori(solo_processi=False), len(self.processi) + 1)  # resta l'area

    def test_modello_non_disponibile(self):
        self.embedding.guasto = True
        r = self._ok(self._client("rpct").get(f"{API}/ricerca", base_url=ENTE, query_string={"testo": "affitto"}))
        self.assertFalse(r["semantica"])
        self.assertEqual([x["id"] for x in r["risultati"]], [self.processi["affitto"]])

    def test_ricerca_pubblica(self):
        rpct = self._client("rpct")
        cittadino = self.app.test_client()
        for percorso in ("/mappatura/ricerca", "/procedimenti/ricerca"):
            self.assertEqual(cittadino.get(f"{PUBBLICO}{percorso}?testo=affitto", base_url=ENTE).status_code, 404)
        self._ok(rpct.put(f"{API}/pubblicazione", base_url=ENTE, json={"attiva": True, "procedimenti_attiva": True}))
        try:
            # solo procedimenti: il processo dei concorsi non c'è
            r = self._ok(cittadino.get(f"{PUBBLICO}/procedimenti/ricerca", base_url=ENTE, query_string={"testo": "concorso"}))
            self.assertEqual(r["risultati"], [])
            r = self._ok(cittadino.get(f"{PUBBLICO}/mappatura/ricerca", base_url=ENTE, query_string={"testo": "concorso"}))
            self.assertEqual([x["id"] for x in r["risultati"]], [self.processi["concorsi"]])
            # oltre il limite per indirizzo (2 al minuto nei test): solo per parole
            r = self._ok(cittadino.get(f"{PUBBLICO}/procedimenti/ricerca", base_url=ENTE, query_string={"testo": "pattume"}))
            self.assertFalse(r["semantica"])
            self.assertEqual(r["risultati"], [])
            r = self._ok(cittadino.get(f"{PUBBLICO}/procedimenti/ricerca", base_url=ENTE, query_string={"testo": "affitto"}))
            self.assertEqual([x["id"] for x in r["risultati"]], [self.processi["affitto"]])
        finally:
            self._ok(rpct.put(f"{API}/pubblicazione", base_url=ENTE, json={"attiva": False, "procedimenti_attiva": False}))


class LimiteRichieste(unittest.TestCase):
    def test_finestra(self):
        from ricerca import LimiteRichieste as Limite

        limite = Limite(2, finestra=0.05)
        self.assertEqual([limite.consenti("a") for _ in range(3)], [True, True, False])
        self.assertTrue(limite.consenti("b"))  # per indirizzo
        import time

        time.sleep(0.06)
        self.assertTrue(limite.consenti("a"))


if __name__ == "__main__":
    unittest.main()
