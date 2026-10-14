"""Analisi di un atto: riferimenti normativi, segnaposto, dati personali, checklist.

Le prime tre analisi sono deterministiche; la checklist è valutata dall'LLM on-premise,
un elemento alla volta, con il testo vigente delle norme pertinenti nel prompt.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.coerenza import valuta_coerenza
from common.config import Settings
from common.dati_personali import (
    DatiPersonaliNonDisponibili,
    StatoDatiPersonali,
    come_dict,
    trova_dati_personali,
)
from common.estrazione import RiferimentoEstratto, estrai_riferimenti
from common.libreria import (
    articolo_alla_data,
    salva_versione,
    scarica_testo,
    trova_partizione,
    versione_alla_data,
)
from common.llm import LlmClient, LlmError, costruisci_prompt
from common.models import Checklist, NormaArticoloVersione, NormaAtto
from common.norme_manuali import norme_manuali
from common.normattiva import (
    AttoNonTrovato,
    NormattivaClient,
    NormattivaError,
    RisultatoAmbiguo,
    Urn,
)
from common.normattiva.citazioni import citazione_atto, citazione_riferimento
from common.normattiva.urn import e_manuale
from common.odt import segnaposto_non_compilati
from common.riconoscimento import riconosci_citazioni

log = logging.getLogger("common.verifica")

GIORNI_MODIFICA_RECENTE = 365


class EsitoRiferimento:
    VIGENTE = "VIGENTE"
    PARTIZIONE_INESISTENTE = "PARTIZIONE_INESISTENTE"
    NON_TROVATO = "NON_TROVATO"
    ATTO_SENZA_ARTICOLO = "ATTO_SENZA_ARTICOLO"  # non più usato: verifiche precedenti
    ABROGATO = "ABROGATO"
    ERRORE_VERIFICA = "ERRORE_VERIFICA"


# Per una norma abrogata Normattiva restituisce una versione "vigente" il cui testo è solo
# la dicitura dell'abrogazione, es. "PROVVEDIMENTO ABROGATO DAL D.LGS. 18 APRILE 2016, N. 50"
_ABROGATO = re.compile(
    r"^[\s(]*(?:\d+[\w-]*\.\s*)?[\s(]*"
    r"(?P<cosa>provvedimento|articolo|comma|lettera|numero|periodo)?\s*abrogat[oa]\b",
    re.IGNORECASE,
)


def abrogazione(testo: str | None, solo_provvedimento: bool = False) -> str | None:
    """La dicitura di abrogazione se il testo vigente è soltanto quella, altrimenti None."""
    if not testo:
        return None
    m = _ABROGATO.match(testo)
    if not m or (solo_provvedimento and (m["cosa"] or "").lower() != "provvedimento"):
        return None
    dicitura = re.sub(r"^[\s(]*\d+[\w-]*\.\s*", "", " ".join(testo.split()))
    return dicitura.strip("() ")[:200]


@dataclass
class RisultatoAnalisi:
    riferimenti: list[dict] = field(default_factory=list)
    segnaposto: list[str] = field(default_factory=list)
    dati_personali: list[dict] = field(default_factory=list)
    dati_personali_stato: str = StatoDatiPersonali.NON_VALUTATI
    dati_personali_errore: str | None = None
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
            "dati_personali_stato": self.dati_personali_stato,
            "dati_personali_errore": self.dati_personali_errore,
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
    visti: dict[tuple, dict] = {}
    manuali = {n.urn: n for n in await norme_manuali(db)}
    denominazioni = [(urn, n.denominazioni_json or []) for urn, n in manuali.items()]
    for rif in estrai_riferimenti(testo, denominazioni):
        chiave = (rif.urn_atto, rif.articolo, rif.comma, rif.lettera)
        if chiave in visti:
            # stessa norma citata più volte (es. in premessa e nel dispositivo): un solo
            # esito, ma si conservano tutte le posizioni per la valutazione di coerenza
            visti[chiave]["occorrenze"].append([rif.inizio, rif.fine])
            continue
        voce = {
            "testo": rif.testo,
            "posizione": rif.inizio,
            "occorrenze": [[rif.inizio, rif.fine]],
            "articolo": rif.articolo,
            "comma": rif.comma,
            "lettera": rif.lettera,
            "urn_atto": rif.urn_atto,
            "citazione": None,
            "vigenza_inizio": None,
            "vigenza_fine": None,
            "avvisi": [],
        }
        visti[chiave] = voce
        if rif.urn in manuali:
            await verifica_norma_manuale(
                db, voce, manuali[rif.urn], rif.articolo, rif.comma, rif.lettera, giorno
            )
            risultati.append(voce)
            continue
        try:
            urn = await _risolvi_urn(db, normattiva, rif, giorno)
            voce["urn_atto"] = urn
            if not rif.articolo:
                # legge citata nel suo complesso: legittimo; si verifica che esista e sia in
                # vigore alla data (tramite l'articolo 1) e se ne registra il titolo
                voce["nel_complesso"] = True
                voce["citazione"] = citazione_atto(urn)
                primo = await articolo_alla_data(db, normattiva, urn, "1", giorno)
                atto = await db.get(NormaAtto, urn)
                voce["titolo_atto"] = atto.titolo if atto else None
                _, testo_primo = trova_partizione(primo.struttura_json, None, None)
                if dicitura := abrogazione(testo_primo, solo_provvedimento=True):
                    voce["esito"] = EsitoRiferimento.ABROGATO
                    voce["avvisi"].append(f"Atto abrogato al {giorno:%d/%m/%Y}: {dicitura}")
                else:
                    voce["esito"] = EsitoRiferimento.VIGENTE
                log.debug(
                    "Riferimento %r: atto citato nel suo complesso, %s", rif.testo, voce["esito"]
                )
                risultati.append(voce)
                continue
            voce["citazione"] = citazione_riferimento(urn, rif.articolo, rif.comma, rif.lettera)
            versione = await articolo_alla_data(db, normattiva, urn, rif.articolo, giorno)
            _valuta_articolo(voce, versione, rif.comma, rif.lettera, giorno)
        except AttoNonTrovato:
            log.debug("Riferimento %r non trovato su Normattiva", rif.testo)
            voce["esito"] = EsitoRiferimento.NON_TROVATO
            voce["avvisi"].append(
                f"Norma non trovata su Normattiva o non vigente al {giorno:%d/%m/%Y}"
            )
        except RisultatoAmbiguo:
            voce["esito"] = EsitoRiferimento.ERRORE_VERIFICA
            voce["avvisi"].append("Più testi corrispondenti su Normattiva: verifica manuale")
        except NormattivaError as e:
            log.warning("Verifica del riferimento %r non riuscita: %s", rif.testo, e)
            voce["esito"] = EsitoRiferimento.ERRORE_VERIFICA
            voce["avvisi"].append(f"Normattiva non disponibile: {e}")
        log.debug("Riferimento %r -> %s (%s)", rif.testo, voce["esito"], voce["urn_atto"])
        risultati.append(voce)
    return _unisci_duplicati(risultati)


def _valuta_articolo(
    voce: dict,
    versione: NormaArticoloVersione,
    comma: str | None,
    lettera: str | None,
    giorno: date,
) -> None:
    """Esito di un articolo citato: partizione esistente, abrogazione, modifiche recenti."""
    voce["vigenza_inizio"] = versione.vigenza_inizio and versione.vigenza_inizio.isoformat()
    voce["vigenza_fine"] = versione.vigenza_fine and versione.vigenza_fine.isoformat()
    trovato, testo_citato = trova_partizione(versione.struttura_json, comma, lettera)
    if trovato and (dicitura := abrogazione(testo_citato)):
        voce["esito"] = EsitoRiferimento.ABROGATO
        voce["avvisi"].append(f"Norma abrogata al {giorno:%d/%m/%Y}: {dicitura}")
    elif not trovato:
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


async def verifica_norma_manuale(
    db: AsyncSession,
    voce: dict,
    atto: NormaAtto,
    articolo: str | None,
    comma: str | None,
    lettera: str | None,
    giorno: date,
) -> None:
    """Esito di una citazione di norma manuale: solo i testi caricati, mai Normattiva."""
    voce["urn_atto"] = atto.urn
    voce["fonte"] = atto.fonte
    voce["citazione"] = (
        citazione_riferimento(atto.urn, articolo, comma, lettera, atto=atto.citazione)
        if articolo
        else atto.citazione
    )
    if atto.abrogata_dal and giorno >= atto.abrogata_dal:
        voce["esito"] = EsitoRiferimento.ABROGATO
        voce["avvisi"].append(f"Norma abrogata dal {atto.abrogata_dal:%d/%m/%Y}")
        return
    testo_vigente = await db.scalar(
        select(NormaArticoloVersione.id)
        .where(
            NormaArticoloVersione.urn_atto == atto.urn,
            NormaArticoloVersione.vigenza_inizio <= giorno,
            or_(
                NormaArticoloVersione.vigenza_fine.is_(None),
                NormaArticoloVersione.vigenza_fine >= giorno,
            ),
        )
        .limit(1)
    )
    if testo_vigente is None:
        voce["esito"] = EsitoRiferimento.NON_TROVATO
        voce["avvisi"].append(
            f"Nessun testo della norma vigente al {giorno:%d/%m/%Y}: caricarlo nella "
            "libreria (Norme inserite manualmente)"
        )
        return
    if not articolo:
        voce["nel_complesso"] = True
        voce["titolo_atto"] = atto.titolo
        voce["esito"] = EsitoRiferimento.VIGENTE
        return
    versione = await versione_alla_data(db, atto.urn, articolo, giorno)
    if versione is None:
        voce["esito"] = EsitoRiferimento.PARTIZIONE_INESISTENTE
        voce["avvisi"].append(
            f"L'articolo {articolo} non è presente nel testo vigente al {giorno:%d/%m/%Y}"
        )
        return
    _valuta_articolo(voce, versione, comma, lettera, giorno)


async def riconosci_norme_manuali(
    db: AsyncSession, llm: LlmClient, testo: str, giorno: date, riferimenti: list[dict]
) -> None:
    """Aggiunge ai riferimenti le citazioni di norme manuali trovate dall'LLM."""
    manuali = await norme_manuali(db)
    if not manuali:
        return
    try:
        trovate = await riconosci_citazioni(llm, testo, manuali, riferimenti)
    except LlmError as e:
        log.warning("Riconoscimento delle norme manuali non riuscito: %s", e)
        return
    per_urn = {n.urn: n for n in manuali}
    for c in trovate:
        voce = {
            "testo": c.testo,
            "posizione": c.occorrenze[0][0],
            "occorrenze": c.occorrenze,
            "articolo": c.articolo,
            "comma": c.comma,
            "lettera": c.lettera,
            "urn_atto": c.urn,
            "citazione": None,
            "vigenza_inizio": None,
            "vigenza_fine": None,
            "riconosciuto_da": "LLM",
            "avvisi": [
                "Citazione riconosciuta dal modello linguistico: verificare che si riferisca "
                "a questa norma (eventualmente aggiungerla alle sue denominazioni)"
            ],
        }
        await verifica_norma_manuale(
            db, voce, per_urn[c.urn], c.articolo, c.comma, c.lettera, giorno
        )
        riferimenti.append(voce)
    if trovate:
        unite = _unisci_duplicati(riferimenti)
        riferimenti[:] = sorted(unite, key=lambda v: v["posizione"])


def _unisci_duplicati(risultati: list[dict]) -> list[dict]:
    """Unisce le citazioni della stessa norma scritte in forme diverse.

    Es. "D.Lgs. 31 marzo 2023, n. 36" e "D.Lgs. n. 36/2023": distinte all'estrazione,
    coincidono dopo aver risolto la URN completa dell'atto.
    """
    uniti: dict[tuple, dict] = {}
    for voce in risultati:
        chiave = (voce["urn_atto"], voce["articolo"], voce["comma"], voce["lettera"])
        if chiave in uniti:
            uniti[chiave]["occorrenze"].extend(voce["occorrenze"])
        else:
            uniti[chiave] = voce
    return list(uniti.values())


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
            atto = await db.get(NormaAtto, u.atto) if e_manuale(u.atto) else None
            citazione = citazione_riferimento(
                u.atto, u.articolo, atto=atto.citazione if atto else None
            )
            norme.append((citazione, testo or ""))
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
    if len(testo) > llm.max_caratteri_atto:
        log.warning(
            "Testo dell'atto troncato nel prompt: %d caratteri su %d",
            llm.max_caratteri_atto,
            len(testo),
        )
    for elemento in checklist.elementi:
        norme = await _norme_elemento(db, normattiva, elemento.riferimenti_json or [], giorno)
        log.debug(
            "Elemento %r: %d norme nel prompt (%s)",
            elemento.titolo,
            len(norme),
            ", ".join(c for c, _ in norme) or "nessuna",
        )
        prompt = costruisci_prompt(
            elemento.titolo,
            elemento.regola,
            testo,
            norme,
            giorno.strftime("%d/%m/%Y"),
            max_caratteri=llm.max_caratteri_atto,
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
            log.debug("Elemento %r: %s", elemento.titolo, esito.esito)
        except LlmError as e:
            log.warning("Elemento %r non valutato: %s", elemento.titolo, e)
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
    settings: Settings | None = None,
) -> RisultatoAnalisi:
    """Analisi completa: riferimenti e loro coerenza, segnaposto, dati personali, checklist."""
    risultato = RisultatoAnalisi(segnaposto=segnaposto_non_compilati(testo))
    if llm is not None and settings is not None and settings.llm_dati_personali:
        try:
            risultato.dati_personali = come_dict(await trova_dati_personali(llm, testo))
            risultato.dati_personali_stato = StatoDatiPersonali.VALUTATI
        except DatiPersonaliNonDisponibili as e:
            log.warning("Rilevamento dei dati personali non riuscito: %s", e)
            risultato.dati_personali_stato = StatoDatiPersonali.ERRORE
            risultato.dati_personali_errore = f"Rilevamento automatico non riuscito: {e}"
        risultato.modello_llm = llm.modello
    log.debug(
        "Analisi di %d caratteri al %s: %d segnaposto, dati personali %s (%d)",
        len(testo),
        giorno,
        len(risultato.segnaposto),
        risultato.dati_personali_stato,
        len(risultato.dati_personali),
    )
    risultato.riferimenti = await verifica_riferimenti(db, normattiva, testo, giorno)
    if llm is not None and settings is not None and settings.llm_riconoscimento_norme_manuali:
        await riconosci_norme_manuali(db, llm, testo, giorno, risultato.riferimenti)
        risultato.modello_llm = llm.modello
    log.debug("%d riferimenti normativi verificati", len(risultato.riferimenti))
    if llm is not None and settings is not None and settings.llm_coerenza_riferimenti:
        await valuta_coerenza(
            db,
            normattiva,
            llm,
            testo,
            giorno,
            risultato.riferimenti,
            gruppo=settings.llm_coerenza_gruppo,
            max_caratteri_norma=settings.llm_coerenza_max_caratteri_norma,
        )
        risultato.modello_llm = llm.modello
    if checklist is not None and llm is not None:
        risultato.checklist = await valuta_checklist(db, normattiva, llm, checklist, testo, giorno)
        risultato.modello_llm = llm.modello
    return risultato
