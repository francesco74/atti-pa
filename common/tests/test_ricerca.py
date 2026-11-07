"""Ricerca in linguaggio naturale (common/ricerca.py): radici, sinonimi, BM25, parte semantica
e fusione dei due elenchi.
    python -m unittest common.tests.test_ricerca
"""

import unittest

from common import ricerca as r

DOCUMENTI = [
    r.Documento("affitto", "P.1 Contributi per il sostegno alla locazione", "Pagamento del canone di affitto"),
    r.Documento("edilizia", "P.2 Permesso di costruire", "Rilascio del titolo edilizio"),
    r.Documento("sport", "P.3 Contributi alle associazioni sportive", "Sostegno alle attività sportive"),
    r.Documento("concorsi", "P.10 Reclutamento del personale", "Concorsi pubblici"),
]


class Lessicale(unittest.TestCase):
    def test_radici_senza_parole_vuote_e_accenti(self):
        self.assertEqual(r.radici("Come chiedo il contributo per l'attività?"), ["contrib", "attiv"])
        self.assertEqual(r.radici("Attivita"), r.radici("attività"))

    def test_sinonimi(self):
        termini = r.termini_domanda("affitto")
        self.assertEqual(termini["affitt"], 1.0)
        self.assertEqual(termini["locazion"], r.PESO_SINONIMO)

    def test_domanda_del_cittadino(self):
        trovati = r.lessicale("come chiedo il contributo per l'affitto?", DOCUMENTI)
        self.assertEqual([x.id for x in trovati], ["affitto", "sport"])
        self.assertGreater(trovati[0].punteggio, trovati[1].punteggio)

    def test_sinonimo_senza_parole_in_comune(self):
        self.assertEqual([x.id for x in r.lessicale("ristrutturazione della casa", DOCUMENTI)], ["edilizia"])

    def test_codice_in_cima(self):
        trovati = r.lessicale("P.10", DOCUMENTI)
        self.assertEqual(trovati[0].id, "concorsi")
        self.assertGreaterEqual(trovati[0].punteggio, 1000)

    def test_niente_da_cercare(self):
        self.assertEqual(r.lessicale("come posso", DOCUMENTI), [])
        self.assertEqual(r.lessicale("multa", DOCUMENTI), [])


class Semantica(unittest.TestCase):
    def test_soglia_e_vicinanza_al_migliore(self):
        vettori = {"a": r.unitario([1, 0]), "b": r.unitario([1, 0.6]), "c": r.unitario([0, 1])}
        trovati = r.semantica(r.unitario([1, 0]), vettori, soglia=0.5)
        self.assertEqual([x.id for x in trovati], ["a", "b"])
        self.assertTrue(all(x.semantica for x in trovati))
        self.assertEqual(r.semantica(r.unitario([0, 1]), {"a": vettori["a"]}, soglia=0.5), [])

    def test_fusione(self):
        lessicali = [r.Risultato("x", 5, ["a"]), r.Risultato("y", 3, ["b"])]
        semantici = [r.Risultato("y", 0.9, semantica=True), r.Risultato("z", 0.8, semantica=True)]
        fusi = r.fondi(lessicali, semantici)
        self.assertEqual([x.id for x in fusi], ["y", "x", "z"])  # in entrambi gli elenchi: primo
        self.assertEqual((fusi[0].parole, fusi[0].semantica), (["b"], True))
        # la corrispondenza esatta resta prima
        fusi = r.fondi([r.Risultato("x", 1001, ["p"])], [r.Risultato("y", 0.9, semantica=True)])
        self.assertEqual(fusi[0].id, "x")

    def test_impronta(self):
        a = r.Documento("1", "Titolo", "testo")
        self.assertEqual(a.impronta, r.Documento("2", "Titolo", "testo").impronta)
        self.assertNotEqual(a.impronta, r.Documento("1", "Titolo", "altro").impronta)



class Registro(unittest.TestCase):
    def test_oscura_dati_personali(self):
        from common.registro_ricerche import oscura

        testo = "Sono Mario, tel. +39 0583 123456, mario.rossi@esempio.it, CF RSSMRA80A01E715X, IBAN IT60X0542811101000000123456"
        self.assertEqual(oscura(testo), "Sono Mario, tel. [omissis], [omissis], CF [omissis], IBAN [omissis]")
        self.assertEqual(oscura("contributo affitto 2026"), "contributo affitto 2026")  # l'anno resta

    def test_chiave_per_radici(self):
        from common.registro_ricerche import chiave

        self.assertEqual(chiave("Contributo per l'affitto"), chiave("affitti contributi"))
        self.assertNotEqual(chiave("affitto"), chiave("contributo"))


if __name__ == "__main__":
    unittest.main()
