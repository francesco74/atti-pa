"""Pacchetti e database che comanda: importazione iniziale, analisi a tre vie (standard di
riferimento, versione dell'ente, nuovo standard), decisioni, ricomposizione dei modelli,
esportazione. Su SQLite in memoria.
    python -m unittest common.tests.test_pacchetti
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.configurazione import leggi_checklist
from common.models import Base, Checklist, ModelloAtto, PacchettoImportato, TipologiaAtto
from common.pacchetti import (
    MANTIENI_BASE,
    PacchettoNonValido,
    analizza,
    da_cartella,
    da_zip,
    esporta,
    importa,
    importa_pacchetto_iniziale,
    in_zip,
    leggi_pacchetto,
    salva_checklist,
    versione_attiva,
)

PACCHETTO = Path(__file__).resolve().parents[2] / "deploy"


def _con_versione(file: dict[str, str], versione: str) -> dict[str, str]:
    manifesto = yaml.safe_load(file["pacchetto.yaml"])
    manifesto["versione"] = versione
    return {**file, "pacchetto.yaml": yaml.safe_dump(manifesto, allow_unicode=True)}


def _cambia_checklist(file: dict[str, str], nome: str, titolo: str) -> dict[str, str]:
    dati = json.loads(file[f"checklist/{nome}"])
    dati["titolo"] = titolo
    return {**file, f"checklist/{nome}": json.dumps(dati, ensure_ascii=False)}


class PacchettiSuDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.motore = create_async_engine("sqlite+aiosqlite://")
        async with self.motore.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        self.file = da_cartella(PACCHETTO)

    async def asyncTearDown(self):
        await self.motore.dispose()

    async def _iniziale(self):
        r = await importa_pacchetto_iniziale(self.motore, PACCHETTO)
        self.assertIsNotNone(r)
        self.assertEqual(r.errori, [])
        self.assertEqual(r.avvisi, [])
        return r

    async def test_primo_avvio_poi_comanda_il_database(self):
        r = await self._iniziale()
        self.assertTrue(r.applicati)
        async with AsyncSession(self.motore) as db:
            self.assertIsNotNone(await db.get(TipologiaAtto, "DETERMINA"))
            modelli = (await db.scalars(select(ModelloAtto))).all()
            self.assertTrue(all(m.pacchetto == "Modelli standard Atti PA 2026.1" for m in modelli))
            self.assertEqual(len((await db.scalars(select(PacchettoImportato))).all()), 1)
        # secondo avvio: il database non è vuoto, non si importa nulla
        self.assertIsNone(await importa_pacchetto_iniziale(self.motore, PACCHETTO))

    async def test_stesso_pacchetto_tutto_invariato(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            voci = await analizza(db, leggi_pacchetto(self.file))
            self.assertEqual({v.stato for v in voci}, {"INVARIATO"})

    async def test_tre_vie(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            # l'ente modifica la scheda CAM nell'app
            cam = await versione_attiva(db, "checklist", "SCHEDA_CAM")
            dati = leggi_checklist(json.dumps({
                "codice": cam.codice, "titolo": "CAM dell'ente", "tipologia_atto": "DETERMINA",
                "modulo": "CAM", "elementi": [{"titolo": "Unico", "regola": "Regola"}],
            }))  # fmt: skip
            await salva_checklist(db, dati, MANTIENI_BASE)
            await db.commit()

            # nuovo standard: cambiano la scheda CAM (modificata anche dall'ente) e la scheda
            # SIA (non toccata dall'ente)
            nuovo = _con_versione(self.file, "2026.2")
            nuovo = _cambia_checklist(nuovo, "scheda_cam.json", "CAM nuova versione standard")
            nuovo = _cambia_checklist(nuovo, "scheda_sia.json", "SIA nuova versione standard")
            p = leggi_pacchetto(nuovo)
            stati = {v.chiave: v.stato for v in await analizza(db, p)}
            self.assertEqual(stati["checklist:SCHEDA_CAM"], "CONFLITTO")
            self.assertEqual(stati["checklist:SCHEDA_SIA"], "AGGIORNABILE")
            self.assertEqual(stati["checklist:SCHEDA_DETERMINE"], "INVARIATO")

            r = await importa(db, p)  # azioni proposte: conflitto mantenuto, SIA aggiornata
            await db.commit()
            self.assertIn("checklist:SCHEDA_SIA", r.applicati)
            self.assertIn("checklist:SCHEDA_CAM", r.mantenuti)
            sia = await versione_attiva(db, "checklist", "SCHEDA_SIA")
            self.assertEqual(sia.titolo, "SIA nuova versione standard")
            self.assertEqual(sia.pacchetto, "Modelli standard Atti PA 2026.2")
            cam = await versione_attiva(db, "checklist", "SCHEDA_CAM")
            self.assertEqual(cam.titolo, "CAM dell'ente")
            # il nuovo standard è il riferimento: reimportarlo non segnala più il conflitto
            stati = {v.chiave: v.stato for v in await analizza(db, p)}
            self.assertEqual(stati["checklist:SCHEDA_CAM"], "INVARIATO")

    async def test_conflitto_sostituito_e_rimosso_dallo_standard(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            cam = await versione_attiva(db, "checklist", "SCHEDA_CAM")
            dati = leggi_checklist(json.dumps({
                "codice": cam.codice, "titolo": "CAM dell'ente", "tipologia_atto": "DETERMINA",
                "modulo": "CAM", "elementi": [{"titolo": "Unico", "regola": "Regola"}],
            }))  # fmt: skip
            await salva_checklist(db, dati, MANTIENI_BASE)
            await db.commit()
            nuovo = _cambia_checklist(_con_versione(self.file, "2026.2"), "scheda_cam.json", "X")
            del nuovo["checklist/scheda_utenze.json"]
            p = leggi_pacchetto(nuovo)
            stati = {v.chiave: v.stato for v in await analizza(db, p)}
            self.assertEqual(stati["checklist:SCHEDA_UTENZE"], "RIMOSSO")
            r = await importa(
                db, p, {"checklist:SCHEDA_CAM": "applica", "checklist:SCHEDA_UTENZE": "disattiva"}
            )
            await db.commit()
            self.assertEqual((await versione_attiva(db, "checklist", "SCHEDA_CAM")).titolo, "X")
            self.assertIsNone(await versione_attiva(db, "checklist", "SCHEDA_UTENZE"))
            self.assertIn("checklist SCHEDA_UTENZE", " ".join(r.disattivati).replace(":", " "))

    async def test_specificita_cambiata_ricompone_i_modelli(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            prima = (await versione_attiva(db, "modello", "DD_AFFIDAMENTO_DIRETTO_SF")).versione
            regola = yaml.safe_load(self.file["modelli/regole/cam.yaml"])
            regola["etichetta"] = "CAM (nuova etichetta)"
            nuovo = {
                **_con_versione(self.file, "2026.2"),
                "modelli/regole/cam.yaml": yaml.safe_dump(regola, allow_unicode=True),
            }
            r = await importa(db, leggi_pacchetto(nuovo))
            await db.commit()
            self.assertEqual(r.errori, [])
            self.assertIn("modulo:CAM", r.applicati)
            dopo = await versione_attiva(db, "modello", "DD_AFFIDAMENTO_DIRETTO_SF")
            self.assertEqual(dopo.versione, prima + 1)
            etichette = {
                q["opzioni"]["cam"]
                for q in dopo.definizione_json["domande"]
                if q.get("opzioni_da_regole")
            }
            self.assertEqual(etichette, {"CAM (nuova etichetta)"})
            # il modello conserva lo standard di riferimento: non risulta modificato dall'ente
            self.assertEqual(dopo.impronta, dopo.impronta_base)

    async def test_esporta_e_reimporta(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            file = await esporta(db, "Ente", "1")
            p = leggi_pacchetto(da_zip(in_zip(file)))
            self.assertEqual(len(p.di_tipo("modello")), 4)
            self.assertEqual(len(p.di_tipo("checklist")), 12)
            # l'esportazione ha gli stessi contenuti: nulla da aggiornare
            stati = {v.stato for v in await analizza(db, p)}
            self.assertEqual(stati, {"INVARIATO"})


class PacchettiNonValidi(unittest.TestCase):
    def test_manca_il_manifesto(self):
        with self.assertRaises(PacchettoNonValido):
            leggi_pacchetto({"modelli/x.yaml": "codice: X"})

    def test_zip_non_valido(self):
        with self.assertRaises(PacchettoNonValido):
            da_zip(b"non e' uno zip")

    def test_percorsi_estranei_ignorati(self):
        file = da_cartella(PACCHETTO)
        dati = in_zip({**file, "../fuori.yaml": "x", "altro/file.txt": "x"})
        self.assertEqual(set(da_zip(dati)), set(file))

    def test_errore_in_una_checklist(self):
        file = {**da_cartella(PACCHETTO), "checklist/rotta.json": "{"}
        with self.assertRaises(PacchettoNonValido) as e:
            leggi_pacchetto(file)
        self.assertIn("checklist/rotta.json", str(e.exception))


if __name__ == "__main__":
    unittest.main()
