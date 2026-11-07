"""Modulo performance via HTTP: PIAO (solo l'amministratore, triennio, chiuso in sola lettura),
obiettivi annuali della propria struttura (il dirigente vede quelli delle sottostanti senza
modificarli), impegni che non superano 100, completamento calcolato, azioni e misure della
mappatura dei rischi, ritardi, storico delle modifiche con i valori prima e dopo, riepilogo,
permessi per ruolo e modulo, separazione tra enti.
    cd api/tests && python test_performance_api.py
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
ALTRO = "http://altro.example.it"
SENZA_MODULO = "http://atti.example.it"
API = "/api/v1/performance"
AC = "/api/v1/anticorruzione"


class PerformanceApi(unittest.TestCase):
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
                            moduli_json=[Modulo.PERFORMANCE, Modulo.ANTICORRUZIONE])  # fmt: skip
                altro = Ente(codice="altro", nome="Altro", dati_json={}, moduli_json=[Modulo.PERFORMANCE])
                senza = Ente(codice="atti", nome="Atti", dati_json={}, moduli_json=[Modulo.REDAZIONE])
                db.add_all([ente, altro, senza])
                await db.flush()
                settore = Struttura(ente_id=ente.id, codice="SETTORE 2", descrizione="Risorse umane")
                db.add(settore)
                await db.flush()
                uo = Struttura(ente_id=ente.id, codice="U.O. 2.1", descrizione="Personale", padre_id=settore.id)
                altra = Struttura(ente_id=ente.id, codice="SETTORE 3", descrizione="Lavori pubblici")
                db.add_all([uo, altra])
                await db.flush()
                cls.settore, cls.uo, cls.altra = settore.id, uo.id, altra.id
                for dominio, e in [("lucca.example.it", ente), ("altro.example.it", altro), ("atti.example.it", senza)]:
                    db.add(EnteDominio(dominio=dominio, ente_id=e.id))
                for e, username, ruoli, struttura in [
                    (ente, "amm", [Ruolo.PERFORMANCE_AMMINISTRATORE], None),
                    (ente, "dirigente", [Ruolo.PERFORMANCE_RESPONSABILE], settore.id),
                    (ente, "responsabile", [Ruolo.PERFORMANCE_RESPONSABILE], uo.id),
                    (ente, "senzastruttura", [Ruolo.PERFORMANCE_RESPONSABILE], None),
                    (ente, "rpct", [Ruolo.ANTICORRUZIONE_RPCT], None),
                    (altro, "amm", [Ruolo.PERFORMANCE_AMMINISTRATORE], None),
                    (senza, "amm", [Ruolo.PERFORMANCE_AMMINISTRATORE], None),
                ]:
                    db.add(User(ente_id=e.id, username=username, origine="LOCALE", struttura_id=struttura,
                                nome_completo=username.title(), password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
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

    def _client(self, username, base=ENTE):
        c = self.app.test_client()
        r = c.post("/api/v1/auth/login", base_url=base, json={"username": username, "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return c

    def _ok(self, r, codice=200):
        self.assertEqual(r.status_code, codice, r.get_data(as_text=True)[:500])
        return r.get_json()

    def _piao(self, amm, anno):
        return self._ok(amm.post(f"{API}/piao", base_url=ENTE, json={"anno_inizio": anno, "titolo": f"PIAO {anno}"}), 201)

    def _misura(self):
        rpct = self._client("rpct")
        area = self._ok(rpct.post(f"{AC}/aree", base_url=ENTE, json={"descrizione": "Personale"}), 201)
        p = self._ok(rpct.post(f"{AC}/processi", base_url=ENTE, json={"area_id": area["id"], "denominazione": "Concorsi"}), 201)
        a = self._ok(rpct.post(f"{AC}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "Bando"}), 201)
        r = self._ok(rpct.post(f"{AC}/attivita/{a['id']}/rischi", base_url=ENTE, json={"evento": "Bando su misura"}), 201)
        return self._ok(rpct.post(f"{AC}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Rotazione dei commissari", "struttura_id": self.uo}), 201)  # fmt: skip

    def test_piao(self):
        amm, resp = self._client("amm"), self._client("responsabile")
        self.assertEqual(resp.post(f"{API}/piao", base_url=ENTE, json={"anno_inizio": 2030, "titolo": "x"}).status_code, 403)
        p = self._piao(amm, 2030)
        self.assertEqual((p["anni"], p["stato"]), ([2030, 2031, 2032], "APERTO"))
        self.assertEqual(amm.post(f"{API}/piao", base_url=ENTE, json={"anno_inizio": 2030, "titolo": "y"}).status_code, 409)
        self.assertIn(p["id"], [x["id"] for x in self._ok(resp.get(f"{API}/piao", base_url=ENTE))])
        self._ok(amm.put(f"{API}/piao/{p['id']}", base_url=ENTE, json={
            "titolo": "PIAO 2030-2032", "atto": "DGC n. 1", "stato": "CHIUSO", "nota": "Approvato"}))  # fmt: skip
        storico = self._ok(amm.get(f"{API}/piao/{p['id']}/storico", base_url=ENTE))
        self.assertEqual(storico[0]["campi"]["stato"], ["APERTO", "CHIUSO"])
        self.assertEqual(storico[0]["nota"], "Approvato")
        # vuoto: si elimina
        self._ok(amm.delete(f"{API}/piao/{p['id']}", base_url=ENTE), 204)

    def test_obiettivi_azioni_misure(self):
        amm, dirig, resp = self._client("amm"), self._client("dirigente"), self._client("responsabile")
        p = self._piao(amm, 2026)
        anno = 2026
        nuovo = {"piao_id": p["id"], "anno": anno, "titolo": "Digitalizzare i concorsi", "tipo": "OPERATIVO",
                 "codice": "P2_OS3_OO1_OG1_26_2", "impegno": 60}  # fmt: skip

        # anno fuori dal triennio; struttura altrui; senza struttura
        self.assertEqual(resp.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "anno": 2029}).status_code, 422)
        self.assertEqual(resp.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "struttura_id": self.altra}).status_code, 403)
        self.assertEqual(self._client("senzastruttura").post(f"{API}/obiettivi", base_url=ENTE, json=nuovo).status_code, 422)

        o = self._ok(resp.post(f"{API}/obiettivi", base_url=ENTE, json=nuovo), 201)
        self.assertEqual((o["struttura_id"], o["completamento"], o["completo"]), (self.uo, None, False))
        # impegni della struttura nell'anno: non oltre 100
        r = resp.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "titolo": "Altro", "impegno": 50})
        self.assertEqual(r.status_code, 422)
        self.assertIn("disponibile 40%", r.get_json()["detail"])
        o2 = self._ok(resp.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "titolo": "Formazione", "codice": None, "impegno": 40}), 201)
        # un altro anno ha il suo 100
        self._ok(resp.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "anno": 2027, "impegno": 100}), 201)

        # azioni e misure
        oggi = date.today()
        url = f"{API}/obiettivi/{o['id']}/elementi"
        self.assertEqual(resp.post(url, base_url=ENTE, json={"tipo": "AZIONE", "impegno": 10, "scadenza": str(oggi)}).status_code, 422)
        az = self._ok(resp.post(url, base_url=ENTE, json={"tipo": "AZIONE", "descrizione": "Piattaforma online",
                                                          "impegno": 70, "completamento": 50,
                                                          "scadenza": str(oggi - timedelta(days=1))}), 201)  # fmt: skip
        self.assertTrue(az["in_ritardo"])
        self.assertEqual(resp.post(url, base_url=ENTE, json={"tipo": "AZIONE", "descrizione": "x", "impegno": 40,
                                                             "scadenza": str(oggi)}).status_code, 422)  # fmt: skip
        misura = self._misura()
        disponibili = self._ok(resp.get(f"{API}/misure?struttura_id={self.uo}", base_url=ENTE))
        self.assertEqual(disponibili[0]["id"], misura["id"])
        self.assertEqual(resp.post(url, base_url=ENTE, json={"tipo": "MISURA", "impegno": 30, "scadenza": str(oggi)}).status_code, 422)
        mi = self._ok(resp.post(url, base_url=ENTE, json={"tipo": "MISURA", "misura_id": misura["id"], "impegno": 30,
                                                          "completamento": 100, "scadenza": str(oggi + timedelta(days=30))}), 201)  # fmt: skip
        self.assertEqual((mi["misura_codice"], mi["descrizione"]), (misura["codice"], "Rotazione dei commissari"))
        self.assertEqual(resp.post(url, base_url=ENTE, json={"tipo": "MISURA", "misura_id": misura["id"], "impegno": 0,
                                                             "scadenza": str(oggi)}).status_code, 409)  # fmt: skip

        # completamento: 70*50 + 30*100 = 65
        d = self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertEqual((d["completamento"], d["completo"], d["ritardi"], d["azioni"], d["misure"]), (65.0, True, 1, 1, 1))
        self.assertEqual([x["tipo"] for x in d["elementi"]], ["AZIONE", "MISURA"])  # per scadenza
        # controlli oggettivi: la misura è della struttura dell'obiettivo, impegni non a zero
        self.assertFalse(any("altra struttura" in c["testo"] or "impegno 0%" in c["testo"] for c in d["controlli"]), d["controlli"])
        self.assertIn("avvisi", d)
        elenco = self._ok(resp.get(f"{API}/obiettivi?piao_id={p['id']}&anno={anno}&struttura_id={self.uo}", base_url=ENTE))
        # struttura: 60*65 + 40*0 = 39
        self.assertEqual((elenco["impegno_totale"], elenco["completo"], elenco["completamento"], elenco["modificabile"]),
                         (100, True, 39.0, True))  # fmt: skip

        # modifiche tracciate: prima e dopo, con la nota
        self._ok(resp.put(f"{API}/elementi/{az['id']}", base_url=ENTE, json={
            "descrizione": "Piattaforma online dei concorsi", "impegno": 70, "completamento": 100,
            "scadenza": str(oggi + timedelta(days=10)), "nota": "Rilasciata"}))  # fmt: skip
        self._ok(resp.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json={**nuovo, "impegno": 55, "nota": "Ripesato"}))
        self.assertEqual(resp.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json={**nuovo, "impegno": 61}).status_code, 422)
        storico = self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))
        self.assertEqual([(m["oggetto"], m["azione"]) for m in storico][:2], [("OBIETTIVO", "MODIFICATO"), ("AZIONE", "MODIFICATO")])
        self.assertEqual(storico[0]["campi"], {"impegno": [60, 55]})
        self.assertEqual(storico[1]["campi"]["completamento"], [50, 100])
        self.assertEqual(storico[1]["nota"], "Rilasciata")
        self.assertEqual(storico[1]["utente"], "Responsabile")
        self.assertEqual({(m["oggetto"], m["azione"]) for m in storico[2:]},
                         {("OBIETTIVO", "CREATO"), ("AZIONE", "CREATO"), ("MISURA", "CREATO")})  # fmt: skip
        # nessun cambiamento: nessuna voce
        self._ok(resp.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json={**nuovo, "impegno": 55}))
        self.assertEqual(len(self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))), len(storico))

        # il dirigente vede l'ufficio sottostante ma non lo modifica; l'altro settore non lo vede
        vista = self._ok(dirig.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertFalse(vista["modificabile"])
        self.assertEqual(dirig.put(f"{API}/elementi/{az['id']}", base_url=ENTE, json={
            "impegno": 70, "completamento": 0, "scadenza": str(oggi)}).status_code, 403)  # fmt: skip
        self.assertEqual(self._client("senzastruttura").get(f"{API}/obiettivi/{o['id']}", base_url=ENTE).status_code, 404)
        riepilogo = self._ok(dirig.get(f"{API}/riepilogo?piao_id={p['id']}&anno={anno}", base_url=ENTE))
        self.assertEqual([(r["struttura_id"], r["obiettivi"], r["obiettivi_incompleti"]) for r in riepilogo], [(self.uo, 2, 1)])
        # l'amministratore vede e corregge tutto
        self._ok(amm.put(f"{API}/elementi/{mi['id']}", base_url=ENTE, json={
            "impegno": 30, "completamento": 80, "scadenza": mi["scadenza"]}))  # fmt: skip

        # eliminazione: resta nello storico del PIAO
        self._ok(resp.delete(f"{API}/obiettivi/{o2['id']}", base_url=ENTE, json={"nota": "Non più previsto"}), 204)
        voci = self._ok(amm.get(f"{API}/piao/{p['id']}/storico", base_url=ENTE))
        self.assertTrue(any(v["oggetto_id"] == o2["id"] and v["azione"] == "ELIMINATO" and v["nota"] == "Non più previsto"
                            for v in voci))  # fmt: skip
        self.assertEqual(amm.delete(f"{API}/piao/{p['id']}", base_url=ENTE).status_code, 409)  # ha obiettivi

        # PIAO chiuso: sola lettura per tutti
        self._ok(amm.put(f"{API}/piao/{p['id']}", base_url=ENTE, json={"titolo": p["titolo"], "stato": "CHIUSO"}))
        self.assertFalse(self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))["modificabile"])
        self.assertEqual(resp.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json=nuovo).status_code, 409)
        self.assertEqual(amm.delete(f"{API}/elementi/{az['id']}", base_url=ENTE).status_code, 409)
        self.assertEqual(resp.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "anno": 2028}).status_code, 409)

    def test_permessi_e_separazione(self):
        amm = self._client("amm")
        p = self._piao(amm, 2040)
        self.assertEqual(self._client("rpct").get(f"{API}/piao", base_url=ENTE).status_code, 403)
        self.assertEqual(self._client("amm", SENZA_MODULO).get(f"{API}/piao", base_url=SENZA_MODULO).status_code, 403)
        altro = self._client("amm", ALTRO)
        self.assertEqual(self._ok(altro.get(f"{API}/piao", base_url=ALTRO)), [])
        self.assertEqual(altro.get(f"{API}/obiettivi?piao_id={p['id']}", base_url=ALTRO).status_code, 404)
        # senza il modulo anticorruzione niente misure
        self.assertEqual(self._ok(altro.get(f"{API}/misure", base_url=ALTRO)), [])
        self.assertFalse(self._ok(altro.get(f"{API}/contesto", base_url=ALTRO))["misure"])
        contesto = self._ok(self._client("dirigente").get(f"{API}/contesto", base_url=ENTE))
        self.assertEqual((contesto["amministratore"], sorted(contesto["visibili"])), (False, sorted([self.settore, self.uo])))


if __name__ == "__main__":
    unittest.main()
