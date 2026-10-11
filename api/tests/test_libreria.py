from datetime import date

import pytest

from atti_common.testing import FakeNormattiva, html_articolo

URN_CODICE = "urn:nir:stato:decreto.legislativo:2023-03-31;36"


@pytest.fixture
def normattiva(app):
    fake = FakeNormattiva()
    fake.aggiungi(
        f"{URN_CODICE}~art1",
        html_articolo("1", {"1": "Principio del risultato."}),
        titolo="Codice dei contratti pubblici",
    )
    fake.aggiungi(
        f"{URN_CODICE}~art50",
        html_articolo(
            "50",
            {
                "1": (
                    "Le stazioni appaltanti procedono:",
                    {
                        "a": "affidamento diretto per lavori sotto 150.000 euro;",
                        "b": "affidamento diretto per servizi sotto 140.000 euro;",
                    },
                )
            },
        ),
        inizio=date(2023, 7, 1),
        fine=date(2024, 12, 30),
    )
    fake.aggiungi(
        f"{URN_CODICE}~art50",
        html_articolo(
            "50",
            {
                "1": (
                    "Le stazioni appaltanti procedono:",
                    {
                        "a": "affidamento diretto per lavori sotto 150.000 euro;",
                        "b": "affidamento diretto per servizi sotto 140.000 euro, anche senza consultazione;",
                    },
                )
            },
        ),
        inizio=date(2024, 12, 31),
    )
    app.state.normattiva = fake
    return fake


async def test_aggiungi_norma(client, login, normattiva):
    h = await login("mrossi")
    r = await client.post(
        "/api/v1/norme", json={"tipo": "d.lgs.", "data": "2023-03-31", "numero": "36"}, headers=h
    )
    assert r.status_code == 201, r.text
    assert r.json()["citazione"] == "D.Lgs. 31 marzo 2023, n. 36"
    assert r.json()["titolo"] == "Codice dei contratti pubblici"

    r = await client.get("/api/v1/norme", headers=h, params={"q": "36"})
    assert [n["urn"] for n in r.json()] == [URN_CODICE]


async def test_norma_inesistente(client, login, normattiva):
    h = await login("mrossi")
    r = await client.post(
        "/api/v1/norme", json={"urn": "urn:nir:stato:legge:1999-01-01;999"}, headers=h
    )
    assert r.status_code == 404


async def test_articolo_per_data_e_cache(client, login, normattiva):
    h = await login("mrossi")
    url = "/api/v1/norme/articolo"

    r = await client.get(
        url, params={"urn": f"{URN_CODICE}~art50", "data": "2024-06-01"}, headers=h
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["vigenza_fine"] == "2024-12-30"
    assert corpo["citazione_atto"] == "D.Lgs. 31 marzo 2023, n. 36"
    lettera_b = corpo["struttura"]["commi"][0]["lettere"][1]["testo"]
    assert "consultazione" not in lettera_b

    r = await client.get(
        url, params={"urn": f"{URN_CODICE}~art50", "data": "2026-10-12"}, headers=h
    )
    assert "consultazione" in r.json()["struttura"]["commi"][0]["lettere"][1]["testo"]

    # stessa data già in cache: nessuna nuova chiamata a Normattiva
    prima = len(normattiva.richieste)
    await client.get(url, params={"urn": f"{URN_CODICE}~art50", "data": "2024-01-15"}, headers=h)
    assert len(normattiva.richieste) == prima


async def test_riferimenti_personali_e_condivisi(client, login, normattiva):
    h_rossi = await login("mrossi")
    h_admin = await login("admin")

    r = await client.post(
        "/api/v1/riferimenti",
        json={
            "urn_atto": URN_CODICE,
            "articolo": "50",
            "comma": "1",
            "lettera": "b",
            "tipologie_atto": ["AFFIDAMENTO_DIRETTO"],
        },
        headers=h_rossi,
    )
    assert r.status_code == 201, r.text
    assert r.json()["citazione"] == "art. 50, comma 1, lett. b), del D.Lgs. 31 marzo 2023, n. 36"

    # un redattore non può condividere
    r = await client.post(
        "/api/v1/riferimenti",
        json={"urn_atto": URN_CODICE, "articolo": "50", "condiviso": True},
        headers=h_rossi,
    )
    assert r.status_code == 403

    r = await client.post(
        "/api/v1/riferimenti",
        json={"urn_atto": URN_CODICE, "articolo": "50", "comma": "1", "condiviso": True},
        headers=h_admin,
    )
    assert r.status_code == 201

    visti_da_rossi = (await client.get("/api/v1/riferimenti", headers=h_rossi)).json()
    visti_da_admin = (await client.get("/api/v1/riferimenti", headers=h_admin)).json()
    assert len(visti_da_rossi) == 2
    assert len(visti_da_admin) == 1  # il riferimento personale di Rossi non è visibile

    per_tipologia = await client.get(
        "/api/v1/riferimenti", params={"tipologia": "IMPEGNO_SPESA"}, headers=h_rossi
    )
    assert len(per_tipologia.json()) == 1  # resta solo quello senza tipologie


async def test_riferimento_a_lettera_inesistente(client, login, normattiva):
    h = await login("mrossi")
    r = await client.post(
        "/api/v1/riferimenti",
        json={"urn_atto": URN_CODICE, "articolo": "50", "comma": "1", "lettera": "z"},
        headers=h,
    )
    assert r.status_code == 422


async def test_elimina_riferimento_altrui_vietato(client, login, normattiva):
    h_rossi = await login("mrossi")
    h_bianchi = await login("lbianchi")
    rif = (
        await client.post(
            "/api/v1/riferimenti", json={"urn_atto": URN_CODICE, "articolo": "50"}, headers=h_rossi
        )
    ).json()
    r = await client.delete(f"/api/v1/riferimenti/{rif['id']}", headers=h_bianchi)
    assert r.status_code == 403
    r = await client.delete(f"/api/v1/riferimenti/{rif['id']}", headers=h_rossi)
    assert r.status_code == 204


async def test_tipologie(client, login):
    h = await login("mrossi")
    r = await client.get("/api/v1/tipologie", headers=h)
    assert any(t["codice"] == "AFFIDAMENTO_DIRETTO" for t in r.json())


async def test_storico_aggiornamenti_solo_admin(client, login):
    assert (
        await client.get("/api/v1/norme/aggiornamenti", headers=await login("mrossi"))
    ).status_code == 403
    assert (
        await client.get("/api/v1/norme/aggiornamenti", headers=await login("admin"))
    ).status_code == 200
