from datetime import date

import pytest
from atti_common.normattiva import TestoArticolo, parse_articolo


def _crea_testo(
    urn: str,
    contenuto: str,
    sottotitolo: str | None = None,
    inizio: date | None = date(2026, 1, 1),
) -> TestoArticolo:
    html = f'<div class="art-comma-div-akn"><span class="comma-num-akn">1. </span>{contenuto}</div>'
    return TestoArticolo(
        urn=urn,
        titolo_atto="",
        sottotitolo=sottotitolo,
        denominazione="",
        data_provvedimento=None,
        numero="",
        data_gu=None,
        vigenza_inizio=inizio,
        vigenza_fine=None,
        html=html,
        articolo=parse_articolo(html),
    )


@pytest.fixture
def crea_testo():
    return _crea_testo
