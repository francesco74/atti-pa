"""Costruzione e parsing delle URN NIR usate da Normattiva.

Formato (specifica API OpenData):
    urn:nir:<autorita>:<denominazione>:<estremi>[<art>][<versione>]
    estremi  ::= yyyy-mm-dd;numero | yyyy;numero
    art      ::= ~art<n> | :<allegato>~art<n>
    versione ::= @originale | !vig=yyyy-mm-dd
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

# Denominazione leggibile -> (autorità, denominazione URN)
TIPI_ATTO: dict[str, tuple[str, str]] = {
    "legge": ("stato", "legge"),
    "legge costituzionale": ("stato", "legge.costituzionale"),
    "decreto legislativo": ("stato", "decreto.legislativo"),
    "decreto-legge": ("stato", "decreto.legge"),
    "decreto legge": ("stato", "decreto.legge"),
    "decreto del presidente della repubblica": ("presidente.repubblica", "decreto"),
    "decreto del presidente del consiglio dei ministri": (
        "presidente.consiglio.ministri",
        "decreto",
    ),
    "regio decreto": ("stato", "regio.decreto"),
    "costituzione": ("stato", "costituzione"),
}

# Abbreviazioni ricorrenti negli atti amministrativi
ABBREVIAZIONI: dict[str, str] = {
    "l.": "legge",
    "d.lgs.": "decreto legislativo",
    "d.lgs": "decreto legislativo",
    "dlgs": "decreto legislativo",
    "d.l.": "decreto-legge",
    "dl": "decreto-legge",
    "d.p.r.": "decreto del presidente della repubblica",
    "dpr": "decreto del presidente della repubblica",
    "d.p.c.m.": "decreto del presidente del consiglio dei ministri",
    "dpcm": "decreto del presidente del consiglio dei ministri",
    "r.d.": "regio decreto",
}

_URN_RE = re.compile(
    r"^urn:nir:(?P<autorita>[a-z.]+):(?P<denominazione>[a-z.]+):"
    r"(?P<data>\d{4}(?:-\d{2}-\d{2})?);(?P<numero>[\w-]+)"
    r"(?::(?P<allegato>\d+))?"
    r"(?:~art(?P<articolo>[\w-]+))?"
    r"(?P<versione>@originale|!vig=\d{4}-\d{2}-\d{2})?$"
)


@dataclass(frozen=True)
class Urn:
    autorita: str
    denominazione: str
    data: str  # "yyyy-mm-dd" oppure "yyyy"
    numero: str
    articolo: str | None = None
    allegato: str | None = None
    vigenza: date | None = None
    originale: bool = False

    @classmethod
    def per_tipo(
        cls,
        tipo: str,
        data: date | str,
        numero: int | str,
        articolo: int | str | None = None,
    ) -> Urn:
        """Costruisce una URN da tipo leggibile o abbreviato (es. "d.lgs.", "legge")."""
        chiave = tipo.strip().lower()
        chiave = ABBREVIAZIONI.get(chiave, chiave)
        if chiave not in TIPI_ATTO:
            raise ValueError(f"Tipo di atto non supportato: {tipo!r}")
        autorita, denominazione = TIPI_ATTO[chiave]
        data_str = data.isoformat() if isinstance(data, date) else data
        return cls(
            autorita=autorita,
            denominazione=denominazione,
            data=data_str,
            numero=str(numero),
            articolo=str(articolo) if articolo is not None else None,
        )

    @classmethod
    def parse(cls, valore: str) -> Urn:
        m = _URN_RE.match(valore.strip())
        if not m:
            raise ValueError(f"URN non valida: {valore!r}")
        versione = m["versione"] or ""
        return cls(
            autorita=m["autorita"],
            denominazione=m["denominazione"],
            data=m["data"],
            numero=m["numero"],
            articolo=m["articolo"],
            allegato=m["allegato"],
            vigenza=date.fromisoformat(versione[5:]) if versione.startswith("!vig=") else None,
            originale=versione == "@originale",
        )

    @property
    def atto(self) -> str:
        """URN dell'atto, senza articolo né versione."""
        return f"urn:nir:{self.autorita}:{self.denominazione}:{self.data};{self.numero}"

    def con_articolo(self, articolo: int | str, allegato: str | None = None) -> Urn:
        return replace(self, articolo=str(articolo), allegato=allegato)

    def alla_data(self, vigenza: date) -> Urn:
        return replace(self, vigenza=vigenza, originale=False)

    def __str__(self) -> str:
        s = self.atto
        if self.allegato:
            s += f":{self.allegato}"
        if self.articolo:
            s += f"~art{self.articolo}"
        if self.originale:
            s += "@originale"
        elif self.vigenza:
            s += f"!vig={self.vigenza.isoformat()}"
        return s
