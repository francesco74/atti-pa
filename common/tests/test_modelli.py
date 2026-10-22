"""Motore dei modelli di atto: condizioni, composizione con i moduli di regole, valutazione
di una bozza e coerenza tra i file dei modelli e quelli delle checklist.

Usa solo la libreria standard (unittest): si esegue anche con pytest.
    python -m unittest discover -s common/tests -t .
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from common.configurazione import leggi_checklist
from common.modelli import (
    Condizione,
    DatiBozza,
    ErroreCondizione,
    ModelloNonValido,
    Valutazione,
    componi,
    leggi_modello,
    leggi_modulo,
)

RADICE = Path(__file__).resolve().parents[2]
PACCHETTO = RADICE / "pacchetto"
MODELLI = PACCHETTO / "modelli"
CHECKLIST = PACCHETTO / "checklist"

BASE = {
    "codice": "PROVA",
    "titolo": "Modello di prova",
    "tipologia_atto": "DETERMINA",
    "provvedimento": "Determinazione",
    "organo": "Dirigente",
    "formula_dispositivo": "DETERMINA",
    "domande": [
        {"id": "importo", "testo": "Importo", "tipo": "importo"},
        {
            "id": "caratteristiche",
            "testo": "Caratteristiche",
            "tipo": "scelta_multipla",
            "opzioni_da_regole": True,
        },
    ],
    "campi": {"oggetto": {"etichetta": "Oggetto"}},
    "fasi": [
        {
            "numero": 1,
            "titolo": "Preambolo",
            "sezioni": [
                {
                    "titolo": "Visti",
                    "innesto": "visti",
                    "capoversi": [{"id": "visto_base", "testo": "il Codice;"}],
                }
            ],
        }
    ],
}

MODULO = {
    "codice": "SPEC",
    "fattore": "spec",
    "etichetta": "Specificità di prova",
    "modelli": ["PROVA"],
    "domande": [{"id": "sotto", "testo": "Sotto caso?", "tipo": "si_no"}],
    "campi": {"dato_spec": {"etichetta": "Dato"}},
    "inserti": [
        {
            "innesto": "visti",
            "prima_di": "visto_base",
            "capoversi": [
                {"id": "visto_spec", "testo": "la norma speciale {{dato_spec}};"},
                {"id": "visto_sotto", "se": "sotto", "testo": "la norma del sotto caso;"},
            ],
        }
    ],
    "suggerimenti": [
        {"domanda": "sotto", "valore": True, "messaggio": "Di solito ricorre."}
    ],
}


def _valuta(m, risposte, valori=None):
    return Valutazione(m, DatiBozza(risposte=risposte, valori=valori or {}))


class Condizioni(unittest.TestCase):
    def test_operatori(self):
        v = {"importo": 4000, "strumento": "oda", "pnrr": True, "cup": False}
        self.assertTrue(Condizione("importo < 5000 and pnrr").valuta(v))
        self.assertTrue(Condizione('strumento in ["oda", "mepa"]').valuta(v))
        self.assertFalse(Condizione("pnrr implica cup").valuta(v))
        self.assertTrue(Condizione("not (cup or importo >= 5000)").valuta(v))

    def test_valore_mancante(self):
        self.assertFalse(Condizione("importo >= 5000").valuta({}))

    def test_sintassi_non_valida(self):
        with self.assertRaises(ErroreCondizione):
            Condizione("importo >= ")
        with self.assertRaises(ErroreCondizione):
            Condizione("__import__('os')")


class Composizione(unittest.TestCase):
    def setUp(self):
        self.m = leggi_modello(BASE, [leggi_modulo(MODULO)])

    def test_fattore_e_domande(self):
        d = self.m.d
        self.assertEqual(d.domande[1].opzioni, {"spec": "Specificità di prova"})
        self.assertEqual(d.domande[2].id, "sotto")  # subito dopo le caratteristiche
        self.assertEqual(d.domande[2].se, "spec")
        self.assertEqual([r.codice for r in d.regole], ["SPEC"])

    def test_inserti_condizionati_dal_fattore(self):
        capoversi = self.m.d.fasi[0].sezioni[0].capoversi
        self.assertEqual([c.id for c in capoversi], ["visto_spec", "visto_sotto", "visto_base"])
        self.assertEqual(capoversi[1].se, "spec and (sotto)")

    def test_senza_fattore_atto_invariato(self):
        v = _valuta(self.m, {"importo": "100", "caratteristiche": []})
        self.assertNotIn("norma speciale", v.testo())
        self.assertEqual(v.moduli_attivi(), [])
        self.assertNotIn("sotto", [q["id"] for q in v.domande()])

    def test_con_fattore(self):
        v = _valuta(
            self.m, {"importo": "100", "caratteristiche": ["spec"], "sotto": True},
            {"dato_spec": "X"},
        )
        self.assertIn("la norma speciale X;", v.testo())
        self.assertIn("la norma del sotto caso;", v.testo())
        self.assertEqual(v.moduli_attivi(), ["SPEC"])
        suggerimento = next(q for q in v.domande() if q["id"] == "sotto")["suggerimento"]
        self.assertEqual(suggerimento["valore"], True)

    def test_caratteristiche_vuote_non_mancanti(self):
        v = _valuta(self.m, {"importo": "100"})
        self.assertTrue(v.domande_complete())

    def test_innesto_inesistente(self):
        modulo = json.loads(json.dumps(MODULO))
        modulo["inserti"][0]["innesto"] = "dispositivo"
        with self.assertRaises(ModelloNonValido):
            componi(leggi_modello(BASE).d, [leggi_modulo(modulo)])

    def test_campo_ridefinito_diversamente(self):
        modulo = json.loads(json.dumps(MODULO))
        modulo["campi"] = {"oggetto": {"etichetta": "Altro oggetto"}}
        with self.assertRaises(ModelloNonValido):
            leggi_modello(BASE, [leggi_modulo(modulo)])

    def test_modulo_di_altro_modello_ignorato(self):
        modulo = dict(MODULO, modelli=["ALTRO"])
        m = leggi_modello(BASE, [leggi_modulo(modulo)])
        self.assertEqual(m.d.regole, [])


class FileDelRepository(unittest.TestCase):
    """I modelli e le checklist pubblicati sono validi e coerenti tra loro."""

    @classmethod
    def setUpClass(cls):
        cls.moduli = [
            leggi_modulo(f.read_text(encoding="utf-8"))
            for f in sorted((MODELLI / "regole").glob("*.yaml"))
        ]
        cls.modelli = [
            leggi_modello(f.read_text(encoding="utf-8"), cls.moduli)
            for f in sorted(MODELLI.glob("*.yaml"))
        ]
        cls.schede = [
            leggi_checklist(f.read_text(encoding="utf-8")) for f in sorted(CHECKLIST.glob("*.json"))
        ]

    def test_ogni_modello_ha_la_sua_scheda(self):
        di_modello = {s.modello for s in self.schede if s.modello}
        for m in self.modelli:
            self.assertIn(m.d.codice, di_modello, f"manca la checklist del modello {m.d.codice}")

    def test_ogni_specificita_ha_la_sua_scheda(self):
        di_modulo = {s.modulo for s in self.schede if s.modulo}
        for mo in self.moduli:
            self.assertIn(mo.codice, di_modulo, f"manca la checklist di {mo.codice}")

    def test_ogni_tipologia_ha_la_scheda_generica(self):
        generiche = {s.tipologia_atto for s in self.schede if not s.modello and not s.modulo}
        for m in self.modelli:
            self.assertIn(m.d.tipologia_atto, generiche)

    def test_le_schede_rimandano_a_cose_esistenti(self):
        modelli = {m.d.codice for m in self.modelli}
        moduli = {mo.codice for mo in self.moduli}
        for s in self.schede:
            if s.modello:
                self.assertIn(s.modello, modelli, s.codice)
            if s.modulo:
                self.assertIn(s.modulo, moduli, s.codice)

    def test_ogni_modulo_si_applica_a_un_modello(self):
        composti = {r.codice for m in self.modelli for r in m.d.regole}
        for mo in self.moduli:
            self.assertIn(mo.codice, composti, f"{mo.codice}: nessun modello lo usa")

    def test_bozze_vuote_si_compongono(self):
        """Ogni modello, con tutte le specificità scelte, produce un testo senza errori."""
        for m in self.modelli:
            fattori = [r.fattore for r in m.d.regole]
            caratteristiche = next((q.id for q in m.d.domande if q.opzioni_da_regole), None)
            risposte = {caratteristiche: fattori} if caratteristiche else {}
            v = _valuta(m, risposte)
            self.assertTrue(v.testo().strip(), m.d.codice)
            v.riepilogo()


if __name__ == "__main__":
    unittest.main()
