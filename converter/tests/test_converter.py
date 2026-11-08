"""Servizio documenti su pa-common: Markdown per la trasparenza (anche da atti firmati .p7m),
PDF scansionati rifiutati senza OCR, conversione con LibreOffice e codici d'errore HTTP.
    cd converter/tests && python test_converter.py
"""

from __future__ import annotations

import io
import shutil
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asn1crypto import cms  # noqa: E402

from main import Settings, create_app  # noqa: E402

CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.3">
 <office:body><office:text><text:h text:outline-level="1">Determinazione</text:h>
 <text:p>Il dirigente determina.</text:p></office:text></office:body></office:document-content>"""


def odt() -> bytes:
    uscita = io.BytesIO()
    with zipfile.ZipFile(uscita, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", CONTENT)
    return uscita.getvalue()


def busta(documento: bytes) -> bytes:
    firmato = cms.SignedData({
        "version": "v1", "digest_algorithms": [], "signer_infos": [],
        "encap_content_info": {"content_type": "data", "content": documento},
    })  # fmt: skip
    return cms.ContentInfo({"content_type": "signed_data", "content": firmato}).dump()


def pdf_scansionato() -> bytes:
    import pymupdf

    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.draw_rect(pymupdf.Rect(50, 50, 500, 700), fill=(0.9, 0.9, 0.9))
    return documento.tobytes()


class Converter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = Settings(_env_file=None, ocr_provider="")  # OCR spento
        cls.c = create_app(settings).test_client()

    def _markdown(self, contenuto: bytes, nome: str):
        return self.c.post("/markdown", data={"file": (io.BytesIO(contenuto), nome)}, content_type="multipart/form-data")

    def test_markdown_anche_da_atto_firmato(self):
        for contenuto, nome in ((odt(), "atto.odt"), (busta(odt()), "atto.odt.p7m")):
            r = self._markdown(contenuto, nome)
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertIn("# Determinazione", r.get_json()["markdown"])

    def test_errori(self):
        r = self._markdown(pdf_scansionato(), "scansione.pdf")
        self.assertEqual(r.status_code, 422)
        self.assertIn("scansione", r.get_json()["detail"])
        self.assertEqual(self._markdown(odt(), "atto.pdf").status_code, 422)  # contenuto diverso
        self.assertEqual(self._markdown(b"x", "atto.exe").status_code, 415)
        self.assertIsNone(self.c.get("/health").get_json()["ocr"])

    @unittest.skipIf(shutil.which("soffice") is None, "LibreOffice non installato")
    def test_converti_in_pdf(self):
        r = self.c.post(
            "/converti?formato=pdf",
            data={"file": (io.BytesIO(b"<html><body><h1>Determinazione</h1></body></html>"), "atto.html")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(self.c.post("/converti?formato=xyz", data={}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
