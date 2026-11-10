"""Modulo performance via HTTP: PIAO (solo l'amministratore, triennio, chiuso in sola lettura),
obiettivi annuali della propria struttura (il dirigente vede quelli delle sottostanti senza
modificarli), iter di approvazione (proposte dei responsabili, decise dall'approvatore), impegni che non superano 100, completamento calcolato, azioni e misure della
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
                    (ente, "approvatore", [Ruolo.PERFORMANCE_APPROVATORE], None),
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
        """Modifiche dirette dell'approvatore; avanzamento del responsabile."""
        amm, appr = self._client("amm"), self._client("approvatore")
        dirig, resp = self._client("dirigente"), self._client("responsabile")
        p = self._piao(amm, 2026)
        anno = 2026
        nuovo = {"piao_id": p["id"], "anno": anno, "struttura_id": self.uo, "titolo": "Digitalizzare i concorsi",
                 "tipo": "OPERATIVO", "codice": "P2_OS3_OO1_OG1_26_2", "impegno": 60}  # fmt: skip

        # solo l'approvatore modifica direttamente; anno fuori dal triennio
        self.assertEqual(resp.post(f"{API}/obiettivi", base_url=ENTE, json=nuovo).status_code, 403)
        self.assertEqual(amm.post(f"{API}/obiettivi", base_url=ENTE, json=nuovo).status_code, 403)
        self.assertEqual(appr.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "anno": 2029}).status_code, 422)

        o = self._ok(appr.post(f"{API}/obiettivi", base_url=ENTE, json=nuovo), 201)
        self.assertEqual((o["struttura_id"], o["completamento"], o["completo"]), (self.uo, None, False))
        # impegni della struttura nell'anno: non oltre 100
        r = appr.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "titolo": "Altro", "impegno": 50})
        self.assertEqual(r.status_code, 422)
        self.assertIn("disponibile 40%", r.get_json()["detail"])
        o2 = self._ok(appr.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "titolo": "Formazione", "codice": None, "impegno": 40}), 201)
        # un altro anno ha il suo 100
        self._ok(appr.post(f"{API}/obiettivi", base_url=ENTE, json={**nuovo, "anno": 2027, "impegno": 100}), 201)

        # azioni e misure
        oggi = date.today()
        url = f"{API}/obiettivi/{o['id']}/elementi"
        self.assertEqual(resp.post(url, base_url=ENTE, json={"tipo": "AZIONE", "descrizione": "x", "impegno": 10,
                                                             "scadenza": str(oggi)}).status_code, 403)  # fmt: skip
        self.assertEqual(appr.post(url, base_url=ENTE, json={"tipo": "AZIONE", "impegno": 10, "scadenza": str(oggi)}).status_code, 422)
        az = self._ok(appr.post(url, base_url=ENTE, json={"tipo": "AZIONE", "descrizione": "Piattaforma online",
                                                          "impegno": 70, "completamento": 50,
                                                          "scadenza": str(oggi - timedelta(days=1))}), 201)  # fmt: skip
        self.assertTrue(az["in_ritardo"])
        self.assertEqual(appr.post(url, base_url=ENTE, json={"tipo": "AZIONE", "descrizione": "x", "impegno": 40,
                                                             "scadenza": str(oggi)}).status_code, 422)  # fmt: skip
        misura = self._misura()
        disponibili = self._ok(resp.get(f"{API}/misure?struttura_id={self.uo}", base_url=ENTE))
        self.assertEqual(disponibili[0]["id"], misura["id"])
        self.assertEqual(appr.post(url, base_url=ENTE, json={"tipo": "MISURA", "impegno": 30, "scadenza": str(oggi)}).status_code, 422)
        mi = self._ok(appr.post(url, base_url=ENTE, json={"tipo": "MISURA", "misura_id": misura["id"], "impegno": 30,
                                                          "completamento": 100, "scadenza": str(oggi + timedelta(days=30))}), 201)  # fmt: skip
        self.assertEqual((mi["misura_codice"], mi["descrizione"]), (misura["codice"], "Rotazione dei commissari"))
        self.assertEqual(appr.post(url, base_url=ENTE, json={"tipo": "MISURA", "misura_id": misura["id"], "impegno": 0,
                                                             "scadenza": str(oggi)}).status_code, 409)  # fmt: skip

        # completamento: 70*50 + 30*100 = 65
        d = self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertEqual((d["completamento"], d["completo"], d["ritardi"], d["azioni"], d["misure"]), (65.0, True, 1, 1, 1))
        self.assertEqual((d["modificabile"], d["proponibile"], d["avanzamento"], d["proposta"]), (False, True, True, None))
        self.assertTrue(self._ok(appr.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))["modificabile"])
        self.assertEqual([x["tipo"] for x in d["elementi"]], ["AZIONE", "MISURA"])  # per scadenza
        # controlli oggettivi: la misura è della struttura dell'obiettivo, impegni non a zero
        self.assertFalse(any("altra struttura" in c["testo"] or "impegno 0%" in c["testo"] for c in d["controlli"]), d["controlli"])
        self.assertIn("avvisi", d)
        elenco = self._ok(resp.get(f"{API}/obiettivi?piao_id={p['id']}&anno={anno}&struttura_id={self.uo}", base_url=ENTE))
        # struttura: 60*65 + 40*0 = 39
        self.assertEqual((elenco["impegno_totale"], elenco["completo"], elenco["completamento"], elenco["aggiunta"]),
                         (100, True, 39.0, "PROPOSTA"))  # fmt: skip
        aggiunta = self._ok(appr.get(f"{API}/obiettivi?piao_id={p['id']}&anno={anno}&struttura_id={self.uo}", base_url=ENTE))["aggiunta"]
        self.assertEqual(aggiunta, "DIRETTA")

        # modifiche tracciate: prima e dopo, con la nota
        self._ok(appr.put(f"{API}/elementi/{az['id']}", base_url=ENTE, json={
            "descrizione": "Piattaforma online dei concorsi", "impegno": 70, "completamento": 50,
            "scadenza": str(oggi + timedelta(days=10)), "nota": "Rinviata"}))  # fmt: skip
        # l'avanzamento: il responsabile lo aggiorna senza approvazione
        self.assertEqual(resp.put(f"{API}/elementi/{az['id']}", base_url=ENTE, json={
            "impegno": 70, "completamento": 100, "scadenza": str(oggi)}).status_code, 403)  # fmt: skip
        self._ok(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={"completamento": 100, "nota": "Rilasciata"}))
        self._ok(appr.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json={**nuovo, "impegno": 55, "nota": "Ripesato"}))
        self.assertEqual(appr.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json={**nuovo, "impegno": 61}).status_code, 422)
        storico = self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))
        self.assertEqual([(m["oggetto"], m["azione"]) for m in storico][:3],
                         [("OBIETTIVO", "MODIFICATO"), ("AZIONE", "MODIFICATO"), ("AZIONE", "MODIFICATO")])  # fmt: skip
        self.assertEqual(storico[0]["campi"], {"impegno": [60, 55]})
        self.assertEqual((storico[1]["campi"], storico[1]["nota"], storico[1]["utente"]),
                         ({"completamento": [50, 100]}, "Rilasciata", "Responsabile"))  # fmt: skip
        self.assertEqual(storico[2]["utente"], "Approvatore")
        self.assertEqual({(m["oggetto"], m["azione"]) for m in storico[3:]},
                         {("OBIETTIVO", "CREATO"), ("AZIONE", "CREATO"), ("MISURA", "CREATO")})  # fmt: skip
        # nessun cambiamento: nessuna voce
        self._ok(appr.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json={**nuovo, "impegno": 55}))
        self._ok(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={"completamento": 100}))
        self.assertEqual(len(self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))), len(storico))

        # il dirigente vede l'ufficio sottostante ma non lo modifica né lo propone; l'altro settore non lo vede
        vista = self._ok(dirig.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertEqual((vista["modificabile"], vista["proponibile"], vista["avanzamento"]), (False, False, False))
        self.assertEqual(dirig.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={"completamento": 0}).status_code, 403)
        self.assertEqual(self._client("senzastruttura").get(f"{API}/obiettivi/{o['id']}", base_url=ENTE).status_code, 404)
        riepilogo = self._ok(dirig.get(f"{API}/riepilogo?piao_id={p['id']}&anno={anno}", base_url=ENTE))
        self.assertEqual([(r["struttura_id"], r["obiettivi"], r["obiettivi_incompleti"]) for r in riepilogo], [(self.uo, 2, 1)])
        # l'amministratore vede tutto e aggiorna l'avanzamento
        self._ok(amm.put(f"{API}/elementi/{mi['id']}/avanzamento", base_url=ENTE, json={"completamento": 80}))

        # eliminazione: resta nello storico del PIAO
        self.assertEqual(resp.delete(f"{API}/obiettivi/{o2['id']}", base_url=ENTE).status_code, 403)
        self._ok(appr.delete(f"{API}/obiettivi/{o2['id']}", base_url=ENTE, json={"nota": "Non più previsto"}), 204)
        voci = self._ok(amm.get(f"{API}/piao/{p['id']}/storico", base_url=ENTE))
        self.assertTrue(any(v["oggetto_id"] == o2["id"] and v["azione"] == "ELIMINATO" and v["nota"] == "Non più previsto"
                            for v in voci))  # fmt: skip
        self.assertEqual(amm.delete(f"{API}/piao/{p['id']}", base_url=ENTE).status_code, 409)  # ha obiettivi

        # PIAO chiuso: sola lettura per tutti
        self._ok(amm.put(f"{API}/piao/{p['id']}", base_url=ENTE, json={"titolo": p["titolo"], "stato": "CHIUSO"}))
        chiuso = self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertEqual((chiuso["proponibile"], chiuso["avanzamento"]), (False, False))
        self.assertEqual(appr.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json=nuovo).status_code, 409)
        self.assertEqual(appr.delete(f"{API}/elementi/{az['id']}", base_url=ENTE).status_code, 409)
        self.assertEqual(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={"completamento": 0}).status_code, 409)
        self.assertEqual(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "ELIMINA", "obiettivo_id": o["id"]}).status_code, 409)

    def test_proposte(self):
        """Iter di approvazione: creazione, modifica (con le azioni e misure), eliminazione;
        bozza, invio, restituzione, ritiro, scarto; modifiche fatte nel frattempo."""
        amm, appr = self._client("amm"), self._client("approvatore")
        dirig, resp = self._client("dirigente"), self._client("responsabile")
        p = self._piao(amm, 2050)
        anno, oggi = 2050, date.today()
        scad = str(date(anno, 6, 30))
        misura = self._misura()
        base = {"piao_id": p["id"], "anno": anno, "struttura_id": self.uo}
        obiettivo = {"titolo": "Ridurre i tempi", "codice": "OB1", "tipo": "OPERATIVO", "impegno": 70, "elementi": [
            {"tipo": "AZIONE", "descrizione": "Nuova procedura", "impegno": 60, "scadenza": scad},
            {"tipo": "MISURA", "misura_id": misura["id"], "impegno": 40, "scadenza": scad},
        ]}  # fmt: skip

        # creazione: nasce in bozza, non è ancora un obiettivo
        self.assertEqual(resp.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "CREA", **base, "dati": {**obiettivo, "impegno": 101}}).status_code, 422)  # fmt: skip
        self.assertEqual(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "CREA", **base, "dati": {
            **obiettivo, "elementi": [{"tipo": "AZIONE", "impegno": 10, "scadenza": scad}]}}).status_code, 422)  # fmt: skip
        self.assertEqual(resp.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "CREA", **base, "struttura_id": self.altra, "dati": obiettivo}).status_code, 403)  # fmt: skip
        self.assertEqual(appr.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "CREA", **base, "dati": obiettivo}).status_code, 403)
        pr = self._ok(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "CREA", **base, "dati": obiettivo}), 201)
        self.assertEqual((pr["stato"], pr["titolo"], pr["modificabile"], pr["inviabile"], pr["decidibile"]),
                         ("BOZZA", "OB1 - Ridurre i tempi", True, True, False))  # fmt: skip
        self.assertEqual([x["misura_codice"] for x in pr["dati"]["elementi"]], [None, misura["codice"]])
        self.assertTrue(all(x["id"].startswith("nuovo-") for x in pr["dati"]["elementi"]))
        elenco = self._ok(resp.get(f"{API}/obiettivi?piao_id={p['id']}&anno={anno}&struttura_id={self.uo}", base_url=ENTE))
        self.assertEqual((elenco["obiettivi"], [x["id"] for x in elenco["proposte"]]), ([], [pr["id"]]))
        # la bozza la vede solo la struttura
        self.assertEqual(self._ok(appr.get(f"{API}/proposte?piao_id={p['id']}", base_url=ENTE)), [])
        self.assertEqual(self._ok(dirig.get(f"{API}/proposte?piao_id={p['id']}", base_url=ENTE)), [])

        # correzione in bozza, poi invio
        dati = {**pr["dati"], "descrizione": "Entro 30 giorni"}
        pr = self._ok(resp.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": dati, "nota": "Prima versione"}))
        self.assertEqual(pr["dati"]["descrizione"], "Entro 30 giorni")
        self.assertEqual(appr.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}).status_code, 409)  # bozza
        pr = self._ok(resp.post(f"{API}/proposte/{pr['id']}/invia", base_url=ENTE, json={}))
        self.assertEqual((pr["stato"], pr["modificabile"], pr["ritirabile"]), ("INVIATA", False, True))
        self.assertEqual(resp.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": dati}).status_code, 409)
        self.assertEqual(self._ok(appr.get(f"{API}/contesto", base_url=ENTE))["da_decidere"], 1)
        self.assertTrue(self._ok(appr.get(f"{API}/proposte/{pr['id']}", base_url=ENTE))["decidibile"])
        self.assertEqual(resp.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}).status_code, 403)
        self.assertEqual(amm.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}).status_code, 403)

        # restituita (serve la motivazione), corretta e reinviata, approvata
        self.assertEqual(appr.post(f"{API}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={}).status_code, 422)
        pr = self._ok(appr.post(f"{API}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={"motivazione": "Indica il codice PIAO"}))
        self.assertEqual((pr["stato"], pr["motivazione"], pr["modificabile"]), ("RESTITUITA", "Indica il codice PIAO", False))
        pr = self._ok(resp.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": {**dati, "codice": "P2_OB1"}}))
        pr = self._ok(resp.post(f"{API}/proposte/{pr['id']}/invia", base_url=ENTE, json={"nota": "Codice aggiunto"}))
        pr = self._ok(appr.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={"motivazione": "Coerente col PIAO"}))
        self.assertEqual((pr["stato"], pr["autore"]), ("APPROVATA", "Responsabile"))
        o = self._ok(resp.get(f"{API}/obiettivi/{pr['obiettivo_id']}", base_url=ENTE))
        self.assertEqual((o["codice"], o["impegno"], o["descrizione"], o["proposta"]), ("P2_OB1", 70, "Entro 30 giorni", None))
        self.assertEqual([(x["tipo"], x["impegno"], x["completamento"]) for x in o["elementi"]], [("AZIONE", 60, 0), ("MISURA", 40, 0)])
        storico = self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))
        self.assertEqual({(m["oggetto"], m["azione"], m["utente"]) for m in storico},
                         {("OBIETTIVO", "CREATO", "Approvatore"), ("AZIONE", "CREATO", "Approvatore"), ("MISURA", "CREATO", "Approvatore")})  # fmt: skip
        self.assertIn("Proposta di Responsabile approvata", storico[0]["nota"])
        self.assertIn("Coerente col PIAO", storico[0]["nota"])
        self.assertEqual(self._ok(appr.get(f"{API}/contesto", base_url=ENTE))["da_decidere"], 0)
        azione, mis = o["elementi"]

        # modifica: nasce in bozza con l'obiettivo com'è; senza cambiamenti non si invia; una sola aperta
        pm = self._ok(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "MODIFICA", "obiettivo_id": o["id"]}), 201)
        self.assertEqual(pm["dati"], pm["prima"])
        self.assertEqual(resp.post(f"{API}/proposte/{pm['id']}/invia", base_url=ENTE, json={}).status_code, 422)
        self.assertEqual(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "ELIMINA", "obiettivo_id": o["id"]}).status_code, 409)
        vista = self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertEqual((vista["proposta"], vista["proponibile"]), ({"id": pm["id"], "tipo": "MODIFICA", "stato": "BOZZA"}, False))
        # l'avanzamento resta libero e non tocca la proposta
        self._ok(resp.put(f"{API}/elementi/{azione['id']}/avanzamento", base_url=ENTE, json={"completamento": 50}))
        self.assertFalse(self._ok(resp.get(f"{API}/proposte/{pm['id']}", base_url=ENTE))["cambiato"])
        # azione ripesata, misura tolta, nuova azione
        nuovi = {**pm["dati"], "elementi": [
            {**pm["dati"]["elementi"][0], "impegno": 70},
            {"tipo": "AZIONE", "descrizione": "Formazione", "impegno": 30, "scadenza": scad},
        ]}  # fmt: skip
        pm = self._ok(resp.put(f"{API}/proposte/{pm['id']}", base_url=ENTE, json={"dati": nuovi}))
        stati = {x["stato"] for x in pm["confronto"]["elementi"]}
        self.assertEqual(stati, {"MODIFICATO", "NUOVO", "ELIMINATO"})
        self.assertEqual(next(x for x in pm["confronto"]["elementi"] if x["id"] == azione["id"])["campi"], {"impegno": [60, 70]})
        pm = self._ok(resp.post(f"{API}/proposte/{pm['id']}/invia", base_url=ENTE, json={"nota": "Ripianificato"}))
        # ritirata torna in bozza, poi di nuovo inviata
        pm = self._ok(resp.post(f"{API}/proposte/{pm['id']}/ritira", base_url=ENTE, json={}))
        self.assertEqual(pm["stato"], "BOZZA")
        pm = self._ok(resp.post(f"{API}/proposte/{pm['id']}/invia", base_url=ENTE, json={}))
        # l'approvatore cambia l'obiettivo nel frattempo: l'approvazione chiede conferma
        self._ok(appr.put(f"{API}/obiettivi/{o['id']}", base_url=ENTE, json={**{k: o[k] for k in ("codice", "titolo", "tipo")},
                                                                               "impegno": 80}))  # fmt: skip
        self.assertTrue(self._ok(appr.get(f"{API}/proposte/{pm['id']}", base_url=ENTE))["cambiato"])
        r = appr.post(f"{API}/proposte/{pm['id']}/approva", base_url=ENTE, json={})
        self.assertEqual(r.status_code, 409)
        self.assertIn("modificato dopo la proposta", r.get_json()["detail"])
        self._ok(appr.post(f"{API}/proposte/{pm['id']}/approva", base_url=ENTE, json={"forza": True}))
        o = self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertEqual(o["impegno"], 70)  # quello della proposta
        self.assertEqual(sorted((x["descrizione"], x["impegno"], x["completamento"]) for x in o["elementi"]),
                         [("Formazione", 30, 0), ("Nuova procedura", 70, 50)])  # l'avanzamento resta  # fmt: skip
        storico = self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))
        self.assertIn(("MISURA", "ELIMINATO"), [(m["oggetto"], m["azione"]) for m in storico])

        # bozza scartata
        pb = self._ok(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "MODIFICA", "obiettivo_id": o["id"]}), 201)
        self.assertEqual(dirig.delete(f"{API}/proposte/{pb['id']}", base_url=ENTE).status_code, 403)
        self._ok(resp.delete(f"{API}/proposte/{pb['id']}", base_url=ENTE), 204)

        # eliminazione: va subito all'approvatore; respinta resta, approvata elimina
        pe = self._ok(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "ELIMINA", "obiettivo_id": o["id"], "nota": "Superato"}), 201)
        self.assertEqual((pe["stato"], pe["dati"], pe["modificabile"]), ("INVIATA", None, False))
        self.assertEqual(appr.post(f"{API}/proposte/{pe['id']}/respingi", base_url=ENTE, json={"motivazione": ""}).status_code, 422)
        pe = self._ok(appr.post(f"{API}/proposte/{pe['id']}/respingi", base_url=ENTE, json={"motivazione": "Resta nel PIAO"}))
        self.assertEqual(pe["stato"], "RESPINTA")
        self.assertEqual(resp.post(f"{API}/proposte/{pe['id']}/invia", base_url=ENTE, json={}).status_code, 409)
        self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        pe = self._ok(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "ELIMINA", "obiettivo_id": o["id"]}), 201)
        self._ok(appr.post(f"{API}/proposte/{pe['id']}/approva", base_url=ENTE, json={}))
        self.assertEqual(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE).status_code, 404)
        voci = self._ok(amm.get(f"{API}/piao/{p['id']}/storico", base_url=ENTE))
        self.assertTrue(any(v["oggetto_id"] == o["id"] and v["azione"] == "ELIMINATO" for v in voci))

        # l'amministratore propone per qualsiasi struttura; elenco e riepilogo
        pa = self._ok(amm.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "CREA", **base, "struttura_id": self.altra, "dati": {**obiettivo, "elementi": []}}), 201)  # fmt: skip
        self._ok(amm.post(f"{API}/proposte/{pa['id']}/invia", base_url=ENTE, json={}))
        self.assertEqual(resp.get(f"{API}/proposte/{pa['id']}", base_url=ENTE).status_code, 404)  # altra struttura
        attesa = self._ok(appr.get(f"{API}/proposte?stato=INVIATA", base_url=ENTE))
        self.assertEqual([x["id"] for x in attesa], [pa["id"]])
        riepilogo = self._ok(appr.get(f"{API}/riepilogo?piao_id={p['id']}&anno={anno}", base_url=ENTE))
        self.assertEqual([(r["struttura_id"], r["obiettivi"], r["proposte"]) for r in riepilogo], [(self.altra, 0, 1)])
        tutte = self._ok(resp.get(f"{API}/proposte?piao_id={p['id']}", base_url=ENTE))
        self.assertEqual({x["stato"] for x in tutte}, {"APPROVATA", "RESPINTA"})

    def test_indicatori(self):
        """Indicatori di azioni e misure: definizione con l'obiettivo (anche nelle proposte),
        valori rilevati come avanzamento, completamento calcolato, storico, controlli."""
        amm, appr, resp = self._client("amm"), self._client("approvatore"), self._client("responsabile")
        p = self._piao(amm, 2060)
        anno, scad = 2060, "2060-12-31"
        o = self._ok(appr.post(f"{API}/obiettivi", base_url=ENTE, json={
            "piao_id": p["id"], "anno": anno, "struttura_id": self.uo, "titolo": "Valorizzazione", "impegno": 50}), 201)  # fmt: skip
        eventi = {"descrizione": "Eventi a cui si partecipa", "tipo": "NUMERO", "unita": "eventi", "target": 3}
        # definizioni non valide
        for errato in [{**eventi, "target": None}, {**eventi, "partenza": 5}, {**eventi, "tipo": "PERCENTUALE", "target": 120},
                       {"descrizione": "Entro giugno", "tipo": "DATA"},
                       {"descrizione": "Attese", "tipo": "NUMERO", "target": 30, "partenza": 20, "verso": "DECRESCENTE"}]:
            self.assertEqual(appr.post(f"{API}/obiettivi/{o['id']}/elementi", base_url=ENTE, json={
                "tipo": "AZIONE", "descrizione": "Partecipazione", "impegno": 60, "scadenza": scad,
                "indicatori": [errato]}).status_code, 422, errato)  # fmt: skip
        az = self._ok(appr.post(f"{API}/obiettivi/{o['id']}/elementi", base_url=ENTE, json={
            "tipo": "AZIONE", "descrizione": "Partecipazione a eventi", "impegno": 60, "scadenza": scad, "completamento": 90,
            "indicatori": [{**eventi, "fonte": "Registro eventi"}]}), 201)  # fmt: skip
        self.assertEqual((az["calcolato"], az["completamento"]), (True, 0))  # il completamento a mano non conta
        ind = az["indicatori"][0]
        self.assertEqual((ind["testo"], ind["partenza"], ind["verso"], ind["raggiungimento"]),
                         ("Eventi a cui si partecipa: 3 eventi", None, "CRESCENTE", 0.0))  # fmt: skip
        senza = self._ok(appr.post(f"{API}/obiettivi/{o['id']}/elementi", base_url=ENTE, json={
            "tipo": "AZIONE", "descrizione": "Comunicazione", "impegno": 40, "scadenza": scad}), 201)  # fmt: skip
        vista = self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))
        self.assertEqual(vista["senza_indicatori"], 1)
        self.assertTrue(any("nessun indicatore" in c["testo"] for c in vista["controlli"]))

        # avanzamento: valori rilevati, completamento calcolato
        self._ok(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={
            "indicatori": [{"id": ind["id"], "rilevato": 2}], "nota": "Fiera e convegno"}))  # fmt: skip
        x = self._ok(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={"completamento": 100}))
        self.assertEqual((x["completamento"], x["indicatori"][0]["rilevato"], x["indicatori"][0]["raggiungimento"]), (67, 2, 66.7))
        self.assertIsNotNone(x["indicatori"][0]["rilevato_il"])
        self.assertEqual(resp.put(f"{API}/elementi/{senza['id']}/avanzamento", base_url=ENTE, json={}).status_code, 422)
        self._ok(resp.put(f"{API}/elementi/{senza['id']}/avanzamento", base_url=ENTE, json={"completamento": 50}))
        self.assertEqual(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={
            "indicatori": [{"id": "inesistente", "rilevato": 1}]}).status_code, 422)  # fmt: skip
        # 60*67 + 40*50 = 60.2
        self.assertEqual(self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))["completamento"], 60.2)
        storico = self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))
        rilevazione = next(m for m in storico if m["oggetto"] == "INDICATORE" and m["azione"] == "MODIFICATO")
        self.assertEqual((rilevazione["campi"], rilevazione["nota"]), ({"rilevato": [None, "2 eventi"]}, "Fiera e convegno"))
        self.assertIn(({"completamento": [0, 67]}), [m["campi"] for m in storico if m["oggetto"] == "AZIONE"])

        # modifica diretta: un secondo indicatore sì/no; il primo resta con il suo rilevato
        x = self._ok(appr.put(f"{API}/elementi/{az['id']}", base_url=ENTE, json={
            "descrizione": "Partecipazione a eventi", "impegno": 60, "scadenza": scad,
            "indicatori": [{**eventi, "id": ind["id"]}, {"descrizione": "Report pubblicato", "tipo": "SI_NO", "target": 7}]}))  # fmt: skip
        self.assertEqual([(i["id"] == ind["id"], i["rilevato"], i["target"]) for i in x["indicatori"]],
                         [(True, 2, 3), (False, None, None)])  # fmt: skip
        self.assertEqual(x["completamento"], 33)  # (66.7 + 0) / 2
        si_no = x["indicatori"][1]
        self.assertEqual(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={
            "indicatori": [{"id": si_no["id"], "rilevato": 2}]}).status_code, 422)  # fmt: skip
        x = self._ok(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={
            "indicatori": [{"id": si_no["id"], "rilevato": 1}]}))  # fmt: skip
        self.assertEqual(x["completamento"], 83)

        # proposta: target da 3 a 5, il sì/no diventa una data; il rilevato degli eventi resta
        pm = self._ok(resp.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "MODIFICA", "obiettivo_id": o["id"]}), 201)
        el = next(e for e in pm["dati"]["elementi"] if e["id"] == az["id"])
        self.assertEqual([i["id"] for i in el["indicatori"]], [ind["id"], si_no["id"]])
        self.assertNotIn("rilevato", el["indicatori"][0])
        nuovi_ind = [{**el["indicatori"][0], "target": 5},
                     {**el["indicatori"][1], "descrizione": "Report pubblicato", "tipo": "DATA", "target_data": "2060-06-30"}]
        dati = {**pm["dati"], "elementi": [e if e["id"] != az["id"] else {**e, "indicatori": nuovi_ind} for e in pm["dati"]["elementi"]]}
        pm = self._ok(resp.put(f"{API}/proposte/{pm['id']}", base_url=ENTE, json={"dati": dati}))
        campi = next(c for c in pm["confronto"]["elementi"] if c["id"] == az["id"])["campi"]
        self.assertEqual(campi["indicatori"], [["Eventi a cui si partecipa: 3 eventi", "Report pubblicato: sì"],
                                               ["Eventi a cui si partecipa: 5 eventi", "Report pubblicato: entro il 30/06/2060"]])  # fmt: skip
        self._ok(resp.post(f"{API}/proposte/{pm['id']}/invia", base_url=ENTE, json={}))
        self._ok(appr.post(f"{API}/proposte/{pm['id']}/approva", base_url=ENTE, json={}))
        x = next(e for e in self._ok(resp.get(f"{API}/obiettivi/{o['id']}", base_url=ENTE))["elementi"] if e["id"] == az["id"])
        self.assertEqual([(i["target"], i["target_data"], i["rilevato"]) for i in x["indicatori"]],
                         [(5, None, 2), (None, "2060-06-30", None)])  # fmt: skip
        self.assertEqual(x["completamento"], 20)  # (40 + 0) / 2
        x = self._ok(resp.put(f"{API}/elementi/{az['id']}/avanzamento", base_url=ENTE, json={
            "indicatori": [{"id": si_no["id"], "rilevato_data": "2060-05-15"}]}))  # fmt: skip
        self.assertEqual(x["completamento"], 70)
        storico = self._ok(resp.get(f"{API}/obiettivi/{o['id']}/storico", base_url=ENTE))
        modifica = next(m for m in storico if m["oggetto"] == "INDICATORE" and m["campi"].get("target"))
        self.assertEqual(modifica["campi"]["target"], [3, 5])

        # indicatore decrescente in una proposta di creazione; misura con l'indicatore della mappatura
        attese = {"descrizione": "Giorni medi di attesa", "tipo": "NUMERO", "unita": "giorni", "partenza": 40, "target": 30,
                  "verso": "DECRESCENTE"}
        pc = self._ok(resp.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "CREA", "piao_id": p["id"], "anno": anno, "struttura_id": self.uo,
            "dati": {"titolo": "Tempi", "impegno": 50, "elementi": [
                {"tipo": "AZIONE", "descrizione": "Riorganizzazione", "impegno": 100, "scadenza": scad, "indicatori": [attese]}]}}), 201)  # fmt: skip
        self.assertEqual(pc["dati"]["elementi"][0]["indicatori"][0]["verso"], "DECRESCENTE")
        self._ok(resp.post(f"{API}/proposte/{pc['id']}/invia", base_url=ENTE, json={}))
        pc = self._ok(appr.post(f"{API}/proposte/{pc['id']}/approva", base_url=ENTE, json={}))
        nuovo = self._ok(resp.get(f"{API}/obiettivi/{pc['obiettivo_id']}", base_url=ENTE))
        x = nuovo["elementi"][0]
        self.assertEqual(x["indicatori"][0]["testo"], "Giorni medi di attesa: da 40 giorni a 30 giorni (più basso è meglio)")
        x = self._ok(resp.put(f"{API}/elementi/{x['id']}/avanzamento", base_url=ENTE, json={
            "indicatori": [{"id": x["indicatori"][0]["id"], "rilevato": 35}]}))  # fmt: skip
        self.assertEqual(x["completamento"], 50)
        riepilogo = self._ok(appr.get(f"{API}/riepilogo?piao_id={p['id']}&anno={anno}", base_url=ENTE))
        self.assertEqual([(r["obiettivi"], r["senza_indicatori"]) for r in riepilogo], [(2, 1)])
        misure = self._ok(resp.get(f"{API}/misure", base_url=ENTE))
        self.assertTrue(all("indicatore" in m and "target" in m for m in misure))

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
        self.assertEqual((contesto["amministratore"], contesto["approvatore"], sorted(contesto["visibili"])),
                         (False, False, sorted([self.settore, self.uo])))  # fmt: skip
        # l'approvatore vede tutto; chi ha solo il modulo anticorruzione no
        contesto = self._ok(self._client("approvatore").get(f"{API}/contesto", base_url=ENTE))
        self.assertEqual((contesto["approvatore"], contesto["visibili"]), (True, None))


if __name__ == "__main__":
    unittest.main()
