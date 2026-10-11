from atti_common.estrazione import estrai_riferimenti


def _sintesi(testo):
    return [(r.urn_atto, r.articolo, r.comma, r.lettera) for r in estrai_riferimenti(testo)]


def test_citazione_completa():
    t = "Visto l'art. 50, comma 1, lett. b), del D.Lgs. 31 marzo 2023, n. 36;"
    assert _sintesi(t) == [("urn:nir:stato:decreto.legislativo:2023-03-31;36", "50", "1", "b")]


def test_forma_estesa_e_abbreviata():
    t = (
        "Visto l'articolo 107 del decreto legislativo 18 agosto 2000, n. 267 e la "
        "L. 241/1990 nonché il D.P.R. n. 445/2000."
    )
    assert _sintesi(t) == [
        ("urn:nir:stato:decreto.legislativo:2000-08-18;267", "107", None, None),
        ("urn:nir:stato:legge:1990;241", None, None, None),
        ("urn:nir:presidente.repubblica:decreto:2000;445", None, None, None),
    ]


def test_piu_articoli():
    t = "ai sensi degli artt. 183 e 184 del D.Lgs. n. 267/2000"
    assert [r.articolo for r in estrai_riferimenti(t)] == ["183", "184"]


def test_alias_tuel_e_suffissi():
    t = "Visto l'art. 147 bis del TUEL e l'art. 6-bis della legge 7 agosto 1990, n. 241"
    assert _sintesi(t) == [
        ("urn:nir:stato:decreto.legislativo:2000-08-18;267", "147-bis", None, None),
        ("urn:nir:stato:legge:1990-08-07;241", "6-bis", None, None),
    ]


def test_decreto_legge_e_anno_con_del():
    t = "l'art. 1, comma 2, del D.L. n. 76 del 2020"
    assert _sintesi(t) == [("urn:nir:stato:decreto.legge:2020;76", "1", "2", None)]


def test_nessun_falso_positivo():
    t = "Il CIG è Z1234/2024 e il protocollo n. 15/2026 del Comune."
    assert estrai_riferimenti(t) == []
