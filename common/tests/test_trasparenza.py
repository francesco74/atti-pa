"""Modulo trasparenza senza rete né LLM veri: contenuti per l'LLM (fogli di calcolo, CSV,
documenti, pagina web con PDF collegati), prompt dell'analisi, report sanificato, estrazione
dei dati con lo schema JSON standard, protezione SSRF.
    python -m unittest common.tests.test_trasparenza
"""

from __future__ import annotations

import asyncio
import io
import unittest
from unittest import mock

import httpx
import openpyxl

from common.trasparenza import analisi, fonti, rete
from common.trasparenza.estrazione import json_schema
from common.trasparenza.registro import get_schema
from common.trasparenza.sicurezza import estrai_esito


class LlmFinto:
    """Registra le richieste; risponde con le risposte preparate, nell'ordine."""

    modello = "finto"

    def __init__(self, *risposte):
        self.risposte = list(risposte)
        self.richieste: list[tuple] = []

    async def dati_json(self, sistema, testo, schema):
        self.richieste.append((sistema, testo, schema))
        return self.risposte.pop(0)


class ConverterFinto:
    def __init__(self, testi: dict[str, str]):
        self.testi = testi

    async def markdown(self, contenuto: bytes, nome_file: str) -> str:
        return self.testi[nome_file]


def _esegui(coro):
    return asyncio.run(coro)


def _xlsx() -> bytes:
    libro = openpyxl.Workbook()
    foglio = libro.active
    foglio.append(["Beneficiario", "Importo", "Anno"])
    foglio.append(["Associazione | Uno", 1026.37, 2025])
    foglio["B2"].number_format = "#,##0.00"
    dati = io.BytesIO()
    libro.save(dati)
    return dati.getvalue()


class Fonti(unittest.TestCase):
    def test_foglio_con_i_numeri_come_li_vede_l_utente(self):
        tabella = fonti.tabella_foglio(_xlsx(), "xlsx")
        righe = tabella.splitlines()
        self.assertEqual(righe[0], "| Beneficiario | Importo | Anno |")
        self.assertIn("1.026,37 [visualizzato in Excel; formato interno: #,##0.00]", tabella)
        self.assertIn("Associazione \\| Uno", tabella)  # il separatore non rompe la tabella
        self.assertIn("| 2025 |", tabella)

    def test_numero_senza_separatore_delle_migliaia(self):
        self.assertEqual(fonti._numero_italiano(1026.375, "0.00"), "1026,38")

    def test_csv_in_latin1(self):
        self.assertEqual(fonti.testo_csv("città;importo".encode("latin-1")), "città;importo")


class Ssrf(unittest.TestCase):
    def test_indirizzi_interni_e_schemi_non_ammessi(self):
        for url in ("ftp://example.org/x", "http://127.0.0.1/", "http://10.1.2.3/admin", "http://[::1]/",
                    "http://169.254.169.254/latest/meta-data", "http://localhost:3306/"):  # fmt: skip
            with self.subTest(url=url), self.assertRaises(rete.UrlNonConsentito):
                rete.verifica_url(url)


class Contenuti(unittest.TestCase):
    def test_piu_file_con_la_mappa_dei_documenti(self):
        files = [
            analisi.File("delibera.pdf", b"%PDF", "delibera di approvazione"),
            analisi.File("importi.xlsx", _xlsx()),
            analisi.File("elenco.csv", b"nome;importo\nRossi;10,00"),
        ]
        c = _esegui(analisi.contenuti("", files, ConverterFinto({"delibera.pdf": "# Delibera n. 12"})))
        self.assertEqual(c.estensione, "Insieme di documenti misti")
        self.assertIn("Documento [1]: delibera.pdf | Note utente: delibera di approvazione | Estensione: PDF", c.testo)
        for atteso in ("# Delibera n. 12", "1.026,37", "Rossi;10,00"):
            self.assertIn(atteso, c.testo)

    def test_scansione_senza_testo(self):
        with self.assertRaises(analisi.AnalisiNonRiuscita):
            _esegui(analisi.contenuti("", [analisi.File("scansione.pdf", b"%PDF")], ConverterFinto({"scansione.pdf": " "})))

    def test_pagina_web_con_pdf_collegato(self):
        pagine = {
            "https://ente.example.it/at/provvedimenti": (
                "text/html",
                b'<html><head><script>x()</script></head><body><nav><a href="/menu">Menu</a></nav>'
                b'<main><h1>Provvedimenti dei dirigenti</h1><a href="/doc/elenco.pdf">Elenco</a>'
                b'<a href="/at/dettaglio">Dettaglio</a></main></body></html>',
            ),
            "https://ente.example.it/doc/elenco.pdf": ("application/pdf", b"%PDF-elenco"),
            "https://ente.example.it/at/dettaglio": ("text/html", b"<body><p>Determina 12/2026</p></body>"),
            "https://ente.example.it/menu": ("text/html", b"<body><p>NON DEVE ESSERE SEGUITO</p></body>"),
        }

        def risposta(richiesta: httpx.Request) -> httpx.Response:
            tipo, corpo = pagine[str(richiesta.url)]
            return httpx.Response(200, headers={"Content-Type": tipo}, content=corpo)

        client = httpx.AsyncClient(transport=httpx.MockTransport(risposta))
        with mock.patch.object(rete, "_host_pubblico", return_value=True):
            c = _esegui(analisi.contenuti(
                "https://ente.example.it/at/provvedimenti", [], ConverterFinto({"elenco.pdf": "Elenco dei provvedimenti"}),
                analizza_pdf=True, segui_link=True, client=client,
            ))  # fmt: skip
        self.assertEqual(c.url, "https://ente.example.it/at/provvedimenti")
        testo = c.testo
        self.assertIn("Provvedimenti dei dirigenti", testo)
        self.assertIn("[FILE ALLEGATO: elenco.pdf]", testo)
        self.assertIn("Elenco dei provvedimenti", testo)  # testo del PDF dal converter
        self.assertIn("Determina 12/2026", testo)  # pagina collegata dal contenuto
        self.assertNotIn("NON DEVE ESSERE SEGUITO", testo)  # link di navigazione ignorato
        self.assertNotIn("x()", testo)

    def test_numero_di_link_seguiti(self):
        corpo = "".join(f'<a href="/at/p{i}">Procedimento {i}</a>' for i in range(20))
        pagine = {"https://ente.example.it/at": f"<body><main>{corpo}</main></body>".encode()}
        pagine |= {f"https://ente.example.it/at/p{i}": f"<body><p>Scheda {i}.</p></body>".encode() for i in range(20)}

        def risposta(richiesta: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"Content-Type": "text/html"}, content=pagine[str(richiesta.url)])

        def schede(**opzioni) -> int:
            client = httpx.AsyncClient(transport=httpx.MockTransport(risposta))
            with mock.patch.object(rete, "_host_pubblico", return_value=True):
                c = _esegui(analisi.contenuti("https://ente.example.it/at", [], ConverterFinto({}),
                                              segui_link=True, client=client, **opzioni))  # fmt: skip
            return sum(f"Scheda {i}." in c.testo for i in range(20))

        self.assertEqual(schede(), 5)  # predefinito
        self.assertEqual(schede(max_link=12), 12)
        self.assertEqual(schede(max_link=50), 15)  # limite massimo


class Analisi(unittest.TestCase):
    def test_report_composto_dalla_risposta_json(self):
        risposta = {
            "analisi": ["Elenco completo.", "<script>alert(1)</script> & altro"],
            "rilievi": [
                {"campo": "Oggetto", "valore_rilevato": "presente", "esito": "Positivo", "nota_correttiva": ""},
                {"campo": "Spesa", "valore_rilevato": "assente", "esito": "Negativo", "nota_correttiva": "Indicarla"},
            ],
            "livello_open_data": 1,
            "motivazione_open_data": "PDF non strutturato",
            "esito_globale": "Parzialmente conforme",
            "esito_validazione": "Pubblicabile provvisoriamente",
            "motivazione_validazione": "Manca la spesa prevista",
        }
        llm = LlmFinto(risposta)
        contesto = analisi.Contesto(ente="Provincia di Prova", caratteristiche="Provincia con 380.000 abitanti")
        c = analisi.Contenuti(["--- DOCUMENTO ---\nElenco provvedimenti"], estensione="pdf", fonte="elenco.pdf")
        html = _esegui(analisi.analizza("ART_23_DIRIGENTI", c, contesto, llm))["html"]
        self.assertTrue(html.startswith("<div class='compliance-section'>"))
        self.assertEqual(estrai_esito(html), "Pubblicabile provvisoriamente")
        self.assertIn("elenco.pdf", html)
        self.assertIn("Indicarla", html)
        self.assertIn("Art. 23", html)
        self.assertNotIn("<script", html)  # il testo del modello è escapato
        self.assertIn("&lt;script&gt;", html)
        sistema, testo, schema = llm.richieste[0]
        self.assertIn("Provincia con 380.000 abitanti", sistema)
        self.assertIn("Estensione originale file: pdf", sistema)
        self.assertNotRegex(sistema, r"_[A-Z]+(_[A-Z]+)*_")  # nessun segnaposto rimasto
        self.assertEqual(testo, c.testo)
        self.assertIn("esito_validazione", schema["required"])
        self.assertFalse(schema["additionalProperties"])

    def test_risposta_fuori_formato(self):
        llm = LlmFinto({"analisi": ["x"], "esito_validazione": "Forse"})
        c = analisi.Contenuti(["testo"], estensione="pdf")
        with self.assertRaises(analisi.AnalisiNonRiuscita):
            _esegui(analisi.analizza("ART_23_DIRIGENTI", c, analisi.Contesto(ente="x"), llm))

    def test_schema_a_sezioni_richiede_il_controllo(self):
        with self.assertRaises(analisi.AnalisiNonRiuscita):
            analisi.prompt_analisi("ART_23", analisi.Contesto(ente="x"))

    def test_schema_a_controllo_unico(self):
        # Art. 36: le sezioni (casi PagoPA) restano nel modulo di creazione, ma l'analisi
        # ha un solo controllo e il modello individua il caso dalla pagina
        schema = get_schema("ART_36")
        self.assertGreater(len(schema.sezioni), 1)
        self.assertFalse(schema.controlli_per_sezione)
        self.assertEqual(schema.audit, [])
        self.assertFalse(schema.per_frontend()["solo_varianti"])
        sistema = analisi.prompt_analisi("ART_36", analisi.Contesto(ente="x"))
        self.assertIn("INDIVIDUAZIONE DEL CASO", sistema)

    def test_estrazione_con_schema_json_standard(self):
        llm = LlmFinto(
            {"sezione": "DIRIGENTI"},
            {"righe": [{"data": "2026-03-10", "numero": "12", "denominazione": "Determinazione",
                        "oggetto": "Affidamento", "ufficio_struttura": "Servizi", "link_provvedimento": None}]},
        )  # fmt: skip
        c = analisi.Contenuti(["Determinazione n. 12 del 10 marzo 2026"])
        risultato = _esegui(analisi.estrai_dati("ART_23", "", c, llm))
        dati = risultato["dati"]
        self.assertEqual((dati["pdf_type"], dati["sezione"]), ("ART_23", "DIRIGENTI"))
        self.assertEqual(dati["righe"][0]["data"], "10/03/2026")  # normalizzata nel formato dello schema
        schema = llm.richieste[1][2]
        riga = schema["properties"]["righe"]["items"]
        self.assertFalse(riga["additionalProperties"])
        self.assertEqual(set(riga["required"]), set(riga["properties"]))
        self.assertEqual(riga["properties"]["data"]["type"], ["string", "null"])

    def test_json_schema_traduce_lo_stile_gemini(self):
        schema = json_schema({
            "type": "object",
            "properties": {"tipo": {"type": "string", "nullable": True, "format": "enum", "enum": ["A", "B"]}},
        })  # fmt: skip
        self.assertEqual(schema["properties"]["tipo"], {"type": ["string", "null"], "enum": ["A", "B", None]})
        self.assertEqual(schema["required"], ["tipo"])


if __name__ == "__main__":
    unittest.main()
