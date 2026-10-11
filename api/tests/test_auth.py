from ldap3 import MOCK_SYNC, OFFLINE_AD_2012_R2, Connection, Server

from atti_api.auth.ldap import LdapAuthenticator, ruoli_da_gruppi
from atti_api.auth.token import COOKIE
from atti_common.config import Settings


async def test_login_e_me(client):
    r = await client.post("/api/v1/auth/login", json={"username": "mrossi", "password": "segreta"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["utente"]["ruoli"] == ["REDATTORE"]
    assert corpo["utente"]["nome_completo"] == "Mario Rossi"
    assert COOKIE in r.cookies

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {corpo['token']}"})
    assert r.status_code == 200
    assert r.json()["username"] == "mrossi"


async def test_cookie_basta_per_autenticarsi(client):
    await client.post("/api/v1/auth/login", json={"username": "mrossi", "password": "segreta"})
    r = await client.get("/api/v1/auth/me")  # il client conserva il cookie
    assert r.status_code == 200


async def test_credenziali_errate(client):
    r = await client.post("/api/v1/auth/login", json={"username": "mrossi", "password": "no"})
    assert r.status_code == 401


async def test_utente_senza_gruppi_non_abilitato(client):
    r = await client.post(
        "/api/v1/auth/login", json={"username": "estraneo", "password": "segreta"}
    )
    assert r.status_code == 403


async def test_token_mancante_o_falso(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401


async def test_secondo_login_aggiorna_senza_duplicare(client, login):
    h1 = await login("mrossi")
    h2 = await login("mrossi")
    id1 = (await client.get("/api/v1/auth/me", headers=h1)).json()["id"]
    id2 = (await client.get("/api/v1/auth/me", headers=h2)).json()["id"]
    assert id1 == id2


async def test_auth_disattivata_usa_utente_locale(app, client):
    app.state.settings.auth_enabled = False
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert set(r.json()["ruoli"]) == {"REDATTORE", "CONTROLLORE", "ADMIN"}


def test_ruoli_da_gruppi_cn_e_dn():
    s = Settings(
        ldap_gruppo_redattori="atti-pa-redattori",
        ldap_gruppo_controllori="CN=Controllo Atti,OU=Gruppi,DC=ente,DC=local",
        ldap_gruppo_admin="",
    )
    gruppi = [
        "CN=ATTI-PA-Redattori,OU=Gruppi,DC=ente,DC=local",
        "cn=controllo atti,ou=gruppi,dc=ente,dc=local",
        "CN=Altro,DC=ente,DC=local",
    ]
    assert ruoli_da_gruppi(gruppi, s) == ["REDATTORE", "CONTROLLORE"]


# --- Flusso LDAP reale su server simulato (ldap3 MOCK_SYNC) ---------------------------

DN_UTENTE = "CN=Mario Rossi,OU=Utenti,DC=ente,DC=local"


class MockAuthenticator(LdapAuthenticator):
    def _bind(self, username, password):
        server = Server("mock-ad", get_info=OFFLINE_AD_2012_R2)
        conn = Connection(server, user=DN_UTENTE, password=password, client_strategy=MOCK_SYNC)
        conn.strategy.add_entry(
            DN_UTENTE,
            {
                "objectClass": ["top", "person", "user"],
                "objectCategory": "person",
                "sAMAccountName": "MRossi",
                "displayName": "Mario Rossi",
                "mail": "m.rossi@ente.it",
                "department": "Ragioneria",
                "memberOf": ["CN=ATTI-PA-Redattori,OU=Gruppi,DC=ente,DC=local"],
                "userPassword": "segreta",
            },
        )
        return conn if conn.bind() else None


def test_autenticazione_ldap_simulata():
    auth = MockAuthenticator(Settings(ldap_base_dn="DC=ente,DC=local"))
    utente = auth.autentica("MRossi", "segreta")
    assert utente.username == "mrossi"
    assert utente.ufficio == "Ragioneria"
    assert utente.gruppi == ["CN=ATTI-PA-Redattori,OU=Gruppi,DC=ente,DC=local"]
    assert auth.autentica("MRossi", "sbagliata") is None


def test_input_pericolosi_rifiutati_senza_bind():
    auth = MockAuthenticator(Settings())
    assert auth.autentica("mrossi", "") is None  # niente bind anonimo
    assert auth.autentica("*)(sAMAccountName=*", "x") is None
    assert auth.autentica("mrossi@altro.dominio", "x") is None
