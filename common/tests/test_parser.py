from atti_common.normattiva import parse_articolo


def test_numero_e_rubrica(articolo_html):
    art = parse_articolo(articolo_html)
    assert art.numero == "2"
    assert art.rubrica == "Misure per la qualità del sistema universitario"


def test_commi(articolo_html):
    art = parse_articolo(articolo_html)
    assert [c.numero for c in art.commi] == ["1", "1-bis", "2"]


def test_lettere_e_alinea(articolo_html):
    comma1 = parse_articolo(articolo_html).comma("1")
    assert comma1.alinea.startswith("A decorrere dall'anno 2009")
    assert [lett.lettera for lett in comma1.lettere] == ["a", "b", "c"]
    assert comma1.lettere[1].testo == "la qualità della ricerca scientifica;"


def test_marcatori_note_rimossi(articolo_html):
    art = parse_articolo(articolo_html)
    assert "((" not in art.comma("1-bis").testo
    assert art.comma("2").testo == "Le modalità di ripartizione sono definite con decreto."


def test_note_aggiornamento_escluse(articolo_html):
    art = parse_articolo(articolo_html)
    assert "AGGIORNAMENTO" not in art.testo()
    # il rinvio presente solo nella nota non va tra i rinvii del testo
    assert art.rinvii == ["urn:nir:stato:legge:1993-12-24;537~art5"]


def test_hash_stabile(articolo_html):
    assert parse_articolo(articolo_html).hash() == parse_articolo(articolo_html).hash()


def test_articolo_comma_unico():
    html = (
        '<div class="bodyTesto"><h2 class="article-num-akn">Art. 7</h2>'
        '<div class="art-commi-div-akn">Il presente decreto entra in vigore il giorno '
        "successivo.</div></div>"
    )
    art = parse_articolo(html)
    assert len(art.commi) == 1
    assert art.commi[0].testo == "Il presente decreto entra in vigore il giorno successivo."
