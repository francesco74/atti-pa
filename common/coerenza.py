"""Coerenza tra i riferimenti normativi citati in un atto e l'uso che l'atto ne fa (LLM).

Dopo la verifica formale dei riferimenti (esistenza, vigenza, comma e lettera), per ogni
riferimento vigente l'LLM riceve:
- l'atto intero, con tutte le citazioni marcate nel punto in cui compaiono
  ([[RIF-n]] ... [[/RIF-n]]): i presupposti possono stare lontano dalla citazione;
- la sola parte citata della norma, vigente alla data di riferimento.

I riferimenti sono inviati a gruppi (LLM_COERENZA_GRUPPO): l'atto marcato è uguale in tutte
le chiamate, così i provider che lo supportano riusano dalla cache l'inizio del messaggio.
L'esito si aggiunge alla voce del riferimento nel campo "coerenza".
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from common.libreria import articolo_alla_data, trova_partizione
from common.llm import LlmClient, LlmError, testo_prompt
from common.normattiva import NormattivaClient, NormattivaError

log = logging.getLogger("common.coerenza")

NON_VALUTATO = "NON_VALUTATO"


def marca_testo(
    testo: str, occorrenze: dict[str, list[list[int]]], max_caratteri: int
) -> tuple[str, set[str]]:
    """Testo dell'atto con le citazioni marcate, troncato a `max_caratteri`.

    Restituisce anche gli identificativi con almeno una citazione nel testo inviato:
    quelli che cadono solo nella parte troncata non sono valutabili.
    """
    intervalli: list[tuple[int, int, list[str]]] = sorted(
        (inizio, fine, [ident])
        for ident, posizioni in occorrenze.items()
        for inizio, fine in posizioni
        if fine <= max_caratteri
    )
    # citazioni sovrapposte (es. "artt. 183 e 184 del ...") diventano un solo marcatore
    uniti: list[tuple[int, int, list[str]]] = []
    for inizio, fine, idents in intervalli:
        if uniti and inizio < uniti[-1][1]:
            u_inizio, u_fine, u_idents = uniti[-1]
            nuovi = u_idents + [i for i in idents if i not in u_idents]
            uniti[-1] = (u_inizio, max(u_fine, fine), nuovi)
        else:
            uniti.append((inizio, fine, idents))

    parti, cursore = [], 0
    for inizio, fine, idents in uniti:
        etichetta = " ".join(idents)
        parti += [
            testo[cursore:inizio],
            f"[[{etichetta}]]",
            testo[inizio:fine],
            f"[[/{etichetta}]]",
        ]
        cursore = fine
    parti.append(testo[cursore:max_caratteri])
    marcato = "".join(parti)
    if len(testo) > max_caratteri:
        marcato += "\n[... testo troncato ...]"
    valutabili = {i for _, _, idents in uniti for i in idents}
    return marcato, valutabili


def _accorcia_norma(testo: str, massimo: int) -> str:
    if len(testo) <= massimo:
        return testo
    return testo[:massimo] + "\n[... testo della norma troncato ...]"


async def valuta_coerenza(
    db: AsyncSession,
    normattiva: NormattivaClient,
    llm: LlmClient,
    testo: str,
    giorno: date,
    riferimenti: list[dict],
    *,
    gruppo: int = 8,
    max_caratteri_norma: int = 8_000,
) -> None:
    """Aggiunge a ogni riferimento vigente il campo "coerenza" con l'esito dell'LLM."""
    da_valutare = {
        f"RIF-{n}": voce
        for n, voce in enumerate(
            (
                v
                for v in riferimenti
                if v.get("esito") == "VIGENTE" and (v.get("articolo") or v.get("nel_complesso"))
            ),
            1,
        )
    }
    if not da_valutare:
        return
    marcato, valutabili = marca_testo(
        testo,
        {ident: voce.get("occorrenze") or [] for ident, voce in da_valutare.items()},
        llm.max_caratteri_atto,
    )

    blocchi: dict[str, str] = {}
    for ident, voce in da_valutare.items():
        if ident not in valutabili:
            voce["coerenza"] = {
                "esito": NON_VALUTATO,
                "motivazione": f"Citazione oltre i primi {llm.max_caratteri_atto} caratteri "
                "dell'atto inviati al modello: da valutare manualmente.",
            }
            continue
        if voce.get("nel_complesso"):
            # nessun comma da confrontare: si valuta la pertinenza dell'atto citato
            testo_norma = (
                "Atto citato nel suo complesso, senza indicare articoli. "
                f"Titolo: {voce.get('titolo_atto') or 'non disponibile'}"
            )
        else:
            try:
                versione = await articolo_alla_data(
                    db, normattiva, voce["urn_atto"], voce["articolo"], giorno
                )
            except NormattivaError as e:
                voce["coerenza"] = {
                    "esito": NON_VALUTATO,
                    "motivazione": f"Norma non disponibile: {e}",
                }
                continue
            _, testo_norma = trova_partizione(
                versione.struttura_json, voce["comma"], voce["lettera"]
            )
        blocchi[ident] = testo_prompt(
            "coerenza_riferimento",
            id=ident,
            citazione=voce.get("citazione") or voce["testo"],
            testo_citazione=voce["testo"],
            testo_norma=_accorcia_norma(testo_norma or "", max_caratteri_norma),
        )

    identificativi = list(blocchi)
    for i in range(0, len(identificativi), max(1, gruppo)):
        parte = identificativi[i : i + gruppo]
        prompt = testo_prompt(
            "coerenza_utente",
            data_riferimento=giorno.strftime("%d/%m/%Y"),
            testo_atto=marcato,
            riferimenti="\n\n".join(blocchi[ident] for ident in parte),
            elenco_id=", ".join(parte),
        )
        log.debug("Coerenza dei riferimenti %s", ", ".join(parte))
        try:
            risposta = await llm.valuta_coerenza(prompt)
        except LlmError as e:
            log.warning("Coerenza dei riferimenti %s non valutata: %s", ", ".join(parte), e)
            for ident in parte:
                da_valutare[ident]["coerenza"] = {
                    "esito": "ERRORE",
                    "motivazione": f"Valutazione automatica non riuscita: {e}",
                }
            continue
        esiti = {e.id.strip(): e for e in risposta.esiti}
        for ident in parte:
            esito = esiti.get(ident)
            if esito is None:
                da_valutare[ident]["coerenza"] = {
                    "esito": NON_VALUTATO,
                    "motivazione": "Il modello non ha restituito un esito per questo riferimento.",
                }
                continue
            da_valutare[ident]["coerenza"] = esito.model_dump(exclude={"id"})
            log.debug("Coerenza %s (%s): %s", ident, da_valutare[ident]["testo"], esito.esito)
