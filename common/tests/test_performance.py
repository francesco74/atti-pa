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
