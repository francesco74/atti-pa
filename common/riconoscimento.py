"""Riconoscimento con l'LLM delle citazioni di norme inserite manualmente.

Le norme manuali sono riconosciute prima con le loro denominazioni (common/estrazione.py);
l'LLM cerca le citazioni scritte in altre forme (titolo abbreviato, estremi della
deliberazione di approvazione...). Una citazione proposta dal modello è accettata solo se
il testo indicato si trova davvero nell'atto e non coincide con una già riconosciuta.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from common.llm import LlmClient, testo_prompt
from common.models import NormaAtto
from common.normattiva.urn import articolo_canonico

log = logging.getLogger("common.riconoscimento")


@dataclass
class CitazioneTrovata:
    urn: str
    testo: str
    occorrenze: list[list[int]] = field(default_factory=list)
    articolo: str | None = None
    comma: str | None = None
    lettera: str | None = None


def posizioni_estratto(testo: str, estratto: str) -> list[tuple[int, int]]:
    """Posizioni dell'estratto nel testo (spazi e maiuscole indifferenti)."""
    parole = estratto.split()
    if not parole:
        return []
    regex = re.compile(r"\s+".join(re.escape(p) for p in parole), re.IGNORECASE)
    return [(m.start(), m.end()) for m in regex.finditer(testo)]


def _partizione(valore: str | None) -> str | None:
    if not valore:
        return None
    valore = re.sub(r"^(?:art(?:icolo|\.)?|comma|lett(?:era|\.)?)\s*", "", valore.strip(), flags=re.I)
    return valore.strip(" .)").lower() or None


def _nel_testo(numero: str, estratto: str) -> bool:
    forme = {numero, numero.replace("-", " "), numero.replace("-", "")}
    return any(re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", estratto, re.I) for f in forme)


async def riconosci_citazioni(
    llm: LlmClient,
    testo: str,
    norme: list[NormaAtto],
    gia_riconosciute: list[dict],
) -> list[CitazioneTrovata]:
    """Citazioni delle norme manuali non riconosciute dalle denominazioni."""
    if not norme:
        return []
    testo_inviato = testo[: llm.max_caratteri_atto]
    per_id = {f"N-{n}": norma for n, norma in enumerate(norme, 1)}
    elenco = "\n\n".join(
        testo_prompt(
            "riconoscimento_norma",
            id=ident,
            citazione=norma.citazione,
            titolo=norma.titolo or "non indicato",
            denominazioni="; ".join(norma.denominazioni_json or []) or "nessuna",
        )
        for ident, norma in per_id.items()
    )
    occupate = [tuple(o) for voce in gia_riconosciute for o in voce.get("occorrenze") or []]
    riconosciute = "\n".join(f"- «{v['testo']}»" for v in gia_riconosciute) or "nessuna"
    prompt = testo_prompt(
        "riconoscimento_utente",
        norme=elenco,
        riconosciute=riconosciute,
        testo_atto=testo_inviato
        + ("\n[... testo troncato ...]" if len(testo) > len(testo_inviato) else ""),
    )
    risposta = await llm.riconosci_citazioni(prompt)

    trovate: dict[tuple, CitazioneTrovata] = {}
    for c in risposta.citazioni:
        norma = per_id.get(c.norma.strip())
        posizioni = [
            p
            for p in posizioni_estratto(testo_inviato, c.testo)
            if not any(p[0] < fine and inizio < p[1] for inizio, fine in occupate)
        ]
        if norma is None or not posizioni:
            log.debug("Citazione proposta dal modello scartata: %s %r", c.norma, c.testo)
            continue
        articolo = _partizione(c.articolo)
        if articolo and not _nel_testo(articolo, c.testo):
            articolo = None  # articolo non presente nella citazione: non verificabile
        comma = _partizione(c.comma) if articolo else None
        lettera = _partizione(c.lettera) if comma else None
        articolo = articolo_canonico(articolo) if articolo else None
        chiave = (norma.urn, articolo, comma, lettera)
        trovata = trovate.setdefault(
            chiave, CitazioneTrovata(norma.urn, c.testo.strip(), [], articolo, comma, lettera)
        )
        for p in posizioni:
            if list(p) not in trovata.occorrenze:
                trovata.occorrenze.append(list(p))
        occupate += posizioni
    log.debug("%d citazioni di norme manuali riconosciute dal modello", len(trovate))
    return list(trovate.values())
