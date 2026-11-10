"""Relazioni di sintesi via HTTP: sezioni con dati e tabelle calcolati (relazione del RPCT,
PIAO, performance), testo scritto dal modello solo dai dati con i numeri da verificare,
esportazione, permessi per ruolo e modulo.
    cd api/tests && python test_relazioni_api.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from auth import password as pw  # noqa: E402
from common.config import Settings  # noqa: E402
from common.models import Base, Ente, EnteDominio, Modulo, Ruolo, Struttura, User  # noqa: E402

PASSWORD = "Password-di-prova-1"
ENTE = "http://lucca.example.it"
API = "/api/v1/relazioni"
AC = "/api/v1/anticorruzione"
PF = "/api/v1/performance"


class LlmFinto:
    def __init__(self):
        self.prompt = []

    async def scrivi(self, sistema: str, testo: str) -> str:
        self.prompt.append((sistema, testo))
        return "Nel periodo sono stati mappati 1 processi con 2 rischi; le misure sono 77."

    async def close(self):
        pass


class DocumentiFinti:
    async def converti(self, contenuto: bytes, nome: str, formato: str) -> bytes:
        self.html = contenuto.decode()
        return b"DOCX:" + contenuto[:20]

    async def close(self):
        pass


class RelazioniApi(unittest.TestCase):
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
                ente = Ente(codice="lucca", nome="Comune di Lucca", dati_json={},
                            moduli_json=[Modulo.ANTICORRUZIONE, Modulo.PERFORMANCE])  # fmt: skip
                db.add(ente)
                await db.flush()
                uo = Struttura(ente_id=ente.id, codice="U.O. 2.1", descrizione="Personale")
                db.add(uo)
                await db.flush()
                cls.uo = uo.id
                db.add(EnteDominio(dominio="lucca.example.it", ente_id=ente.id))
                for username, ruoli, struttura in [
                    ("rpct", [Ruolo.ANTICORRUZIONE_RPCT], None), ("referente", [Ruolo.ANTICORRUZIONE_REFERENTE], uo.id),
                    ("perf", [Ruolo.PERFORMANCE_AMMINISTRATORE, Ruolo.PERFORMANCE_APPROVATORE], None), ("resp", [Ruolo.PERFORMANCE_RESPONSABILE], uo.id),
                ]:  # fmt: skip
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
        cls.llm = cls.app.state.llm = LlmFinto()
        cls.documenti = cls.app.state.documenti = DocumentiFinti()

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()

    def _client(self, username):
        c = self.app.test_client()
        r = c.post("/api/v1/auth/login", base_url=ENTE, json={"username": username, "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return c

    def _ok(self, r, codice=200):
        self.assertEqual(r.status_code, codice, r.get_data(as_text=True)[:600])
        return r.get_json()

    def test_relazione_rpct_e_piao(self):
        rpct = self._client("rpct")
        area = self._ok(rpct.post(f"{AC}/aree", base_url=ENTE, json={"descrizione": "Personale"}), 201)
        p = self._ok(rpct.post(f"{AC}/processi", base_url=ENTE, json={"area_id": area["id"], "denominazione": "Concorsi"}), 201)
        a = self._ok(rpct.post(f"{AC}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "Bando"}), 201)
        r = self._ok(rpct.post(f"{AC}/attivita/{a['id']}/rischi", base_url=ENTE, json={"evento": "Bando su misura"}), 201)
        self._ok(rpct.post(f"{AC}/attivita/{a['id']}/rischi", base_url=ENTE, json={"evento": "Commissione"}), 201)
        met = self._ok(rpct.get(f"{AC}/metodologia", base_url=ENTE))
        self._ok(rpct.put(f"{AC}/rischi/{r['id']}/valutazione", base_url=ENTE, json={
            "valori_probabilita": {i["id"]: "Alto" for i in met["indicatori_probabilita"]},
            "valori_impatto": {i["id"]: "Alto" for i in met["indicatori_impatto"]}}))  # fmt: skip

        self.assertEqual([t["id"] for t in self._ok(rpct.get(API, base_url=ENTE))], ["RPCT", "PIAO"])
        self.assertEqual(self._client("referente").get(f"{API}/RPCT", base_url=ENTE).status_code, 404)

        rel = self._ok(rpct.get(f"{API}/RPCT?anno=2026", base_url=ENTE))
        self.assertEqual([s["id"] for s in rel["sezioni"]], ["mappatura", "monitoraggio", "proposte", "trasparenza"])
        mappatura = rel["sezioni"][0]
        self.assertEqual((mappatura["dati"]["processi_e_procedimenti"], mappatura["dati"]["rischi"],
                          mappatura["dati"]["rischi_non_valutati"]), (1, 2, 1))  # fmt: skip
        self.assertEqual(mappatura["dati"]["rischi_per_livello_dal_piu_grave"]["Rischio Critico"], 1)
        self.assertEqual(mappatura["tabelle"][0]["righe"][0][1], 2)

        piao = self._ok(rpct.get(f"{API}/PIAO?anno=2026", base_url=ENTE))
        gravi = next(s for s in piao["sezioni"] if s["id"] == "rischi_gravi")
        self.assertEqual((gravi["dati"]["rischi"], gravi["dati"]["rischi_senza_misure"]), (1, 1))
        self.assertEqual(gravi["tabelle"][0]["righe"][0][3], "Rischio Critico")

        # testo dal modello: riceve i dati della sezione, il numero inventato è da verificare
        testo = self._ok(rpct.post(f"{API}/RPCT/testo", base_url=ENTE, json={"sezione": "mappatura", "anno": 2026}))
        self.assertEqual(testo["numeri_da_verificare"], ["77"])
        sistema, prompt = self.llm.prompt[-1]
        self.assertIn("Usa solo i fatti", sistema)
        self.assertIn('"rischi": 2', prompt)
        self.assertIn("Comune di Lucca", prompt)
        self.assertEqual(rpct.post(f"{API}/RPCT/testo", base_url=ENTE, json={"sezione": "x"}).status_code, 404)

        # esportazione della bozza rivista
        r = rpct.post(f"{API}/esporta", base_url=ENTE, json={
            "titolo": "Relazione annuale del RPCT", "sottotitolo": "Anno 2026", "formato": "docx",
            "sezioni": [{"titolo": "Mappatura", "testo": "Testo rivisto.", "tabelle": mappatura["tabelle"]}]})  # fmt: skip
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.data.startswith(b"DOCX:"))
        self.assertIn("Testo rivisto.", self.documenti.html)
        self.assertIn("Comune di Lucca - Anno 2026", self.documenti.html)

    def test_relazione_performance(self):
        perf = self._client("perf")
        self.assertEqual([t["id"] for t in self._ok(perf.get(API, base_url=ENTE))], ["PERFORMANCE"])
        self.assertEqual(self._client("resp").get(f"{API}/PERFORMANCE", base_url=ENTE).status_code, 404)
        piao = self._ok(perf.post(f"{PF}/piao", base_url=ENTE, json={"anno_inizio": 2026, "titolo": "PIAO 2026-2028"}), 201)
        self.assertEqual(perf.get(f"{API}/PERFORMANCE?anno=2026", base_url=ENTE).status_code, 422)  # senza PIAO
        o = self._ok(perf.post(f"{PF}/obiettivi", base_url=ENTE, json={
            "piao_id": piao["id"], "anno": 2026, "struttura_id": self.uo, "titolo": "Digitalizzare", "impegno": 100}), 201)  # fmt: skip
        x = self._ok(perf.post(f"{PF}/obiettivi/{o['id']}/elementi", base_url=ENTE, json={
            "tipo": "AZIONE", "descrizione": "Piattaforma", "impegno": 100, "scadenza": str(date.today() + timedelta(days=5)),
            "indicatori": [{"descrizione": "Servizi online", "tipo": "NUMERO", "unita": "servizi", "target": 4}]}), 201)  # fmt: skip
        self._ok(perf.put(f"{PF}/elementi/{x['id']}/avanzamento", base_url=ENTE, json={
            "indicatori": [{"id": x["indicatori"][0]["id"], "rilevato": 4}]}))  # fmt: skip
        rel = self._ok(perf.get(f"{API}/PERFORMANCE?anno=2026&piao_id={piao['id']}", base_url=ENTE))
        sintesi = rel["sezioni"][0]
        self.assertEqual((sintesi["dati"]["obiettivi"], sintesi["dati"]["obiettivi_completati_al_100"],
                          sintesi["dati"]["strutture_con_impegni_non_al_100"]), (1, 1, []))  # fmt: skip
        self.assertEqual(sintesi["tabelle"][0]["righe"], [["U.O. 2.1 - Personale", 1, 100, 100.0, 0]])
        indicatori = rel["sezioni"][2]
        self.assertEqual((indicatori["id"], indicatori["dati"]["indicatori"], indicatori["dati"]["raggiunti_al_100"]), ("indicatori", 1, 1))
        self.assertEqual(indicatori["tabelle"][0]["righe"], [["U.O. 2.1", "Digitalizzare", "Piattaforma", "Servizi online",
                                                               "4 servizi", "4 servizi", 100.0]])  # fmt: skip
        self.assertEqual(rel["sottotitolo"], "PIAO 2026-2028 - anno 2026")


if __name__ == "__main__":
    unittest.main()
