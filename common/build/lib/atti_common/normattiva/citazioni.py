"""Formule di citazione dei riferimenti normativi negli atti."""

from __future__ import annotations

from datetime import date

from atti_common.normattiva.urn import Urn

MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]  # fmt: skip

# (autorità, denominazione URN) -> (forma estesa, forma abbreviata)
DENOMINAZIONI: dict[tuple[str, str], tuple[str, str]] = {
    ("stato", "legge"): ("legge", "L."),
    ("stato", "legge.costituzionale"): ("legge costituzionale", "L. cost."),
    ("stato", "decreto.legislativo"): ("decreto legislativo", "D.Lgs."),
    ("stato", "decreto.legge"): ("decreto-legge", "D.L."),
    ("presidente.repubblica", "decreto"): ("decreto del Presidente della Repubblica", "D.P.R."),
    ("presidente.consiglio.ministri", "decreto"): (
        "decreto del Presidente del Consiglio dei ministri",
        "D.P.C.M.",
    ),
    ("stato", "regio.decreto"): ("regio decreto", "R.D."),
    ("stato", "costituzione"): ("Costituzione", "Cost."),
}


def data_estesa(giorno: date) -> str:
    return f"{giorno.day} {MESI[giorno.month - 1]} {giorno.year}"


def citazione_atto(urn: Urn | str, abbreviata: bool = True) -> str:
    """Es. "D.Lgs. 31 marzo 2023, n. 36" oppure "decreto legislativo 31 marzo 2023, n. 36"."""
    u = Urn.parse(urn) if isinstance(urn, str) else urn
    if u.denominazione == "costituzione":
        return "Costituzione"
    estesa, breve = DENOMINAZIONI.get(
        (u.autorita, u.denominazione), (u.denominazione.replace(".", " "), u.denominazione)
    )
    nome = breve if abbreviata else estesa
    if len(u.data) == 10:
        return f"{nome} {data_estesa(date.fromisoformat(u.data))}, n. {u.numero}"
    return f"{nome} n. {u.numero}/{u.data}"


def citazione_riferimento(
    urn_atto: str,
    articolo: str,
    comma: str | None = None,
    lettera: str | None = None,
    abbreviata: bool = True,
) -> str:
    """Es. "art. 50, comma 1, lett. b), del D.Lgs. 31 marzo 2023, n. 36"."""
    parti = [f"art. {articolo}"]
    if comma:
        parti.append(f"comma {comma}")
    if lettera:
        parti.append(f"lett. {lettera})")
    return f"{', '.join(parti)}, del {citazione_atto(urn_atto, abbreviata)}"
