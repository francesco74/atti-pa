"""Analisi di un atto: riferimenti normativi, segnaposto, dati personali, checklist.

Le prime tre analisi sono deterministiche; la checklist è valutata dall'LLM on-premise,
un elemento alla volta, con il testo vigente delle norme pertinenti nel prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atti_common.dati_personali import come_dict, trova_dati_personali
from atti_common.estrazione import RiferimentoEstratto, estrai_riferimenti
from atti_common.libreria import articolo_alla_data, salva_versione, scarica_testo, trova_partizione
from atti_common.llm import LlmClient, LlmError, costruisci_prompt
from atti_common.models import Checklist, NormaAtto
from atti_common.normattiva import (
    AttoNonTrovato,
    NormattivaClient,
    NormattivaError,
    RisultatoAmbiguo,
    Urn,
)
from atti_common.normattiva.citazioni import citazione_riferimento
from atti_common.odt import segnaposto_non_compilati

log = logging.getLogger("atti_common.verifica")

GIORNI_MODIFICA_RECENTE = 365


class EsitoRiferimento:
    VIGENTE = "VIGENTE"
    PARTIZIONE_INESISTENTE = "PARTIZIONE_INESISTENTE"
    NON_TROVATO = "NON_TROVATO"
    ATTO_SENZA_ARTICOLO = "ATTO_SENZA_ARTICOLO"
    ERRORE_VERIFICA = "ERRORE_VERIFICA"


@dataclass
class RisultatoAnalisi:
    riferimenti: list[dict] = field(default_factory=list)
    segnaposto: list[str] = field(default_factory=list)
    dati_personali: list[dict] = field(default_factory=list)
    checklist: list[dict] = field(default_factory=list)
    modello_llm: str | None = None

    def esito_riferimenti(self) -> dict:
        conteggio: dict[str, int] = {}
        for r in self.riferimenti:
            conteggio[r["esito"]] = conteggio.get(r["esito"], 0) + 1
        return {
            "riferimenti": self.riferimenti,
            "segnaposto": self.segnaposto,
            "dati_personali": self.dati_personali,
            "riepilogo": {
                "riferimenti": conteggio,
                "segnaposto": len(self.segnaposto),
                "dati_personali": len(self.dati_personali),
            },
        }


async def _risolvi_urn(
    db: AsyncSession, normattiva: NormattivaClient, rif: RiferimentoEstratto, giorno: date
) -> str:
    """URN completa (con data) dell'atto citato: dal testo, dalla libreria o da Normattiva."""
    if rif.data:
        return rif.urn_atto
    u = Urn.parse(rif.urn_atto)
    in_libreria = await db.scalar(
        select(NormaAtto.urn).where(
            NormaAtto.urn.like(f"urn:nir:{u.autorita}:{u.denominazione}:{rif.anno}-%;{rif.numero}")
        )
    )
    if in_libreria:
        return in_libreria
    articolo = rif.articolo or "1"
    testo = await scarica_testo(normattiva, u.con_articolo(articolo), giorno)
    if testo.data_provvedimento is None:
        raise AttoNonTrovato(rif.urn_atto)
    completa = Urn.per_tipo(rif.tipo, testo.data_provvedimento, rif.numero).atto
    await salva_versione(db, completa, articolo, testo)
    await db.commit()
    return completa


async def verifica_riferimenti(
    db: AsyncSession, normattiva: NormattivaClient, testo: str, giorno: date
) -> list[dict]:
    risultati: list[dict] = []
    visti: set[tuple] = set()
    for rif in estrai_riferimenti(testo):
        chiave = (rif.urn_atto, rif.articolo, rif.comma, rif.lettera)
        if chiave in visti:
            continue
        visti.add(chiave)
        voce = {
            "testo": rif.testo,
            "posizione": rif.inizio,
            "articolo": rif.articolo,
            "comma": rif.comma,
            "lettera": rif.lettera,
            "urn_atto": rif.urn_atto,
            "citazione": None,
            "vigenza_inizio": None,
            "vigenza_fine": None,
            "avvisi": [],
        }
        try:
            urn = await _risolvi_urn(db, normattiva, rif, giorno)
            voce["urn_atto"] = urn
            if not rif.articolo:
                voce["esito"] = EsitoRiferimento.ATTO_SENZA_ARTICOLO
                voce["avvisi"].append("Citazione dell'intero atto: indicare l'articolo pertinente")
                risultati.append(voce)
                continue
            voce["citazione"] = citazione_riferimento(urn, rif.articolo, rif.comma, rif.lettera)
            versione = await articolo_alla_data(db, normattiva, urn, rif.articolo, giorno)
            voce["vigenza_inizio"] = versione.vigenza_inizio and versione.vigenza_inizio.isoformat()
            voce["vigenza_fine"] = versione.vigenza_fine and versione.vigenza_fine.isoformat()
            trovato, _ = trova_partizione(versione.struttura_json, rif.comma, rif.lettera)
            if not trovato:
                voce["esito"] = EsitoRiferimento.PARTIZIONE_INESISTENTE
                voce["avvisi"].append(
                    f"Il comma o la lettera citati non esistono nel testo vigente al {giorno:%d/%m/%Y}"
                )
            else:
                voce["esito"] = EsitoRiferimento.VIGENTE
                if (
                    versione.vigenza_inizio
                    and 0 <= (giorno - versione.vigenza_inizio).days <= GIORNI_MODIFICA_RECENTE
                ):
                    voce["avvisi"].append(
                        f"Testo modificato di recente (vigente dal "
                        f"{versione.vigenza_inizio:%d/%m/%Y}): verificare che la citazione sia attuale"
                    )
        except AttoNonTrovato:
            voce["esito"] = EsitoRiferimento.NON_TROVATO
            voce["avvisi"].append(
                f"Norma non trovata su Normattiva o non vigente al {giorno:%d/%m/%Y}"
            )
        except RisultatoAmbiguo:
            voce["esito"] = EsitoRiferimento.ERRORE_VERIFICA
            voce["avvisi"].append("Più testi corrispondenti su Normattiva: verifica manuale")
        except NormattivaError as e:
            voce["esito"] = EsitoRiferimento.ERRORE_VERIFICA
            voce["avvisi"].append(f"Normattiva non disponibile: {e}")
        risultati.append(voce)
    return risultati


async def _norme_elemento(
    db: AsyncSession, normattiva: NormattivaClient, urns: list[str], giorno: date
) -> list[tuple[str, str]]:
    norme = []
    for valore in urns or []:
        try:
            u = Urn.parse(valore)
            if not u.articolo:
                continue
            versione = await articolo_alla_data(db, normattiva, u.atto, u.articolo, giorno)
            _, testo = trova_partizione(versione.struttura_json, None, None)
            norme.append((citazione_riferimento(u.atto, u.articolo), testo or ""))
        except (ValueError, NormattivaError) as e:
            log.warning("Norma %s non disponibile per il prompt: %s", valore, e)
    return norme


async def valuta_checklist(
    db: AsyncSession,
    normattiva: NormattivaClient,
    llm: LlmClient,
    checklist: Checklist,
    testo: str,
    giorno: date,
) -> list[dict]:
    esiti = []
    for elemento in checklist.elementi:
        norme = await _norme_elemento(db, normattiva, elemento.riferimenti_json or [], giorno)
        prompt = costruisci_prompt(
            elemento.titolo, elemento.regola, testo, norme, giorno.strftime("%d/%m/%Y")
        )
        voce = {
            "elemento_id": elemento.id,
            "titolo": elemento.titolo,
            "obbligatorio": elemento.obbligatorio,
            "norme_usate": [c for c, _ in norme],
        }
        try:
            esito = await llm.valuta(prompt)
            voce.update(esito.model_dump())
        except LlmError as e:
            voce.update(
                esito="ERRORE",
                motivazione=f"Valutazione automatica non riuscita: {e}",
                evidenza=None,
                suggerimento=None,
            )
        esiti.append(voce)
    return esiti


async def analizza(
    db: AsyncSession,
    normattiva: NormattivaClient,
    llm: LlmClient | None,
    testo: str,
    giorno: date,
    checklist: Checklist | None = None,
) -> RisultatoAnalisi:
    risultato = RisultatoAnalisi(
        segnaposto=segnaposto_non_compilati(testo),
        dati_personali=come_dict(trova_dati_personali(testo)),
    )
    risultato.riferimenti = await verifica_riferimenti(db, normattiva, testo, giorno)
    if checklist is not None and llm is not None:
        risultato.checklist = await valuta_checklist(db, normattiva, llm, checklist, testo, giorno)
        risultato.modello_llm = llm.modello
    return risultato
