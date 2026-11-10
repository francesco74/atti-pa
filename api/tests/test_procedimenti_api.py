"""Procedimenti e art. 35 d.lgs. 33/2013 via HTTP: dati propri del procedimento nella mappatura
(uffici = strutture con i recapiti, letti al momento), scheda nel formato dello schema ART_35
con i dati mancanti, conservazione dei dati quando non si inviano, proposte dei referenti,
importazione nella scheda della trasparenza, pagina pubblica dei procedimenti con il suo
interruttore; catalogo condiviso: con la sola trasparenza i procedimenti si gestiscono
direttamente lì, con l'anticorruzione attiva solo nella mappatura.
    cd api/tests && python test_procedimenti_api.py
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
from common.models import Base, Ente, EnteDominio, Modulo, Ruolo, User  # noqa: E402

PASSWORD = "Password-di-prova-1"
ENTE = "http://lucca.example.it"
ALTRO = "http://altro.example.it"
SOLO = "http://solo.example.it"  # solo modulo trasparenza
TR = "/api/v1/trasparenza"
API = "/api/v1/anticorruzione"
PUBBLICO = "/api/v1/pubblico"

RECAPITI = {"telefono": "0583 1234", "peo": "ufficio@ente.it", "pec": "ente@pec.ente.it", "sede": "Via Roma 1, Lucca",
            "responsabile": "Mario Rossi", "qualifica": "Dirigente",
            "orari": [{"giorni": "Lunedì e giovedì", "ora_inizio": "09:00", "ora_fine": "12:30"}]}  # fmt: skip


class ProcedimentiApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import create_app

        cls.cartella = tempfile.TemporaryDirectory()
        url = cls.url = f"sqlite+aiosqlite:///{cls.cartella.name}/prova.db"

        async def dati():
            motore = create_async_engine(url)
            async with motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(motore) as db:
                ente = Ente(codice="lucca", nome="Comune di Lucca", dati_json={},
                            moduli_json=[Modulo.ANTICORRUZIONE, Modulo.TRASPARENZA])  # fmt: skip
                altro = Ente(codice="altro", nome="Altro", dati_json={}, moduli_json=[Modulo.ANTICORRUZIONE],
                             procedimenti_pubblici=True)  # fmt: skip
                solo = Ente(codice="solo", nome="Comune di Solo", dati_json={}, moduli_json=[Modulo.TRASPARENZA])
                db.add_all([ente, altro, solo])
                await db.flush()
                cls.ente_id = ente.id
                db.add_all([EnteDominio(dominio="lucca.example.it", ente_id=ente.id),
                            EnteDominio(dominio="altro.example.it", ente_id=altro.id),
                            EnteDominio(dominio="solo.example.it", ente_id=solo.id)])  # fmt: skip
                for username, ruoli in [("admin", [Ruolo.ADMIN]), ("trasparenza", [Ruolo.TRASPARENZA]),
                                        ("rpct", [Ruolo.ANTICORRUZIONE_RPCT])]:  # fmt: skip
                    db.add(User(ente_id=solo.id, username=username, origine="LOCALE",
                                password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
                for username, ruoli in [("admin", [Ruolo.ADMIN]), ("rpct", [Ruolo.ANTICORRUZIONE_RPCT]),
                                        ("referente", [Ruolo.ANTICORRUZIONE_REFERENTE]),
                                        ("trasparenza", [Ruolo.TRASPARENZA])]:  # fmt: skip
                    db.add(User(ente_id=ente.id, username=username, origine="LOCALE",
                                password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
                db.add(User(ente_id=altro.id, username="admin", origine="LOCALE",
                            password_hash=pw.calcola(PASSWORD), ruoli=[Ruolo.ADMIN]))  # fmt: skip
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
        self.assertEqual(r.status_code, codice, r.get_data(as_text=True)[:600])
        return r.get_json()

    def test_procedimento_art35(self):
        admin, rpct = self._client("admin"), self._client("rpct")
        struttura = lambda codice, descrizione, **altro: self._ok(admin.post(  # noqa: E731
            "/api/v1/ente/strutture", base_url=ENTE, json={"codice": codice, "descrizione": descrizione, **altro}), 201)
        servizi = struttura("SETTORE 4", "Servizi sociali", **RECAPITI)
        sportello = struttura("U.O. 4.1", "Sportello sociale", padre_id=servizi["id"],
                              **{**RECAPITI, "peo": "sportello@ente.it"})  # fmt: skip
        segreteria = struttura("STAFF A", "Segreteria generale", **{**RECAPITI, "responsabile": "Anna Bianchi",
                                                                      "qualifica": "Segretario generale"})  # fmt: skip
        altro_admin = self._client("admin", ALTRO)
        estranea = self._ok(altro_admin.post("/api/v1/ente/strutture", base_url=ALTRO,
                                             json={"codice": "X", "descrizione": "Estranea"}), 201)  # fmt: skip
        # il referente propone per la sua struttura
        utenti = self._ok(admin.get("/api/v1/ente/utenti", base_url=ENTE))
        referente = next(u for u in (utenti if isinstance(utenti, list) else utenti["utenti"]) if u["username"] == "referente")
        self._ok(admin.put(f"/api/v1/ente/utenti/{referente['id']}", base_url=ENTE,
                           json={"struttura_id": servizi["id"]}))  # fmt: skip

        area = self._ok(rpct.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Servizi sociali"}), 201)
        base = {"tipo": "PROCEDIMENTO", "area_id": area["id"], "denominazione": "Contributo affitto",
                "descrizione": "Contributo per il pagamento del canone", "struttura_id": servizi["id"],
                "termine_conclusione": "30 giorni", "norma_riferimento": "L. 431/1998, art. 11"}  # fmt: skip
        art35 = {"tipologia": "Contributi economici", "istanza_di_parte": "SI", "ist_struttura_id": sportello["id"],
                 "ist_modulistica": "https://www.ente.it/moduli/affitto", "modalita_info": "Telefonando allo sportello",
                 "dichiarazione_sostitutiva": "NO", "silenzio_assenso": "NO",
                 "strumenti_tutela": "Ricorso al TAR entro 60 giorni", "servizio_online_tempi": "Entro il 2027",
                 "sost_struttura_id": segreteria["id"], "sost_attivazione": "Istanza scritta al Segretario"}  # fmt: skip

        # controlli: URL e strutture dell'ente
        self.assertEqual(rpct.post(f"{API}/processi", base_url=ENTE, json={
            **base, "art35": {**art35, "ist_modulistica": "non un link"}}).status_code, 422)  # fmt: skip
        self.assertEqual(rpct.post(f"{API}/processi", base_url=ENTE, json={
            **base, "art35": {**art35, "sost_struttura_id": estranea["id"]}}).status_code, 422)  # fmt: skip

        # senza dati art. 35: si salva, con i dati mancanti
        p = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json=base), 201)
        d = self._ok(rpct.get(f"{API}/processi/{p['id']}", base_url=ENTE))
        self.assertTrue(any("Tipologia" in m for m in d["art35_mancanti"]))
        self.assertEqual(d["scheda_art35"]["unita_istruttoria"], "Servizi sociali")
        self.assertEqual(d["scheda_art35"]["uff_resp_tel"], "0583 1234")  # ufficio responsabile = struttura

        # con i dati: completi, recapiti dalle strutture
        self._ok(rpct.put(f"{API}/processi/{p['id']}", base_url=ENTE, json={**base, "art35": art35}))
        d = self._ok(rpct.get(f"{API}/processi/{p['id']}", base_url=ENTE))
        self.assertEqual(d["art35_mancanti"], [], d["art35_mancanti"])
        s = d["scheda_art35"]
        self.assertEqual((s["ist_ufficio"], s["ist_peo"], s["ist_indirizzo"]), ("Sportello sociale", "sportello@ente.it", "Via Roma 1, Lucca"))
        self.assertEqual(s["orari"], RECAPITI["orari"])
        self.assertEqual((s["sost_nominativo"], s["sost_qualifica"]), ("Anna Bianchi", "Segretario generale"))
        self.assertEqual((s["ufficio_finale_diverso"], s["riferimenti_normativi"]), ("NO", "L. 431/1998, art. 11"))
        elenco = self._ok(rpct.get(f"{API}/processi", base_url=ENTE))
        self.assertEqual([x["art35_mancanti"] for x in elenco if x["id"] == p["id"]], [0])
        # anche nell'elenco piatto della mappatura, con la scheda
        voce = next(x for x in self._ok(rpct.get(f"{API}/elenco", base_url=ENTE))["processi"] if x["id"] == p["id"])
        self.assertEqual((voce["art35_mancanti"], voce["scheda_art35"]["ist_ufficio"]), ([], "Sportello sociale"))

        # recapiti scritti nel procedimento al posto di quelli della struttura (es. uno sportello)
        propri = {**art35, "ist_telefono": "0583 9999", "ist_indirizzo": "Piazza Grande 3",
                  "orari": [{"giorni": "Martedì", "ora_inizio": "15:00", "ora_fine": "17:00"}], "sost_nominativo": "Marco Neri"}
        self.assertEqual(rpct.put(f"{API}/processi/{p['id']}", base_url=ENTE, json={
            **base, "art35": {**propri, "orari": [{"giorni": "Martedì"}]}}).status_code, 422)  # fmt: skip
        self._ok(rpct.put(f"{API}/processi/{p['id']}", base_url=ENTE, json={**base, "art35": propri}))
        s = self._ok(rpct.get(f"{API}/processi/{p['id']}", base_url=ENTE))["scheda_art35"]
        self.assertEqual((s["ist_telefono"], s["ist_indirizzo"], s["ist_peo"], s["orari"], s["sost_nominativo"], s["sost_qualifica"]),
                         ("0583 9999", "Piazza Grande 3", "sportello@ente.it", propri["orari"], "Marco Neri", "Segretario generale"))  # fmt: skip
        self._ok(rpct.put(f"{API}/processi/{p['id']}", base_url=ENTE, json={**base, "art35": art35}))

        # modifica senza art35: i dati restano; i recapiti si leggono al momento
        self._ok(rpct.put(f"{API}/processi/{p['id']}", base_url=ENTE, json={**base, "denominazione": "Contributo affitti"}))
        self._ok(admin.put(f"/api/v1/ente/strutture/{sportello['id']}", base_url=ENTE, json={
            "codice": "U.O. 4.1", "descrizione": "Sportello sociale", "padre_id": servizi["id"],
            **{**RECAPITI, "peo": None, "pec": None}}))  # fmt: skip
        d = self._ok(rpct.get(f"{API}/processi/{p['id']}", base_url=ENTE))
        self.assertEqual(d["art35"]["tipologia"], "Contributi economici")
        self.assertTrue(any("almeno uno" in m for m in d["art35_mancanti"]), d["art35_mancanti"])  # né PEO né PEC

        # un processo non ha dati art. 35
        pr = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={**base, "tipo": "PROCESSO", "art35": art35}), 201)
        self.assertIsNone(pr["art35"])
        self.assertNotIn("scheda_art35", self._ok(rpct.get(f"{API}/processi/{pr['id']}", base_url=ENTE)))

        # proposta del referente sui dati art. 35
        ref = self._client("referente")
        proposta = self._ok(ref.post(f"{API}/proposte", base_url=ENTE, json={
            "tipo": "MODIFICA", "oggetto": "PROCESSO", "elemento_id": p["id"],
            "dati": {**base, "art35": {**art35, "silenzio_assenso": "SI"}}}), 201)  # fmt: skip
        self.assertEqual(proposta["prima"]["art35"]["silenzio_assenso"], "NO")
        # controlli oggettivi per il RPCT (il procedimento ha termine e riferimenti normativi)
        controlli = self._ok(rpct.get(f"{API}/proposte/{proposta['id']}", base_url=ENTE))["controlli"]
        self.assertFalse(any("termine" in c["testo"] for c in controlli), controlli)
        self._ok(rpct.post(f"{API}/proposte/{proposta['id']}/approva", base_url=ENTE, json={}))
        self.assertEqual(self._ok(rpct.get(f"{API}/processi/{p['id']}", base_url=ENTE))["art35"]["silenzio_assenso"], "SI")

        # trasparenza: importazione nella scheda ART_35
        trasp = self._client("trasparenza")
        importabili = self._ok(trasp.get("/api/v1/trasparenza/procedimenti-mappatura", base_url=ENTE))
        ids = [x["id"] for x in importabili]
        self.assertIn(p["id"], ids)
        self.assertNotIn(pr["id"], ids)  # solo i procedimenti
        nostro = next(x for x in importabili if x["id"] == p["id"])
        self.assertEqual(nostro["elemento"]["silenzio_assenso"], "SI")
        self.assertTrue(nostro["mancanti"])

        # pagina pubblica dei procedimenti: spenta, poi accesa dal RPCT
        cittadino = self.app.test_client()
        self.assertEqual(cittadino.get(f"{PUBBLICO}/procedimenti", base_url=ENTE).status_code, 404)
        stato = self._ok(rpct.put(f"{API}/pubblicazione", base_url=ENTE, json={"procedimenti_attiva": True}))
        self.assertEqual((stato["procedimenti_attiva"], stato["attiva"]), (True, False))  # la mappatura resta spenta
        self.assertEqual(cittadino.get(f"{PUBBLICO}/mappatura", base_url=ENTE).status_code, 404)
        pagina = self._ok(cittadino.get(f"{PUBBLICO}/procedimenti", base_url=ENTE))
        nostro = next(x for x in pagina["procedimenti"] if x["id"] == p["id"])
        self.assertEqual(nostro["denominazione"], "Contributo affitto")  # dalla proposta approvata
        self.assertIn(servizi["id"], [x["id"] for x in pagina["strutture"]])
        scheda = self._ok(cittadino.get(f"{PUBBLICO}/procedimenti/{p['id']}", base_url=ENTE))["scheda"]
        self.assertEqual((scheda["tipologia"], scheda["sost_nominativo"]), ("Contributi economici", "Anna Bianchi"))
        self.assertEqual(cittadino.get(f"{PUBBLICO}/procedimenti/{pr['id']}", base_url=ENTE).status_code, 404)  # processo
        self.assertEqual(cittadino.get(f"{PUBBLICO}/procedimenti/{p['id']}", base_url=ALTRO).status_code, 404)  # altro ente

    def test_importazione_dal_sito(self):
        from common.models import StatoVerifica, TrasparenzaLavoro

        rpct, admin = self._client("rpct"), self._client("admin")
        sociali = self._ok(admin.post("/api/v1/ente/strutture", base_url=ENTE,
                                      json={"codice": "SETTORE 9", "descrizione": "Politiche abitative"}), 201)  # fmt: skip
        area = self._ok(rpct.post(f"{API}/aree", base_url=ENTE, json={"descrizione": "Casa"}), 201)
        esistente = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={
            "tipo": "PROCEDIMENTO", "area_id": area["id"], "denominazione": "Assegnazione alloggi ERP"}), 201)  # fmt: skip

        # solo il RPCT; serve una fonte
        self.assertEqual(self._client("referente").post(f"{API}/procedimenti/importazioni", base_url=ENTE,
                                                        json={"url": "https://www.ente.it/at"}).status_code, 403)  # fmt: skip
        self.assertEqual(rpct.post(f"{API}/procedimenti/importazioni", base_url=ENTE, json={}).status_code, 422)
        # al più 15 link seguiti
        self.assertEqual(rpct.post(f"{API}/procedimenti/importazioni", base_url=ENTE, json={
            "url": "https://www.ente.it/at", "segui_link": True, "max_link": 16}).status_code, 422)  # fmt: skip
        lavoro = self._ok(rpct.post(f"{API}/procedimenti/importazioni", base_url=ENTE, json={
            "url": "https://www.ente.it/amministrazione-trasparente/tipologie-di-procedimento", "segui_link": True,
            "max_link": 12}), 202)  # fmt: skip
        stato = self._ok(rpct.get(f"{API}/procedimenti/importazioni/{lavoro['id']}", base_url=ENTE))
        self.assertEqual(stato["stato"], "IN_CODA")
        self.assertNotIn("procedimenti", stato)

        # il worker ha letto la pagina (simulato): due procedimenti, uno già nella mappatura
        righe = [
            {"denominazione": "Assegnazione alloggi di ERP", "tipologia": "Concessioni", "uff_resp_denom": "Politiche abitative"},
            {"denominazione": "Contributo morosità incolpevole", "silenzio_assenso": "NO"},
        ]  # fmt: skip

        async def completa():
            motore = create_async_engine(self.url)
            async with AsyncSession(motore) as db:
                lv = await db.get(TrasparenzaLavoro, lavoro["id"])
                self.assertEqual((lv.richiesta["segui_link"], lv.richiesta["max_link"]), (True, 12))
                lv.stato = StatoVerifica.COMPLETATA
                lv.risultato = {"dati": {"sezione": "PROCEDIMENTI", "righe": righe}, "avvisi": ["Orari non trovati"]}
                await db.commit()
            await motore.dispose()

        asyncio.run(completa())
        esito = self._ok(rpct.get(f"{API}/procedimenti/importazioni/{lavoro['id']}", base_url=ENTE))
        self.assertEqual(esito["stato"], "COMPLETATA")
        self.assertEqual(esito["avvisi"], ["Orari non trovati"])
        self.assertEqual([p["procedimento_id"] for p in esito["procedimenti"]], [esistente["id"], None])
        self.assertEqual(esito["procedimenti"][0]["uffici"]["uff_resp_struttura_id"]["struttura_id"], sociali["id"])
        # l'importazione è di chi l'ha avviata
        self.assertEqual(admin.get(f"{API}/procedimenti/importazioni/{lavoro['id']}", base_url=ENTE).status_code, 404)

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

    def test_solo_trasparenza(self):
        """Senza anticorruzione l'operatore della trasparenza gestisce i procedimenti."""
        from common.models import AcAttivita, AcProcesso

        tr, admin = self._client("trasparenza", SOLO), self._client("admin", SOLO)
        ufficio = self._ok(admin.post("/api/v1/ente/strutture", base_url=SOLO,
                                      json={"codice": "U.O. 1", "descrizione": "Anagrafe", **RECAPITI}), 201)  # fmt: skip
        self.assertFalse(self._ok(tr.get(f"{TR}/procedimenti/pubblicazione", base_url=SOLO))["con_iter"])
        # la mappatura dell'anticorruzione non c'è
        self.assertEqual(self._client("rpct", SOLO).get(f"{API}/processi", base_url=SOLO).status_code, 403)

        nuovo = {"denominazione": "Cambio di residenza", "termine_conclusione": "45 giorni", "struttura_id": ufficio["id"],
                 "art35": {"tipologia": "Anagrafe", "uff_resp_struttura_id": ufficio["id"], "istanza_di_parte": "SI"},
                 "tipo": "PROCESSO", "area_id": "ignorata"}  # campi della mappatura: ignorati  # fmt: skip
        self.assertEqual(tr.post(f"{TR}/procedimenti", base_url=SOLO, json={**nuovo, "denominazione": ""}).status_code, 422)
        p = self._ok(tr.post(f"{TR}/procedimenti", base_url=SOLO, json=nuovo), 201)
        self.assertEqual((p["codice"], p["tipo"], p["area_id"]), ("P.1", "PROCEDIMENTO", None))
        self.assertEqual(p["scheda_art35"]["uff_resp_tel"], RECAPITI["telefono"])  # recapiti dalla struttura
        self.assertIn("art35_mancanti", p)
        # modifica senza art35: i dati dell'art. 35 restano
        p = self._ok(tr.put(f"{TR}/procedimenti/{p['id']}", base_url=SOLO, json={
            "denominazione": "Cambio di residenza e di indirizzo", "struttura_id": ufficio["id"]}))  # fmt: skip
        self.assertEqual((p["denominazione"], p["art35"]["tipologia"], p["termine_conclusione"]),
                         ("Cambio di residenza e di indirizzo", "Anagrafe", None))  # fmt: skip
        self.assertEqual([x["codice"] for x in self._ok(tr.get(f"{TR}/procedimenti", base_url=SOLO))], ["P.1"])
        # importazione nella scheda art. 35 anche senza anticorruzione
        importabili = self._ok(tr.get(f"{TR}/procedimenti-mappatura", base_url=SOLO))
        self.assertEqual([x["codice"] for x in importabili], ["P.1"])
        # importazione dal sito: avviata dalla trasparenza
        self._ok(tr.post(f"{TR}/procedimenti/importazioni", base_url=SOLO, json={"url": "https://www.ente.it/at"}), 202)

        # pagina pubblica dei procedimenti: con la sola trasparenza; la mappatura no
        self.assertEqual(self.app.test_client().get(f"{PUBBLICO}/procedimenti", base_url=SOLO).status_code, 404)
        stato = self._ok(tr.put(f"{TR}/procedimenti/pubblicazione", base_url=SOLO, json={"procedimenti_attiva": True}))
        self.assertTrue(stato["procedimenti_attiva"])
        pubblico = self.app.test_client()
        elenco = self._ok(pubblico.get(f"{PUBBLICO}/procedimenti", base_url=SOLO))
        self.assertEqual([x["codice"] for x in elenco["procedimenti"]], ["P.1"])
        self._ok(pubblico.get(f"{PUBBLICO}/procedimenti/{p['id']}", base_url=SOLO))
        self._ok(pubblico.get(f"{PUBBLICO}/procedimenti/ricerca?testo=residenza", base_url=SOLO))
        self.assertEqual(pubblico.get(f"{PUBBLICO}/mappatura", base_url=SOLO).status_code, 404)
        self._ok(pubblico.post(f"{PUBBLICO}/ricerche/registro", base_url=SOLO, json={
            "ambito": "PROCEDIMENTI", "testo": "residenza", "risultati": 1, "esito": "TROVATA", "posizione": 1}), 201)  # fmt: skip

        # un procedimento con attività della mappatura (anticorruzione avuta in passato) non si elimina
        async def attivita(db):
            processo = await db.get(AcProcesso, p["id"])
            db.add(AcAttivita(ente_id=processo.ente_id, processo_id=processo.id, codice="P.1.1", descrizione="Istruttoria"))

        self._db(attivita)
        self.assertEqual(tr.delete(f"{TR}/procedimenti/{p['id']}", base_url=SOLO).status_code, 409)
        altro = self._ok(tr.post(f"{TR}/procedimenti", base_url=SOLO, json={"denominazione": "Carta d'identità"}), 201)
        self.assertEqual(altro["codice"], "P.2")
        self._ok(tr.delete(f"{TR}/procedimenti/{altro['id']}", base_url=SOLO), 204)
        self.assertEqual(tr.get(f"{TR}/procedimenti/{altro['id']}", base_url=SOLO).status_code, 404)
        # i procedimenti di un altro ente non si vedono
        self.assertEqual(self._client("trasparenza").get(f"{TR}/procedimenti/{p['id']}", base_url=ENTE).status_code, 404)

    def test_con_anticorruzione_solo_lettura(self):
        """Con l'anticorruzione attiva la trasparenza consulta, la mappatura modifica."""
        rpct, tr = self._client("rpct"), self._client("trasparenza")
        p = self._ok(rpct.post(f"{API}/processi", base_url=ENTE, json={
            "tipo": "PROCEDIMENTO", "denominazione": "Accesso agli atti"}), 201)  # fmt: skip
        self.assertTrue(self._ok(tr.get(f"{TR}/procedimenti/pubblicazione", base_url=ENTE))["con_iter"])
        self.assertIn(p["id"], [x["id"] for x in self._ok(tr.get(f"{TR}/procedimenti", base_url=ENTE))])
        self._ok(tr.get(f"{TR}/procedimenti/{p['id']}", base_url=ENTE))
        for r in (tr.post(f"{TR}/procedimenti", base_url=ENTE, json={"denominazione": "x"}),
                  tr.put(f"{TR}/procedimenti/{p['id']}", base_url=ENTE, json={"denominazione": "x"}),
                  tr.delete(f"{TR}/procedimenti/{p['id']}", base_url=ENTE),
                  tr.post(f"{TR}/procedimenti/importazioni", base_url=ENTE, json={"url": "https://www.ente.it/at"})):
            self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
            self.assertIn("mappatura", r.get_json()["detail"])
        # l'interruttore della pagina pubblica dei procedimenti c'è anche per la trasparenza
        self._ok(tr.put(f"{TR}/procedimenti/pubblicazione", base_url=ENTE, json={"procedimenti_attiva": False}))
        self.assertFalse(self._ok(rpct.get(f"{API}/pubblicazione", base_url=ENTE))["procedimenti_attiva"])


if __name__ == "__main__":
    unittest.main()
