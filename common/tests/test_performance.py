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
        self.assertEqual([c["testo"] for c in solo_azioni], ["Nessuna misura o attività della mappatura dei rischi collegata all'obiettivo"])
        # azioni copiate da attività della mappatura: di un processo di un'altra struttura, o tolte
        bando = {"tipo": "AZIONE", "descrizione": "Bando", "impegno": 50, "scadenza": date(2026, 5, 1),
                 "processo_id": "p1", "attivita_id": "a1", "mappatura_codice": "C.3.1"}  # fmt: skip
        gara = {**bando, "descrizione": "Gara", "attivita_id": "a2", "mappatura_codice": "C.3.2"}
        testi = [c["testo"] for c in controlli_obiettivo(100, 2026, "s1", [bando, gara], misure_attive=True,
                                                          strutture_mappatura={"a1": None, "a2": ["s2"]})]  # fmt: skip
        self.assertEqual(testi, ["Azione «Gara»: l'attività è di un processo di un'altra struttura nella mappatura"])
        # la struttura dell'obiettivo coinvolta nel processo: niente da segnalare
        testi = [c["testo"] for c in controlli_obiettivo(100, 2026, "s1", [gara | {"impegno": 100}], misure_attive=True,
                                                          strutture_mappatura={"a2": ["s2", "s1"]})]  # fmt: skip
        self.assertEqual(testi, [])
        tolta = {**bando, "attivita_id": None, "impegno": 100}
        testi = [c["testo"] for c in controlli_obiettivo(100, 2026, "s1", [tolta], misure_attive=True)]
        self.assertEqual(testi, ["Azione «Bando»: l'attività C.3.1 non è più nella mappatura dei rischi"])


class Importazione(unittest.TestCase):
    """Obiettivi letti da un documento a parti (common/importazione, common/performance/importazione)."""

    def test_parti(self):
        from common.importazione import parti

        testo = "".join(f"riga {i:04d}\n" for i in range(1000))  # 10.000 caratteri
        p = parti(testo, dimensione=3000, sovrapposizione=500)
        self.assertTrue(all(len(x) <= 3000 for x in p))
        self.assertTrue(all(x.endswith("\n") for x in p))  # tagliate a fine riga
        self.assertIn("riga 0999", p[-1])
        for prima, dopo in zip(p, p[1:]):  # ogni parte riprende la fine della precedente
            self.assertIn(dopo.splitlines()[0], prima)
        self.assertEqual(parti("breve"), ["breve"])

    def test_estrai_unisce_le_parti(self):
        """La scheda spezzata tra due parti diventa un obiettivo; una parte non letta è un
        avviso; le parti senza obiettivi non vanno al modello."""
        import asyncio

        from common.llm import LlmError
        from common.performance.importazione import estrai

        class LlmFinto:
            def __init__(self):
                self.testi = []

            async def dati_json(self, sistema, testo, schema):
                self.testi.append(testo)
                if "GUASTO" in testo:
                    raise LlmError("Il modello non ha risposto")
                if "PRIMA" in testo:
                    return {"obiettivi": [{"codice": "P1_26_1", "titolo": "Concorsi", "descrizione": "Breve",
                                           "struttura": "Settore 2", "responsabile": None,
                                           "azioni": [{"descrizione": "Bando", "fine": "30/06/2026"}], "indicatori": []}]}
                return {"obiettivi": [{"codice": "p1_26_1 ", "titolo": "Concorsi", "descrizione": "Descrizione più lunga",
                                       "struttura": None, "responsabile": "Rossi",
                                       "azioni": [{"descrizione": "bando.", "fine": None}, {"descrizione": "Prove", "fine": None}],
                                       "indicatori": [{"descrizione": "Tempi", "tipo": None, "valore_atteso": "90 giorni"}]}]}  # fmt: skip

        pagina = "Scheda obiettivo PRIMA indicatori\n" + "x" * 30_000 + "\nScheda obiettivo SECONDA fasi\n"
        llm = LlmFinto()
        esito = asyncio.run(estrai(pagina + "Premessa senza nulla\n" * 2000 + "obiettivo GUASTO indicatori\n", llm))
        self.assertEqual(len(esito["obiettivi"]), 1)
        o = esito["obiettivi"][0]
        self.assertEqual((o["codice"], o["struttura"], o["responsabile"], o["descrizione"]),
                         ("P1_26_1", "Settore 2", "Rossi", "Descrizione più lunga"))  # fmt: skip
        self.assertEqual([a["descrizione"] for a in o["azioni"]], ["Bando", "Prove"])
        self.assertEqual(len(esito["avvisi"]), 1)
        self.assertIn("non letta", esito["avvisi"][0])
        self.assertTrue(all("Premessa senza nulla\nPremessa" not in t or "obiettiv" in t.lower() for t in llm.testi))

    def test_indicatori_scambiati_per_fasi(self):
        from common.performance.importazione import unisci

        ind = {"descrizione": "Approvazione del piano di protezione civile", "tipo": None, "valore_atteso": "30/06/2026"}
        letture = [
            {"codice": "P2", "titolo": "Rischi", "azioni": [{"descrizione": "Aggiornamento del piano", "fine": None}],
             "indicatori": [ind]},
            {"codice": "P2", "titolo": "Rischi", "indicatori": [ind],
             "azioni": [{"descrizione": "Approvazione del piano di protezione civile", "fine": "30/06/2026"}]},
        ]  # fmt: skip
        self.assertEqual([a["descrizione"] for a in unisci(letture)[0]["azioni"]], ["Aggiornamento del piano"])
        # se tutte le fasi coincidono con indicatori restano (meglio che nessuna)
        solo = [{"codice": "P3", "titolo": "X", "indicatori": [ind], "azioni": [{"descrizione": ind["descrizione"], "fine": None}]}]
        self.assertEqual(len(unisci(solo)[0]["azioni"]), 1)

    def test_documento_senza_obiettivi(self):
        import asyncio

        from common.importazione import ImportazioneNonRiuscita
        from common.performance.importazione import estrai

        with self.assertRaisesRegex(ImportazioneNonRiuscita, "non ci sono obiettivi"):
            asyncio.run(estrai("Relazione sul lavoro agile", None))

    def test_indicatori_dal_valore_atteso(self):
        from common.performance.importazione import indicatore

        def tipo(valore):
            i, avviso = indicatore({"descrizione": "Indicatore", "valore_atteso": valore}, 2026)
            return i["tipo"], i["target"], i["target_data"], i["unita"], avviso is not None

        self.assertEqual(tipo("31/12/2026"), ("DATA", None, "2026-12-31", None, False))
        self.assertEqual(tipo("entro il 30.06.2026"), ("DATA", None, "2026-06-30", None, False))
        self.assertEqual(tipo("100,00 %"), ("PERCENTUALE", 100.0, None, None, False))
        self.assertEqual(tipo("2,00 N."), ("NUMERO", 2.0, None, None, False))
        self.assertEqual(tipo("1.558.203"), ("NUMERO", 1558203.0, None, None, False))
        self.assertEqual(tipo("Km 42,385"), ("NUMERO", 42.385, None, "Km", False))
        self.assertEqual(tipo("150%"), ("NUMERO", 150.0, None, "%", False))  # non è una percentuale valida
        self.assertEqual(tipo("SI"), ("SI_NO", None, None, None, False))
        self.assertEqual(tipo("miglioramento"), ("SI_NO", None, None, None, True))
        self.assertEqual(tipo(None), ("SI_NO", None, None, None, True))

    def test_abbina_struttura(self):
        from types import SimpleNamespace as S

        from common.performance.importazione import abbina_struttura

        strutture = [S(id="s5", codice="SETTORE 5", descrizione="Lavori pubblici e traffico"),
                     S(id="s6", codice="SETTORE 6", descrizione="Protezione civile e sistemi informativi")]  # fmt: skip
        self.assertEqual(abbina_struttura("Settore Dipartimentale 5 Lavori Pubblici e Traffico", strutture), "s5")
        self.assertEqual(abbina_struttura("Settore Dipartimentale 6 Protezione Civile e Sistemi Infomativi", strutture), "s6")
        self.assertIsNone(abbina_struttura("Gabinetto del Sindaco", strutture))
        self.assertIsNone(abbina_struttura(None, strutture))
