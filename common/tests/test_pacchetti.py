"""Pacchetti e database che comanda: primo pacchetto sul database vuoto, analisi a tre vie (standard di
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
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.configurazione import leggi_checklist
from common.models import Base, Checklist, Ente, ModelloAtto, TipologiaAtto
from common.pacchetti import (
    MANTIENI_BASE,
    PacchettoNonValido,
    analizza,
    da_cartella,
    da_zip,
    esporta,
    importa,
    in_zip,
    leggi_pacchetto,
    salva_checklist,
    versione_attiva,
)

PACCHETTO = Path(__file__).resolve().parents[2] / "pacchetto"
# la versione del pacchetto standard (cambia a ogni rilascio) e una sempre successiva
VERSIONE = yaml.safe_load((PACCHETTO / "pacchetto.yaml").read_text(encoding="utf-8"))["versione"]
SUCCESSIVA = "2099.1"
ENTE = "ente-di-prova"


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
        async with AsyncSession(self.motore) as db:
            db.add(Ente(id=ENTE, codice="prova", nome="Ente di prova", moduli_json=[], dati_json={}))
            await db.commit()
        self.file = da_cartella(PACCHETTO)

    async def asyncTearDown(self):
        await self.motore.dispose()

    async def _iniziale(self):
        """Il sistema parte vuoto: il pacchetto standard si importa come tutti gli altri."""
        async with AsyncSession(self.motore, expire_on_commit=False) as db:
            r = await importa(db, ENTE, leggi_pacchetto(self.file))
            await db.commit()
        self.assertEqual(r.errori, [])
        self.assertEqual(r.avvisi, [])
        return r

    async def test_primo_pacchetto_sul_database_vuoto(self):
        pacchetto = leggi_pacchetto(self.file)
        async with AsyncSession(self.motore) as db:
            voci = await analizza(db, ENTE, pacchetto)
        self.assertTrue(voci)
        self.assertEqual({v.stato for v in voci}, {"NUOVO"})
        r = await self._iniziale()
        self.assertEqual(len(r.applicati), len(voci))
        async with AsyncSession(self.motore) as db:
            self.assertIsNotNone(await db.get(TipologiaAtto, "DETERMINA"))
            modelli = (await db.scalars(select(ModelloAtto))).all()
            self.assertTrue(all(m.pacchetto == f"Modelli standard Atti PA {VERSIONE}" for m in modelli))

    async def test_stesso_pacchetto_tutto_invariato(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            voci = await analizza(db, ENTE, leggi_pacchetto(self.file))
            self.assertEqual({v.stato for v in voci}, {"INVARIATO"})

    async def test_tre_vie(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            # l'ente modifica la scheda CAM nell'app
            cam = await versione_attiva(db, ENTE, "checklist", "SCHEDA_CAM")
            dati = leggi_checklist(json.dumps({
                "codice": cam.codice, "titolo": "CAM dell'ente", "tipologia_atto": "DETERMINA",
                "modulo": "CAM", "elementi": [{"titolo": "Unico", "regola": "Regola"}],
            }))  # fmt: skip
            await salva_checklist(db, ENTE, dati, MANTIENI_BASE)
            await db.commit()

            # nuovo standard: cambiano la scheda CAM (modificata anche dall'ente) e la scheda
            # SIA (non toccata dall'ente)
            nuovo = _con_versione(self.file, SUCCESSIVA)
            nuovo = _cambia_checklist(nuovo, "scheda_cam.json", "CAM nuova versione standard")
            nuovo = _cambia_checklist(nuovo, "scheda_sia.json", "SIA nuova versione standard")
            p = leggi_pacchetto(nuovo)
            stati = {v.chiave: v.stato for v in await analizza(db, ENTE, p)}
            self.assertEqual(stati["checklist:SCHEDA_CAM"], "CONFLITTO")
            self.assertEqual(stati["checklist:SCHEDA_SIA"], "AGGIORNABILE")
            self.assertEqual(stati["checklist:SCHEDA_DETERMINE"], "INVARIATO")

            r = await importa(db, ENTE, p)  # azioni proposte: conflitto mantenuto, SIA aggiornata
            await db.commit()
            self.assertIn("checklist:SCHEDA_SIA", r.applicati)
            self.assertIn("checklist:SCHEDA_CAM", r.mantenuti)
            sia = await versione_attiva(db, ENTE, "checklist", "SCHEDA_SIA")
            self.assertEqual(sia.titolo, "SIA nuova versione standard")
            self.assertEqual(sia.pacchetto, f"Modelli standard Atti PA {SUCCESSIVA}")
            cam = await versione_attiva(db, ENTE, "checklist", "SCHEDA_CAM")
            self.assertEqual(cam.titolo, "CAM dell'ente")
            # il nuovo standard è il riferimento: reimportarlo non segnala più il conflitto
            stati = {v.chiave: v.stato for v in await analizza(db, ENTE, p)}
            self.assertEqual(stati["checklist:SCHEDA_CAM"], "INVARIATO")

    async def test_conflitto_sostituito_e_rimosso_dallo_standard(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            cam = await versione_attiva(db, ENTE, "checklist", "SCHEDA_CAM")
            dati = leggi_checklist(json.dumps({
                "codice": cam.codice, "titolo": "CAM dell'ente", "tipologia_atto": "DETERMINA",
                "modulo": "CAM", "elementi": [{"titolo": "Unico", "regola": "Regola"}],
            }))  # fmt: skip
            await salva_checklist(db, ENTE, dati, MANTIENI_BASE)
            await db.commit()
            nuovo = _cambia_checklist(_con_versione(self.file, SUCCESSIVA), "scheda_cam.json", "X")
            del nuovo["checklist/scheda_utenze.json"]
            p = leggi_pacchetto(nuovo)
            stati = {v.chiave: v.stato for v in await analizza(db, ENTE, p)}
            self.assertEqual(stati["checklist:SCHEDA_UTENZE"], "RIMOSSO")
            r = await importa(
                db, ENTE, p, {"checklist:SCHEDA_CAM": "applica", "checklist:SCHEDA_UTENZE": "disattiva"}
            )
            await db.commit()
            self.assertEqual((await versione_attiva(db, ENTE, "checklist", "SCHEDA_CAM")).titolo, "X")
            self.assertIsNone(await versione_attiva(db, ENTE, "checklist", "SCHEDA_UTENZE"))
            self.assertIn("checklist SCHEDA_UTENZE", " ".join(r.disattivati).replace(":", " "))

    async def test_specificita_cambiata_ricompone_i_modelli(self):
        await self._iniziale()
        async with AsyncSession(self.motore) as db:
            prima = (await versione_attiva(db, ENTE, "modello", "DD_AFFIDAMENTO_DIRETTO_SF")).versione
            regola = yaml.safe_load(self.file["modelli/regole/cam.yaml"])
            regola["etichetta"] = "CAM (nuova etichetta)"
            nuovo = {
                **_con_versione(self.file, SUCCESSIVA),
                "modelli/regole/cam.yaml": yaml.safe_dump(regola, allow_unicode=True),
            }
            r = await importa(db, ENTE, leggi_pacchetto(nuovo))
            await db.commit()
            self.assertEqual(r.errori, [])
            self.assertIn("modulo:CAM", r.applicati)
            dopo = await versione_attiva(db, ENTE, "modello", "DD_AFFIDAMENTO_DIRETTO_SF")
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
            file = await esporta(db, ENTE, "Ente", "1")
            p = leggi_pacchetto(da_zip(in_zip(file)))
            self.assertEqual(len(p.di_tipo("modello")), 4)
            self.assertEqual(len(p.di_tipo("checklist")), 12)
            # l'esportazione ha gli stessi contenuti: nulla da aggiornare
            stati = {v.stato for v in await analizza(db, ENTE, p)}
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


class AnticorruzioneNeiPacchetti(unittest.IsolatedAsyncioTestCase):
    """Metodologia, aree e processi standard: solo per gli enti con il modulo; confronto a tre
    vie sui processi, aggiornamento per codice che conserva gli identificativi e le
    valutazioni dell'ente, esportazione rileggibile."""

    async def asyncSetUp(self):
        from common.models import Modulo

        self.motore = create_async_engine("sqlite+aiosqlite://")
        # chiavi esterne controllate come in MySQL: l'ordine degli inserimenti conta
        event.listen(self.motore.sync_engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
        async with self.motore.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with AsyncSession(self.motore) as db:
            db.add(Ente(id=ENTE, codice="prova", nome="Ente", moduli_json=[Modulo.ANTICORRUZIONE], dati_json={}))
            db.add(Ente(id="senza", codice="senza", nome="Senza modulo", moduli_json=[], dati_json={}))
            await db.commit()
        self.file = da_cartella(PACCHETTO)

    async def asyncTearDown(self):
        await self.motore.dispose()

    def _processo_cambiato(self, codice: str, descrizione: str) -> dict[str, str]:
        """Il pacchetto con una nuova descrizione per la prima attività del processo."""
        area = codice.split(".")[0].lower()
        nome = f"anticorruzione/processi/{area}.yaml"
        dati = yaml.safe_load(self.file[nome])
        processo = next(p for p in dati["processi"] if p["codice"] == codice)
        processo["attivita"][0]["descrizione"] = descrizione
        return _con_versione({**self.file, nome: yaml.safe_dump(dati, allow_unicode=True)}, "2026.9")

    async def test_tre_vie_sui_processi(self):
        from common.models import AcArea, AcAttivita, AcMetodologia, AcProcesso, AcRischio

        pacchetto = leggi_pacchetto(self.file)
        async with AsyncSession(self.motore, expire_on_commit=False) as db:
            self.assertFalse([v for v in await analizza(db, "senza", pacchetto) if v.tipo == "processo"])
            voci = [v for v in await analizza(db, ENTE, pacchetto) if v.tipo in ("processo", "metodologia")]
            self.assertEqual({v.stato for v in voci}, {"NUOVO"})
            r = await importa(db, ENTE, pacchetto)
            await db.commit()
            self.assertEqual(r.errori, [])
            n_processi = len(pacchetto.di_tipo("processo"))
            self.assertGreaterEqual(n_processi, 120)
            self.assertEqual(len((await db.scalars(select(AcProcesso))).all()), n_processi)
            self.assertEqual(len((await db.scalars(select(AcArea))).all()), len(pacchetto.aree))
            self.assertIsNotNone(await db.get(AcMetodologia, ENTE))
            rischi = (await db.scalars(select(AcRischio))).all()
            self.assertTrue(rischi and all(x.livello for x in rischi))  # valutazione proposta nei rischi nuovi
            # procedimenti standard: tutti creati (nessun tipo di ente indicato), con il codice P.n
            from common.models import AcProcedimento

            procedimenti = (await db.scalars(select(AcProcedimento))).all()
            self.assertEqual(len(procedimenti), len(pacchetto.procedimenti))
            self.assertTrue(all(p.codice.startswith("P.") and p.standard.startswith("PRC-") for p in procedimenti))
            # le attività che sono procedimenti puntano a quello dell'ente, senza voce
            att_proc = (await db.scalars(select(AcAttivita).where(AcAttivita.procedimento_id.is_not(None)))).all()
            self.assertTrue(att_proc)
            self.assertFalse([a for a in att_proc if a.voce_id])
            # catalogo: le voci standard e ogni elemento collegato a una di loro (testi uguali: una voce)
            from common.models import AcMisura, AcVoce

            voci_std = (await db.scalars(select(AcVoce))).all()
            self.assertEqual(len(voci_std), len(pacchetto.catalogo.voci()))
            self.assertFalse([v for v in voci_std if "-E" in v.codice])  # nessuna voce dell'ente
            for modello in (AcAttivita, AcRischio, AcMisura):
                senza = select(modello).where(modello.voce_id.is_(None))
                if modello is AcAttivita:
                    senza = senza.where(AcAttivita.procedimento_id.is_(None))
                self.assertFalse((await db.scalars(senza)).all(), modello)
            misure = (await db.scalars(select(AcMisura))).all()
            self.assertLess(len({x.voce_id for x in misure}), len(misure))
            voci = await analizza(db, ENTE, pacchetto)
            self.assertEqual({v.stato for v in voci if v.tipo == "processo"}, {"INVARIATO"})

            # l'ente modifica C.1 e rivaluta un rischio di C.4; lo standard cambia C.1 e C.4
            c1 = await db.scalar(select(AcProcesso).where(AcProcesso.codice == "C.1"))
            att = (await db.scalars(select(AcAttivita).where(AcAttivita.processo_id == c1.id))).all()
            min(att, key=lambda a: a.codice).descrizione = "Versione dell'ente"
            c4 = await db.scalar(select(AcProcesso).where(AcProcesso.codice == "C.4"))
            att2 = min((await db.scalars(select(AcAttivita).where(AcAttivita.processo_id == c4.id))).all(),
                       key=lambda a: a.codice)  # fmt: skip
            id_att2 = att2.id
            # procedimenti già presenti: uno con la descrizione vuota, uno scritto dall'ente
            p1, p2 = sorted(procedimenti, key=lambda p: p.standard)[:2]
            p1.descrizione, p1.norma_riferimento = None, " "
            p2.descrizione = "Descrizione dell'ente"
            id_p1, id_p2 = p1.id, p2.id
            await db.commit()
        file = self._processo_cambiato("C.1", "Nuovo standard")
        dati = yaml.safe_load(file["anticorruzione/processi/c.yaml"])
        next(p for p in dati["processi"] if p["codice"] == "C.4")["denominazione"] += " (aggiornato)"
        file["anticorruzione/processi/c.yaml"] = yaml.safe_dump(dati, allow_unicode=True)
        nuovo = leggi_pacchetto(file)
        async with AsyncSession(self.motore, expire_on_commit=False) as db:
            stati = {v.codice: v.stato for v in await analizza(db, ENTE, nuovo) if v.tipo == "processo"}
            self.assertEqual((stati["C.1"], stati["C.4"], stati["C.5"]), ("CONFLITTO", "AGGIORNABILE", "INVARIATO"))
            r = await importa(db, ENTE, nuovo)
            await db.commit()
            self.assertIn("processo:C.4", r.applicati)
            self.assertIn("processo:C.1", r.mantenuti)
            c4 = await db.scalar(select(AcProcesso).where(AcProcesso.codice == "C.4"))
            self.assertTrue(c4.denominazione.endswith("(aggiornato)"))
            self.assertIsNotNone(await db.get(AcAttivita, id_att2))  # stesso codice, stesso id
            # nei procedimenti già presenti si riempiono solo i campi vuoti
            std = {p.codice: p for p in nuovo.procedimenti}
            p1, p2 = await db.get(AcProcedimento, id_p1), await db.get(AcProcedimento, id_p2)
            self.assertEqual(p1.descrizione, std[p1.standard].descrizione)
            self.assertEqual(p1.norma_riferimento, std[p1.standard].norma_riferimento)
            self.assertEqual(p2.descrizione, "Descrizione dell'ente")
            self.assertEqual(len((await db.scalars(select(AcProcedimento))).all()), len(nuovo.procedimenti))
            # dopo "mantieni" il nuovo standard è il riferimento: C.1 non è più in conflitto
            stati = {v.codice: v.stato for v in await analizza(db, ENTE, nuovo) if v.tipo == "processo"}
            self.assertEqual(stati["C.1"], "INVARIATO")

            # esportazione rileggibile come pacchetto
            esportato = await esporta(db, ENTE, "Esportazione", "1")
            riletto = leggi_pacchetto(esportato)
            self.assertEqual(len(riletto.di_tipo("processo")), n_processi)
            self.assertEqual(len(riletto.aree), len(pacchetto.aree))
            self.assertEqual(len(riletto.catalogo.voci()), len(pacchetto.catalogo.voci()))
            self.assertEqual(len(riletto.procedimenti), len(pacchetto.procedimenti))

    async def test_catalogo_con_codici_ripetuti(self):
        file = {**self.file, "anticorruzione/catalogo.yaml": "attivita:\n- {codice: ATT-0001, descrizione: a}\n"
                "- {codice: ATT-0001, descrizione: b}\n"}  # fmt: skip
        with self.assertRaises(PacchettoNonValido):
            leggi_pacchetto(file)

    async def test_voce_indicata_fuori_dal_catalogo(self):
        nome = "anticorruzione/processi/c.yaml"
        dati = yaml.safe_load(self.file[nome])
        dati["processi"][0]["attivita"][0]["rischi"][0]["misure"][0]["voce"] = "MIS-9999"
        with self.assertRaises(PacchettoNonValido) as e:
            leggi_pacchetto({**self.file, nome: yaml.safe_dump(dati, allow_unicode=True)})
        self.assertIn("MIS-9999", str(e.exception.errori))

    async def test_procedimento_fuori_dal_catalogo(self):
        nome = "anticorruzione/processi/c.yaml"
        file = {**self.file, nome: self.file[nome].replace("procedimento: PRC-0004", "procedimento: PRC-9999", 1)}
        with self.assertRaises(PacchettoNonValido) as e:
            leggi_pacchetto(file)
        self.assertIn("PRC-9999", str(e.exception.errori))

    async def test_tipo_di_ente(self):
        """Una provincia non importa i processi e i procedimenti dei soli comuni (e viceversa)."""
        from common.models import AcProcedimento, AcProcesso

        pacchetto = leggi_pacchetto(self.file)
        dei_comuni = {o.codice for o in pacchetto.di_tipo("processo") if o.ambito == "COMUNE"}
        delle_province = {o.codice for o in pacchetto.di_tipo("processo") if o.ambito == "PROVINCIA"}
        self.assertTrue(dei_comuni and delle_province)
        async with AsyncSession(self.motore, expire_on_commit=False) as db:
            voci = {v.codice: v for v in await analizza(db, ENTE, pacchetto) if v.tipo == "processo"}
            self.assertIn("solo comuni", voci[min(dei_comuni)].nota)
            r = await importa(db, ENTE, pacchetto, {f"processo:{max(dei_comuni)}": "applica"}, ambito="PROVINCIA")
            await db.commit()
            importati = set(await db.scalars(select(AcProcesso.codice)))
            self.assertEqual(importati & dei_comuni, {max(dei_comuni)})  # solo quello scelto esplicitamente
            self.assertLessEqual(delle_province, importati)
            standard = set(await db.scalars(select(AcProcedimento.standard)))
            self.assertFalse({p.codice for p in pacchetto.procedimenti if p.ambito == "COMUNE"} & standard)
            self.assertLessEqual({p.codice for p in pacchetto.procedimenti if p.ambito == "PROVINCIA"}, standard)
            self.assertEqual(r.errori, [])

    async def test_area_mancante(self):
        file = {**self.file, "anticorruzione/aree.yaml": "aree: []\n"}
        with self.assertRaises(PacchettoNonValido):
            leggi_pacchetto(file)
