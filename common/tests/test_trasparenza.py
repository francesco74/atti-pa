"""Modulo trasparenza senza rete né LLM veri: contenuti per l'LLM (fogli di calcolo, CSV,
documenti, pagina web con i documenti collegati), prompt dell'analisi, report sanificato, estrazione
dei dati con lo schema JSON standard, protezione SSRF.
    python -m unittest common.tests.test_trasparenza
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import xml.etree.ElementTree as ET
import unittest
from unittest import mock

import httpx
import openpyxl

from common.trasparenza import analisi, esportazione, fonti, rete
from common.trasparenza.estrazione import json_schema
from common.trasparenza.registro import Campo, get_schema
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


class Fogli(unittest.TestCase):
    """Fogli, CSV, XML e JSON li legge pa-common; qui il formato atteso dai prompt delle verifiche."""

    def test_foglio_con_i_numeri_come_li_vede_l_utente(self):
        tabella = _esegui(analisi.testo_file(analisi.File("importi.xlsx", _xlsx()), None))
        righe = tabella.splitlines()
        self.assertEqual(righe[0], "| Beneficiario | Importo | Anno |")
        self.assertIn("1.026,37 [visualizzato in Excel; formato interno: #,##0.00]", tabella)
        self.assertIn("Associazione \\| Uno", tabella)  # il separatore non rompe la tabella
        self.assertIn("| 2025 |", tabella)

    def test_foglio_illeggibile(self):
        with self.assertRaises(analisi.AnalisiNonRiuscita):
            _esegui(analisi.testo_file(analisi.File("rotto.xlsx", b"PK\x03\x04 rotto"), None))

    def test_csv_in_latin1(self):
        testo = _esegui(analisi.testo_file(analisi.File("elenco.csv", "città;importo".encode("latin-1")), None))
        self.assertEqual(testo, "città;importo")

    def test_xml_compattato_come_testo(self):
        xml = '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>\n<lotti>\n  <lotto>\n    <oggetto>Manutenzione città</oggetto>\n    <importo>&e;</importo>\n  </lotto>\n</lotti>\n'
        testo = _esegui(analisi.testo_file(analisi.File("dataset.xml", xml.encode("latin-1")), None))
        self.assertIn("<lotti><lotto><oggetto>Manutenzione città</oggetto><importo>&e;</importo></lotto></lotti>", testo)
        self.assertNotIn("root:", testo)  # le entità non si risolvono

    def test_json_compattato(self):
        dati = '{\n  "procedimenti": [\n    {"nome": "Accesso agli atti", "giorni": 30}\n  ]\n}'
        testo = _esegui(analisi.testo_file(analisi.File("dati.json", dati.encode()), None))
        self.assertEqual(testo, '{"procedimenti":[{"nome":"Accesso agli atti","giorni":30}]}')
        rotto = _esegui(analisi.testo_file(analisi.File("rotto.json", b'  {"a": 1,\n'), None))
        self.assertEqual(rotto, '{"a": 1,')


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
                analizza_documenti=True, segui_link=True, client=client,
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

    def _leggi(self, pagine: dict, testi: dict, **opzioni) -> analisi.Contenuti:
        """Pagina https://ente.example.it/at con i documenti collegati; `pagine`: indirizzo ->
        (stato, intestazioni, corpo)."""

        def risposta(richiesta: httpx.Request) -> httpx.Response:
            stato, intestazioni, corpo = pagine[str(richiesta.url)]
            return httpx.Response(stato, headers=intestazioni, content=corpo)

        client = httpx.AsyncClient(transport=httpx.MockTransport(risposta))
        with mock.patch.object(rete, "_host_pubblico", return_value=True):
            return _esegui(analisi.contenuti("https://ente.example.it/at", [], ConverterFinto(testi),
                                             analizza_documenti=True, client=client, **opzioni))  # fmt: skip

    def test_documenti_collegati_di_tutti_i_formati(self):
        html = {"Content-Type": "text/html"}
        corpo = (
            '<body><nav><a href="/download/menu">Scarica il menu</a></nav><main>'
            '<a href="/doc/delibera.docx">Delibera</a>'
            '<a href="/doc/importi.xlsx">Importi</a>'
            '<a href="/dati/contratti.xml">Contratti</a>'
            '<a href="/dati/elenco.json">Elenco</a>'
            '<a href="/download/123">Bando</a>'  # nome dal Content-Disposition
            '<a href="/allegato.php?id=7">Allegato</a>'  # formato dal Content-Type
            '<a href="/download/pagina">Area download</a>'  # è una pagina: ignorata
            '<a href="/doc/mancante.pdf">Mancante</a>'
            '<a href="/doc/scansione.pdf">Scansione</a>'
            "</main></body>"
        )
        pagine = {
            "https://ente.example.it/at": (200, html, corpo.encode()),
            "https://ente.example.it/doc/delibera.docx": (200, {"Content-Type": "application/octet-stream"}, b"PK"),
            "https://ente.example.it/doc/importi.xlsx": (200, {}, _xlsx()),
            "https://ente.example.it/dati/contratti.xml": (200, {"Content-Type": "text/xml"}, b"<lotti>\n  <lotto>Strade</lotto>\n</lotti>"),
            "https://ente.example.it/dati/elenco.json": (200, {"Content-Type": "application/json"}, b'{"ufficio": "Tributi"}'),
            "https://ente.example.it/download/123": (
                200, {"Content-Type": "application/octet-stream",
                      "Content-Disposition": "attachment; filename*=UTF-8''bando%20gara%20%C3%A0.pdf"}, b"%PDF"),
            "https://ente.example.it/allegato.php?id=7": (200, {"Content-Type": "text/csv; charset=utf-8"}, b"nome;importo\nRossi;10"),
            "https://ente.example.it/download/pagina": (200, html, b"<body>Area download</body>"),
            "https://ente.example.it/doc/mancante.pdf": (404, {}, b""),
            "https://ente.example.it/doc/scansione.pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF"),
        }  # fmt: skip
        testi = {"delibera.docx": "Delibera di giunta", "bando gara à.pdf": "Bando di gara", "scansione.pdf": " "}
        c = self._leggi(pagine, testi, max_documenti=10)
        testo = c.testo
        for atteso in ("[FILE ALLEGATO: delibera.docx]", "--- DOCUMENTO COLLEGATO: delibera.docx ---", "Delibera di giunta",
                       "1.026,37", "<lotti><lotto>Strade</lotto></lotti>", '{"ufficio":"Tributi"}',
                       "[FILE ALLEGATO: bando gara à.pdf]", "Bando di gara",
                       "DOCUMENTO COLLEGATO: allegato.php.csv", "Rossi;10"):  # fmt: skip
            self.assertIn(atteso, testo)
        self.assertNotIn("Scarica il menu ]", testo)
        self.assertNotIn("FILE ALLEGATO: menu", testo)  # link da download nella navigazione
        self.assertNotIn("FILE ALLEGATO: pagina", testo)
        self.assertEqual(len(c.non_letti), 2)
        self.assertIn("mancante.pdf: non scaricato (errore HTTP 404)", c.non_letti)
        self.assertTrue(c.non_letti[1].startswith("scansione.pdf: scansione.pdf non contiene testo leggibile"))

    def test_numero_di_documenti_collegati(self):
        corpo = "".join(f'<a href="/doc/d{i}.csv">Documento {i}</a>' for i in range(15))
        pagine = {"https://ente.example.it/at": (200, {"Content-Type": "text/html"}, f"<body>{corpo}</body>".encode())}
        pagine |= {f"https://ente.example.it/doc/d{i}.csv": (200, {}, f"riga {i};".encode()) for i in range(15)}

        def letti(**opzioni) -> int:
            return sum(f"riga {i};" in self._leggi(pagine, {}, **opzioni).testo for i in range(15))

        self.assertEqual(letti(), 5)  # predefinito
        self.assertEqual(letti(max_documenti=8), 8)
        self.assertEqual(letti(max_documenti=50), 10)  # limite massimo

    def test_report_con_i_documenti_non_letti(self):
        risposta = {
            "analisi": ["Pagina completa."], "rilievi": [], "livello_open_data": 3, "motivazione_open_data": "CSV",
            "esito_globale": "Conforme", "esito_validazione": "Pubblicabile", "motivazione_validazione": "",
        }  # fmt: skip
        c = analisi.Contenuti(["pagina"], url="https://ente.example.it/at", non_letti=["mancante.pdf: non scaricato (errore HTTP 404)"])
        html = _esegui(analisi.analizza("ART_23_DIRIGENTI", c, analisi.Contesto(ente="Prova"), LlmFinto(risposta)))["html"]
        self.assertIn("Documenti collegati non letti", html)
        self.assertIn("mancante.pdf: non scaricato (errore HTTP 404)", html)


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


class Esportazione(unittest.TestCase):
    """Dati della scheda in JSON, XML e CSV: valori in formato aperto, elenchi annidati."""

    DATI = {
        "pdf_type": "ART_23", "sezione": "DIRIGENTI", "note": "Primo semestre",
        "righe": [
            {"data": "10/03/2026", "numero": "12", "denominazione": "Determinazione", "oggetto": "Affidamento <servizio> & co",
             "ufficio_struttura": "Servizi informatici",
             "allegati": [{"link": "https://ente.it/a1.pdf"}, {"link": ""}, {"link": "https://ente.it/a2.pdf"}]},
            {"data": "11/03/2026", "numero": "13", "denominazione": "Ordinanza", "oggetto": "Viabilità, città",
             "ufficio_struttura": "Strade"},
        ],
    }  # fmt: skip

    def _aperti(self) -> dict:
        return esportazione.dati_aperti(get_schema("ART_23"), self.DATI, "Provincia di Prova")

    def test_valori_in_formato_aperto(self):
        def campo(tipo, **altro):
            return Campo(id="c", etichetta="C", tipo=tipo, **altro)

        self.assertEqual(esportazione.valore(campo("data"), "05/01/2026"), "2026-01-05")
        self.assertEqual(esportazione.valore(campo("data", separatore_data="."), "05.01.2026"), "2026-01-05")
        self.assertEqual(esportazione.valore(campo("importo"), "1.234,56"), 1234.56)
        self.assertEqual(esportazione.valore(campo("percentuale"), "45,00"), 45.0)
        self.assertEqual(esportazione.valore(campo("decimale"), "1.234"), 1234)
        self.assertEqual(esportazione.valore(campo("anno"), "2025"), 2025)
        self.assertEqual(esportazione.valore(campo("iban"), "it60 x054 2811"), "IT60X0542811")
        self.assertEqual(esportazione.valore(campo("data"), "ieri"), "ieri")  # non riconosciuto: com'è
        self.assertIsNone(esportazione.valore(campo("testo"), "  "))

    def test_json(self):
        d = json.loads(esportazione.in_json(self._aperti()))
        self.assertEqual(d["schema"]["id"], "ART_23")
        self.assertIn("delibera", d["schema"]["fonte"])
        self.assertEqual((d["ente"], d["sezione"]["id"], d["note"]), ("Provincia di Prova", "DIRIGENTI", "Primo semestre"))
        primo = d["elementi"][0]
        self.assertEqual(primo["data"], "2026-03-10")
        self.assertEqual(primo["allegati"], [{"link": "https://ente.it/a1.pdf"}, {"link": "https://ente.it/a2.pdf"}])
        self.assertIsNone(primo["link_provvedimento"])
        self.assertEqual(d["elementi"][1]["allegati"], [])
        self.assertEqual(d["campi"]["allegati.link"], "Link al documento allegato")

    def test_xml(self):
        radice = ET.fromstring(esportazione.in_xml(self._aperti()))
        self.assertEqual(radice.find("schema").get("id"), "ART_23")
        primo = radice.find("elementi/elemento")
        self.assertEqual(primo.findtext("data"), "2026-03-10")
        self.assertEqual(primo.findtext("oggetto"), "Affidamento <servizio> & co")  # escapato e riletto
        self.assertIsNone(primo.find("link_provvedimento"))  # vuoto: assente
        self.assertEqual([e.findtext("link") for e in primo.findall("allegati/elemento")],
                         ["https://ente.it/a1.pdf", "https://ente.it/a2.pdf"])  # fmt: skip
        self.assertEqual(radice.find("campi/campo[@id='oggetto']").get("etichetta"), "Oggetto")

    def test_csv(self):
        contenuto = esportazione.in_csv(self._aperti())
        self.assertTrue(contenuto.startswith(b"\xef\xbb\xbf"))  # BOM per Excel
        righe = list(csv.reader(io.StringIO(contenuto.decode("utf-8-sig"))))
        self.assertEqual(righe[0][:3], ["Data", "Numero", "Denominazione"])
        self.assertEqual(righe[1][righe[0].index("Provvedimento adottato")], "")  # campo visibile ma vuoto
        self.assertEqual(len(righe), 3)
        self.assertIn("Viabilità, città", righe[2])  # la virgola resta nella cella
        allegati = righe[1][righe[0].index("Allegati (ove previsti)")]
        self.assertEqual(allegati, "Link al documento allegato: https://ente.it/a1.pdf | "
                                   "Link al documento allegato: https://ente.it/a2.pdf")  # fmt: skip
