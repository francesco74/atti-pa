"""Verifica con più schede: generica della tipologia, del modello e delle specificità.

Il modello linguistico è sostituito da uno finto, quindi non si invia nulla all'esterno;
gli elementi senza riferimenti normativi non richiedono Normattiva.
    python -m unittest common.tests.test_verifica_schede
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import date
from types import SimpleNamespace

from common.llm import EsitoElemento
from common.verifica import valuta_checklist


class LlmFinto:
    max_caratteri_atto = 60_000
    modello = "finto"

    def __init__(self):
        self.prompt: list[str] = []

    async def valuta(self, prompt: str) -> EsitoElemento:
        self.prompt.append(prompt)
        return EsitoElemento(esito="CONFORME", motivazione="ok")


def _scheda(codice: str, titolo: str, elementi: list[str]):
    return SimpleNamespace(
        codice=codice,
        titolo=titolo,
        elementi=[
            SimpleNamespace(
                id=f"{codice}-{i}", titolo=t, regola=f"Regola {t}", riferimenti_json=[],
                obbligatorio=True,
            )
            for i, t in enumerate(elementi)
        ],
    )


class VerificaConPiuSchede(unittest.TestCase):
    def test_esiti_nell_ordine_e_con_la_scheda(self):
        schede = [
            _scheda("SCHEDA_DETERMINE", "Determine", ["Competenza", "Motivazione"]),
            _scheda("SCHEDA_MODELLO", "Affidamento", ["Forma del contratto"]),
            _scheda("SCHEDA_ICT_CLOUD", "Cloud", ["Qualificazione ACN"]),
        ]
        llm = LlmFinto()
        esiti = asyncio.run(
            valuta_checklist(None, None, llm, schede, "Testo dell'atto", date(2026, 10, 21))
        )
        self.assertEqual(
            [(e["scheda"], e["titolo"]) for e in esiti],
            [
                ("SCHEDA_DETERMINE", "Competenza"),
                ("SCHEDA_DETERMINE", "Motivazione"),
                ("SCHEDA_MODELLO", "Forma del contratto"),
                ("SCHEDA_ICT_CLOUD", "Qualificazione ACN"),
            ],
        )
        self.assertEqual(esiti[3]["scheda_titolo"], "Cloud")
        self.assertTrue(all(e["esito"] == "CONFORME" for e in esiti))
        self.assertEqual(len(llm.prompt), 4)  # un elemento, una valutazione

    def test_nessuna_scheda(self):
        esiti = asyncio.run(
            valuta_checklist(None, None, LlmFinto(), [], "Testo", date(2026, 10, 21))
        )
        self.assertEqual(esiti, [])


if __name__ == "__main__":
    unittest.main()
