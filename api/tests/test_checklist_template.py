from atti_common.testing import crea_odt

CHECKLIST = {
    "codice": "affidamento-base",
    "titolo": "Affidamento diretto",
    "tipologia_atto": "AFFIDAMENTO_DIRETTO",
    "elementi": [
        {"titolo": "CIG", "regola": "L'atto riporta il CIG."},
        {
            "titolo": "Motivazione",
            "regola": "È motivata la scelta dell'operatore.",
            "riferimenti": ["urn:nir:stato:decreto.legislativo:2023-03-31;36~art50"],
        },
    ],
}


async def test_checklist_versionata(client, login):
    admin = await login("admin")
    r = await client.post("/api/v1/checklists", json=CHECKLIST, headers=admin)
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["codice"] == "AFFIDAMENTO-BASE"
    assert [e["titolo"] for e in v1["elementi"]] == ["CIG", "Motivazione"]

    modifica = {
        **CHECKLIST,
        "elementi": CHECKLIST["elementi"]
        + [{"titolo": "Rotazione", "regola": "È rispettato il principio di rotazione."}],
    }
    del modifica["codice"]
    r = await client.put("/api/v1/checklists/codice/AFFIDAMENTO-BASE", json=modifica, headers=admin)
    assert r.status_code == 200
    assert r.json()["versione"] == 2

    attive = (await client.get("/api/v1/checklists", headers=admin)).json()
    assert [(c["versione"], len(c["elementi"])) for c in attive] == [(2, 3)]
    tutte = (await client.get("/api/v1/checklists", params={"tutte": True}, headers=admin)).json()
    assert len(tutte) == 2

    # la versione 1 resta consultabile per le verifiche già fatte
    r = await client.get(f"/api/v1/checklists/{v1['id']}", headers=admin)
    assert r.json()["attiva"] is False


async def test_checklist_solo_admin(client, login):
    r = await client.post("/api/v1/checklists", json=CHECKLIST, headers=await login("mrossi"))
    assert r.status_code == 403


async def test_checklist_codice_duplicato_e_tipologia(client, login):
    admin = await login("admin")
    await client.post("/api/v1/checklists", json=CHECKLIST, headers=admin)
    assert (
        await client.post("/api/v1/checklists", json=CHECKLIST, headers=admin)
    ).status_code == 409
    errata = {**CHECKLIST, "codice": "altro", "tipologia_atto": "NON_ESISTE"}
    assert (await client.post("/api/v1/checklists", json=errata, headers=admin)).status_code == 422


async def _carica_template(client, headers, contenuto, nome="Affidamento standard"):
    return await client.post(
        "/api/v1/templates",
        data={"nome": nome, "tipologia_atto": "AFFIDAMENTO_DIRETTO"},
        files={"file": ("affidamento.odt", contenuto, "application/vnd.oasis.opendocument.text")},
        headers=headers,
    )


async def test_template_campi_e_versioni(client, login):
    admin = await login("admin")
    odt = crea_odt(
        [
            "OGGETTO: {{oggetto}}",
            "{{riferimenti_normativi}}",
            "Premesso che {{premesse}}",
            "Operatore: {{operatore_economico}} - CIG {{cig}} - importo {{importo}}",
        ]
    )
    r = await _carica_template(client, admin, odt)
    assert r.status_code == 201, r.text
    t1 = r.json()
    assert [c["nome"] for c in t1["campi_json"]] == [
        "premesse",
        "operatore_economico",
        "cig",
        "importo",
    ]
    assert t1["campi_json"][0]["tipo"] == "testo_lungo"

    r = await client.put(
        f"/api/v1/templates/{t1['id']}/campi",
        json={
            "campi": [
                {"nome": "cig", "etichetta": "Codice CIG", "aiuto": "10 caratteri"},
                {"nome": "importo", "etichetta": "Importo netto", "tipo": "importo"},
            ]
        },
        headers=admin,
    )
    assert r.status_code == 200
    assert r.json()["campi_json"][1]["tipo"] == "importo"

    r = await _carica_template(client, admin, odt)
    assert r.json()["versione"] == 2
    attivi = (await client.get("/api/v1/templates", headers=admin)).json()
    assert [t["versione"] for t in attivi] == [2]

    r = await client.get(f"/api/v1/templates/{t1['id']}/file", headers=admin)
    assert r.content == odt


async def test_template_non_valido(client, login):
    admin = await login("admin")
    assert (await _carica_template(client, admin, b"ciao")).status_code == 422
    senza_campi = crea_odt(["Testo fisso"])
    assert (await _carica_template(client, admin, senza_campi)).status_code == 422


async def test_campo_inesistente(client, login):
    admin = await login("admin")
    t = (await _carica_template(client, admin, crea_odt(["{{cig}}"]))).json()
    r = await client.put(
        f"/api/v1/templates/{t['id']}/campi",
        json={"campi": [{"nome": "inventato", "etichetta": "X"}]},
        headers=admin,
    )
    assert r.status_code == 422
