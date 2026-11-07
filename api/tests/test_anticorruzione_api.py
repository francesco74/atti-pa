"""Modulo anticorruzione via HTTP: metodologia (standard e dell'ente, con il ricalcolo),
aree, mappatura area -> processo o procedimento -> attività -> rischio -> misura con i codici
assegnati dal sistema e mai riusati, valutazione (parità verso il più alto, correzione
motivata), filtri, eliminazione a cascata, proposte dei referenti su ogni elemento (creazione
con gli elementi sottostanti, modifica, eliminazione; solo per la propria struttura;
restituzione, conflitti), monitoraggio delle misure (per struttura e sottostanti,
trasversali, verifica, cruscotto, Excel), permessi per ruolo e modulo, separazione tra enti.
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
                    (ente, "senzastruttura", [Ruolo.ANTICORRUZIONE_REFERENTE]),
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
            "descrizione": "Acquisizione e gestione del personale"}), 201)  # fmt: skip
        d = area["codice"]
        p = self._ok(c.post(f"{API}/processi", base_url=ENTE, json={
            "area_id": area["id"], "denominazione": "Concorsi pubblici", "struttura_id": self.uo}), 201)  # fmt: skip
        self.assertEqual(p["codice"], f"{d}.1")
        a = self._ok(c.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE,
                            json={"descrizione": "Nomina della commissione"}), 201)  # fmt: skip
        self.assertEqual(a["codice"], f"{d}.1.1")
        r = self._ok(c.post(f"{API}/attivita/{a['id']}/rischi", base_url=ENTE,
                            json={"evento": "Commissari in conflitto di interessi"}), 201)  # fmt: skip
        self.assertEqual(r["codice"], f"{d}.1.1_R.1")
        m = self._ok(c.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Dichiarazioni di assenza di conflitto", "tipo": "GENERALE",
            "categoria": "Disciplina del conflitto di interessi", "struttura_id": self.uo,
        }), 201)  # fmt: skip
        self.assertEqual(m["codice"], f"{d}.1.1_R.1_M.1")
        self.assertEqual(c.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Pubblicazione", "obbligo_trasparenza": "ART_99"}).status_code, 422)  # fmt: skip
        self._ok(c.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE, json={
            "descrizione": "Pubblicazione dei bandi", "categoria": "Trasparenza", "obbligo_trasparenza": "ART_23"}), 201)  # fmt: skip

        # valutazione: 4 Alto, 4 Medio, 1 Basso -> Alto (parità); impatto Medio -> Alto
        met = self._ok(c.get(f"{API}/metodologia", base_url=ENTE))
        self.assertTrue(met["standard"])
        prob = {i["id"]: "Alto" if int(i["id"]) <= 4 else "Medio" if int(i["id"]) <= 8 else "Basso"
                for i in met["indicatori_probabilita"]}  # fmt: skip
        imp = {i["id"]: "Medio" for i in met["indicatori_impatto"]}
        v = self._ok(c.put(f"{API}/rischi/{r['id']}/valutazione", base_url=ENTE,
                           json={"valori_probabilita": prob, "valori_impatto": imp}))  # fmt: skip
        self.assertEqual((v["probabilita"], v["livello"]), ("Alto", "Rischio Alto"))
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

    def test_codici_univoci_e_procedimenti(self):
        c = self._client("rpct")
        x = self._ok(c.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Prima"}), 201)
        y = self._ok(c.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Seconda", "codice": "ZZ"}), 201)
        self.assertNotEqual(y["codice"], "ZZ")  # il codice non si sceglie
        self.assertEqual(ord(y["codice"][-1]) - ord(x["codice"][-1]), 1)
        self.assertEqual(c.delete(f"{API}/aree/{y['id']}", base_url=ENTE).status_code, 204)
        z = self._ok(c.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Terza"}), 201)
        self.assertEqual(ord(z["codice"][-1]) - ord(y["codice"][-1]), 1)  # quello eliminato non torna
        # elenco in ordine alfabetico della descrizione breve (o della descrizione), senza
        # distinguere maiuscole e accenti
        self._ok(c.put(f"{API}/aree/{z['id']}", base_url=ENTE, json={"descrizione": "Terza", "descrizione_breve": "Èsami"}))
        self._ok(c.put(f"{API}/aree/{x['id']}", base_url=ENTE, json={"descrizione": "Prima", "descrizione_breve": "zone"}))
        nomi = [a["descrizione_breve"] or a["descrizione"] for a in self._ok(c.get(f"{API}/aree", base_url=ENTE))]
        self.assertLess(nomi.index("Èsami"), nomi.index("zone"))
        self.assertEqual(nomi, sorted(nomi, key=lambda s: s.lower().replace("è", "e")))

        p = self._ok(c.post(f"{API}/processi", base_url=ENTE, json={"area_id": x["id"], "denominazione": "Uno"}), 201)
        a1 = self._ok(c.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "a"}), 201)
        a2 = self._ok(c.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "b"}), 201)
        self.assertEqual(c.delete(f"{API}/attivita/{a2['id']}", base_url=ENTE).status_code, 204)
        a3 = self._ok(c.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "c"}), 201)
        self.assertEqual([a1["codice"], a3["codice"]], [f"{p['codice']}.1", f"{p['codice']}.3"])

        # procedimento: termine e norma; per un processo non si conservano
        pr = self._ok(c.post(f"{API}/processi", base_url=ENTE, json={
            "tipo": "PROCEDIMENTO", "area_id": x["id"], "denominazione": "Autorizzazione unica",
            "termine_conclusione": "30 giorni", "norma_riferimento": "L. 241/1990, art. 2"}), 201)  # fmt: skip
        self.assertEqual(pr["codice"], f"{x['codice']}.2")  # stessa numerazione dei processi dell'area
        self.assertEqual((pr["tipo"], pr["termine_conclusione"]), ("PROCEDIMENTO", "30 giorni"))
        self.assertEqual([q["id"] for q in self._ok(c.get(f"{API}/processi?tipo=PROCEDIMENTO", base_url=ENTE))], [pr["id"]])
        pr = self._ok(c.put(f"{API}/processi/{pr['id']}", base_url=ENTE, json={
            "tipo": "PROCESSO", "area_id": z["id"], "denominazione": "Autorizzazione unica",
            "termine_conclusione": "30 giorni"}))  # fmt: skip
        self.assertEqual((pr["termine_conclusione"], pr["codice"]), (None, f"{x['codice']}.2"))  # il codice resta

    def _valutazione(self, c, valore="Basso"):
        met = self._ok(c.get(f"{API}/metodologia", base_url=ENTE))
        return {"valori_probabilita": {i["id"]: valore for i in met["indicatori_probabilita"]},
                "valori_impatto": {i["id"]: valore for i in met["indicatori_impatto"]}}  # fmt: skip

    def _proponi(self, c, **proposta):
        return self._ok(c.post(f"{API}/proposte", base_url=ENTE, json=proposta), 201)

    def _approva(self, rpct, pr, **corpo):
        return self._ok(rpct.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json=corpo))

    def test_proposte(self):
        rpct, ref, dirig = self._client("rpct"), self._client("referente"), self._client("dirigente")

        # nuova area: codice assegnato all'approvazione
        pa = self._proponi(ref, tipo="CREA", oggetto="AREA", dati={"descrizione": "Contratti"})
        self.assertIsNone(pa["codice"])
        self.assertEqual(rpct.post(f"{API}/proposte/{pa['id']}/approva", base_url=ENTE, json={}).status_code, 200)
        area = next(a for a in self._ok(rpct.get(f"{API}/aree", base_url=ENTE)) if a["descrizione"] == "Contratti")

        # nuovo processo con attività, rischio valutato e misura, per la propria U.O.
        nuovo = {"area_id": area["id"], "denominazione": "Affidamenti diretti", "struttura_id": self.uo, "attivita": [
            {"descrizione": "Scelta dell'operatore", "rischi": [
                {"evento": "Frazionamento artificioso", "valutazione": self._valutazione(ref, "Alto"),
                 "misure": [{"descrizione": "Verifica del frazionamento", "categoria": "Controllo"}]},
            ]},
        ]}  # fmt: skip
        pr = self._ok(ref.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "CREA", "oggetto": "PROCESSO", "dati": nuovo}), 201)
        self.assertEqual(pr["dati"]["attivita"][0]["rischi"][0]["valutazione"]["livello"], "Rischio Critico")
        self.assertEqual(pr["percorso"][0].split()[0], area["codice"])
        # va subito al RPCT; finché non decide il referente la corregge
        self.assertEqual((pr["stato"], pr["inviata_il"] is not None), ("INVIATA", True))
        self.assertIn(pr["id"], [x["id"] for x in self._ok(rpct.get(f"{API}/proposte?stato=INVIATA", base_url=ENTE))])
        self.assertEqual(self._ok(ref.put(f"{API}/proposte/{pr['id']}", base_url=ENTE,
                                          json={"dati": nuovo, "nota": "Prima nota"}))["stato"], "INVIATA")  # fmt: skip
        # restituita (con motivazione): corretta, torna da sola al RPCT
        self.assertEqual(rpct.post(f"{API}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={}).status_code, 422)
        self._ok(rpct.post(f"{API}/proposte/{pr['id']}/restituisci", base_url=ENTE, json={"motivazione": "Manca la nota"}))
        r = self._ok(ref.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"dati": nuovo, "nota": "Integrata"}))
        self.assertEqual(r["stato"], "INVIATA")
        self.assertEqual(ref.post(f"{API}/proposte/{pr['id']}/approva", base_url=ENTE, json={}).status_code, 403)
        esito = self._approva(rpct, pr)
        self.assertEqual(esito["stato"], "APPROVATA")
        self.assertEqual(ref.put(f"{API}/proposte/{pr['id']}", base_url=ENTE, json={"nota": "tardi"}).status_code, 409)
        albero = self._ok(ref.get(f"{API}/processi/{esito['elemento_id']}", base_url=ENTE))
        cp = albero["codice"]
        self.assertEqual((cp, esito["codice"], albero["proponibile"]), (f"{area['codice']}.1", cp, True))
        rischio = albero["attivita"][0]["rischi"][0]
        self.assertEqual((rischio["codice"], rischio["livello"]), (f"{cp}.1_R.1", "Rischio Critico"))
        self.assertEqual(rischio["misure"][0]["codice"], f"{cp}.1_R.1_M.1")

        # nuova attività con il suo rischio, proposta dal dirigente del settore (la U.O. è sotto)
        pat = self._proponi(dirig, tipo="CREA", oggetto="ATTIVITA", padre_id=albero["id"], dati={
            "descrizione": "Stipula", "rischi": [{"evento": "Clausole di favore", "misure": [{"descrizione": "Doppia firma"}]}]})  # fmt: skip
        self.assertEqual(pat["percorso"][-1].split()[0], cp)
        self._approva(rpct, pat)
        albero = self._ok(rpct.get(f"{API}/processi/{albero['id']}", base_url=ENTE))
        self.assertEqual(albero["attivita"][1]["rischi"][0]["misure"][0]["codice"], f"{cp}.2_R.1_M.1")

        # rivalutazione di un rischio (modifica) e nuova misura
        r0 = albero["attivita"][0]["rischi"][0]
        pv = self._proponi(ref, tipo="MODIFICA", oggetto="RISCHIO", elemento_id=r0["id"],
                           dati={"evento": r0["evento"], "valutazione": self._valutazione(ref, "Basso")})  # fmt: skip
        self.assertEqual(pv["prima"]["valutazione"]["livello"], "Rischio Critico")
        self.assertEqual(pv["dati"]["valutazione"]["livello"], "Rischio Minimo")
        pm = self._proponi(ref, tipo="CREA", oggetto="MISURA", padre_id=r0["id"], dati={"descrizione": "Rotazione"})
        self._approva(rpct, pv)
        self._approva(rpct, pm)
        r0 = self._ok(rpct.get(f"{API}/processi/{albero['id']}", base_url=ENTE))["attivita"][0]["rischi"][0]
        self.assertEqual((r0["livello"], [m["codice"][-3:] for m in r0["misure"]]), ("Rischio Minimo", ["M.1", "M.2"]))

        # modifica di un elemento cambiato nel frattempo: si approva solo confermando
        a0 = albero["attivita"][0]
        pmod = self._proponi(ref, tipo="MODIFICA", oggetto="ATTIVITA", elemento_id=a0["id"],
                             dati={"descrizione": "Scelta e verifica dell'operatore"})  # fmt: skip
        self._ok(rpct.put(f"{API}/attivita/{a0['id']}", base_url=ENTE, json={"descrizione": "Modificata dal RPCT"}))
        self.assertTrue(self._ok(rpct.get(f"{API}/proposte/{pmod['id']}", base_url=ENTE))["cambiato"])
        self.assertEqual(rpct.post(f"{API}/proposte/{pmod['id']}/approva", base_url=ENTE, json={}).status_code, 409)
        self._approva(rpct, pmod, forza=True)
        self.assertEqual(self._ok(rpct.get(f"{API}/processi/{albero['id']}", base_url=ENTE))["attivita"][0]["descrizione"],
                         "Scelta e verifica dell'operatore")  # fmt: skip

        # eliminazione di una misura: respinta, poi approvata; il codice non si riusa
        m1 = r0["misure"][0]
        pe = self._proponi(ref, tipo="ELIMINA", oggetto="MISURA", elemento_id=m1["id"])
        self.assertEqual(pe["dati"]["descrizione"], m1["descrizione"])
        self._ok(rpct.post(f"{API}/proposte/{pe['id']}/respingi", base_url=ENTE, json={"motivazione": "Serve"}))
        pe = self._proponi(ref, tipo="ELIMINA", oggetto="MISURA", elemento_id=m1["id"])
        self._approva(rpct, pe)
        nuova = self._ok(rpct.post(f"{API}/rischi/{r0['id']}/misure", base_url=ENTE, json={"descrizione": "Altra"}), 201)
        self.assertTrue(nuova["codice"].endswith("_M.3"))

        # proposta su un elemento sparito prima dell'approvazione
        pr_r = self._proponi(ref, tipo="CREA", oggetto="RISCHIO", padre_id=a0["id"], dati={"evento": "Nuovo"})
        self.assertEqual(rpct.delete(f"{API}/attivita/{a0['id']}", base_url=ENTE).status_code, 204)
        self.assertEqual(rpct.post(f"{API}/proposte/{pr_r['id']}/approva", base_url=ENTE, json={}).status_code, 409)

        # elenchi: il referente vede le sue, il RPCT tutte; si ritira solo quella non decisa
        attesa = self._proponi(ref, tipo="CREA", oggetto="AREA", dati={"descrizione": "Da ritirare"})
        stati = {x["id"]: x["stato"] for x in self._ok(ref.get(f"{API}/proposte", base_url=ENTE))}
        self.assertEqual((stati[pr["id"]], stati[attesa["id"]]), ("APPROVATA", "INVIATA"))
        self.assertEqual(len(self._ok(rpct.get(f"{API}/proposte?stato=RESPINTA", base_url=ENTE))), 1)
        self.assertEqual(dirig.delete(f"{API}/proposte/{attesa['id']}", base_url=ENTE).status_code, 404)  # non è sua
        self.assertEqual(ref.delete(f"{API}/proposte/{attesa['id']}", base_url=ENTE).status_code, 204)
        self.assertEqual(ref.delete(f"{API}/proposte/{pr['id']}", base_url=ENTE).status_code, 409)
        # valutazione non valida rifiutata già al salvataggio
        sbagliata = {"evento": "e", "valutazione": {"valori_probabilita": {"1": "Alto"}, "valori_impatto": {}}}
        self.assertEqual(ref.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "CREA", "oggetto": "RISCHIO", "padre_id": albero["attivita"][1]["id"], "dati": sbagliata}).status_code, 422)  # fmt: skip

    def test_proposte_solo_per_la_propria_struttura(self):
        rpct, ref, dirig = self._client("rpct"), self._client("referente"), self._client("dirigente")
        del_settore = self._ok(rpct.post(f"{API}/processi", base_url=ENTE,
                                         json={"denominazione": "Del settore", "struttura_id": self.settore}), 201)  # fmt: skip
        trasversale = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={"denominazione": "Di tutti"}), 201)
        for processo in (del_settore, trasversale):  # la U.O. non propone sul settore né sui trasversali
            r = ref.post(f"{API}/proposte", base_url=ENTE, json={
                "tipo": "CREA", "oggetto": "ATTIVITA", "padre_id": processo["id"], "dati": {"descrizione": "x"}})  # fmt: skip
            self.assertEqual(r.status_code, 403, processo["denominazione"])
        self.assertFalse(self._ok(ref.get(f"{API}/processi/{del_settore['id']}", base_url=ENTE))["proponibile"])
        self.assertEqual(ref.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "CREA", "oggetto": "PROCESSO", "dati": {"denominazione": "x", "struttura_id": self.settore}}).status_code, 403)  # fmt: skip
        self.assertEqual(ref.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "MODIFICA", "oggetto": "PROCESSO", "elemento_id": del_settore["id"],
            "dati": {"denominazione": "y", "struttura_id": self.uo}}).status_code, 403)  # fmt: skip
        self._ok(dirig.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "ELIMINA", "oggetto": "PROCESSO", "elemento_id": del_settore["id"]}), 201)  # fmt: skip
        senza = self._client("senzastruttura")
        r = senza.post(f"{API}/proposte", base_url=ENTE, json={"tipo": "CREA", "oggetto": "AREA", "dati": {"descrizione": "x"}})
        self.assertEqual(r.status_code, 403)
        self.assertIn("struttura nel profilo", r.get_data(as_text=True))
        # area con processi: l'eliminazione non si propone
        area = self._ok(rpct.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Piena"}), 201)
        self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={"area_id": area["id"], "denominazione": "p"}), 201)
        self.assertEqual(ref.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "ELIMINA", "oggetto": "AREA", "elemento_id": area["id"]}).status_code, 409)  # fmt: skip

    def test_monitoraggio(self):
        rpct, ref, dir_ = self._client("rpct"), self._client("referente"), self._client("dirigente")
        p = self._ok(rpct.post(f"{API}/processi", base_url=ENTE,
                               json={"denominazione": "Gare", "struttura_id": self.uo}), 201)  # fmt: skip
        a = self._ok(rpct.post(f"{API}/processi/{p['id']}/attivita", base_url=ENTE, json={"descrizione": "Bando"}), 201)
        r = self._ok(rpct.post(f"{API}/attivita/{a['id']}/rischi", base_url=ENTE, json={"evento": "Bando su misura"}), 201)
        mis = self._ok(rpct.post(f"{API}/rischi/{r['id']}/misure", base_url=ENTE,
                                 json={"descrizione": "Doppia firma sul bando", "indicatore": "n. bandi"}), 201)  # fmt: skip
        t = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={"denominazione": "Formazione"}), 201)
        ta = self._ok(rpct.post(f"{API}/processi/{t['id']}/attivita", base_url=ENTE, json={"descrizione": "Corsi"}), 201)
        tr = self._ok(rpct.post(f"{API}/attivita/{ta['id']}/rischi", base_url=ENTE, json={"evento": "Scarsa cultura"}), 201)
        trasv = self._ok(rpct.post(f"{API}/rischi/{tr['id']}/misure", base_url=ENTE,
                                   json={"descrizione": "Formazione annuale", "tipo": "GENERALE"}), 201)  # fmt: skip
        anno = f"{API}/monitoraggio/2026"

        # il referente della U.O. vede la sua misura e la trasversale; il dirigente del settore anche
        misure = {m["misura_id"]: m for m in self._ok(ref.get(f"{anno}/misure", base_url=ENTE))}
        self.assertIn(mis["id"], misure)
        self.assertTrue(misure[trasv["id"]]["trasversale"])
        self.assertEqual(misure[mis["id"]]["contesto"]["processo"]["codice"], p["codice"])
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
        self.assertEqual(riep["livelli"][0], "Rischio Critico")  # dal più grave
        self.assertGreaterEqual(riep["per_livello"]["None"], 2)  # rischi non valutati
        x = ref.get(f"{API}/esporta/ptpct", base_url=ENTE)
        self.assertEqual(x.status_code, 200)
        import io

        from openpyxl import load_workbook

        libro = load_workbook(io.BytesIO(x.data))
        self.assertEqual(libro.sheetnames, ["PTPC", "Attuazione misure"])
        self.assertIn(mis["codice"], [c.value for c in libro["PTPC"]["K"]])

        # cruscotto, anni, Excel; il redattore non entra
        c = self._ok(rpct.get(f"{anno}/cruscotto", base_url=ENTE))
        uo = next(s for s in c["strutture"] if s["struttura_id"] == self.uo)
        self.assertEqual((uo["attese"], uo["totale"], uo["attuate"], uo["verificate"]), (1, 2, 2, 1))
        self.assertIn(2026, self._ok(rpct.get(f"{API}/monitoraggio/anni", base_url=ENTE)))
        x = rpct.get(f"{anno}/esporta", base_url=ENTE)
        self.assertEqual(x.status_code, 200)
        self.assertTrue(x.data.startswith(b"PK"))  # xlsx
        self.assertEqual(self._client("redattore").get(f"{anno}/misure", base_url=ENTE).status_code, 403)


    def test_struttura_scelta_dal_profilo(self):
        c = self._client("senzastruttura")
        profilo = "/api/v1/auth/profilo"
        self.assertEqual(c.put(profilo, base_url=ENTE, json={"struttura_id": "inesistente"}).status_code, 422)
        u = self._ok(c.put(profilo, base_url=ENTE, json={"struttura_id": self.uo}))
        self.assertEqual(u["struttura_id"], self.uo)
        # scelta una volta sola: poi la cambia l'amministratore
        r = c.put(profilo, base_url=ENTE, json={"struttura_id": self.settore})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self._ok(c.put(profilo, base_url=ENTE, json={"ufficio": "Personale"}))["struttura_id"], self.uo)


if __name__ == "__main__":
    unittest.main()
