"""Caricamento degli atti da controllare (deps.archivia_caricato, con pa_common.ingresso):
atti firmati .p7m sbustati e archiviati come documento, contenuto che deve corrispondere
all'estensione, formati non ammessi.
    cd api/tests && python test_caricamento_atti_api.py
"""

from __future__ import annotations

import asyncio
import io
import sys
import tempfile
import unittest
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RADICE), str(RADICE / "api" / "src")]

from asn1crypto import cms  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from auth import password as pw  # noqa: E402
from common.config import Settings  # noqa: E402
from common.models import Base, Ente, EnteDominio, Modulo, Ruolo, User  # noqa: E402

PASSWORD = "Password-di-prova-1"
ENTE = "http://atti.example.it"
API = "/api/v1/controllo"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def busta(documento: bytes) -> bytes:
    firmato = cms.SignedData({
        "version": "v1", "digest_algorithms": [], "signer_infos": [],
        "encap_content_info": {"content_type": "data", "content": documento},
    })  # fmt: skip
    return cms.ContentInfo({"content_type": "signed_data", "content": firmato}).dump()


class CaricamentoAtti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import create_app

        cls.cartella = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{cls.cartella.name}/prova.db"

        async def dati():
            motore = create_async_engine(url)
            async with motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with AsyncSession(motore) as db:
                ente = Ente(codice="atti", nome="Ente", dati_json={}, moduli_json=[Modulo.REDAZIONE])
                db.add(ente)
                await db.flush()
                db.add_all([
                    EnteDominio(dominio="atti.example.it", ente_id=ente.id),
                    User(ente_id=ente.id, username="controllore", origine="LOCALE",
                         password_hash=pw.calcola(PASSWORD), ruoli=[Ruolo.CONTROLLORE]),
                ])  # fmt: skip
                await db.commit()
            await motore.dispose()

        asyncio.run(dati())
        settings = Settings(
            _env_file=None, database_url=url, jwt_secret="x" * 40, cookie_secure=False,
            llm_provider="ollama", llm_model="prova", archivio_dir=cls.cartella.name,
        )  # fmt: skip
        cls.app = create_app(settings)

    @classmethod
    def tearDownClass(cls):
        cls.cartella.cleanup()

    def setUp(self):
        self.c = self.app.test_client()
        r = self.c.post("/api/v1/auth/login", base_url=ENTE, json={"username": "controllore", "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def _carica(self, contenuto: bytes, nome: str):
        return self.c.post(
            f"{API}/controlli", base_url=ENTE, content_type="multipart/form-data",
            data={"titolo": "Determina di prova", "data_adozione": "2026-03-01", "file": (io.BytesIO(contenuto), nome)},
        )  # fmt: skip

    def test_atto_firmato_sbustato(self):
        r = self._carica(busta(PDF), "determina.pdf.p7m")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        atto = r.get_json()["atto"]
        self.assertEqual(atto["file_nome"], "determina.pdf")
        # nell'archivio c'è il documento, non la busta
        originale = self.c.get(f"{API}/atti/{atto['id']}/file", base_url=ENTE)
        self.assertEqual(originale.data, PDF)

    def test_contenuto_diverso_dall_estensione(self):
        r = self._carica(PDF, "determina.docx")
        self.assertEqual(r.status_code, 422)
        self.assertIn("non corrisponde", r.get_json()["detail"])
        self.assertEqual(self._carica(busta(b"testo qualsiasi"), "determina.p7m").status_code, 422)

    def test_formato_non_ammesso(self):
        self.assertEqual(self._carica(b"\x89PNG\r\n\x1a\n", "foto.png").status_code, 415)


if __name__ == "__main__":
    unittest.main()
