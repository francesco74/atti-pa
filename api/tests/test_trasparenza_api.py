"""Modulo trasparenza via HTTP: catalogo degli schemi, scheda generata dal form (validata
sul server, con nome e logo dell'ente), documenti privati con l'amministratore che li vede
tutti, verbale, esportazione (converter simulato), accesso per ruolo e per modulo.
    cd api/tests && python test_trasparenza_api.py
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
ENTE = "http://trasparenza.example.it"
SENZA_MODULO = "http://atti.example.it"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

DATI_SCHEDA = {
    "pdf_type": "ART_23",
    "sezione": "DIRIGENTI",
    "note": "Primo semestre",
    "righe": [{
        "data": "10/03/2026", "numero": "12", "denominazione": "Determinazione",
        "oggetto": "Affidamento <b>servizio</b>", "ufficio_struttura": "Servizi informatici",
    }],
}  # fmt: skip

REPORT = (
    '<p onclick="x()">Analisi</p><script>alert(1)</script>'
    '<span class="esito-validazione">Pubblicabile provvisoriamente</span>'
)


class ConverterFinto:
    def __init__(self):
        self.ricevuto: list[tuple[bytes, str, str]] = []

    async def converti(self, contenuto: bytes, nome_file: str, formato: str) -> bytes:
        self.ricevuto.append((contenuto, nome_file, formato))
        return b"%PDF-finto"

    async def close(self) -> None:
        pass


class TrasparenzaApi(unittest.TestCase):
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
                ente = Ente(codice="provincia", nome="Provincia di Prova", dati_json={},
                            moduli_json=[Modulo.TRASPARENZA], logo=PNG, logo_mime="image/png")  # fmt: skip
                altro = Ente(codice="comune", nome="Comune", dati_json={}, moduli_json=[Modulo.REDAZIONE])
                db.add_all([ente, altro])
                await db.flush()
                db.add_all([
                    EnteDominio(dominio="trasparenza.example.it", ente_id=ente.id),
                    EnteDominio(dominio="atti.example.it", ente_id=altro.id),
                ])  # fmt: skip
                for e, username, ruoli in [
                    (ente, "operatore", [Ruolo.TRASPARENZA]),
                    (ente, "collega", [Ruolo.TRASPARENZA]),
                    (ente, "admin", [Ruolo.ADMIN]),
                    (ente, "redattore", [Ruolo.REDATTORE]),
                    (altro, "operatore", [Ruolo.TRASPARENZA]),
                ]:
                    db.add(User(ente_id=e.id, username=username, origine="LOCALE",
                                password_hash=pw.calcola(PASSWORD), ruoli=ruoli))  # fmt: skip
                await db.commit()
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=url, jwt_secret="x" * 40, cookie_secure=False,
            llm_provider="ollama", llm_model="prova", archivio_dir=cls.cartella.name,
        )  # fmt: skip
        cls.app = create_app(settings)
        cls.converter = ConverterFinto()
        cls.app.state.documenti = cls.converter

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

    def test_catalogo_e_scheda(self):
        c = self._client("operatore")
        schemi = self._ok(c.get("/api/v1/trasparenza/schemi", base_url=ENTE))
        self.assertEqual(len(schemi), 19)
        self.assertIn("ART_23", {s["id"] for s in schemi})
        html = self._ok(c.post("/api/v1/trasparenza/schede", base_url=ENTE, json=DATI_SCHEDA))["html"]
        for atteso in ("Provincia di Prova", "Primo semestre", "Servizi informatici", "data:image/png;base64"):
            self.assertIn(atteso, html)
        self.assertNotIn("<b>servizio</b>", html)  # i valori dell'utente sono escapati
        # dati non validi: errori dal registro degli schemi
        sbagliati = {**DATI_SCHEDA, "righe": [{**DATI_SCHEDA["righe"][0], "data": "ieri"}]}
        r = c.post("/api/v1/trasparenza/schede", base_url=ENTE, json=sbagliati)
        self.assertEqual(r.status_code, 422)
        self.assertIn("Dati non validi", r.get_data(as_text=True))
        r = c.post("/api/v1/trasparenza/schede", base_url=ENTE, json={"pdf_type": "ART_99"})
        self.assertEqual(r.status_code, 422)

    def test_documenti_privati_e_amministratore(self):
        op, collega, admin = self._client("operatore"), self._client("collega"), self._client("admin")
        report = self._ok(op.post("/api/v1/trasparenza/documenti", base_url=ENTE,
                                  json={"descrizione": "Analisi art. 23", "html": REPORT}), 201)  # fmt: skip
        self.assertEqual((report["tipo"], report["esito"]), ("ANALISI", "Pubblicabile provvisoriamente"))
        scheda = self._ok(op.post("/api/v1/trasparenza/documenti", base_url=ENTE, json={
            "descrizione": "Scheda art. 23", "html": "<p>scheda</p>", "dati_schema": DATI_SCHEDA,
        }), 201)  # fmt: skip
        self.assertEqual((scheda["tipo"], scheda["schema_id"]), ("SCHEDA", "ART_23"))

        letto = self._ok(op.get(f"/api/v1/trasparenza/documenti/{report['id']}", base_url=ENTE))
        self.assertNotIn("script", letto["html"])
        self.assertNotIn("onclick", letto["html"])
        dati = self._ok(op.get(f"/api/v1/trasparenza/documenti/{scheda['id']}", base_url=ENTE))["dati_schema"]
        self.assertEqual(dati["sezione"], "DIRIGENTI")

        # il collega non li vede né li tocca
        self.assertEqual(self._ok(collega.get("/api/v1/trasparenza/documenti", base_url=ENTE)), [])
        self.assertEqual(collega.get(f"/api/v1/trasparenza/documenti/{report['id']}", base_url=ENTE).status_code, 404)
        self.assertEqual(collega.delete(f"/api/v1/trasparenza/documenti/{report['id']}", base_url=ENTE).status_code, 404)
        # l'amministratore li vede tutti, in sola lettura
        tutti = self._ok(admin.get("/api/v1/trasparenza/documenti", base_url=ENTE))
        self.assertGreaterEqual({d["id"] for d in tutti}, {report["id"], scheda["id"]})
        self.assertFalse(next(d for d in tutti if d["id"] == report["id"])["proprio"])
        self._ok(admin.get(f"/api/v1/trasparenza/documenti/{report['id']}", base_url=ENTE))
        modifica = {"descrizione": "x", "html": "<p>x</p>"}
        r = admin.put(f"/api/v1/trasparenza/documenti/{report['id']}", base_url=ENTE, json=modifica)
        self.assertEqual(r.status_code, 404)

        # aggiornamento: l'esito si ricalcola, i dati del form restano se non inviati
        agg = self._ok(op.put(f"/api/v1/trasparenza/documenti/{scheda['id']}", base_url=ENTE,
                              json={"descrizione": "Scheda rivista", "html": "<p>nuova</p>"}))  # fmt: skip
        self.assertEqual(agg["descrizione"], "Scheda rivista")
        dati = self._ok(op.get(f"/api/v1/trasparenza/documenti/{scheda['id']}", base_url=ENTE))["dati_schema"]
        self.assertEqual(dati["pdf_type"], "ART_23")

        # verbale con i documenti scelti; quelli di altri non entrano
        verbale = self._ok(op.post("/api/v1/trasparenza/verbale", base_url=ENTE,
                                   json={"documenti": [scheda["id"], report["id"]]}))["html"]  # fmt: skip
        self.assertIn("VERBALE n.", verbale)
        self.assertLess(verbale.index("nuova"), verbale.index("Analisi"))
        r = collega.post("/api/v1/trasparenza/verbale", base_url=ENTE, json={"documenti": [scheda["id"]]})
        self.assertEqual(r.status_code, 404)

        self.assertEqual(op.delete(f"/api/v1/trasparenza/documenti/{report['id']}", base_url=ENTE).status_code, 204)
        self.assertEqual(op.get(f"/api/v1/trasparenza/documenti/{report['id']}", base_url=ENTE).status_code, 404)

    def test_esportazione(self):
        c = self._client("operatore")
        html = '<p>Testo</p><img src="https://esterno.example/x.png"><img src="data:image/png;base64,AAAA">'
        r = c.post("/api/v1/trasparenza/esporta", base_url=ENTE,
                   json={"html": html, "nome": "scheda art. 23", "formato": "docx"})  # fmt: skip
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertIn('filename="scheda-art-23.docx"', r.headers["Content-Disposition"])
        contenuto, nome, formato = self.converter.ricevuto[-1]
        self.assertEqual((nome, formato), ("documento.html", "docx"))
        self.assertIn(b'<meta charset="utf-8">', contenuto)
        self.assertNotIn(b"esterno.example", contenuto)  # niente risorse esterne al converter
        self.assertIn(b"data:image/png;base64,AAAA", contenuto)

    def test_analisi_ed_estrazioni_in_coda(self):
        import io
        from pathlib import Path

        op, collega = self._client("operatore"), self._client("collega")
        r = op.post("/api/v1/trasparenza/analisi", base_url=ENTE, json={
            "controllo": "ART_23_DIRIGENTI", "url": "https://ente.example.it/at", "segui_link": True,
            "note": "Primo semestre", "data_pubblicazione": "15/07/2026",
        })  # fmt: skip
        lavoro = self._ok(r, 202)
        self.assertEqual((lavoro["tipo"], lavoro["stato"]), ("ANALISI", "IN_CODA"))
        stato = self._ok(op.get(f"/api/v1/trasparenza/lavori/{lavoro['id']}", base_url=ENTE))
        self.assertNotIn("risultato", stato)  # solo a lavoro completato
        self.assertEqual(collega.get(f"/api/v1/trasparenza/lavori/{lavoro['id']}", base_url=ENTE).status_code, 404)

        # file caricati: salvati nell'archivio, con le note dell'utente
        r = op.post("/api/v1/trasparenza/estrazioni", base_url=ENTE, content_type="multipart/form-data", data={
            "dati": '{"schema_id": "ART_23", "descrizioni": {"elenco.csv": "elenco semestrale"}}',
            "file": [(io.BytesIO(b"data;numero\n10/03/2026;12"), "elenco.csv")],
        })  # fmt: skip
        estrazione = self._ok(r, 202)
        self.assertEqual(estrazione["tipo"], "ESTRAZIONE")

        async def richiesta(lavoro_id):
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from common.models import TrasparenzaLavoro

            motore = create_async_engine(f"sqlite+aiosqlite:///{self.cartella.name}/prova.db")
            async with AsyncSession(motore) as db:
                dati = (await db.get(TrasparenzaLavoro, lavoro_id)).richiesta
            await motore.dispose()
            return dati

        salvata = asyncio.run(richiesta(estrazione["id"]))
        self.assertEqual(salvata["file"][0]["descrizione"], "elenco semestrale")
        self.assertTrue((Path(self.cartella.name) / salvata["file"][0]["percorso"]).exists())

        # richieste non valide
        for corpo, codice in [
            ({"controllo": "ART_23", "url": "https://ente.example.it"}, 422),  # serve la sezione
            ({"controllo": "ART_99", "url": "https://ente.example.it"}, 422),
            ({"controllo": "ART_23_DIRIGENTI"}, 422),  # né pagina né documenti
            ({"controllo": "ART_23_DIRIGENTI", "url": "file:///etc/passwd"}, 422),
        ]:
            with self.subTest(corpo=corpo):
                self.assertEqual(op.post("/api/v1/trasparenza/analisi", base_url=ENTE, json=corpo).status_code, codice)
        r = op.post("/api/v1/trasparenza/analisi", base_url=ENTE, content_type="multipart/form-data", data={
            "dati": '{"controllo": "ART_23_DIRIGENTI"}', "file": [(io.BytesIO(b"x"), "virus.exe")],
        })  # fmt: skip
        self.assertEqual(r.status_code, 415)

    def test_accesso_per_ruolo_e_modulo(self):
        redattore = self._client("redattore")
        self.assertEqual(redattore.get("/api/v1/trasparenza/schemi", base_url=ENTE).status_code, 403)
        senza = self._client("operatore", SENZA_MODULO)
        self.assertEqual(senza.get("/api/v1/trasparenza/schemi", base_url=SENZA_MODULO).status_code, 403)


if __name__ == "__main__":
    unittest.main()
