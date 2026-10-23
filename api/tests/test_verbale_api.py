"""Verbale del controllo di un atto (GET /api/v1/verifiche/<id>/verbale) in ODT: dati
dell'atto, esiti per scheda (automatici e del controllore), riferimenti, dati personali
senza i valori. Il PDF lo produce il servizio di conversione, qui non usato.
    cd api/tests && python test_verbale_api.py
"""

from __future__ import annotations

import asyncio
import io
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from common.config import Settings  # noqa: E402
from common.models import (  # noqa: E402
    AttoControllato,
    Base,
    ImpostazioniEnte,
    Ruolo,
    SessioneControllo,
    StatoVerifica,
    TipologiaAtto,
    User,
    Verifica,
)

AUTOMATICI = [
    {
        "elemento_id": "e1", "scheda": "SCHEDA_DETERMINE", "scheda_titolo": "Scheda delle determinazioni",
        "titolo": "Oggetto dell'atto", "esito": "CONFORME", "motivazione": "L'oggetto è indicato.",
        "norme_usate": [], "obbligatorio": True,
    },
    {
        "elemento_id": "e2", "scheda": "SCHEDA_DETERMINE", "scheda_titolo": "Scheda delle determinazioni",
        "titolo": "Visto di regolarità contabile", "esito": "DUBBIO", "motivazione": "Non è chiaro se c'è spesa.",
        "norme_usate": ["art. 183 D.Lgs. 267/2000"], "obbligatorio": True,
    },
    {
        "elemento_id": "e3", "scheda": "SCHEDA_ICT_CLOUD", "scheda_titolo": "Scheda Cloud ICT",
        "titolo": "Qualificazione ACN", "esito": "NON_CONFORME", "motivazione": "Manca la qualificazione.",
        "norme_usate": [], "obbligatorio": True,
    },
]  # fmt: skip
RIFERIMENTI = {
    "riferimenti": [
        {"testo": "art. 50 del D.Lgs. 36/2023", "citazione": "art. 50 D.Lgs. 36/2023",
         "esito": "VIGENTE", "avvisi": []},
        {"testo": "Regolamento dei contratti (C.P. n. 17/2022)", "citazione": None,
         "titolo_atto": "Regolamento dei contratti", "esito": "ABROGATO",
         "avvisi": ["Norma abrogata dal 01/03/2026"]},
    ],
    "segnaposto": [],
    "dati_personali": [{"categoria": "nome_cognome", "testo": "Mario Rossi"}],
    "dati_personali_stato": "VALUTATI",
}  # fmt: skip


def _testo_odt(contenuto: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenuto)) as z:
        return z.read("content.xml").decode()


class VerbaleApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import create_app

        cls.cartella = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{cls.cartella.name}/prova.db"

        async def dati():
            motore = create_async_engine(url)
            async with motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(motore, expire_on_commit=False) as db:
                db.add(TipologiaAtto(codice="DETERMINA", descrizione="Determinazione dirigenziale"))
                db.add(ImpostazioniEnte(id=1, dati_json={"ente": "Provincia di Prova"}))
                user = User(username="locale", nome_completo="Utente locale", ruoli=list(Ruolo.TUTTI))
                db.add(user)
                await db.flush()
                controllo = SessioneControllo(titolo="Controllo primo semestre", creata_da=user.id)
                db.add(controllo)
                await db.flush()
                atto = AttoControllato(
                    sessione_id=controllo.id, numero_registro="123/2026", data_adozione=date(2026, 3, 2),
                    settore="Servizi informatici", tipologia_atto="DETERMINA",
                    modello="DD_AFFIDAMENTO_DIRETTO_SF", moduli_json=["ICT_CLOUD"],
                    oggetto="Affidamento del servizio di posta elettronica", file_nome="atto.pdf",
                    file_mime="application/pdf", stato="ANALIZZATO",
                )  # fmt: skip
                db.add(atto)
                await db.flush()
                verifica = Verifica(
                    atto_controllato_id=atto.id, data_riferimento=atto.data_adozione,
                    stato=StatoVerifica.COMPLETATA, richiesta_da=user.id, modello_llm="prova",
                    esito_automatico=AUTOMATICI, esito_riferimenti=RIFERIMENTI,
                )  # fmt: skip
                db.add(verifica)
                await db.commit()
                cls.verifica_id = verifica.id
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=url, auth_enabled=False, llm_provider="ollama",
            llm_model="prova", archivio_dir=cls.cartella.name,
        )  # fmt: skip
        cls.c = create_app(settings).test_client()

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()

    def _verbale(self) -> str:
        r = self.c.get(f"/api/v1/verifiche/{self.verifica_id}/verbale?formato=odt")
        self.assertEqual(r.status_code, 200, r.data[:300])
        self.assertIn("verbale-controllo-123-2026.odt", r.headers["Content-Disposition"])
        return _testo_odt(r.data)

    def test_1_non_revisionato(self):
        testo = self._verbale()
        for atteso in [
            "Provincia di Prova",
            "Verbale di controllo successivo di regolarità amministrativa",
            "non ancora revisionati",
            "123/2026",
            "Affidamento del servizio di posta elettronica",
            "Scheda delle determinazioni",
            "Scheda Cloud ICT",
            "Qualificazione ACN",
            "Non conforme",
            "Abrogata",
            "Norma abrogata dal 01/03/2026",
            "nome cognome (1)",
        ]:
            self.assertIn(atteso, testo)
        self.assertNotIn("Mario Rossi", testo)  # i dati personali non compaiono

    def test_2_revisionato(self):
        r = self.c.put(
            f"/api/v1/verifiche/{self.verifica_id}/revisione",
            json={
                "esiti": [
                    {"elemento_id": "e1", "titolo": "Oggetto dell'atto", "esito": "CONFORME"},
                    {"elemento_id": "e2", "titolo": "Visto di regolarità contabile",
                     "esito": "CONFORME", "nota": "L'atto non comporta spesa."},
                    {"elemento_id": "e3", "titolo": "Qualificazione ACN", "esito": "NON_CONFORME"},
                ],
                "motivazione": "Atto regolare salvo la qualificazione ACN.",
                "conclusa": True,
            },
        )  # fmt: skip
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        testo = self._verbale()
        self.assertNotIn("non ancora revisionati", testo)
        self.assertIn("modificato dal controllore", testo)
        self.assertIn("Nota del controllore: L'atto non comporta spesa.", testo)
        self.assertIn("Atto regolare salvo la qualificazione ACN.", testo)
        self.assertIn("Utente locale", testo)

    def test_3_bozza_o_verifica_inesistente(self):
        self.assertEqual(self.c.get("/api/v1/verifiche/inesistente/verbale").status_code, 404)


if __name__ == "__main__":
    unittest.main()
