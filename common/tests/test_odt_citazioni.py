import shutil
import subprocess

import pytest

from atti_common.normattiva.citazioni import citazione_atto, citazione_riferimento
from atti_common.odt import (
    OdtNonValido,
    compila,
    estrai_segnaposto,
    estrai_testo,
    segnaposto_non_compilati,
)
from atti_common.testing import crea_odt


def test_citazioni():
    urn = "urn:nir:stato:decreto.legislativo:2023-03-31;36"
    assert citazione_atto(urn) == "D.Lgs. 31 marzo 2023, n. 36"
    assert citazione_atto(urn, abbreviata=False) == "decreto legislativo 31 marzo 2023, n. 36"
    assert (
        citazione_riferimento(urn, "50", "1", "b")
        == "art. 50, comma 1, lett. b), del D.Lgs. 31 marzo 2023, n. 36"
    )
    assert citazione_atto("urn:nir:presidente.repubblica:decreto:2000-12-28;445").startswith(
        "D.P.R. 28 dicembre 2000"
    )


def test_segnaposto_spezzati_da_span():
    # LibreOffice spezza spesso i segnaposto in più span
    odt = crea_odt(
        [
            'Oggetto: {{ <text:span text:style-name="T1">oggetto</text:span> }}',
            "Importo: {{importo}} euro, CIG {{cig}}",
            "Di nuovo {{importo}}",
        ],
        xml_grezzo=True,
    )
    assert estrai_segnaposto(odt) == ["oggetto", "importo", "cig"]


def test_compila_e_righe_multiple():
    odt = crea_odt(["Premesso che {{premesse}}", "CIG: {{cig}}"])
    risultato = compila(odt, {"premesse": "prima riga\nseconda riga", "cig": ""})
    testo = estrai_testo(risultato)
    assert "Premesso che prima riga\nseconda riga" in testo
    assert "CIG: [[cig]]" in testo
    assert segnaposto_non_compilati(testo) == ["cig"]


def test_file_non_odt():
    with pytest.raises(OdtNonValido):
        estrai_segnaposto(b"non sono un odt")


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice non installato")
def test_odt_compilato_apribile_da_libreoffice(tmp_path):
    odt = compila(crea_odt(["Determina: {{oggetto}}"]), {"oggetto": "Acquisto toner"})
    sorgente = tmp_path / "atto.odt"
    sorgente.write_bytes(odt)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(sorgente)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    assert (tmp_path / "atto.pdf").stat().st_size > 0
