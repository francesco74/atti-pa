"""Registro delle ricerche e feedback, comune a tutte le ricerche del sistema.

L'app registra una ricerca quando è **conclusa**: la persona apre un risultato (TROVATA, con la
posizione) oppure resta senza aprirne. In quel caso l'esito è NESSUN_RISULTATO, RISULTATI_DEBOLI
(trovati solo per significato) o NON_APERTI. Non si registrano i frammenti scritti mentre si
digita. Il feedback è facoltativo: sui risultati di una ricerca o su una scheda (es. un
procedimento pubblico).

Non si salvano utente né IP; email, telefoni, codici fiscali e IBAN scritti nel testo si
oscurano prima di salvare ([oscura]). Le ricerche senza risposta si raggruppano per `chiave`
(le radici delle parole: "contributo affitto" = "affitti contributi") e le consulta chi ha il
ruolo ANALISI_RICERCHE (o l'amministratore dell'ente). Il worker cancella i dati più vecchi di
RICERCHE_CONSERVAZIONE_MESI.

Per registrare una nuova ricerca basta aggiungere il suo ambito ad [AMBITI].
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import delete

from common import ricerca
from common.models import Modulo, RicercaFeedback, RicercaRegistrata

# ambito -> (descrizione, moduli che lo rendono disponibile: basta uno)
AMBITI: dict[str, tuple[str, tuple[str, ...]]] = {
    "MAPPATURA": ("Mappatura dei processi", (Modulo.ANTICORRUZIONE,)),
    "ELENCO": ("Elenco della mappatura (aree, processi, attività, rischi, misure)", (Modulo.ANTICORRUZIONE,)),
    # catalogo condiviso (common/procedimenti.py)
    "PROCEDIMENTI": ("Procedimenti (art. 35)", (Modulo.ANTICORRUZIONE, Modulo.TRASPARENZA)),
}

TROVATA = "TROVATA"
NESSUN_RISULTATO = "NESSUN_RISULTATO"
RISULTATI_DEBOLI = "RISULTATI_DEBOLI"
NON_APERTI = "NON_APERTI"
ESITI = (TROVATA, NESSUN_RISULTATO, RISULTATI_DEBOLI, NON_APERTI)
SENZA_RISPOSTA = (NESSUN_RISULTATO, RISULTATI_DEBOLI, NON_APERTI)

OMISSIS = "[omissis]"
_DATI_PERSONALI = [
    re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"),  # email
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.IGNORECASE),  # IBAN
    re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.IGNORECASE),  # codice fiscale
    re.compile(r"(?<![\w])\+?\d[\d .\-/]{5,}\d"),  # telefoni e altri numeri lunghi
]


def oscura(testo: str) -> str:
    """Il testo con email, IBAN, codici fiscali e numeri lunghi (telefoni...) sostituiti."""
    for r in _DATI_PERSONALI:
        testo = r.sub(OMISSIS, testo)
    return testo


def chiave(testo: str) -> str:
    """Chiave di raggruppamento: radici distinte delle parole, in ordine alfabetico."""
    radici = sorted(set(ricerca.radici(testo)))
    return (" ".join(radici) or ricerca.normalizza(testo).strip())[:300]


def ambiti_disponibili(ente) -> dict[str, str]:
    """Ambiti dei moduli attivi dell'ente: {codice: descrizione}."""
    return {k: d for k, (d, moduli) in AMBITI.items() if any(ente.modulo_attivo(m) for m in moduli)}


def nuova_ricerca(ente_id: str, ambito: str, pubblica: bool, testo: str, risultati: int, esito: str,
                  posizione: int | None, semantica: bool) -> RicercaRegistrata:  # fmt: skip
    testo = oscura(testo.strip())[:300]
    return RicercaRegistrata(
        ente_id=ente_id, ambito=ambito, pubblica=pubblica, testo=testo, chiave=chiave(testo),
        risultati=max(0, risultati), esito=esito, posizione=posizione if esito == TROVATA else None,
        semantica=semantica,
    )  # fmt: skip


async def pulisci(sessione, mesi: int, adesso: datetime | None = None) -> int:
    """Cancella ricerche e feedback più vecchi di [mesi] (30 giorni l'uno); quanti righe."""
    limite = (adesso or datetime.now()) - timedelta(days=30 * mesi)
    f = await sessione.execute(delete(RicercaFeedback).where(RicercaFeedback.created_at < limite))
    r = await sessione.execute(delete(RicercaRegistrata).where(RicercaRegistrata.created_at < limite))
    await sessione.commit()
    return (f.rowcount or 0) + (r.rowcount or 0)
