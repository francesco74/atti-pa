"""Strumenti di supporto ai test, condivisi tra i componenti."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from common.normattiva import AttoNonTrovato, TestoArticolo, Urn, parse_articolo
from common.odt import nuovo_odt


def crea_odt(paragrafi: list[str], xml_grezzo: bool = False) -> bytes:
    """ODT minimale valido: un paragrafo per elemento (testo semplice o XML se xml_grezzo)."""
    return nuovo_odt(paragrafi, xml_grezzo)


def html_articolo(numero: str, commi: dict[str, str | tuple[str, dict[str, str]]]) -> str:
    """HTML in stile Normattiva. Un comma può avere (alinea, {lettera: testo})."""
    parti = [f'<div class="bodyTesto"><h2 class="article-num-akn">Art. {numero}</h2>']
    parti.append('<div class="art-commi-div-akn">')
    for num, contenuto in commi.items():
        if isinstance(contenuto, tuple):
            alinea, lettere = contenuto
            parti.append(
                f'<div class="art-comma-div-akn"><div class="pointedList-first-akn">'
                f'<span class="comma-num-akn">{num}. </span>{alinea}</div>'
            )
            parti += [
                f'<div class="pointedList-rest-akn">{lett}) {t}</div>'
                for lett, t in lettere.items()
            ]
            parti.append("</div>")
        else:
            parti.append(
                f'<div class="art-comma-div-akn"><span class="comma-num-akn">{num}. </span>'
                f'<span class="art_text_in_comma">{contenuto}</span></div>'
            )
    parti.append("</div></div>")
    return "".join(parti)


@dataclass
class VersioneFinta:
    html: str
    inizio: date | None = None
    fine: date | None = None


@dataclass
class FakeNormattiva:
    """Client Normattiva in memoria: chiave "urn_atto~artN" -> versioni."""

    articoli: dict[str, list[VersioneFinta]] = field(default_factory=dict)
    titoli: dict[str, str] = field(default_factory=dict)
    richieste: list[str] = field(default_factory=list)

    def aggiungi(self, urn_articolo: str, html: str, inizio=None, fine=None, titolo=None):
        self.articoli.setdefault(urn_articolo, []).append(VersioneFinta(html, inizio, fine))
        if titolo:
            self.titoli[Urn.parse(urn_articolo).atto] = titolo

    async def articolo(self, urn, vigenza: date | None = None) -> TestoArticolo:
        u = Urn.parse(urn) if isinstance(urn, str) else urn
        chiave = f"{u.atto}~art{u.articolo}"
        self.richieste.append(f"{chiave}@{vigenza}")
        giorno = vigenza or date.today()
        if len(u.data) == 4:
            # URN con il solo anno: come Normattiva, risolve sull'atto con data completa
            for k in self.articoli:
                ku = Urn.parse(k)
                if (ku.autorita, ku.denominazione, ku.data[:4], ku.numero, ku.articolo) == (
                    u.autorita,
                    u.denominazione,
                    u.data,
                    u.numero,
                    u.articolo,
                ):
                    chiave, u = k, ku
                    break
        for v in self.articoli.get(chiave, []):
            if (v.inizio is None or v.inizio <= giorno) and (v.fine is None or v.fine >= giorno):
                return TestoArticolo(
                    urn=str(u),
                    titolo_atto="",
                    sottotitolo=self.titoli.get(u.atto),
                    denominazione="",
                    data_provvedimento=date.fromisoformat(u.data) if len(u.data) == 10 else None,
                    numero=u.numero,
                    data_gu=None,
                    vigenza_inizio=v.inizio,
                    vigenza_fine=v.fine,
                    html=v.html,
                    articolo=parse_articolo(v.html),
                )
        raise AttoNonTrovato(chiave)

    async def atti_aggiornati(self, da, a):
        return []

    async def close(self):
        pass
