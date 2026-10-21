"""Composizione di una bozza: modello di atto, dati dell'ente, profilo, testo e documento.

Il testo dell'atto è composto dal modello (common/modelli.py) per fasi; il documento ODT è
la carta intestata dell'ente (o un'impaginazione semplice) con i segnaposto
{{intestazione}}, {{preambolo}}, {{dispositivo}} e {{chiusura}}, uno per fase.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import undefer

from common.dati_personali import (
    DatiPersonaliNonDisponibili,
    applica_omissis,
    trova_dati_personali,
)
from common.llm import LlmClient
from common.models import Bozza, ImpostazioniEnte, ModelloAtto, User
from common.modelli import DatiBozza, ModelloCompilato, Valutazione, leggi_modello
from common.odt import compila, nuovo_odt

SEGNAPOSTO_CARTA = ("intestazione", "preambolo", "dispositivo", "chiusura")

# impaginazione usata se l'ente non ha caricato una carta intestata
CARTA_PREDEFINITA = nuovo_odt(
    ["{{intestazione}}", "", "{{preambolo}}", "", "{{dispositivo}}", "", "{{chiusura}}"]
)


_COMPILATI: dict[str, ModelloCompilato] = {}


def modello_compilato(modello: ModelloAtto) -> ModelloCompilato:
    """Modello già controllato: una versione non cambia mai, quindi si tiene in memoria."""
    if modello.id not in _COMPILATI:
        _COMPILATI[modello.id] = leggi_modello(modello.definizione_json)
    return _COMPILATI[modello.id]


async def impostazioni_ente(db) -> ImpostazioniEnte:
    impostazioni = await db.get(ImpostazioniEnte, 1)
    if impostazioni is None:
        impostazioni = ImpostazioniEnte(id=1, dati_json={})
        db.add(impostazioni)
        await db.flush()
    return impostazioni


def profilo(user: User | None) -> dict[str, str | None]:
    """Campi con fonte "profilo": proposti dai dati dell'utente, modificabili nell'atto."""
    if user is None:
        return {}
    return {
        "settore": user.ufficio,
        "firmatario": user.nome_completo,
        "rup": user.nome_completo,
        "decreto_incarico": user.decreto_incarico,
    }


async def valuta(db, bozza: Bozza, owner: User | None = None) -> Valutazione:
    owner = owner or await db.get(User, bozza.owner_id)
    ente = await impostazioni_ente(db)
    personalizzazioni = bozza.personalizzazioni_json or {}
    dati = DatiBozza(
        risposte=bozza.risposte_json or {},
        valori=bozza.valori_json or {},
        esclusi=set(personalizzazioni.get("esclusi") or []),
        inclusi=set(personalizzazioni.get("inclusi") or []),
        testi=dict(personalizzazioni.get("testi") or {}),
        riferimenti=bozza.riferimenti_json or [],
        ente=ente.dati_json or {},
        profilo=profilo(owner),
    )
    return Valutazione(modello_compilato(bozza.modello), dati)


def aggiorna_bozza(bozza: Bozza, valutazione: Valutazione) -> None:
    """Testo composto, oggetto, data di adozione e avanzamento: per l'elenco, la ricerca e
    la verifica."""
    bozza.contenuto_testo = valutazione.testo()
    bozza.fasi_complete = (
        sum(1 for f in valutazione.m.d.fasi if valutazione.fase(f.numero)["completa"])
        if valutazione.domande_complete()
        else None
    )
    bozza.oggetto = valutazione.oggetto()[:5000] or bozza.modello.titolo
    data = (bozza.valori_json or {}).get("data_adozione")
    try:
        bozza.data_adozione_prevista = date.fromisoformat(str(data)[:10]) if data else None
    except ValueError:
        bozza.data_adozione_prevista = None


def data_riferimento(bozza: Bozza, oggi: date) -> date:
    return bozza.data_adozione_prevista or oggi


async def carta_intestata(db) -> bytes:
    impostazioni = await db.scalar(
        select(ImpostazioniEnte)
        .where(ImpostazioniEnte.id == 1)
        .options(undefer(ImpostazioniEnte.carta_intestata))
    )
    if impostazioni is not None and impostazioni.carta_intestata:
        return impostazioni.carta_intestata
    return CARTA_PREDEFINITA


def documento_odt(carta: bytes, valutazione: Valutazione) -> bytes:
    return compila(carta, valutazione.parti())


async def parti_con_omissis(parti: dict[str, str], llm: LlmClient | None) -> dict[str, str]:
    """Le parti dell'atto con i dati personali oscurati: una chiamata al modello per tutte.

    Solleva DatiPersonaliNonDisponibili se il modello non c'è o non risponde: mai un
    documento "con omissis" con i dati in chiaro.
    """
    if llm is None:
        raise DatiPersonaliNonDisponibili(
            "rilevamento con il modello linguistico disattivato (LLM_DATI_PERSONALI)"
        )
    separatore = "\n\n"
    chiavi = list(parti)
    inizi, posizione = {}, 0
    for k in chiavi:
        inizi[k] = posizione
        posizione += len(parti[k]) + len(separatore)
    unito = separatore.join(parti[k] for k in chiavi)
    dati = await trova_dati_personali(llm, unito, interattiva=True)
    risultato = {}
    for k in chiavi:
        inizio, fine = inizi[k], inizi[k] + len(parti[k])
        nella_parte = [
            replace(d, inizio=d.inizio - inizio, fine=d.fine - inizio)
            for d in dati
            if d.inizio >= inizio and d.fine <= fine
        ]
        risultato[k] = applica_omissis(parti[k], nella_parte)
    return risultato


async def documento_odt_con_omissis(
    carta: bytes, valutazione: Valutazione, llm: LlmClient | None
) -> bytes:
    """Documento da pubblicare, con i dati personali rilevati dal modello oscurati."""
    return compila(carta, await parti_con_omissis(valutazione.parti(), llm))
