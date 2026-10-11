from datetime import date

import pytest

from app.normattiva import Urn


def test_costruzione_da_abbreviazione():
    u = Urn.per_tipo("D.Lgs.", date(2023, 3, 31), 36, articolo=50)
    assert str(u) == "urn:nir:stato:decreto.legislativo:2023-03-31;36~art50"


def test_dpr_usa_autorita_corretta():
    u = Urn.per_tipo("DPR", "2000-12-28", 445)
    assert u.atto == "urn:nir:presidente.repubblica:decreto:2000-12-28;445"


def test_vigenza_e_originale():
    base = Urn.per_tipo("legge", "1990-08-07", 241, articolo=3)
    assert str(base.alla_data(date(2026, 1, 1))).endswith("~art3!vig=2026-01-01")


@pytest.mark.parametrize(
    "valore",
    [
        "urn:nir:stato:decreto.legge:2008-11-10;180~art2",
        "urn:nir:stato:legge:2001-12-28;448~art2!vig=2020-01-01",
        "urn:nir:stato:legge:1990;241",
        "urn:nir:stato:decreto.legislativo:2023-03-31;36:1~art3",
        "urn:nir:stato:legge:1988-08-23;400~art13-bis@originale",
    ],
)
def test_roundtrip(valore):
    assert str(Urn.parse(valore)) == valore


def test_parse_campi():
    u = Urn.parse("urn:nir:stato:decreto.legislativo:2023-03-31;36:1~art3!vig=2025-01-01")
    assert u.allegato == "1"
    assert u.articolo == "3"
    assert u.vigenza == date(2025, 1, 1)


def test_urn_non_valida():
    with pytest.raises(ValueError):
        Urn.parse("d.lgs. 36/2023")


def test_tipo_non_supportato():
    with pytest.raises(ValueError):
        Urn.per_tipo("circolare", "2024-01-01", 1)
