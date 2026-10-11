from datetime import date

import httpx
import pytest
import respx

from atti_common.normattiva import AttoNonTrovato, NormattivaClient, RisultatoAmbiguo

BASE = "https://test.normattiva/t/normattiva.api"
URL_URN = BASE + "/bff-opendata/v1/api/v1/atto/dettaglio-atto-urn"


@pytest.fixture
def client():
    return NormattivaClient(base_url=BASE, tentativi=1)


@respx.mock
async def test_articolo_vigente(client, risposta_atto):
    route = respx.post(URL_URN).mock(return_value=httpx.Response(200, json=risposta_atto))

    testo = await client.articolo(
        "urn:nir:stato:decreto.legge:2008-11-10;180~art2", vigenza=date(2026, 1, 1)
    )

    inviato = route.calls.last.request.read().decode()
    assert "!vig=2026-01-01" in inviato
    assert testo.vigenza_inizio == date(2013, 8, 21)
    assert testo.vigenza_fine is None
    assert testo.in_vigore_al(date(2026, 1, 1))
    assert not testo.in_vigore_al(date(2010, 1, 1))
    assert testo.articolo.comma("1").lettere[0].lettera == "a"
    assert testo.data_provvedimento == date(2008, 11, 10)


@respx.mock
async def test_risultato_ambiguo(client, risposta_atto):
    atto = risposta_atto["data"]["atto"]
    ambigua = {"data": {"atto": None, "lista": [atto, atto]}, "success": True}
    respx.post(URL_URN).mock(return_value=httpx.Response(200, json=ambigua))

    with pytest.raises(RisultatoAmbiguo) as exc:
        await client.articolo("urn:nir:stato:legge:2001-12-28;448~art2")
    assert len(exc.value.candidati) == 2


@respx.mock
async def test_non_trovato(client):
    respx.post(URL_URN).mock(return_value=httpx.Response(404, json={"code": "404"}))
    with pytest.raises(AttoNonTrovato):
        await client.articolo("urn:nir:stato:legge:2001-12-28;448~art2")


async def test_articolo_obbligatorio(client):
    with pytest.raises(ValueError):
        await client.articolo("urn:nir:stato:legge:1990-08-07;241")
