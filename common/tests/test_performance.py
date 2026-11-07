"""Calcoli della performance: media pesata (provvisoria con impegni sotto 100), disponibile,
ritardo.
    python -m unittest common.tests.test_performance
"""

from __future__ import annotations

import unittest
from datetime import date

from common.performance import disponibile, in_ritardo, media_pesata


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
