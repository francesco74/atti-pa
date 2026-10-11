import shutil

import httpx
import pytest

from atti_common.testing import crea_odt
from documenti.main import app

pytestmark = pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice non installato")


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=180
    ) as c:
        yield c


async def test_odt_in_pdf_e_pdfa(client):
    odt = crea_odt(["Determinazione dirigenziale di prova"])
    for formato in ("pdf", "pdfa"):
        r = await client.post(
            "/converti", params={"formato": formato}, files={"file": ("atto.odt", odt)}
        )
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")


async def test_formato_non_ammesso(client):
    r = await client.post("/converti", files={"file": ("virus.exe", b"MZ")})
    assert r.status_code == 415
