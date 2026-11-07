"""Controlli oggettivi sulle proposte dei referenti, mostrati al RPCT prima di decidere.

Solo regole verificabili sui dati, senza modello linguistico: elementi mancanti (rischio senza
misure o non valutato, misura senza struttura, indicatore, target o tempi, procedimento senza
termine o riferimenti normativi), doppioni nella mappatura, livello di rischio che scende,
elementi eliminati insieme a quello proposto. Due livelli: AVVISO (da guardare) e INFO.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common.anticorruzione.art35 import somiglianza

AVVISO, INFO = "AVVISO", "INFO"
SOGLIA_DOPPIONE = 0.9


@dataclass
class Contesto:
    """Dati della mappatura che servono ai controlli."""

    livelli: list[str]  # dal più basso
    processi: dict[str, str] = field(default_factory=dict)  # id -> denominazione (tutti i processi dell'ente)
    elemento_id: str | None = None  # elemento modificato (escluso dai doppioni)
    fratelli: list[str] = field(default_factory=list)  # attività del processo o rischi dell'attività già presenti
    misure_del_rischio: int | None = None  # eliminazione di una misura: quante ne ha il suo rischio


def _c(livello: str, testo: str) -> dict:
    return {"livello": livello, "testo": testo}


def _breve(testo: str | None, n: int = 60) -> str:
    testo = (testo or "").strip()
    return testo if len(testo) <= n else testo[: n - 1] + "…"


def _vuoto(v) -> bool:
    return not str(v or "").strip()


def _misura(m: dict, dove: str) -> list[dict]:
    nome = f"{dove}misura «{_breve(m.get('descrizione'))}»"
    esito = []
    if _vuoto(m.get("struttura_id")):
        esito.append(_c(AVVISO, f"{nome}: manca la struttura responsabile dell'attuazione"))
    for campo, testo in (("tempi", "i tempi di attuazione"), ("indicatore", "l'indicatore di monitoraggio"),
                         ("target", "il valore atteso (target)")):  # fmt: skip
        if _vuoto(m.get(campo)):
            esito.append(_c(AVVISO, f"{nome}: manca {testo}"))
    if "traspar" in (m.get("categoria") or "").lower() and _vuoto(m.get("obbligo_trasparenza")):
        esito.append(_c(AVVISO, f"{nome}: misura di trasparenza senza l'obbligo di pubblicazione collegato"))
    return esito


def _rischio(r: dict, dove: str, ctx: Contesto, *, nuovo: bool) -> list[dict]:
    nome = f"{dove}rischio «{_breve(r.get('evento'))}»"
    esito = []
    valutazione = r.get("valutazione") or {}
    livello = valutazione.get("livello")
    if not valutazione:
        esito.append(_c(AVVISO, f"{nome}: non è valutato"))
    if _vuoto(r.get("fattore_abilitante")):
        esito.append(_c(INFO, f"{nome}: senza fattore abilitante"))
    misure = r.get("misure")
    if nuovo and misure is not None:
        if not misure:
            esito.append(_c(AVVISO, f"{nome}: nessuna misura per prevenirlo"))
        elif livello in ctx.livelli[-2:] and all(m.get("tipo") == "GENERALE" for m in misure):
            esito.append(_c(INFO, f"{nome}: livello «{livello}» con sole misure generali"))
        for m in misure:
            esito += _misura(m, f"{nome} > ")
    return esito


def _attivita(a: dict, dove: str, ctx: Contesto) -> list[dict]:
    nome = f"{dove}attività «{_breve(a.get('descrizione'))}»"
    esito = []
    rischi = a.get("rischi") or []
    if not rischi:
        esito.append(_c(INFO, f"{nome}: nessun rischio individuato"))
    for r in rischi:
        esito += _rischio(r, f"{nome} > ", ctx, nuovo=True)
    return esito


def _doppione(testo: str, esistenti: list[str]) -> str | None:
    return next((e for e in esistenti if somiglianza(testo, e) >= SOGLIA_DOPPIONE), None)


def _conta(dati: dict) -> tuple[int, int, int]:
    attivita = dati.get("attivita") or []
    rischi = [r for a in attivita for r in a.get("rischi") or []] + (dati.get("rischi") or [])
    misure = [m for r in rischi for m in r.get("misure") or []] + (dati.get("misure") or [])
    return len(attivita), len(rischi), len(misure)


def controlli_proposta(oggetto: str, tipo: str, dati: dict, prima: dict | None, ctx: Contesto) -> list[dict]:
    """Avvisi e informazioni sulla proposta (prima gli avvisi)."""
    dati = dati or {}
    esito: list[dict] = []
    if tipo == "ELIMINA":
        n_att, n_ris, n_mis = _conta(dati)
        parti = [f"{n} {nome}" for n, nome in ((n_att, "attività"), (n_ris, "rischi"), (n_mis, "misure")) if n]
        if parti:
            esito.append(_c(INFO, "Si eliminano anche: " + ", ".join(parti)))
        if oggetto == "MISURA" and ctx.misure_del_rischio == 1:
            esito.append(_c(AVVISO, "È l'unica misura del rischio: il rischio resterebbe senza misure"))
    elif oggetto == "PROCESSO":
        if _vuoto(dati.get("area_id")):
            esito.append(_c(AVVISO, "Manca l'area di rischio"))
        if _vuoto(dati.get("struttura_id")):
            esito.append(_c(INFO, "Processo trasversale: nessuna struttura responsabile"))
        if dati.get("tipo") == "PROCEDIMENTO":
            if _vuoto(dati.get("termine_conclusione")):
                esito.append(_c(AVVISO, "Procedimento senza termine di conclusione"))
            if _vuoto(dati.get("norma_riferimento")):
                esito.append(_c(AVVISO, "Procedimento senza riferimenti normativi"))
        altri = [d for i, d in ctx.processi.items() if i != ctx.elemento_id]
        if doppio := _doppione(dati.get("denominazione") or "", altri):
            esito.append(_c(AVVISO, f"Esiste già un processo con una denominazione molto simile: «{_breve(doppio, 80)}»"))
        if tipo == "CREA":
            if not dati.get("attivita"):
                esito.append(_c(INFO, "Nessuna attività: andranno aggiunte"))
            for a in dati.get("attivita") or []:
                esito += _attivita(a, "", ctx)
    elif oggetto == "ATTIVITA":
        if doppio := _doppione(dati.get("descrizione") or "", ctx.fratelli):
            esito.append(_c(AVVISO, f"Il processo ha già un'attività molto simile: «{_breve(doppio, 80)}»"))
        if tipo == "CREA":
            esito += _attivita(dati, "", ctx)
    elif oggetto == "RISCHIO":
        if doppio := _doppione(dati.get("evento") or "", ctx.fratelli):
            esito.append(_c(AVVISO, f"L'attività ha già un rischio molto simile: «{_breve(doppio, 80)}»"))
        esito += _rischio(dati, "", ctx, nuovo=tipo == "CREA")
        if tipo == "MODIFICA" and prima:
            da = (prima.get("valutazione") or {}).get("livello")
            a = (dati.get("valutazione") or {}).get("livello")
            if da and a and da != a and da in ctx.livelli and a in ctx.livelli:
                if ctx.livelli.index(a) < ctx.livelli.index(da):
                    esito.append(_c(AVVISO, f"Il livello di rischio scende da «{da}» a «{a}»"))
                else:
                    esito.append(_c(INFO, f"Il livello di rischio sale da «{da}» a «{a}»"))
    elif oggetto == "MISURA":
        esito += _misura(dati, "")
    for c in esito:
        c["testo"] = c["testo"][:1].upper() + c["testo"][1:]
    return sorted(esito, key=lambda c: c["livello"] != AVVISO)
