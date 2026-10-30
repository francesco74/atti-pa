"""Metodologia di valutazione del rischio: standard valida, moda con la parità risolta verso
il valore più alto (PIAO, § 2.5, nota 6), matrice con "Critico" sotto "Alto", correzione dei
valori, controlli sugli indicatori; codici successivi e ordinamento naturale; lettura del file
degli obiettivi del Piano (righe di titolo saltate, tabella HTML con estensione .xls) e
abbinamento del centro del Piano alla struttura.
    python -m unittest common.tests.test_anticorruzione
"""

from __future__ import annotations

import unittest

from common.anticorruzione import obiettivi
from common.anticorruzione.metodologia import Metodologia, chiave_naturale, moda, prossimo_codice, standard, valuta


def _tutti(m, indicatori, valore):
    return {i.id: valore for i in indicatori}


class Valutazione(unittest.TestCase):
    def test_standard(self):
        m = standard()
        self.assertEqual(len(m.indicatori_probabilita), 9)
        self.assertEqual(len(m.indicatori_impatto), 4)
        self.assertLess(m.ordine_livello("Rischio Critico"), m.ordine_livello("Rischio Alto"))

    def test_moda_con_parita(self):
        scala = ["Basso", "Medio", "Alto"]
        self.assertEqual(moda(["Basso", "Basso", "Alto"], scala), "Basso")
        self.assertEqual(moda(["Medio", "Alto", "Alto", "Medio", "Basso"], scala), "Alto")  # parità: il più alto
        self.assertEqual(moda(["Alto", "Medio", "Basso"], scala), "Alto")

    def test_matrice_e_correzione(self):
        m = standard()
        p = {**_tutti(m, m.indicatori_probabilita, "Basso"), "1": "Alto", "2": "Alto", "3": "Alto", "4": "Alto",
             "5": "Medio", "6": "Medio", "7": "Medio", "8": "Medio"}  # 4 Alto, 4 Medio, 1 Basso
        i = _tutti(m, m.indicatori_impatto, "Medio")
        v = valuta(m, p, i)
        self.assertEqual((v.probabilita, v.impatto, v.livello), ("Alto", "Medio", "Rischio Critico"))
        v = valuta(m, p, _tutti(m, m.indicatori_impatto, "Alto"))
        self.assertEqual(v.livello, "Rischio Alto")
        v = valuta(m, p, i, probabilita="Medio")  # correzione motivata dal chiamante
        self.assertEqual((v.probabilita_calcolata, v.probabilita, v.livello), ("Alto", "Medio", "Rischio Medio"))

    def test_indicatori_controllati(self):
        m = standard()
        p, i = _tutti(m, m.indicatori_probabilita, "Basso"), _tutti(m, m.indicatori_impatto, "Basso")
        for prob, imp in [({**p, "1": "Altissimo"}, i), ({k: v for k, v in p.items() if k != "9"}, i), (p, {**i, "99": "Basso"})]:
            with self.assertRaises(ValueError):
                valuta(m, prob, imp)

    def test_metodologia_incoerente(self):
        dati = standard().model_dump()
        del dati["matrice"]["Alto"]["Basso"]
        with self.assertRaises(ValueError):
            Metodologia.model_validate(dati)

    def test_codici(self):
        self.assertEqual(prossimo_codice("A.1.", ["A.1.1", "A.1.3", "A.10.2", "A.1.2_R.1"]), "A.1.4")
        self.assertEqual(prossimo_codice("A.1.1_R.", []), "A.1.1_R.1")
        self.assertEqual(sorted(["A.10", "A.2", "B.1", "A.1"], key=chiave_naturale), ["A.1", "A.2", "A.10", "B.1"])



class Obiettivi(unittest.TestCase):
    def test_file_del_piano(self):
        import io

        from openpyxl import Workbook

        libro = Workbook()
        f = libro.active
        f.append(["Piano della performance 2026"])
        f.append(["Codice", "Titolo", "Tipo", "Anno", "Centro", "Descrizione", "Responsabile"])
        f.append(["PERF_ORG_STAFF B", "Nomina del CUG", "Funzionamento", 2026, "STAFF B_NOV. 2024", "Segreteria", "Rossi"])
        f.append(["PERF_ORG_STAFF B", "Doppione", "Funzionamento", 2026, "STAFF B", "", ""])
        f.append(["OB.2", "Senza anno", "", "", "", "", ""])
        dati = io.BytesIO()
        libro.save(dati)
        righe = obiettivi.leggi(dati.getvalue(), "piano.xlsx")
        self.assertEqual([(r["codice"], r["anno"], r["titolo"]) for r in righe], [("PERF_ORG_STAFF B", 2026, "Nomina del CUG")])
        html = (b"<html><table><tr><td>Codice</td></tr><tr><td>OB.1</td><td>Digitale</td><td>Operativo</td>"
                b"<td>2026.0</td><td>SETTORE 6</td><td></td><td>Bianchi</td></tr></table></html>")
        self.assertEqual(obiettivi.leggi(html, "esportato.xls")[0]["centro"], "SETTORE 6")
        with self.assertRaises(obiettivi.FileNonLeggibile):
            obiettivi.leggi(b"\xd0\xcf\x11\xe0binario", "vecchio.xls")

    def test_abbinamento_struttura(self):
        strutture = {"s1": "STAFF B", "s2": "SETTORE 6", "s3": "U.O. 6.1"}
        self.assertEqual(obiettivi.abbina_struttura("STAFF B_NOV. 2024", strutture), "s1")
        self.assertEqual(obiettivi.abbina_struttura("settore  6", strutture), "s2")
        self.assertIsNone(obiettivi.abbina_struttura("SETTORE 9", strutture))


if __name__ == "__main__":
    unittest.main()
