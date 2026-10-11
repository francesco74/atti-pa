import pytest

# Struttura ricalcata sugli esempi della specifica API Normattiva (art. 2 D.L. 180/2008)
ARTICOLO_HTML = """
<div class="bodyTesto">
  <h2 class="preamble-title-akn"></h2>
  <h2 class="article-num-akn" id="art_2">Art. 2</h2>
  <div class="article-heading-akn"> Misure per la qualit&agrave; del sistema universitario</div>
  <div class="art-commi-div-akn">
    <div class="art-comma-div-akn">
      <div>
        <div class="pointedList-first-akn">
          <span class="comma-num-akn">1. </span>A decorrere dall'anno 2009 una quota del fondo di cui
          all'<a href="http://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1993-12-24;537~art5">articolo 5
          della legge 24 dicembre 1993, n. 537</a> &egrave; ripartita prendendo in considerazione: <br>
        </div>
        <div class="pointedList-rest-akn"> a) la qualit&agrave; dell'offerta formativa; <br></div>
        <div class="pointedList-rest-akn"> b) la qualit&agrave; della ricerca scientifica; <br></div>
        <div class="pointedList-rest-akn"> c) l'efficienza delle sedi didattiche. <br></div>
      </div>
    </div>
    <div class="art-comma-div-akn">
      <span class="comma-num-akn">1-bis. </span><span class="art_text_in_comma">Gli incrementi di
      cui al comma 1 sono disposti annualmente. ((6))</span>
    </div>
    <div class="art-comma-div-akn">
      <span class="comma-num-akn">2. </span><span class="art_text_in_comma">Le modalit&agrave; di
      ripartizione sono definite con decreto. <div class="ins-akn" eId="ins_1">((6))</div></span>
    </div>
  </div>
  <div class="art_aggiornamento-akn">
    <div class="art_aggiornamento_title-akn">AGGIORNAMENTO (6)</div>
    <div class="art_aggiornamento_testo-akn">Il <a href="http://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legge:2013-06-21;69">D.L. 69/2013</a> ha disposto...</div>
  </div>
</div>
"""


@pytest.fixture
def articolo_html() -> str:
    return ARTICOLO_HTML


@pytest.fixture
def risposta_atto(articolo_html) -> dict:
    return {
        "code": None,
        "message": None,
        "data": {
            "atto": {
                "titolo": "DECRETO-LEGGE 10 novembre 2008, n. 180",
                "sottoTitolo": "Disposizioni urgenti per il diritto allo studio.\r\n",
                "articoloHtml": articolo_html,
                "tipoProvvedimentoDescrizione": "DECRETO-LEGGE",
                "annoProvvedimento": 2008,
                "meseProvvedimento": 11,
                "giornoProvvedimento": 10,
                "numeroProvvedimento": 180,
                "annoGU": 2008,
                "meseGU": 11,
                "giornoGU": 10,
                "articoloDataInizioVigenza": "20130821",
                "articoloDataFineVigenza": "99999999",
            },
            "lista": None,
        },
        "success": True,
    }
