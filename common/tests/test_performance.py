"""Calcoli della performance: media pesata (provvisoria con impegni sotto 100), disponibile,
ritardo, raggiungimento degli indicatori e completamento che ne deriva.
    python -m unittest common.tests.test_performance
"""

from __future__ import annotations

import unittest
from datetime import date

from common.performance import (
    completamento_indicatori, disponibile, errore_indicatore, in_ritardo, media_pesata, raggiungimento, testo_indicatore,
)  # fmt: skip


class Calcoli(unittest.TestCase):
    def test_media_pesata(self):
        self.assertEqual(media_pesata([(60, 100), (40, 50)]), 80.0)
        self.assertEqual(media_pesata([(30, 100), (30, 0)]), 50.0)  # provvisoria sui pesi presenti
        self.assertEqual(media_pesata([(50, None), (50, 100)]), 50.0)  # obiettivo senza azioni: 0
        self.assertIsNone(media_pesata([]))
        self.assertIsNone(media_pesata([(0, 100)]))

    def test_disponibile(self):
        self.assertEqual(disponibile([30, 20]), 50)
        self.assertEqual(disponibile([]), 100)

    def test_ritardo(self):
        oggi = date(2026, 6, 1)
        self.assertTrue(in_ritardo(date(2026, 5, 31), 90, oggi))
        self.assertFalse(in_ritardo(date(2026, 5, 31), 100, oggi))
        self.assertFalse(in_ritardo(date(2026, 6, 1), 0, oggi))


class Indicatori(unittest.TestCase):
    def test_raggiungimento(self):
        eventi = {"tipo": "NUMERO", "target": 3, "unita": "eventi"}
        self.assertEqual(raggiungimento(eventi), 0.0)  # non rilevato
        self.assertEqual(raggiungimento({**eventi, "rilevato": 2}), 66.7)
        self.assertEqual(raggiungimento({**eventi, "rilevato": 5}), 100.0)  # oltre il target: 100
        self.assertEqual(raggiungimento({**eventi, "partenza": 1, "rilevato": 2}), 50.0)
        self.assertEqual(raggiungimento({**eventi, "partenza": 1, "rilevato": 0}), 0.0)  # peggiorato: 0
        attese = {"tipo": "NUMERO", "partenza": 40, "target": 30, "verso": "DECRESCENTE"}
        self.assertEqual(raggiungimento({**attese, "rilevato": 35}), 50.0)
        self.assertEqual(raggiungimento({**attese, "rilevato": 25}), 100.0)
        self.assertEqual(raggiungimento({**attese, "partenza": None, "rilevato": 60}), 50.0)  # target / rilevato
        self.assertEqual(raggiungimento({"tipo": "SI_NO", "rilevato": 1}), 100.0)
        self.assertEqual(raggiungimento({"tipo": "SI_NO", "rilevato": 0}), 0.0)
        entro = {"tipo": "DATA", "target_data": "2026-06-30"}
        self.assertEqual(raggiungimento({**entro, "rilevato_data": date(2026, 6, 30)}), 100.0)
        self.assertEqual(raggiungimento({**entro, "rilevato_data": "2026-07-01"}), 0.0)  # in ritardo
        self.assertEqual(raggiungimento(entro), 0.0)

    def test_completamento(self):
        self.assertIsNone(completamento_indicatori([]))  # si inserisce a mano
        self.assertEqual(completamento_indicatori([{"tipo": "NUMERO", "target": 3, "rilevato": 2}]), 67)
        self.assertEqual(completamento_indicatori([{"tipo": "NUMERO", "target": 4, "rilevato": 2}, {"tipo": "SI_NO", "rilevato": 1}]), 75)

    def test_definizione(self):
        self.assertIsNone(errore_indicatore({"tipo": "NUMERO", "target": 3}))
        self.assertIn("target", errore_indicatore({"tipo": "NUMERO"}))
        self.assertIsNotNone(errore_indicatore({"tipo": "NUMERO", "partenza": 3, "target": 3}))
        self.assertIsNotNone(errore_indicatore({"tipo": "NUMERO", "partenza": 20, "target": 30, "verso": "DECRESCENTE"}))
        self.assertIsNotNone(errore_indicatore({"tipo": "PERCENTUALE", "target": 101}))
        self.assertIsNotNone(errore_indicatore({"tipo": "DATA"}))
        self.assertIsNone(errore_indicatore({"tipo": "SI_NO"}))
        self.assertEqual(testo_indicatore({"descrizione": "Eventi", "tipo": "NUMERO", "target": 3.0, "unita": "eventi"}), "Eventi: 3 eventi")
        self.assertEqual(testo_indicatore({"descrizione": "Copertura", "tipo": "PERCENTUALE", "partenza": 50, "target": 72.5}),
                         "Copertura: da 50% a 72,5%")  # fmt: skip
        self.assertEqual(testo_indicatore({"descrizione": "Report", "tipo": "DATA", "target_data": "2026-06-30"}), "Report: entro il 30/06/2026")


class Controlli(unittest.TestCase):
    def test_controlli_obiettivo(self):
        from common.performance import AVVISO, controlli_obiettivo

        elementi = [
            {"tipo": "AZIONE", "descrizione": "Formazione", "impegno": 0, "scadenza": date(2027, 3, 1), "misura_id": None},
            {"tipo": "MISURA", "descrizione": "Rotazione", "impegno": 100, "scadenza": date(2026, 6, 1), "misura_id": None},
            {"tipo": "MISURA", "descrizione": "Codice", "impegno": 0, "scadenza": date(2026, 6, 1), "misura_id": "m1"},
        ]
        testi = [c["testo"] for c in controlli_obiettivo(50, 2026, "s1", elementi, misure_attive=True,
                                                          strutture_misure={"m1": "s2"})]  # fmt: skip
        self.assertTrue(any("dopo la fine dell'anno" in t for t in testi))
        self.assertTrue(any("non è più nella mappatura" in t for t in testi))
        self.assertTrue(any("altra struttura" in t for t in testi))
        self.assertEqual(sum("impegno 0%" in t for t in testi), 2)
        vuoto = controlli_obiettivo(0, 2026, "s1", [], misure_attive=True)
        self.assertEqual([c["livello"] for c in vuoto], [AVVISO, AVVISO])
        solo_azioni = controlli_obiettivo(100, 2026, "s1", [elementi[0] | {"impegno": 100, "scadenza": date(2026, 5, 1)}],
                                          misure_attive=True)  # fmt: skip
        self.assertEqual([c["testo"] for c in solo_azioni], ["Nessuna misura della mappatura dei rischi collegata all'obiettivo"])
