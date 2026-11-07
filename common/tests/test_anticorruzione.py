"""Metodologia di valutazione del rischio: standard valida, moda con la parità risolta verso
il valore più alto (PIAO, § 2.5, nota 6), matrice con "Critico" livello più grave (Alto/Alto), correzione dei
valori, controlli sugli indicatori; codici successivi e ordinamento naturale.
    python -m unittest common.tests.test_anticorruzione
"""

from __future__ import annotations

import unittest

from common.anticorruzione.metodologia import Metodologia, chiave_naturale, moda, prossimo_codice, standard, valuta


def _tutti(m, indicatori, valore):
    return {i.id: valore for i in indicatori}


class Valutazione(unittest.TestCase):
    def test_standard(self):
        m = standard()
        self.assertEqual(len(m.indicatori_probabilita), 9)
        self.assertEqual(len(m.indicatori_impatto), 4)
        self.assertLess(m.ordine_livello("Rischio Alto"), m.ordine_livello("Rischio Critico"))

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
        self.assertEqual((v.probabilita, v.impatto, v.livello), ("Alto", "Medio", "Rischio Alto"))
        v = valuta(m, p, _tutti(m, m.indicatori_impatto, "Alto"))
        self.assertEqual(v.livello, "Rischio Critico")
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


if __name__ == "__main__":
    unittest.main()


class AbbinamentiArt35(unittest.TestCase):
    """Procedimenti estratti dal sito AT o da un documento: abbinamento ai procedimenti della
    mappatura (per denominazione, ciascuno una volta sola) e alle strutture (per nome o codice)."""

    def test_abbina(self):
        from types import SimpleNamespace as N

        from common.anticorruzione.art35 import abbina, somiglianza

        procedimenti = [N(id="p1", denominazione="Contributo per il pagamento dell'affitto"),
                        N(id="p2", denominazione="Accesso agli atti")]  # fmt: skip
        strutture = {"s1": N(id="s1", codice="U.O. 4.1", descrizione="Servizi sociali"),
                     "s2": N(id="s2", codice="STAFF A", descrizione="Segreteria generale")}  # fmt: skip
        righe = [
            {"denominazione": "Contributo pagamento affitto", "uff_resp_denom": "U.O. Servizi Sociali",
             "sost_ufficio": "Segreteria Generale", "ist_ufficio": "Ufficio protocollo"},
            {"denominazione": "Accesso agli atti amministrativi", "uff_resp_denom": "U.O. 4.1"},
            {"denominazione": "Rilascio contrassegno disabili"},
        ]  # fmt: skip
        esito = abbina(righe, procedimenti, strutture)
        self.assertEqual([e["procedimento_id"] for e in esito], ["p1", "p2", None])
        uffici = esito[0]["uffici"]
        self.assertEqual(uffici["uff_resp_struttura_id"]["struttura_id"], "s1")
        self.assertEqual(uffici["sost_struttura_id"]["struttura_id"], "s2")
        self.assertIsNone(uffici["ist_struttura_id"]["struttura_id"])  # nessuna struttura simile
        self.assertEqual(esito[1]["uffici"]["uff_resp_struttura_id"]["struttura_id"], "s1")  # per codice
        self.assertEqual(somiglianza("", "x"), 0.0)


class ControlliProposte(unittest.TestCase):
    """Controlli oggettivi sulle proposte, per il RPCT."""

    def setUp(self):
        from common.anticorruzione.controlli import Contesto

        self.ctx = Contesto(livelli=["Minimo", "Basso", "Medio", "Critico", "Alto"],
                            processi={"p1": "Concessione contributi alle associazioni"})  # fmt: skip

    def _testi(self, esito):
        return [c["testo"] for c in esito]

    def test_processo_nuovo(self):
        from common.anticorruzione.controlli import AVVISO, controlli_proposta

        dati = {
            "tipo": "PROCEDIMENTO", "denominazione": "Concessione di contributi alle associazioni", "area_id": None,
            "attivita": [{"descrizione": "Istruttoria", "rischi": [
                {"evento": "Favoritismi", "valutazione": {"livello": "Alto"}, "misure": [
                    {"descrizione": "Codice di comportamento", "tipo": "GENERALE", "struttura_id": "s1",
                     "tempi": "2026", "indicatore": "n. dichiarazioni", "target": "100%"}]},
                {"evento": "Ritardi", "valutazione": None, "misure": []},
            ]}],
        }  # fmt: skip
        esito = controlli_proposta("PROCESSO", "CREA", dati, None, self.ctx)
        testi = self._testi(esito)
        self.assertIn("Manca l'area di rischio", testi)
        self.assertIn("Procedimento senza termine di conclusione", testi)
        self.assertTrue(any("molto simile" in t for t in testi))  # doppione
        self.assertTrue(any("«Ritardi»: non è valutato" in t for t in testi))
        self.assertTrue(any("«Ritardi»: nessuna misura" in t for t in testi))
        self.assertTrue(any("sole misure generali" in t for t in testi))
        self.assertEqual(esito[0]["livello"], AVVISO)  # prima gli avvisi
        # la modifica dello stesso processo non è un doppione di sé stesso
        self.ctx.elemento_id = "p1"
        modifica = controlli_proposta("PROCESSO", "MODIFICA", {**dati, "attivita": None}, None, self.ctx)
        self.assertFalse(any("molto simile" in t for t in self._testi(modifica)))

    def test_misura_rischio_ed_eliminazione(self):
        from common.anticorruzione.controlli import controlli_proposta

        testi = self._testi(controlli_proposta("MISURA", "CREA", {"descrizione": "Pubblicazione bandi",
                                                                   "categoria": "Trasparenza"}, None, self.ctx))  # fmt: skip
        for atteso in ("struttura responsabile", "tempi", "indicatore", "target", "obbligo di pubblicazione"):
            self.assertTrue(any(atteso in t for t in testi), atteso)
        scende = controlli_proposta("RISCHIO", "MODIFICA", {"evento": "x", "valutazione": {"livello": "Basso"}},
                                    {"valutazione": {"livello": "Alto"}}, self.ctx)  # fmt: skip
        self.assertIn("Il livello di rischio scende da «Alto» a «Basso»", self._testi(scende))
        self.ctx.misure_del_rischio = 1
        elimina = controlli_proposta("MISURA", "ELIMINA", {"descrizione": "x"}, None, self.ctx)
        self.assertTrue(any("unica misura" in t for t in self._testi(elimina)))
        processo = controlli_proposta("PROCESSO", "ELIMINA", {"attivita": [{"rischi": [{"misure": [{}, {}]}]}]}, None, self.ctx)
        self.assertIn("Si eliminano anche: 1 attività, 1 rischi, 2 misure", self._testi(processo))
