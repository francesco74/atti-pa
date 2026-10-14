"""Estrazione deterministica dei riferimenti normativi dal testo di un atto.

Riconosce le forme di citazione più comuni negli atti degli enti locali, ad esempio:
    art. 50, comma 1, lett. b), del D.Lgs. 31 marzo 2023, n. 36
    articolo 107 del decreto legislativo 18 agosto 2000, n. 267
    artt. 183 e 184 del D.Lgs. n. 267/2000
    L. 241/1990 · legge 7 agosto 1990, n. 241 · D.P.R. 445/2000 · art. 147-bis del TUEL

e le norme inserite manualmente (regolamenti interni, altre fonti) tramite le
denominazioni indicate per ciascuna, es. "art. 12 del Regolamento di contabilità".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from common.normattiva.citazioni import MESI
from common.normattiva.urn import Urn

_SUFFISSI = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)"
_NUM_ART = rf"\d+(?:\s?-?\s?{_SUFFISSI})?"

_TIPI: list[tuple[str, str]] = [
    (r"d\.\s?lgs\.?|d\.\s?lg\.?|dlgs\.?|decreto\s+legislativo", "decreto legislativo"),
    (r"d\.\s?l\.|decreto[\s-]+legge", "decreto-legge"),
    (r"d\.\s?p\.\s?r\.?|dpr|decreto\s+del\s+presidente\s+della\s+repubblica",
     "decreto del presidente della repubblica"),
    (r"d\.\s?p\.\s?c\.\s?m\.?|dpcm|decreto\s+del\s+presidente\s+del\s+consiglio\s+dei\s+ministri",
     "decreto del presidente del consiglio dei ministri"),
    (r"r\.\s?d\.|regio\s+decreto", "regio decreto"),
    (r"l\.\s?cost\.|legge\s+costituzionale", "legge costituzionale"),
    (r"l\.|legge", "legge"),
]  # fmt: skip

_TIPO = "|".join(f"(?P<t{i}>{p})" for i, (p, _) in enumerate(_TIPI))
_MESE = "|".join(MESI)

_ATTO = re.compile(
    rf"(?<![\w.])(?:{_TIPO})\s*"
    rf"(?:"
    rf"(?P<giorno>\d{{1,2}})(?:°|º)?\s+(?P<mese>{_MESE})\s+(?P<anno>\d{{4}}),?\s*n\.?\s*(?P<numero>\d+)"
    rf"|n\.?\s*(?P<numero2>\d+)\s*/\s*(?P<anno2>\d{{4}})"
    rf"|n\.?\s*(?P<numero4>\d+)\s+del\s+(?P<anno4>\d{{4}})"
    rf"|(?P<numero3>\d+)\s*/\s*(?P<anno3>\d{{4}})"
    rf")",
    re.IGNORECASE,
)

# Denominazioni consolidate che sostituiscono gli estremi dell'atto
_ALIAS = re.compile(
    r"(?<!\w)(?P<alias>T\.?U\.?E\.?L\.?|testo\s+unico\s+(?:delle\s+leggi\s+sull'ordinamento\s+degli\s+)?enti\s+locali)(?!\w)",
    re.IGNORECASE,
)
_ALIAS_URN = "urn:nir:stato:decreto.legislativo:2000-08-18;267"

_ARTICOLO_PRIMA = re.compile(
    rf"(?:art(?:icol[oi]|t)?\.?)\s*(?P<articoli>{_NUM_ART}(?:\s*(?:,|e|ed)\s*{_NUM_ART})*)"
    r"(?:,?\s*(?:comma|commi|co\.|c\.)\s*(?P<comma>\d+(?:\s?-?\s?(?:bis|ter|quater|quinquies))?))?"
    r"(?:,?\s*(?:lettera|lett\.|let\.)\s*(?P<lettera>[a-z]{1,2}(?:-?(?:bis|ter|quater))?)\)?)?"
    r",?\s*(?:del(?:la|lo|l['’])?|di\s+cui\s+al(?:la|lo|l['’])?|d\.?)?"
    r"(?:\s*(?:vigente|citat[oa]|predett[oa]|richiamat[oa]))?\s*$",
    re.IGNORECASE,
)

_MESI_NUM = {m: i + 1 for i, m in enumerate(MESI)}


@dataclass
class RiferimentoEstratto:
    testo: str  # porzione di testo riconosciuta
    inizio: int
    fine: int
    tipo: str  # tipo di atto normalizzato
    anno: str
    numero: str
    data: str | None  # yyyy-mm-dd se presente nel testo
    articolo: str | None = None
    comma: str | None = None
    lettera: str | None = None
    urn: str | None = None  # norme manuali: URN nota, riconosciuta dalla denominazione

    @property
    def urn_atto(self) -> str:
        """URN dell'atto: completa se nel testo c'è la data, altrimenti con il solo anno."""
        if self.urn:
            return self.urn
        return Urn.per_tipo(self.tipo, self.data or self.anno, self.numero).atto

    def to_dict(self) -> dict:
        d = asdict(self)
        d["urn_atto"] = self.urn_atto
        return d


def _normalizza_articolo(valore: str) -> str:
    """ "147 bis", "147bis", "147 - bis" -> "147-bis"."""
    return re.sub(rf"(\d+)\s*-?\s*({_SUFFISSI})", r"\1-\2", valore.strip().lower())


def _tipo(m: re.Match) -> str:
    for i, (_, nome) in enumerate(_TIPI):
        if m.group(f"t{i}"):
            return nome
    raise ValueError("tipo non riconosciuto")


def _regex_denominazione(denominazione: str) -> re.Pattern | None:
    """Denominazione come espressione regolare: maiuscole, spazi e punti indifferenti."""
    parole = denominazione.split()
    if not parole:
        return None
    corpo = r"\s+".join(re.escape(p).replace(r"\.", r"\.\s*") for p in parole)
    return re.compile(rf"(?<!\w){corpo}(?!\w)", re.IGNORECASE)


def _norme_manuali(
    testo: str, norme: list[tuple[str, list[str]]]
) -> list[tuple[int, int, str, str, str, str | None, str | None]]:
    """Citazioni delle norme manuali; a parità di posizione vince la denominazione più lunga."""
    candidati = []
    for urn, denominazioni in norme:
        u = Urn.parse(urn)
        for denominazione in denominazioni:
            regex = _regex_denominazione(denominazione)
            if regex is None:
                continue
            for m in regex.finditer(testo):
                fine = m.start() + len(m.group().rstrip())
                candidati.append((m.start(), fine, "manuale", u.data[:4], u.numero, u.data, urn))
    candidati.sort(key=lambda c: (c[0], c[0] - c[1]))
    scelti: list[tuple] = []
    for c in candidati:
        if not scelti or c[0] >= scelti[-1][1]:
            scelti.append(c)
    return scelti


def _atti(
    testo: str, norme_manuali: list[tuple[str, list[str]]] | None = None
) -> list[tuple[int, int, str, str, str, str | None, str | None]]:
    manuali = _norme_manuali(testo, norme_manuali or [])
    trovati = []
    for m in _ATTO.finditer(testo):
        if m.group("numero"):
            anno, numero = m.group("anno"), m.group("numero")
            mese = _MESI_NUM[m.group("mese").lower()]
            data = f"{anno}-{mese:02d}-{int(m.group('giorno')):02d}"
        else:
            numero = m.group("numero2") or m.group("numero3") or m.group("numero4")
            anno = m.group("anno2") or m.group("anno3") or m.group("anno4")
            data = None
        trovati.append((m.start(), m.end(), _tipo(m), anno, numero, data, None))
    for m in _ALIAS.finditer(testo):
        trovati.append(
            (m.start(), m.end(), "decreto legislativo", "2000", "267", "2000-08-18", None)
        )
    # una citazione dentro la denominazione di una norma manuale (es. "Regolamento ...
    # approvato ai sensi della L. 241/1990") resta parte della norma manuale
    trovati = [t for t in trovati if not any(t[0] < m[1] and m[0] < t[1] for m in manuali)]
    return sorted(trovati + manuali)


def estrai_riferimenti(
    testo: str, norme_manuali: list[tuple[str, list[str]]] | None = None
) -> list[RiferimentoEstratto]:
    """Riferimenti normativi nel testo; `norme_manuali` è [(urn, denominazioni)]."""
    risultati: list[RiferimentoEstratto] = []
    for inizio, fine, tipo, anno, numero, data, urn in _atti(testo, norme_manuali):
        # cerca la parte "art. X, comma Y, lett. z) del" immediatamente prima dell'atto
        finestra_inizio = max(0, inizio - 160)
        prima = testo[finestra_inizio:inizio]
        m = _ARTICOLO_PRIMA.search(prima)
        if m:
            articoli = re.split(r"\s*(?:,|\be\b|\bed\b)\s*", m.group("articoli"))
            articoli = [_normalizza_articolo(a) for a in articoli if a.strip()]
            singolo = len(articoli) == 1
            inizio_rif = finestra_inizio + m.start()
            for art in articoli:
                risultati.append(
                    RiferimentoEstratto(
                        testo=testo[inizio_rif:fine],
                        inizio=inizio_rif,
                        fine=fine,
                        tipo=tipo,
                        anno=anno,
                        numero=numero,
                        data=data,
                        articolo=art,
                        comma=_normalizza_articolo(m.group("comma"))
                        if singolo and m.group("comma")
                        else None,
                        lettera=m.group("lettera").lower()
                        if singolo and m.group("lettera")
                        else None,
                        urn=urn,
                    )
                )
        else:
            risultati.append(
                RiferimentoEstratto(
                    testo=testo[inizio:fine],
                    inizio=inizio,
                    fine=fine,
                    tipo=tipo,
                    anno=anno,
                    numero=numero,
                    data=data,
                    urn=urn,
                )
            )
    return risultati
