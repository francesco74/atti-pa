"""Azioni dell'assistente sui documenti (common/assistente_azioni.py) con RAG e LLM simulati:
blocchi di parti consecutive con le etichette, riassunto di un documento corto in una sola
chiamata, map-reduce sui documenti lunghi, unione a gruppi oltre il limite, confronto tra
schede, estrazione senza i blocchi vuoti, annullamento, documenti troppo lunghi.
    python -m unittest common.tests.test_assistente_azioni
"""

import unittest

from common import assistente_azioni as az


class RagFinto:
    def __init__(self, documenti: dict[str, list[str]]):
        self.documenti = documenti
        self.letture = []

    async def sezioni(self, sessione, doc_id, da, quante):
        self.letture.append((doc_id, da))
        parti = self.documenti[doc_id]
        return {"total": len(parti), "sections": [
            {"index": i, "content": parti[i], "headings": {}} for i in range(da, min(da + quante, len(parti)))]}


class LlmFinto:
    def __init__(self, risposte=None):
        self.chiamate: list[str] = []
        self.risposte = risposte or {}

    async def elabora(self, sistema, testo):
        assert "etichetta" in sistema
        self.chiamate.append(testo)
        for chiave, risposta in self.risposte.items():
            if chiave in testo:
                return risposta
        return f"risultato {len(self.chiamate)}"


def documento(n_parti: int, lunghezza: int = 100) -> list[str]:
    return [f"Parte {i + 1}: " + "x" * lunghezza for i in range(n_parti)]


async def avanza_sempre(fatti, totale):
    return True


class Azioni(unittest.IsolatedAsyncioTestCase):
    async def _esegui(self, tipo, rag, llm, ids, istruzioni="", blocco=1000, unione=5000, max_blocchi=50, avanza=None):
        avanzamenti = []

        async def registra(fatti, totale):
            avanzamenti.append((fatti, totale))
            return True if avanza is None else await avanza(fatti, totale)

        testo = await az.esegui(tipo, rag, "s", [az.Documento(i, f"{i}.pdf") for i in ids], istruzioni, llm, registra,
                                caratteri_blocco=blocco, caratteri_unione=unione, max_blocchi=max_blocchi)  # fmt: skip
        return testo, avanzamenti

    async def test_blocchi_con_etichette(self):
        rag = RagFinto({"a": documento(120, 300)})
        blocchi = await az.leggi_blocchi(rag, "s", az.Documento("a", "Legge.pdf"), 1000)
        self.assertEqual([r[1] for r in rag.letture], [0, 50, 100])  # letture a pagine
        self.assertEqual(blocchi[0].prima, 1)
        self.assertEqual(blocchi[-1].ultima, 120)
        self.assertTrue(all(len(b.testo) <= 1000 for b in blocchi))
        self.assertIn("[Legge.pdf, parte 1]", blocchi[0].testo)
        self.assertEqual(blocchi[1].parti, f"parti {blocchi[1].prima}-{blocchi[1].ultima}")
        # parti consecutive, nessuna persa
        self.assertEqual(sum(b.ultima - b.prima + 1 for b in blocchi), 120)

    async def test_riassunto_breve_in_una_chiamata(self):
        llm = LlmFinto()
        testo, avanzamenti = await self._esegui(az.RIASSUNTO, RagFinto({"a": documento(3)}), llm, ["a"], "in 5 righe")
        self.assertEqual(len(llm.chiamate), 1)
        self.assertIn("[a.pdf, parte 3]", llm.chiamate[0])
        self.assertIn("in 5 righe", llm.chiamate[0])
        self.assertEqual(testo, "risultato 1")
        self.assertEqual(avanzamenti, [(0, 1), (1, 1)])

    async def test_riassunto_lungo_map_reduce(self):
        llm = LlmFinto()
        testo, avanzamenti = await self._esegui(az.RIASSUNTO, RagFinto({"a": documento(30, 300), "b": documento(2)}),
                                                llm, ["a", "b"])  # fmt: skip
        parti = [c for c in llm.chiamate if c.startswith("Riassumi questa porzione")]
        self.assertGreater(len(parti), 1)
        finale_a = next(c for c in llm.chiamate if c.startswith('Scrivi il riassunto del documento "a.pdf"'))
        self.assertIn("Riassunto delle parti 1-", finale_a)
        self.assertIn("## a.pdf", testo)
        self.assertIn("## b.pdf", testo)
        self.assertEqual(avanzamenti[-1][0], len(llm.chiamate))
        self.assertEqual(avanzamenti[-1][0], avanzamenti[-1][1])

    async def test_unione_a_gruppi_oltre_il_limite(self):
        llm = LlmFinto({"Riassumi questa porzione": "r" * 900})
        await self._esegui(az.RIASSUNTO, RagFinto({"a": documento(40, 300)}), llm, ["a"], unione=2500)
        unioni = [c for c in llm.chiamate if c.startswith("Ricevi riassunti di parti consecutive")]
        self.assertTrue(unioni)
        self.assertTrue(all(len(c) < 2500 + 600 for c in unioni))  # ogni unione sta nel limite (più il prompt)

    async def test_confronto(self):
        llm = LlmFinto()
        testo, _ = await self._esegui(az.CONFRONTO, RagFinto({"a": documento(2), "b": documento(2)}), llm, ["a", "b"],
                                      "importi")  # fmt: skip
        self.assertEqual(sum(c.startswith("Compila la scheda") for c in llm.chiamate), 2)
        finale = llm.chiamate[-1]
        self.assertTrue(finale.startswith("Confronta i documenti"))
        self.assertIn("### Scheda di a.pdf", finale)
        self.assertIn("### Scheda di b.pdf", finale)
        self.assertEqual(testo, "risultato 3")

    async def test_estrazione_senza_blocchi_vuoti(self):
        llm = LlmFinto({"parte 1]": "- scadenza 30/06 [a.pdf, parte 1]", "porzione": "NESSUNO"})
        testo, _ = await self._esegui(az.ESTRAZIONE, RagFinto({"a": documento(6, 400)}), llm, ["a"], "le scadenze",
                                      blocco=900)  # fmt: skip
        finale = llm.chiamate[-1]
        self.assertTrue(finale.startswith("Ecco gli elementi estratti"))
        self.assertIn("scadenza 30/06", finale)
        self.assertNotIn("NESSUNO", finale)
        llm = LlmFinto({"porzione": "NESSUNO."})
        testo, _ = await self._esegui(az.ESTRAZIONE, RagFinto({"a": documento(2)}), llm, ["a"], "gli importi")
        self.assertIn("non ho trovato", testo)

    async def test_annullamento(self):
        async def annullata(fatti, totale):
            return fatti < 2

        llm = LlmFinto()
        with self.assertRaises(az.AzioneInterrotta):
            await self._esegui(az.ESTRAZIONE, RagFinto({"a": documento(10, 400)}), llm, ["a"], "x", blocco=900,
                               avanza=annullata)  # fmt: skip
        self.assertEqual(len(llm.chiamate), 2)

    async def test_documenti_troppo_lunghi_o_vuoti(self):
        with self.assertRaises(az.AzioneNonEseguibile):
            await self._esegui(az.RIASSUNTO, RagFinto({"a": documento(100, 900)}), LlmFinto(), ["a"], max_blocchi=10)
        with self.assertRaises(az.AzioneNonEseguibile):
            await self._esegui(az.RIASSUNTO, RagFinto({"a": []}), LlmFinto(), ["a"])


if __name__ == "__main__":
    unittest.main()
