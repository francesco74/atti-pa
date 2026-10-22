"""Editor di modelli, specificità e checklist via HTTP: dettaglio, bozza, controllo,
anteprima, confronto, pubblicazione, proposte; pacchetti: esportazione e analisi.

L'API gira con l'autenticazione disattivata (utente locale con tutti i ruoli) su un
database SQLite temporaneo in cui è importato il pacchetto standard (pacchetto/). Non usa .env,
Normattiva né il modello linguistico.
    cd api/src && python -m unittest discover -s ../tests -t ..
"""

from __future__ import annotations

import asyncio
import io
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from common.config import Settings  # noqa: E402
from common.models import Base  # noqa: E402
from common.pacchetti import da_cartella, importa, leggi_pacchetto  # noqa: E402


class EditorApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import create_app

        cls.cartella = tempfile.TemporaryDirectory()
        cls.file_db = f"{cls.cartella.name}/prova.db"
        url = f"sqlite+aiosqlite:///{cls.file_db}"

        async def schema():
            motore = create_async_engine(url)
            async with motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(motore) as db:
                await importa(db, leggi_pacchetto(da_cartella(RADICE / "pacchetto")))
                await db.commit()
            await motore.dispose()

        asyncio.run(schema())
        settings = Settings(
            _env_file=None,
            database_url=url,
            auth_enabled=False,
            llm_provider="ollama",
            llm_model="prova",
            archivio_dir=cls.cartella.name,
        )
        cls.app = create_app(settings)
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()

    def _ok(self, risposta, codice=200):
        self.assertEqual(risposta.status_code, codice, risposta.get_data(as_text=True)[:500])
        return risposta.get_json()

    def _prendi(self, base):
        self.assertEqual(self.c.post(f"{base}/prendi").status_code, 204)

    def test_elenco_e_dettaglio(self):
        elenco = self._ok(self.c.get("/api/v1/configurazione"))
        # i test girano sullo stesso database: altri possono aver aggiunto oggetti
        self.assertGreaterEqual(len(elenco["modelli"]), 4)
        self.assertGreaterEqual(len(elenco["moduli"]), 7)
        self.assertGreaterEqual(len(elenco["checklist"]), 12)
        sf = next(m for m in elenco["modelli"] if m["codice"] == "DD_AFFIDAMENTO_DIRETTO_SF")
        self.assertEqual(sf["pacchetto"], "Modelli standard Atti PA 2026.1")
        d = self._ok(self.c.get("/api/v1/configurazione/modello/DD_AFFIDAMENTO_DIRETTO_SF"))
        self.assertGreaterEqual(d["pubblicata"]["versione"], 1)  # altri test lo ricompongono
        self.assertIsNotNone(d["standard"])
        self.assertEqual(d["stato"], "ABILITATO")
        self.assertEqual(len(d["contesto"]["modelli"]), 4)

    def test_modifica_capoverso_bozza_anteprima_pubblica(self):
        base = "/api/v1/configurazione/modello/DD_INCARICO_PATROCINIO_LEGALE"
        d = self._ok(self.c.get(base))["pubblicata"]["definizione"]
        for f in d["fasi"]:
            for s in f["sezioni"]:
                for cap in s["capoversi"]:
                    if cap["id"] == "necessita_legale":
                        cap["testo"] = "Considerato che l'ente non ha un'avvocatura interna;"
        # senza presa in carico non si modifica
        self.assertEqual(self.c.put(f"{base}/bozza", json={"definizione": d}).status_code, 409)
        self._prendi(base)
        self.assertEqual(self._ok(self.c.get(base))["stato"], "IN_REDAZIONE")
        esito = self._ok(self.c.put(f"{base}/bozza", json={"definizione": d}))
        self.assertEqual(esito["errori"], [])
        # la bozza non cambia la versione usata dagli atti
        self.assertIsNotNone(self._ok(self.c.get(base))["bozza"])
        anteprima = self._ok(
            self.c.post(f"{base}/anteprima", json={"definizione": d, "risposte": {}})
        )
        testi = [
            c["testo"] for f in anteprima["fasi"] for s in f["sezioni"] for c in s["capoversi"]
        ]
        self.assertIn("Considerato che l'ente non ha un'avvocatura interna;", testi)
        diff = self._ok(self.c.post(f"{base}/confronta", json={"definizione": d}))["differenze"]
        self.assertEqual([x["chiave"] for x in diff], ["capoverso:necessita_legale"])
        pub = self._ok(self.c.post(f"{base}/pubblica"))
        self.assertEqual(pub["versione"], 2)
        dopo = self._ok(self.c.get(base))
        self.assertIsNone(dopo["bozza"])
        self.assertTrue(dopo["pubblicata"]["modificato"])  # rispetto allo standard
        diff = self._ok(
            self.c.post(f"{base}/confronta", json={"definizione": dopo["pubblicata"]["definizione"], "con": "standard"})
        )["differenze"]
        self.assertEqual([x["chiave"] for x in diff], ["capoverso:necessita_legale"])
        storico = self._ok(self.c.get(f"{base}/storico"))
        self.assertEqual([v["versione"] for v in storico], [2, 1])

    def test_errori_impediscono_la_pubblicazione(self):
        base = "/api/v1/configurazione/modello/DD_CONCESSIONE_CONTRIBUTO"
        d = self._ok(self.c.get(base))["pubblicata"]["definizione"]
        d["fasi"][0]["sezioni"][1]["capoversi"][0]["testo"] = "Contributo a {{dato_inesistente}}"
        d["fasi"][0]["sezioni"][1]["capoversi"][0]["se"] = "domanda_che_non_esiste"
        self._prendi(base)
        esito = self._ok(self.c.put(f"{base}/bozza", json={"definizione": d}))
        self.assertTrue(any("dato_inesistente" in e for e in esito["errori"]))
        self.assertTrue(any("domanda_che_non_esiste" in e for e in esito["errori"]))
        self.assertEqual(self.c.post(f"{base}/pubblica").status_code, 422)
        self.assertEqual(self.c.delete(f"{base}/bozza").status_code, 204)

    def test_specificita_anteprima_e_ricomposizione(self):
        base = "/api/v1/configurazione/modulo/CAM"
        d = self._ok(self.c.get(base))["pubblicata"]["definizione"]
        anteprima = self._ok(
            self.c.post(f"{base}/anteprima", json={"definizione": d, "modello": "DD_AFFIDAMENTO_DIRETTO_LAVORI"})
        )
        evidenziati = [
            c["id"] for f in anteprima["fasi"] for s in f["sezioni"] for c in s["capoversi"]
            if c["evidenziato"]
        ]
        self.assertIn("cam_inseriti", evidenziati)
        d["etichetta"] = "Criteri ambientali minimi"
        self._prendi(base)
        self._ok(self.c.put(f"{base}/bozza", json={"definizione": d}))
        self._ok(self.c.post(f"{base}/pubblica"))
        elenco = self._ok(self.c.get("/api/v1/configurazione"))
        versioni = {m["codice"]: m["versione"] for m in elenco["modelli"]}
        self.assertGreaterEqual(versioni["DD_AFFIDAMENTO_DIRETTO_LAVORI"], 2)  # ricomposto

    def test_checklist_collegamenti_e_nuovo_oggetto(self):
        base = "/api/v1/configurazione/checklist/SCHEDA_SIA"
        d = self._ok(self.c.get(base))["pubblicata"]["definizione"]
        d["elementi"][0]["capoversi"] = ["sia_corrispettivo", "capoverso_inventato"]
        esito = self._ok(self.c.post(f"{base}/controlla", json={"definizione": d}))
        self.assertEqual(esito["errori"], [])
        self.assertTrue(any("capoverso_inventato" in a for a in esito["avvisi"]))
        nuovo = self.c.post(
            "/api/v1/configurazione/checklist/nuovo",
            json={"codice": "SCHEDA_SIA_ENTE", "copia_da": "SCHEDA_SIA"},
        )
        self._ok(nuovo, 201)
        d = self._ok(self.c.get("/api/v1/configurazione/checklist/SCHEDA_SIA_ENTE"))
        self.assertIsNone(d["pubblicata"])
        self.assertEqual(d["bozza"]["definizione"]["codice"], "SCHEDA_SIA_ENTE")
        self.assertEqual(self.c.post("/api/v1/configurazione/checklist/SCHEDA_SIA_ENTE/pubblica").status_code, 200)

    def test_redazione_bloccata_da_un_altro(self):
        base = "/api/v1/configurazione/modulo/MANODOPERA"
        self._prendi(base)
        # la bozza passa a un altro utente
        c = sqlite3.connect(self.file_db)
        with c:
            c.execute(
                "UPDATE bozze_configurazione SET autore_id = 'altro' WHERE codice = 'MANODOPERA'"
            )
        c.close()
        d = self._ok(self.c.get(base))
        self.assertEqual(d["stato"], "IN_REDAZIONE")
        self.assertFalse(d["redazione"]["mia"])
        r = self.c.put(f"{base}/bozza", json={"definizione": d["bozza"]["definizione"]})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.c.post(f"{base}/prendi").status_code, 409)
        # gli atti continuano a usare la versione pubblicata
        self.assertIsNotNone(d["pubblicata"])
        # l'amministratore sblocca e la bozza diventa sua
        self.assertEqual(self.c.post(f"{base}/sblocca").status_code, 204)
        self.assertTrue(self._ok(self.c.get(base))["redazione"]["mia"])
        self.assertEqual(self.c.delete(f"{base}/bozza").status_code, 204)
        self.assertEqual(self._ok(self.c.get(base))["stato"], "ABILITATO")

    def test_disattiva_e_riattiva(self):
        base = "/api/v1/configurazione/checklist/SCHEDA_UTENZE"
        esito = self._ok(self.c.post(f"{base}/disattiva"))
        self.assertEqual(esito["avvisi"], [])
        d = self._ok(self.c.get(base))
        self.assertEqual(d["stato"], "DISATTIVATO")
        self.assertEqual(self.c.post(f"{base}/prendi").status_code, 409)
        elenco = self._ok(self.c.get("/api/v1/configurazione"))
        voce = next(c for c in elenco["checklist"] if c["codice"] == "SCHEDA_UTENZE")
        self.assertEqual(voce["stato"], "DISATTIVATO")
        nuovo = self.c.post("/api/v1/configurazione/checklist/nuovo", json={"codice": "SCHEDA_UTENZE"})
        self.assertEqual(nuovo.status_code, 409)  # codice già usato
        self._ok(self.c.post(f"{base}/riattiva"))
        self.assertEqual(self._ok(self.c.get(base))["stato"], "ABILITATO")
        # una specificità disattivata esce dai modelli, che sono ricomposti
        modulo = "/api/v1/configurazione/modulo/UTENZE"
        prima = {m["codice"]: m["versione"] for m in self._ok(self.c.get("/api/v1/configurazione"))["modelli"]}
        esito = self._ok(self.c.post(f"{modulo}/disattiva"))
        self.assertTrue(any("SCHEDA_UTENZE" in a for a in esito["avvisi"]))
        dopo = {m["codice"]: m["versione"] for m in self._ok(self.c.get("/api/v1/configurazione"))["modelli"]}
        self.assertGreater(dopo["DD_AFFIDAMENTO_DIRETTO_SF"], prima["DD_AFFIDAMENTO_DIRETTO_SF"])
        self._ok(self.c.post(f"{modulo}/riattiva"))

    def test_sorgente(self):
        d = self._ok(self.c.get("/api/v1/configurazione/modulo/UTENZE"))["pubblicata"]["definizione"]
        s = self._ok(self.c.post("/api/v1/configurazione/modulo/sorgente", json={"definizione": d}))
        di_nuovo = self._ok(
            self.c.post("/api/v1/configurazione/sorgente", json={"tipo": "modulo", "sorgente": s["sorgente"]})
        )["definizione"]
        self.assertEqual(di_nuovo, d)
        rotto = self.c.post(
            "/api/v1/configurazione/sorgente", json={"tipo": "modulo", "sorgente": "codice: [rotto"}
        )
        self.assertEqual(rotto.status_code, 422)

    def test_proposte(self):
        p = self._ok(
            self.c.post(
                "/api/v1/proposte",
                json={
                    "modello": "DD_AFFIDAMENTO_DIRETTO_SF", "versione": 1, "capoverso": "esigenza",
                    "testo_attuale": "x", "testo_proposto": "y", "motivazione": "più chiaro",
                },
            ),
            201,
        )
        aperte = self._ok(self.c.get("/api/v1/proposte?modello=DD_AFFIDAMENTO_DIRETTO_SF"))
        self.assertEqual([x["id"] for x in aperte], [p["id"]])
        self._ok(self.c.put(f"/api/v1/proposte/{p['id']}", json={"stato": "ACCOLTA"}))
        self.assertEqual(self._ok(self.c.get("/api/v1/proposte?modello=DD_AFFIDAMENTO_DIRETTO_SF")), [])

    def test_esporta_e_analizza_pacchetto(self):
        r = self.c.get("/api/v1/pacchetti/esporta")
        self.assertEqual(r.status_code, 200)
        nomi = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
        self.assertIn("pacchetto.yaml", nomi)
        analisi = self._ok(
            self.c.post(
                "/api/v1/pacchetti",
                data={"file": (io.BytesIO(r.data), "configurazione.zip")},
                content_type="multipart/form-data",
            ),
            201,
        )
        self.assertEqual(analisi["stato"], "ANALIZZATO")
        self.assertTrue(analisi["analisi_json"])
        self.assertEqual(self.c.delete(f"/api/v1/pacchetti/{analisi['id']}").status_code, 204)


if __name__ == "__main__":
    unittest.main()
