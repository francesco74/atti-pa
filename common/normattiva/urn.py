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
    # le API di Normattiva rifiutano la forma NIR "presidente.repubblica:decreto" (HTTP 400)
    # e accettano solo quella con emettitore "stato"
    "decreto del presidente della repubblica": ("stato", "decreto.del.presidente.della.repubblica"),
    "decreto del presidente del consiglio dei ministri": (
        "stato",
        "decreto.del.presidente.del.consiglio.dei.ministri",
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

# Norme inserite manualmente (regolamenti interni, leggi regionali, altre fonti non
# presenti su Normattiva): URN "urn:nir:locale:<tipo>:<data>;<numero>", mai inviate a
# Normattiva. Tipo URN -> descrizione.
AUTORITA_LOCALE = "locale"
TIPI_MANUALI: dict[str, str] = {
    "regolamento": "Regolamento",
    "statuto": "Statuto",
    "legge.regionale": "Legge regionale",
    "regolamento.regionale": "Regolamento regionale",
    "deliberazione": "Deliberazione",
    "decreto": "Decreto",
    "circolare": "Circolare",
    "altro": "Altro atto",
}


def e_manuale(urn: str) -> bool:
    """True per le norme inserite manualmente (da non cercare su Normattiva)."""
    return urn.startswith(f"urn:nir:{AUTORITA_LOCALE}:")


_SUFFISSI = "bis|ter|quater|quinquies|sexies|septies|octies|novies|decies"
_ARTICOLO_SUFFISSO = re.compile(rf"^(\d+)\s*-?\s*({_SUFFISSI})$", re.IGNORECASE)


def articolo_canonico(articolo: str) -> str:
    """Forma interna del numero di articolo: "6bis", "6 bis", "6-bis" -> "6-bis"."""
    return _ARTICOLO_SUFFISSO.sub(r"\1-\2", articolo.strip()).lower()


def articolo_urn(articolo: str) -> str:
    """Forma usata da Normattiva nelle URN: "147-bis" -> "147bis"."""
    return re.sub(r"[\s-]", "", articolo)


# Forma NIR standard -> forma accettata da Normattiva (URN scritte a mano o salvate prima)
_FORME_EQUIVALENTI = {
    ("presidente.repubblica", "decreto"): TIPI_ATTO["decreto del presidente della repubblica"],
    ("presidente.consiglio.ministri", "decreto"): TIPI_ATTO[
        "decreto del presidente del consiglio dei ministri"
    ],
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
    def manuale(cls, tipo: str, data: date, numero: str) -> Urn:
        """URN di una norma inserita manualmente; il numero diventa un identificativo."""
        if tipo not in TIPI_MANUALI:
            raise ValueError(f"Tipo di norma non supportato: {tipo!r}")
        identificativo = re.sub(r"[^\w-]+", "-", numero.strip().lower()).strip("-_")
        if not identificativo:
            raise ValueError("Numero non valido")
        return cls(AUTORITA_LOCALE, tipo, data.isoformat(), identificativo)

    @classmethod
    def da_metadati(cls, atto: dict) -> Urn | None:
        """URN dell'atto da un elemento `listaAtti` delle API di ricerca.

        Restituisce None per tipi di atto non gestiti (es. decreti ministeriali).
        """
        try:
            giorno = date(
                int(atto["annoProvvedimento"]),
                int(atto["meseProvvedimento"]),
                int(atto["giornoProvvedimento"]),
            )
            return cls.per_tipo(atto["denominazioneAtto"], giorno, atto["numeroProvvedimento"])
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def parse(cls, valore: str) -> Urn:
        m = _URN_RE.match(valore.strip())
        if not m:
            raise ValueError(f"URN non valida: {valore!r}")
        versione = m["versione"] or ""
        autorita, denominazione = _FORME_EQUIVALENTI.get(
            (m["autorita"], m["denominazione"]), (m["autorita"], m["denominazione"])
        )
        return cls(
            autorita=autorita,
            denominazione=denominazione,
            data=m["data"],
            numero=m["numero"],
            articolo=articolo_canonico(m["articolo"]) if m["articolo"] else None,
            allegato=m["allegato"],
            vigenza=date.fromisoformat(versione[5:]) if versione.startswith("!vig=") else None,
            originale=versione == "@originale",
        )

    @property
    def atto(self) -> str:
        """URN dell'atto, senza articolo né versione."""
        return f"urn:nir:{self.autorita}:{self.denominazione}:{self.data};{self.numero}"

    def con_articolo(self, articolo: int | str, allegato: str | None = None) -> Urn:
        return replace(self, articolo=articolo_canonico(str(articolo)), allegato=allegato)

    def alla_data(self, vigenza: date) -> Urn:
        return replace(self, vigenza=vigenza, originale=False)

    def __str__(self) -> str:
        s = self.atto
        if self.allegato:
            s += f":{self.allegato}"
        if self.articolo:
            s += f"~art{articolo_urn(self.articolo)}"
        if self.originale:
            s += "@originale"
        elif self.vigenza:
            s += f"!vig={self.vigenza.isoformat()}"
        return s
