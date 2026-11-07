"""Registro delle ricerche e feedback via HTTP: registrazione delle ricerche concluse e dei
feedback (utenti interni e cittadini, dati personali oscurati, limiti), consultazione per chi ha
il ruolo ANALISI_RICERCHE o è amministratore (raggruppamento, gestione, riepilogo, CSV).
    cd api/tests && python test_registro_ricerche_api.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from auth import password as pw  # noqa: E402
from common import registro_ricerche as reg  # noqa: E402
from common.config import Settings  # noqa: E402
from common.models import (  # noqa: E402
    Base, Ente, EnteDominio, Modulo, RicercaFeedback, RicercaRegistrata, Ruolo, User,
)  # fmt: skip

PASSWORD = "Password-di-prova-1"
ENTE = "http://lucca.example.it"
ALTRO = "http://altro.example.it"
API = "/api/v1/ricerche"
PUBBLICO = "/api/v1/pubblico"


class RegistroRicercheApi(unittest.TestCase):
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
                ente = Ente(codice="lucca", nome="Comune di Lucca", dati_json={}, moduli_json=[Modulo.ANTICORRUZIONE],
                            procedimenti_pubblici=True)  # fmt: skip
                altro = Ente(codice="altro", nome="Altro", dati_json={}, moduli_json=[Modulo.REDAZIONE])
                db.add_all([ente, altro])
                await db.flush()
                db.add_all([EnteDominio(dominio="lucca.example.it", ente_id=ente.id),
                            EnteDominio(dominio="altro.example.it", ente_id=altro.id)])  # fmt: skip
                for username, ruoli, e in [
                    ("referente", [Ruolo.ANTICORRUZIONE_REFERENTE], ente),
                    ("statistica", [Ruolo.ANALISI_RICERCHE], ente),
                    ("admin", [Ruolo.ADMIN], ente),
                    ("altro", [Ruolo.ANALISI_RICERCHE], altro),
                ]:
                    db.add(User(ente_id=e.id, username=username, origine="LOCALE", nome_completo=username.title(),
                                password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
                await db.commit()
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=cls.url, jwt_secret="x" * 40, cookie_secure=False,
            llm_provider="ollama", llm_model="prova", archivio_dir=cls.cartella.name,
            ricerche_limite_registro=1000,
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

    def _sql(self, funzione):
        async def esegui():
            motore = create_async_engine(self.url)
            async with AsyncSession(motore, expire_on_commit=False) as db:
                risultato = await funzione(db)
                await db.commit()
            await motore.dispose()
            return risultato

        return asyncio.run(esegui())

    def _svuota(self):
        async def svuota(db):
            await db.execute(RicercaFeedback.__table__.delete())
            await db.execute(RicercaRegistrata.__table__.delete())

        self._sql(svuota)

    def setUp(self):
        self._svuota()

    def _ricerca(self, client, testo, esito="NESSUN_RISULTATO", ambito="MAPPATURA", base=ENTE, percorso=API, **altro):
        return self._ok(client.post(f"{percorso}/registro", base_url=base, json={
            "ambito": ambito, "testo": testo, "risultati": 0 if esito == "NESSUN_RISULTATO" else 3,
            "esito": esito, **altro}), 201)["id"]  # fmt: skip

    def test_registrazione_interna(self):
        referente = self._client("referente")
        rid = self._ricerca(referente, "Contributo affitto, chiamatemi al 0583 123456 o mario@esempio.it")
        r = self._sql(lambda db: db.get(RicercaRegistrata, rid))
        self.assertEqual(r.testo, "Contributo affitto, chiamatemi al [omissis] o [omissis]")
        self.assertEqual((r.pubblica, r.chiave), (False, reg.chiave("affitti contributi chiamatemi omissis omissis")))
        self.assertIsNone(r.posizione)
        # ambito sconosciuto o di un modulo non attivo
        for ambito in ("XYZ",):
            self.assertEqual(referente.post(f"{API}/registro", base_url=ENTE, json={
                "ambito": ambito, "testo": "x", "risultati": 0, "esito": "NESSUN_RISULTATO"}).status_code, 422)  # fmt: skip
        altro = self._client("altro", ALTRO)  # ente senza anticorruzione
        self.assertEqual(altro.post(f"{API}/registro", base_url=ALTRO, json={
            "ambito": "MAPPATURA", "testo": "x", "risultati": 0, "esito": "NESSUN_RISULTATO"}).status_code, 422)  # fmt: skip
        self.assertEqual(self.app.test_client().post(f"{API}/registro", base_url=ENTE, json={}).status_code, 401)

        # feedback: una volta per ricerca, con il commento oscurato
        self._ok(referente.post(f"{API}/feedback", base_url=ENTE, json={
            "ambito": "MAPPATURA", "tipo": "RICERCA", "ricerca_id": rid, "utile": False,
            "commento": "Cercavo il bando, CF RSSMRA80A01E715X"}), 201)  # fmt: skip
        self.assertEqual(referente.post(f"{API}/feedback", base_url=ENTE, json={
            "ambito": "MAPPATURA", "tipo": "RICERCA", "ricerca_id": rid, "utile": True}).status_code, 409)  # fmt: skip
        f = self._sql(lambda db: db.scalar(select(RicercaFeedback)))
        self.assertEqual((f.commento, f.testo, f.pubblica), ("Cercavo il bando, CF [omissis]", r.testo, False))
        # la ricerca di un cittadino non si usa per il feedback interno
        pubblica = self._ricerca(self.app.test_client(), "affitto", ambito="PROCEDIMENTI", percorso=f"{PUBBLICO}/ricerche")
        self.assertEqual(referente.post(f"{API}/feedback", base_url=ENTE, json={
            "ambito": "MAPPATURA", "tipo": "RICERCA", "ricerca_id": pubblica, "utile": True}).status_code, 422)  # fmt: skip

    def test_registrazione_pubblica(self):
        cittadino = self.app.test_client()
        percorso = f"{PUBBLICO}/ricerche"
        rid = self._ricerca(cittadino, "contributo per l'affitto", "TROVATA", "PROCEDIMENTI", percorso=percorso, posizione=2)
        r = self._sql(lambda db: db.get(RicercaRegistrata, rid))
        self.assertEqual((r.pubblica, r.posizione, r.esito), (True, 2, "TROVATA"))
        # mappatura non pubblicata: ambito non ammesso; ente senza pagine pubbliche: 404
        self.assertEqual(cittadino.post(f"{percorso}/registro", base_url=ENTE, json={
            "ambito": "MAPPATURA", "testo": "x", "risultati": 0, "esito": "NESSUN_RISULTATO"}).status_code, 422)  # fmt: skip
        self.assertEqual(cittadino.post(f"{percorso}/registro", base_url=ALTRO, json={
            "ambito": "PROCEDIMENTI", "testo": "x", "risultati": 0, "esito": "NESSUN_RISULTATO"}).status_code, 404)  # fmt: skip
        # feedback sulla scheda di un procedimento
        self._ok(cittadino.post(f"{percorso}/feedback", base_url=ENTE, json={
            "ambito": "PROCEDIMENTI", "tipo": "SCHEDA", "riferimento_id": "p1", "riferimento": "Contributo affitto",
            "utile": False, "commento": "Manca il modulo"}), 201)  # fmt: skip
        self.assertEqual(cittadino.post(f"{percorso}/feedback", base_url=ENTE, json={
            "ambito": "PROCEDIMENTI", "tipo": "SCHEDA", "utile": True}).status_code, 422)  # fmt: skip

        # segnalazione di accessibilità: descrizione obbligatoria, email facoltativa e non oscurata
        corpo = {"ambito": "PROCEDIMENTI", "tipo": "ACCESSIBILITA", "riferimento": "Tipologie di procedimento", "utile": False}
        self.assertEqual(cittadino.post(f"{percorso}/feedback", base_url=ENTE, json=corpo).status_code, 422)
        self.assertEqual(cittadino.post(f"{percorso}/feedback", base_url=ENTE, json={
            **corpo, "commento": "x", "contatto": "non-email"}).status_code, 422)  # fmt: skip
        fid = self._ok(cittadino.post(f"{percorso}/feedback", base_url=ENTE, json={
            **corpo, "commento": "Il lettore di schermo non legge la tabella", "contatto": "mario@esempio.it"}), 201)["id"]  # fmt: skip
        f = self._sql(lambda db: db.get(RicercaFeedback, fid))
        self.assertEqual((f.tipo, f.contatto, f.riferimento, f.utile),
                         ("ACCESSIBILITA", "mario@esempio.it", "Tipologie di procedimento", False))  # fmt: skip
        elenco = self._ok(self._client("statistica").get(f"{API}/feedback", base_url=ENTE, query_string={"tipo": "ACCESSIBILITA"}))
        self.assertEqual([x["contatto"] for x in elenco], ["mario@esempio.it"])

    def test_limite_pubblico(self):
        import routers.pubblico as pubblico
        from ricerca import LimiteRichieste

        prima = pubblico._limite_registro
        pubblico._limite_registro = LimiteRichieste(2)
        try:
            cittadino = self.app.test_client()
            corpo = {"ambito": "PROCEDIMENTI", "testo": "x", "risultati": 0, "esito": "NESSUN_RISULTATO"}
            codici = [cittadino.post(f"{PUBBLICO}/ricerche/registro", base_url=ENTE, json=corpo).status_code for _ in range(3)]
            self.assertEqual(codici, [201, 201, 429])
        finally:
            pubblico._limite_registro = prima

    def test_consultazione(self):
        referente, cittadino = self._client("referente"), self.app.test_client()
        percorso = f"{PUBBLICO}/ricerche"
        self._ricerca(referente, "contributo affitto")
        self._ricerca(cittadino, "Affitti contributi", ambito="PROCEDIMENTI", percorso=percorso)
        self._ricerca(cittadino, "affitti contributi", "RISULTATI_DEBOLI", "PROCEDIMENTI", percorso=percorso)
        self._ricerca(cittadino, "affitto", "TROVATA", "PROCEDIMENTI", percorso=percorso, posizione=1)
        self._ricerca(cittadino, "passo carrabile", "NON_APERTI", "PROCEDIMENTI", percorso=percorso)

        # solo il ruolo ANALISI_RICERCHE e l'amministratore
        self.assertEqual(referente.get(f"{API}/senza-risposta", base_url=ENTE).status_code, 403)
        statistica = self._client("statistica")
        self._ok(self._client("admin").get(f"{API}/senza-risposta", base_url=ENTE))
        self.assertEqual(self._ok(statistica.get(f"{API}/ambiti", base_url=ENTE)),
                         [{"id": "MAPPATURA", "descrizione": "Mappatura dei processi"},
                          {"id": "PROCEDIMENTI", "descrizione": "Procedimenti (art. 35)"}])  # fmt: skip

        gruppi = self._ok(statistica.get(f"{API}/senza-risposta", base_url=ENTE))
        self.assertEqual([(g["ambito"], g["testo"], g["volte"]) for g in gruppi],
                         [("PROCEDIMENTI", "Affitti contributi", 2), ("MAPPATURA", "contributo affitto", 1),
                          ("PROCEDIMENTI", "passo carrabile", 1)])  # fmt: skip
        self.assertEqual(gruppi[0]["esiti"], {"NESSUN_RISULTATO": 1, "RISULTATI_DEBOLI": 1})
        self.assertEqual(gruppi[0]["pubbliche"], 2)
        solo_interne = self._ok(statistica.get(f"{API}/senza-risposta", base_url=ENTE, query_string={"pubblica": "false"}))
        self.assertEqual([g["testo"] for g in solo_interne], ["contributo affitto"])

        # gestione del gruppo: sparisce; una nuova ricerca uguale lo fa ricomparire con la nota
        g = gruppi[0]
        self.assertEqual(self._ok(statistica.put(f"{API}/senza-risposta/gestione", base_url=ENTE, json={
            "ambito": g["ambito"], "chiave": g["chiave"], "nota": "Aggiunto 'locazione' alla descrizione"})), {"gestite": 2})  # fmt: skip
        gruppi = self._ok(statistica.get(f"{API}/senza-risposta", base_url=ENTE))
        self.assertNotIn(g["chiave"], [x["chiave"] for x in gruppi if x["ambito"] == "PROCEDIMENTI"])
        self._ricerca(cittadino, "contributi affitto", ambito="PROCEDIMENTI", percorso=percorso)
        gruppo = next(x for x in self._ok(statistica.get(f"{API}/senza-risposta", base_url=ENTE))
                      if x["chiave"] == g["chiave"] and x["ambito"] == "PROCEDIMENTI")  # fmt: skip
        self.assertEqual((gruppo["volte"], gruppo["da_gestire"], gruppo["gestita_da"]), (3, 1, "Statistica"))
        self.assertEqual(gruppo["nota"], "Aggiunto 'locazione' alla descrizione")

        # feedback
        self._ok(cittadino.post(f"{percorso}/feedback", base_url=ENTE, json={
            "ambito": "PROCEDIMENTI", "tipo": "SCHEDA", "riferimento_id": "p1", "riferimento": "Contributo affitto",
            "utile": False, "commento": "Manca il modulo"}), 201)  # fmt: skip
        self._ok(cittadino.post(f"{percorso}/feedback", base_url=ENTE, json={
            "ambito": "PROCEDIMENTI", "tipo": "SCHEDA", "riferimento_id": "p1", "riferimento": "Contributo affitto",
            "utile": True}), 201)  # fmt: skip
        negativi = self._ok(statistica.get(f"{API}/feedback", base_url=ENTE, query_string={"utile": "false"}))
        self.assertEqual([(x["riferimento"], x["commento"]) for x in negativi], [("Contributo affitto", "Manca il modulo")])
        gestito = self._ok(statistica.put(f"{API}/feedback/{negativi[0]['id']}/gestione", base_url=ENTE,
                                          json={"nota": "Modulo pubblicato"}))  # fmt: skip
        self.assertEqual((gestito["nota"], gestito["gestito_da"]), ("Modulo pubblicato", "Statistica"))
        self.assertEqual(self._ok(statistica.get(f"{API}/feedback", base_url=ENTE, query_string={"utile": "false"})), [])
        self.assertEqual(len(self._ok(statistica.get(f"{API}/feedback", base_url=ENTE,
                                                     query_string={"utile": "false", "gestite": "true"}))), 1)  # fmt: skip
        # altro ente: niente
        self.assertEqual(self._client("altro", ALTRO).put(f"{API}/feedback/{negativi[0]['id']}/gestione", base_url=ALTRO,
                                                          json={"nota": "x"}).status_code, 404)  # fmt: skip

        # riepilogo del mese
        riepilogo = self._ok(statistica.get(f"{API}/riepilogo", base_url=ENTE))
        [mese] = riepilogo["mesi"]
        self.assertEqual({k: mese[k] for k in ("ricerche", "trovate", "senza_risposta", "utili", "non_utili")},
                         {"ricerche": 6, "trovate": 1, "senza_risposta": 5, "utili": 1, "non_utili": 1})  # fmt: skip
        self.assertEqual(riepilogo["schede_non_utili"], [{"riferimento": "Contributo affitto", "volte": 1}])
        # periodo senza dati
        ieri = (datetime.now() - timedelta(days=1)).date().isoformat()
        self.assertEqual(self._ok(statistica.get(f"{API}/riepilogo", base_url=ENTE, query_string={"a": ieri}))["mesi"], [])

        # CSV
        r = statistica.get(f"{API}/esporta/senza-risposta", base_url=ENTE)
        self.assertEqual(r.status_code, 200)
        testo = r.get_data().decode("utf-8-sig")
        self.assertTrue(testo.startswith("Ambito;Domanda;Varianti"))
        self.assertIn("passo carrabile", testo)
        r = statistica.get(f"{API}/esporta/feedback", base_url=ENTE, query_string={"gestite": "true"})
        self.assertIn("Manca il modulo", r.get_data().decode("utf-8-sig"))

    def test_pulizia(self):
        self._ricerca(self._client("referente"), "vecchia")
        self._ricerca(self._client("referente"), "recente")

        async def invecchia(db):
            await db.execute(update(RicercaRegistrata).where(RicercaRegistrata.testo == "vecchia")
                             .values(created_at=datetime.now() - timedelta(days=400)))  # fmt: skip

        self._sql(invecchia)
        self.assertEqual(self._sql(lambda db: reg.pulisci(db, 12)), 1)
        testi = self._sql(lambda db: db.scalars(select(RicercaRegistrata.testo)))
        self.assertEqual(list(testi), ["recente"])
        self.assertEqual(self._sql(lambda db: db.scalar(select(func.count()).select_from(RicercaRegistrata))), 1)


if __name__ == "__main__":
    unittest.main()
