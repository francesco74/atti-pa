"""Modulo anticorruzione via HTTP: metodologia (standard e dell'ente, con il ricalcolo),
aree, mappatura processo -> attività -> rischio -> misura con i codici assegnati, valutazione
(parità verso il più alto, correzione motivata), filtri, eliminazione a cascata, proposte dei
referenti (creazione, modifica, eliminazione; restituzione, approvazione atomica, conflitti),
monitoraggio delle misure (per struttura e sottostanti, trasversali, verifica, cruscotto,
Excel), PIAO e obiettivi (importazione, collegamenti a processi e attività con l'eredità),
permessi per ruolo e modulo, separazione tra enti.
    cd api/tests && python test_anticorruzione_api.py
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


class AnticorruzioneApi(unittest.TestCase):
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
                ente = Ente(codice="lucca", nome="Comune", dati_json={}, moduli_json=[Modulo.ANTICORRUZIONE])
                altro = Ente(codice="altro", nome="Altro", dati_json={}, moduli_json=[Modulo.ANTICORRUZIONE])
                senza = Ente(codice="atti", nome="Atti", dati_json={}, moduli_json=[Modulo.REDAZIONE])
                db.add_all([ente, altro, senza])
                await db.flush()
                settore = Struttura(ente_id=ente.id, codice="SETTORE 2", descrizione="Risorse umane")
                db.add(settore)
                await db.flush()
                uo = Struttura(ente_id=ente.id, codice="U.O. 2.1", descrizione="Personale", padre_id=settore.id)
                db.add(uo)
                await db.flush()
                cls.settore, cls.uo = settore.id, uo.id
                for dominio, e in [("lucca.example.it", ente), ("altro.example.it", altro), ("atti.example.it", senza)]:
                    db.add(EnteDominio(dominio=dominio, ente_id=e.id))
                for e, username, ruoli in [
                    (ente, "rpct", [Ruolo.ANTICORRUZIONE_RPCT]),
                    (ente, "referente", [Ruolo.ANTICORRUZIONE_REFERENTE]),
                    (ente, "dirigente", [Ruolo.ANTICORRUZIONE_REFERENTE]),
                    (ente, "redattore", [Ruolo.REDATTORE]),
                    (altro, "rpct", [Ruolo.ANTICORRUZIONE_RPCT]),
                    (senza, "rpct", [Ruolo.ANTICORRUZIONE_RPCT]),
                ]:
                    struttura = {"referente": uo.id, "dirigente": settore.id}.get(username) if e is ente else None
                    db.add(User(ente_id=e.id, username=username, origine="LOCALE", struttura_id=struttura,
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

    def _client(self, username, base=ENTE):
        c = self.app.test_client()
        r = c.post("/api/v1/auth/login", base_url=base, json={"username": username, "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return c

    def _ok(self, r, codice=200):
        self.assertEqual(r.status_code, codice, r.get_data(as_text=True)[:500])
        return r.get_json()

    def test_mappatura_e_valutazione(self):
        c = self._client("rpct")
        area = self._ok(c.post(f"{API}/aree", base_url=ENTE, json={
            "codice": "D", "descrizione": "Acquisizione e gestione del personale", "ordine": 4}), 201)  # fmt: skip
        p = self._ok(c.post(f"{API}/processi", base_url=ENTE, json={
            "area_id": area["id"], "denominazione": "Concorsi pubblici", "struttura_id": self.uo}), 201)  # fmt: skip
        self.assertEqual(p["codice"], "D.1")
        a = self._ok(c.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE,
                            json={"descrizione": "Nomina della commissione"}), 201)  # fmt: skip
        self.assertEqual(a["codice"], "D.1.1")
        r = self._ok(c.post(f"{API}/attivita/{a['id']}/rischi", base_url=ENTE,
                            json={"evento": "Commissari in conflitto di interessi"}), 201)  # fmt: skip
        self.assertEqual(r["codice"], "D.1.1_R.1")
        m = self._ok(c.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Dichiarazioni di assenza di conflitto", "tipo": "GENERALE",
            "categoria": "Disciplina del conflitto di interessi", "struttura_id": self.uo,
        }), 201)  # fmt: skip
        self.assertEqual(m["codice"], "D.1.1_R.1_M.1")
        self.assertEqual(c.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Pubblicazione", "obbligo_trasparenza": "ART_99"}).status_code, 422)  # fmt: skip
        self._ok(c.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Pubblicazione dei bandi", "categoria": "Trasparenza", "obbligo_trasparenza": "ART_23"}), 201)  # fmt: skip

        # valutazione: 4 Alto, 4 Medio, 1 Basso -> Alto (parità); impatto Medio -> Critico
        met = self._ok(c.get(f"{API}/metodologia", base_url=ENTE))
        self.assertTrue(met["standard"])
        prob = {i["id"]: "Alto" if int(i["id"]) <= 4 else "Medio" if int(i["id"]) <= 8 else "Basso"
                for i in met["indicatori_probabilita"]}  # fmt: skip
        imp = {i["id"]: "Medio" for i in met["indicatori_impatto"]}
        v = self._ok(c.put(f"{API}/rischi/{r['id']}/valutazione", base_url=ENTE,
                           json={"valori_probabilita": prob, "valori_impatto": imp}))  # fmt: skip
        self.assertEqual((v["probabilita"], v["livello"]), ("Alto", "Rischio Critico"))
        corpo = {"valori_probabilita": prob, "valori_impatto": imp, "probabilita": "Medio"}
        self.assertEqual(c.put(f"{API}/rischi/{r['id']}/valutazione", base_url=ENTE, json=corpo).status_code, 422)
        v = self._ok(c.put(f"{API}/rischi/{r['id']}/valutazione", base_url=ENTE,
                           json={**corpo, "motivazione_correzione": "Dati oggettivi di segno opposto"}))  # fmt: skip
        self.assertEqual((v["probabilita_calcolata"], v["probabilita"], v["livello"]), ("Alto", "Medio", "Rischio Medio"))

        # albero, elenco con conteggi e livello, filtri
        albero = self._ok(c.get(f"{API}/processi/{p['id']}", base_url=ENTE))
        self.assertEqual(len(albero["attivita"][0]["rischi"][0]["misure"]), 2)
        elenco = self._ok(c.get(f"{API}/processi", base_url=ENTE))
        voce = next(x for x in elenco if x["id"] == p["id"])
        self.assertEqual((voce["attivita"], voce["rischi"], voce["misure"], voce["livello_massimo"]),
                         (1, 1, 2, "Rischio Medio"))  # fmt: skip
        self.assertTrue(self._ok(c.get(f"{API}/processi?struttura={self.settore}", base_url=ENTE)))  # U.O. sotto il settore
        self.assertFalse(self._ok(c.get(f"{API}/processi?livello=Rischio Alto", base_url=ENTE)))
        self.assertTrue(self._ok(c.get(f"{API}/processi?testo=concors", base_url=ENTE)))

        # metodologia dell'ente: impatto Medio diventa Alto nella matrice -> ricalcolo
        nuova = {k: v for k, v in met.items() if k != "standard"}
        nuova["matrice"]["Medio"]["Medio"] = "Rischio Alto"
        self.assertEqual(self._ok(c.put(f"{API}/metodologia", base_url=ENTE, json=nuova))["ricalcolati"], 1)
        self.assertEqual(self._ok(c.get(f"{API}/processi/{p['id']}", base_url=ENTE))["attivita"][0]["rischi"][0]["livello"],
                         "Rischio Alto")  # corretta resta Medio/Medio  # fmt: skip
        nuova["matrice"]["Alto"].pop("Basso")
        self.assertEqual(c.put(f"{API}/metodologia", base_url=ENTE, json=nuova).status_code, 422)

        # il referente legge ma non modifica; l'area con processi non si elimina
        ref = self._client("referente")
        self.assertEqual(len(self._ok(ref.get(f"{API}/processi", base_url=ENTE))), len(elenco))
        self.assertEqual(ref.post(f"{API}/processi", base_url=ENTE, json={"denominazione": "x"}).status_code, 403)
        self.assertEqual(c.delete(f"{API}/aree/{area['id']}", base_url=ENTE).status_code, 409)

        # eliminazione a cascata
        self.assertEqual(c.delete(f"{API}/processi/{p['id']}", base_url=ENTE).status_code, 204)
        self.assertEqual(c.get(f"{API}/processi/{p['id']}", base_url=ENTE).status_code, 404)
        self.assertEqual(c.put(f"{API}/rischi/{r['id']}", base_url=ENTE, json={"evento": "x"}).status_code, 404)

    def test_accesso_ed_enti_separati(self):
        c = self._client("rpct")
        p = self._ok(c.post(f"{API}/processi", base_url=ENTE, json={"denominazione": "Trasversale"}), 201)
        self.assertEqual(p["codice"], "P.1")  # senza area
        altro = self._client("rpct", ALTRO)
        self.assertEqual(altro.get(f"{API}/processi/{p['id']}", base_url=ALTRO).status_code, 404)
        self.assertEqual(self._ok(altro.get(f"{API}/processi", base_url=ALTRO)), [])
        self.assertEqual(self._client("redattore").get(f"{API}/processi", base_url=ENTE).status_code, 403)
        senza = self._client("rpct", SENZA_MODULO)
        self.assertEqual(senza.get(f"{API}/processi", base_url=SENZA_MODULO).status_code, 403)
        self.assertTrue(any(o["id"] == "ART_23" for o in self._ok(c.get(f"{API}/obblighi", base_url=ENTE))))

    def _valutazione(self, c, valore="Basso"):
        met = self._ok(c.get(f"{API}/metodologia", base_url=ENTE))
        return {"valori_probabilita": {i["id"]: valore for i in met["indicatori_probabilita"]},
                "valori_impatto": {i["id"]: valore for i in met["indicatori_impatto"]}}  # fmt: skip

    def test_proposte(self):
        rpct, ref = self._client("rpct"), self._client("referente")
        area = self._ok(rpct.post(f"{API}/aree", base_url=ENTE, json={"codice": "C", "descrizione": "Contratti"}), 201)

        # il referente propone un processo nuovo con attività, rischio valutato e misura
        nuovo = {"processo": {"area_id": area["id"], "denominazione": "Affidamenti diretti"}, "attivita": [
            {"descrizione": "Scelta dell'operatore", "rischi": [
                {"evento": "Frazionamento artificioso", "valutazione": self._valutazione(ref, "Alto"),
                 "misure": [{"descrizione": "Verifica del frazionamento", "categoria": "Controllo"}]},
            ]},
        ]}  # fmt: skip
        pr = self._ok(ref.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "CREA", "dati": nuovo}), 201)
        self.assertEqual(pr["dati"]["attivita"][0]["rischi"][0]["valutazione"]["livello"], "Rischio Alto")
        self.assertNotIn(pr["id"], [x["id"] for x in self._ok(rpct.get(f"{API}/proposte", base_url=ENTE))])  # bozza
        self.assertEqual(rpct.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}).status_code, 404)
        self._ok(ref.post(f"{API}/proposte/{pr['id']}/invia", base_url=ENTE))
        self.assertEqual(ref.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": nuovo}).status_code, 409)

        # restituita senza motivazione no; con motivazione torna al referente, che corregge e reinvia
        self.assertEqual(rpct.post(f"{API}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={}).status_code, 422)
        self._ok(rpct.post(f"{API}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={"motivazione": "Manca la nota"}))
        self._ok(ref.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": nuovo, "nota": "Integrata"}))
        self._ok(ref.post(f"{API}/proposte/{pr['id']}/invia", base_url=ENTE))
        self.assertEqual(ref.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}).status_code, 403)
        esito = self._ok(rpct.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}))
        self.assertEqual(esito["stato"], "APPROVATA")
        albero = self._ok(rpct.get(f"{API}/processi/{esito['processo_id']}", base_url=ENTE))
        self.assertEqual(albero["codice"], "C.1")
        rischio = albero["attivita"][0]["rischi"][0]
        self.assertEqual((rischio["codice"], rischio["livello"]), ("C.1.1_R.1", "Rischio Alto"))
        self.assertEqual(rischio["misure"][0]["codice"], "C.1.1_R.1_M.1")

        # modifica: parte dal processo com'è; si cambia l'attività, se ne aggiunge una, si toglie la misura
        mod = self._ok(ref.post(f"{API}/proposte", base_url=ENTE,
                                json={"tipo": "MODIFICA", "processo_id": albero["id"]}), 201)  # fmt: skip
        dati = mod["dati"]
        self.assertEqual(dati["attivita"][0]["id"], albero["attivita"][0]["id"])
        dati["attivita"][0]["descrizione"] = "Scelta e verifica dell'operatore"
        dati["attivita"][0]["rischi"][0]["misure"] = []
        dati["attivita"].append({"descrizione": "Stipula", "rischi": []})
        self._ok(ref.put(f"{API}/proposte/{mod['id']}", base_url=ENTE, json={"dati": dati}))
        self._ok(ref.post(f"{API}/proposte/{mod['id']}/invia", base_url=ENTE))

        # intanto il RPCT modifica il processo: l'approvazione chiede conferma
        self._ok(rpct.put(f"{API}/attivita/{albero['attivita'][0]['id']}", base_url=ENTE,
                          json={"descrizione": "Modificata dal RPCT"}))  # fmt: skip
        self.assertTrue(self._ok(rpct.get(f"{API}/proposte/{mod['id']}", base_url=ENTE))["processo_cambiato"])
        self.assertEqual(rpct.post(f"{API}/proposte/{mod['id']}/approva", base_url=ENTE, json={}).status_code, 409)
        self._ok(rpct.post(f"{API}/proposte/{mod['id']}/approva", base_url=ENTE, json={"forza": True}))
        albero = self._ok(rpct.get(f"{API}/processi/{albero['id']}", base_url=ENTE))
        self.assertEqual([a["codice"] for a in albero["attivita"]], ["C.1.1", "C.1.2"])
        self.assertEqual(albero["attivita"][0]["descrizione"], "Scelta e verifica dell'operatore")
        self.assertEqual(albero["attivita"][0]["rischi"][0]["misure"], [])
        self.assertEqual(albero["attivita"][0]["rischi"][0]["livello"], "Rischio Alto")  # valutazione conservata

        # eliminazione: respinta con motivazione, poi una nuova approvata
        el = self._ok(ref.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "ELIMINA", "processo_id": albero["id"]}), 201)
        self._ok(ref.post(f"{API}/proposte/{el['id']}/invia", base_url=ENTE))
        self._ok(rpct.post(f"{API}/proposte/{el['id']}/respingi", base_url=ENTE, json={"motivazione": "Processo attivo"}))
        self.assertEqual(rpct.get(f"{API}/processi/{albero['id']}", base_url=ENTE).status_code, 200)
        el = self._ok(ref.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "ELIMINA", "processo_id": albero["id"]}), 201)
        self._ok(ref.post(f"{API}/proposte/{el['id']}/invia", base_url=ENTE))
        self._ok(rpct.post(f"{API}/proposte/{el['id']}/approva", base_url=ENTE, json={}))
        self.assertEqual(rpct.get(f"{API}/processi/{albero['id']}", base_url=ENTE).status_code, 404)

        # elenchi: il referente vede le sue, il RPCT quelle inviate o decise; bozze ritirabili
        bozza = self._ok(ref.post(f"{API}/proposte", base_url=ENTE,
                                  json={"tipo": "CREA", "dati": {"processo": {"denominazione": "Bozza"}}}), 201)  # fmt: skip
        stati = {x["id"]: x["stato"] for x in self._ok(ref.get(f"{API}/proposte", base_url=ENTE))}
        self.assertEqual(stati[pr["id"]], "APPROVATA")
        self.assertEqual(stati[bozza["id"]], "BOZZA")
        self.assertEqual(len(self._ok(rpct.get(f"{API}/proposte?stato=RESPINTA", base_url=ENTE))), 1)
        self.assertEqual(ref.delete(f"{API}/proposte/{bozza['id']}", base_url=ENTE).status_code, 204)
        self.assertEqual(ref.delete(f"{API}/proposte/{pr['id']}", base_url=ENTE).status_code, 409)
        # valutazione non valida rifiutata già al salvataggio
        sbagliata = {"processo": {"denominazione": "X"}, "attivita": [{"descrizione": "a", "rischi": [
            {"evento": "e", "valutazione": {"valori_probabilita": {"1": "Alto"}, "valori_impatto": {}}}]}]}  # fmt: skip
        self.assertEqual(ref.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "CREA", "dati": sbagliata}).status_code, 422)

    def test_monitoraggio(self):
        rpct, ref, dir_ = self._client("rpct"), self._client("referente"), self._client("dirigente")
        p = self._ok(rpct.post(f"{API}/processi", base_url=ENTE,
                               json={"codice": "M.1", "denominazione": "Gare", "struttura_id": self.uo}), 201)  # fmt: skip
        a = self._ok(rpct.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "Bando"}), 201)
        r = self._ok(rpct.post(f"{API}/attivita/{a['id']}/rischi", base_url=ENTE, json={"evento": "Bando su misura"}), 201)
        mis = self._ok(rpct.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE,
                                 json={"descrizione": "Doppia firma sul bando", "indicatore": "n. bandi"}), 201)  # fmt: skip
        t = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={"codice": "T.1", "denominazione": "Formazione"}), 201)
        ta = self._ok(rpct.post(f"{API}/processi/{t['id']}/attivita", base_url=ENTE, json={"descrizione": "Corsi"}), 201)
        tr = self._ok(rpct.post(f"{API}/attivita/{ta['id']}/rischi", base_url=ENTE, json={"evento": "Scarsa cultura"}), 201)
        trasv = self._ok(rpct.post(f"{API}/rischi/{tr['id']}/misure", base_url=ENTE,
                                   json={"descrizione": "Formazione annuale", "tipo": "GENERALE"}), 201)  # fmt: skip
        anno = f"{API}/monitoraggio/2026"

        # il referente della U.O. vede la sua misura e la trasversale; il dirigente del settore anche
        misure = {m["misura_id"]: m for m in self._ok(ref.get(f"{anno}/misure", base_url=ENTE))}
        self.assertIn(mis["id"], misure)
        self.assertTrue(misure[trasv["id"]]["trasversale"])
        self.assertEqual(misure[mis["id"]]["contesto"]["processo"]["codice"], "M.1")
        self.assertIn(mis["id"], [m["misura_id"] for m in self._ok(dir_.get(f"{anno}/misure", base_url=ENTE))])
        self.assertEqual(ref.get(f"{anno}/misure?struttura={self.settore}", base_url=ENTE).status_code, 403)

        # dichiarazioni: motivazione se non attuata; trasversale per la propria struttura
        self.assertEqual(ref.put(f"{anno}/misure/{mis['id']}", base_url=ENTE,
                                 json={"stato_attuazione": "PARZIALE"}).status_code, 422)  # fmt: skip
        d = self._ok(ref.put(f"{anno}/misure/{mis['id']}", base_url=ENTE,
                             json={"stato_attuazione": "PARZIALE", "motivazione": "Solo 3 bandi su 5"}))  # fmt: skip
        self.assertEqual((d["struttura_id"], d["stato_verifica"]), (self.uo, "DA_VERIFICARE"))
        self.assertEqual(ref.put(f"{anno}/misure/{trasv['id']}", base_url=ENTE,
                                 json={"stato_attuazione": "ATTUATA", "struttura_id": self.settore}).status_code, 403)  # fmt: skip
        dt = self._ok(ref.put(f"{anno}/misure/{trasv['id']}", base_url=ENTE, json={"stato_attuazione": "ATTUATA"}))
        self.assertEqual(dt["struttura_id"], self.uo)  # la struttura dell'utente
        self.assertEqual(dt["contesto"]["struttura"]["codice"], "U.O. 2.1")

        # verifica: contestata (con nota) -> corretta -> verificata -> chiusa
        self.assertEqual(ref.post(f"{API}/monitoraggio/dichiarazioni/{d['id']}/verifica", base_url=ENTE, json={}).status_code, 403)
        self.assertEqual(rpct.post(f"{API}/monitoraggio/dichiarazioni/{d['id']}/contesta", base_url=ENTE, json={}).status_code, 422)
        self._ok(rpct.post(f"{API}/monitoraggio/dichiarazioni/{d['id']}/contesta", base_url=ENTE,
                           json={"note": "Allegare i bandi"}))  # fmt: skip
        self.assertEqual(len(self._ok(rpct.get(f"{anno}?stato_verifica=CONTESTATA", base_url=ENTE))), 1)
        d = self._ok(ref.put(f"{anno}/misure/{mis['id']}", base_url=ENTE, json={
            "stato_attuazione": "ATTUATA", "evidenze": "Bandi n. 1-5"}))  # fmt: skip
        self.assertEqual(d["stato_verifica"], "DA_VERIFICARE")
        self._ok(rpct.post(f"{API}/monitoraggio/dichiarazioni/{d['id']}/verifica", base_url=ENTE, json={}))
        self.assertEqual(ref.put(f"{anno}/misure/{mis['id']}", base_url=ENTE,
                                 json={"stato_attuazione": "NON_ATTUATA", "motivazione": "x"}).status_code, 409)  # fmt: skip

        # la copia del contesto resta anche se la misura cambia
        self._ok(rpct.put(f"{API}/misure/{mis['id']}", base_url=ENTE, json={"descrizione": "Nuova descrizione"}))
        voce = next(x for x in self._ok(rpct.get(anno, base_url=ENTE)) if x["id"] == d["id"])
        self.assertEqual(voce["contesto"]["misura"]["descrizione"], "Doppia firma sul bando")

        # riepilogo e allegati al PTPCT
        riep = self._ok(ref.get(f"{API}/riepilogo", base_url=ENTE))
        self.assertGreaterEqual(riep["totali"]["misure"], 2)
        self.assertEqual(riep["livelli"][0], "Rischio Alto")  # dal più grave
        self.assertGreaterEqual(riep["per_livello"]["None"], 2)  # rischi non valutati
        x = ref.get(f"{API}/esporta/ptpct", base_url=ENTE)
        self.assertEqual(x.status_code, 200)
        import io

        from openpyxl import load_workbook

        libro = load_workbook(io.BytesIO(x.data))
        self.assertEqual(libro.sheetnames, ["PTPC", "Attuazione misure"])
        self.assertIn("M.1.1_R.1_M.1", [c.value for c in libro["PTPC"]["K"]])

        # cruscotto, anni, Excel; il redattore non entra
        c = self._ok(rpct.get(f"{anno}/cruscotto", base_url=ENTE))
        uo = next(s for s in c["strutture"] if s["struttura_id"] == self.uo)
        self.assertEqual((uo["attese"], uo["totale"], uo["attuate"], uo["verificate"]), (1, 2, 2, 1))
        self.assertIn(2026, self._ok(rpct.get(f"{API}/monitoraggio/anni", base_url=ENTE)))
        x = rpct.get(f"{anno}/esporta", base_url=ENTE)
        self.assertEqual(x.status_code, 200)
        self.assertTrue(x.data.startswith(b"PK"))  # xlsx
        self.assertEqual(self._client("redattore").get(f"{anno}/misure", base_url=ENTE).status_code, 403)

    def test_piao_e_obiettivi(self):
        import io

        rpct, ref = self._client("rpct"), self._client("referente")
        piao = self._ok(rpct.post(f"{API}/piao", base_url=ENTE, json={
            "anno_inizio": 2026, "anno_fine": 2028, "descrizione": "PIAO 2026-2028", "atto": "DGC n. 59/2026"}), 201)  # fmt: skip
        self.assertEqual(rpct.post(f"{API}/piao", base_url=ENTE, json={
            "anno_inizio": 2026, "anno_fine": 2028, "descrizione": "doppio"}).status_code, 409)  # fmt: skip
        csv = ("Piano della performance\ncodice;titolo;tipo;anno;centro;descrizione;responsabile\n"
               "PERF_ORG_SETTORE 2;Formazione specifica;Operativo;2026;SETTORE 2_GEN. 2026;Risorse umane;Verdi\n"
               "OB.X;Senza centro noto;Operativo;2030;STAFF Z;;\n")  # fmt: skip
        r = self._ok(rpct.post(f"{API}/piao/{piao['id']}/obiettivi/importa", base_url=ENTE,
                               content_type="multipart/form-data",
                               data={"file": (io.BytesIO(csv.encode()), "piano.csv")}))  # fmt: skip
        self.assertEqual((r["creati"], r["centri_non_abbinati"], r["anni_fuori_dal_piao"]), (2, ["STAFF Z"], [2030]))
        elenco = self._ok(ref.get(f"{API}/piao/{piao['id']}/obiettivi?struttura={self.uo}", base_url=ENTE))
        self.assertEqual([o["codice"] for o in elenco], ["PERF_ORG_SETTORE 2"])  # del settore superiore
        ob = elenco[0]
        self.assertEqual(ob["struttura_id"], self.settore)

        # collegamenti (aperti a tutti): processo intero o singola attività
        p = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={"codice": "O.1", "denominazione": "Formazione"}), 201)
        a1 = self._ok(rpct.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "Piano"}), 201)
        c = self._ok(ref.post(f"{API}/obiettivi/{ob['id']}/collegamenti", base_url=ENTE, json={"attivita_id": a1["id"]}), 201)
        albero = self._ok(ref.get(f"{API}/processi/{p['id']}", base_url=ENTE))
        self.assertEqual(albero["obiettivi"], [])
        self.assertEqual([o["codice"] for o in albero["attivita"][0]["obiettivi"]], ["PERF_ORG_SETTORE 2"])
        self._ok(ref.post(f"{API}/obiettivi/{ob['id']}/collegamenti", base_url=ENTE, json={"processo_id": p["id"]}), 201)
        dettaglio = self._ok(ref.get(f"{API}/obiettivi/{ob['id']}", base_url=ENTE))
        self.assertEqual([v["tipo"] for v in dettaglio["collegamenti"]], ["processo"])  # l'attività è assorbita
        self.assertEqual(ref.delete(f"{API}/collegamenti/{c['id']}", base_url=ENTE).status_code, 404)
        self.assertEqual(ref.post(f"{API}/obiettivi/{ob['id']}/collegamenti", base_url=ENTE,
                                  json={"attivita_id": a1["id"]}).status_code, 409)  # fmt: skip

        # le attività aggiunte dopo ereditano l'obiettivo del processo
        a2 = self._ok(rpct.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "Corsi"}), 201)
        albero = self._ok(ref.get(f"{API}/processi/{p['id']}", base_url=ENTE))
        nuova = next(x for x in albero["attivita"] if x["id"] == a2["id"])
        self.assertTrue(nuova["obiettivi"][0]["ereditato"])
        self.assertEqual(albero["obiettivi"][0]["codice"], "PERF_ORG_SETTORE 2")

        # gestione degli obiettivi solo per il RPCT; eliminando il PIAO spariscono anche i collegamenti
        self.assertEqual(ref.post(f"{API}/piao/{piao['id']}/obiettivi", base_url=ENTE,
                                  json={"codice": "X", "anno": 2026}).status_code, 403)  # fmt: skip
        self.assertEqual(rpct.delete(f"{API}/piao/{piao['id']}", base_url=ENTE).status_code, 204)
        self.assertEqual(self._ok(ref.get(f"{API}/processi/{p['id']}", base_url=ENTE))["obiettivi"], [])


if __name__ == "__main__":
    unittest.main()
