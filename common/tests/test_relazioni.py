"""Relazioni di sintesi: controllo dei numeri del testo rispetto ai dati, HTML esportato.
    python -m unittest common.tests.test_relazioni
"""

from __future__ import annotations

import unittest

from common.relazioni import html_relazione, numeri_da_verificare, percentuale


class Relazioni(unittest.TestCase):
    def test_numeri(self):
        dati = {"anno": 2026, "misure": 120, "attuate": 90, "percentuale_attuate": 75.0, "quota": 12.5,
                "riferimento": "art. 1, comma 14, l. 190/2012", "struttura": "U.O. 2.1", "grandi": 1234}  # fmt: skip
        testo = ("Nel 2026 sono state monitorate 120 misure, di cui 90 attuate (75%, cioè il 12,5% in più). "
                 "Ai sensi dell'art. 1, comma 14, della l. 190/2012 la U.O. 2.1 ... 1.234 atti; 7 misure nuove e 33%.")
        self.assertEqual(numeri_da_verificare(testo, dati), ["7", "33"])

    def test_percentuale_e_html(self):
        self.assertEqual((percentuale(1, 3), percentuale(0, 0)), (33.3, 0.0))
        h = html_relazione("Relazione <RPCT>", "Anno 2026", [
            {"titolo": "Misure", "testo": "Primo paragrafo.\n\nSecondo.", "tabelle": [
                {"titolo": "Per struttura", "intestazioni": ["Struttura", "Misure"], "righe": [["U.O. 1", 3]]}]}])  # fmt: skip
        self.assertIn("<h1>Relazione &lt;RPCT&gt;</h1>", h)
        self.assertEqual(h.count("<p>"), 4)  # sottotitolo, due paragrafi, titolo della tabella
        self.assertIn("<td>U.O. 1</td><td>3</td>", h)
