"""Editor di modelli, specificità e checklist nell'app.

L'app lavora sulla definizione strutturata (JSON) e la salva in bozza; alla pubblicazione la
definizione diventa il sorgente (YAML per modelli e specificità, JSON per le checklist) di
una nuova versione (common/pacchetti.py). Qui:

- conversione tra sorgente e definizione;
- controllo: errori che impediscono la pubblicazione e avvisi (dati mai usati, checklist
  mancanti, controlli collegati a capoversi che non esistono più...);
- anteprima dell'atto composto con le risposte di uno scenario di prova;
- confronto elemento per elemento (domande, dati, capoversi, elementi di checklist) con la
  versione pubblicata o con lo standard da cui deriva.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from common.configurazione import (
    ChecklistNuovaIn,
    controlla_checklist,
    sorgente_checklist,
)
from common.models import Checklist, ModelloAtto, ModuloDiRegole, TipologiaAtto
from common.modelli import (
    SEGNAPOSTO,
    DatiBozza,
    Modello,
    ModelloNonValido,
    ModuloRegole,
    Valutazione,
    componi,
    leggi_modello,
)
from common.pacchetti import moduli_attivi

Tipo = Literal["modello", "modulo", "checklist"]
TIPI: tuple[Tipo, ...] = ("modello", "modulo", "checklist")


def _errori(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]


# --- sorgente e definizione -------------------------------------------------------------------


def definizione_da_sorgente(tipo: Tipo, sorgente: str) -> dict:
    """Definizione completa (con i valori predefiniti) da un sorgente. Solleva ValueError."""
    try:
        if tipo == "checklist":
            return ChecklistNuovaIn.model_validate(json.loads(sorgente)).model_dump(mode="json")
        dati = yaml.safe_load(sorgente)
        classe = Modello if tipo == "modello" else ModuloRegole
        return classe.model_validate(dati).model_dump(mode="json")
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ValueError(f"Sorgente non leggibile: {e}") from e
    except ValidationError as e:
        raise ModelloNonValido(_errori(e)) from e


def sorgente_da_definizione(tipo: Tipo, definizione: dict) -> str:
    """Sorgente da pubblicare. Solleva ModelloNonValido o ValueError se non è valida."""
    try:
        if tipo == "checklist":
            dati = ChecklistNuovaIn.model_validate(definizione)
            return sorgente_checklist(controlla_checklist(dati))
        classe = Modello if tipo == "modello" else ModuloRegole
        d = classe.model_validate(definizione)
    except ValidationError as e:
        raise ModelloNonValido(_errori(e)) from e
    dati = d.model_dump(mode="json", exclude_defaults=True)
    if tipo == "modello":
        dati.pop("regole", None)  # le specificità si compongono, non si salvano nel modello
    return yaml.safe_dump(dati, allow_unicode=True, sort_keys=False, width=100)


def sorgente_grezzo(tipo: Tipo, definizione: dict) -> str:
    """Sorgente della definizione anche se non è valida (scheda "Sorgente" dell'editor)."""
    try:
        return sorgente_da_definizione(tipo, definizione)
    except (ModelloNonValido, ValueError):
        if tipo == "checklist":
            return json.dumps(definizione, ensure_ascii=False, indent=2)
        return yaml.safe_dump(definizione, allow_unicode=True, sort_keys=False, width=100)


# --- contenuti delle definizioni ---------------------------------------------------------------


def capoversi_del_modello(definizione: dict) -> list[dict]:
    """Capoversi con la loro posizione: [{id, dove, testo, se}]."""
    risultato = []
    for f in definizione.get("fasi") or []:
        for s in f.get("sezioni") or []:
            for c in s.get("capoversi") or []:
                risultato.append(
                    {
                        "id": c.get("id"),
                        "dove": f"Fase {f.get('numero')} › {s.get('titolo')}",
                        "testo": c.get("testo", ""),
                        "se": c.get("se"),
                    }
                )
    return risultato


def capoversi_del_modulo(definizione: dict) -> list[dict]:
    risultato = []
    for ins in definizione.get("inserti") or []:
        for c in ins.get("capoversi") or []:
            risultato.append(
                {
                    "id": c.get("id"),
                    "dove": f"Innesto {ins.get('innesto')}",
                    "testo": c.get("testo", ""),
                    "se": c.get("se"),
                }
            )
    return risultato


def punti_di_innesto(definizione: dict) -> list[dict]:
    """Sezioni del modello in cui le specificità possono inserire capoversi."""
    return [
        {
            "innesto": s["innesto"],
            "sezione": s.get("titolo"),
            "fase": f.get("numero"),
            "capoversi": [c.get("id") for c in s.get("capoversi") or []],
        }
        for f in definizione.get("fasi") or []
        for s in f.get("sezioni") or []
        if s.get("innesto")
    ]


def _campi_usati(testi: list[str]) -> set[str]:
    return {nome for t in testi for nome, _, _ in SEGNAPOSTO.findall(t or "")}


# --- controllo ---------------------------------------------------------------------------------


async def _modelli_attivi(db: AsyncSession) -> list[ModelloAtto]:
    return list(
        (
            await db.scalars(
                select(ModelloAtto)
                .where(ModelloAtto.attivo.is_(True))
                .options(undefer(ModelloAtto.sorgente))
            )
        ).all()
    )


async def _checklist_attive(db: AsyncSession) -> list[Checklist]:
    return list((await db.scalars(select(Checklist).where(Checklist.attiva.is_(True)))).all())


def _avvisi_collegamenti(schede: list[Checklist], ids: set[str]) -> list[str]:
    avvisi = []
    for cl in schede:
        for el in cl.elementi:
            for c in el.capoversi_json or []:
                if c not in ids:
                    avvisi.append(
                        f"Il controllo «{el.titolo}» della checklist {cl.codice} è collegato al "
                        f"capoverso {c}, che non esiste più"
                    )
    return avvisi


async def controlla(db: AsyncSession, tipo: Tipo, codice: str, definizione: dict) -> dict:
    """{"errori": [...], "avvisi": [...]}: gli errori impediscono la pubblicazione."""
    errori: list[str] = []
    avvisi: list[str] = []
    if (definizione.get("codice") or "") != codice:
        errori.append(f"Il codice della definizione deve essere {codice}")
    try:
        sorgente = sorgente_da_definizione(tipo, definizione)
    except ModelloNonValido as e:
        return {"errori": errori + e.errori, "avvisi": []}
    except ValueError as e:
        return {"errori": errori + [str(e)], "avvisi": []}
    schede = await _checklist_attive(db)
    moduli = await moduli_attivi(db)

    if tipo in ("modello", "checklist"):
        tipologia = definizione.get("tipologia_atto")
        if tipologia and await db.get(TipologiaAtto, tipologia) is None:
            errori.append(f"Tipologia di atto inesistente: {tipologia}")

    if tipo == "modello":
        try:
            composto = leggi_modello(sorgente, [m for m, _ in moduli.values()]).d
        except ModelloNonValido as e:
            errori += e.errori
            composto = None
        testi = [c["testo"] for c in capoversi_del_modello(definizione)]
        testi += [c.get("predefinito") or "" for c in (definizione.get("campi") or {}).values()]
        if composto is not None:
            for m, _ in moduli.values():
                if codice in m.modelli:
                    testi += [c.testo for ins in m.inserti for c in ins.capoversi]
        usati = _campi_usati(testi)
        for nome, campo in (definizione.get("campi") or {}).items():
            if nome not in usati and campo.get("fonte") != "sistema":
                etichetta = campo.get("etichetta", nome)
                avvisi.append(f"Il dato «{etichetta}» non è usato in nessun testo")
        for f in definizione.get("fasi") or []:
            for s in f.get("sezioni") or []:
                vuota = not s.get("capoversi") and not s.get("innesto")
                if vuota and not s.get("riferimenti_libreria"):
                    avvisi.append(f"La sezione «{s.get('titolo')}» non ha capoversi")
        mie = [c for c in schede if c.modello == codice]
        if not mie:
            avvisi.append("Manca la checklist del modello")
        ids = {c["id"] for c in capoversi_del_modello(definizione)}
        avvisi += _avvisi_collegamenti(mie, ids)

    elif tipo == "modulo":
        nuovo = ModuloRegole.model_validate(definizione)
        altri = [m for c, (m, _) in moduli.items() if c != codice]
        attivi = {m.codice: m for m in await _modelli_attivi(db)}
        for codice_modello in nuovo.modelli:
            m = attivi.get(codice_modello)
            if m is None:
                avvisi.append(f"Il modello {codice_modello} non esiste o non è attivo")
                continue
            try:
                leggi_modello(m.sorgente, [*altri, nuovo])
            except ModelloNonValido as e:
                errori += [f"Nel modello {codice_modello}: {x}" for x in e.errori]
        mie = [c for c in schede if c.modulo == codice]
        if not mie:
            avvisi.append("Manca la checklist della specificità")
        avvisi += _avvisi_collegamenti(mie, {c["id"] for c in capoversi_del_modulo(definizione)})

    else:  # checklist
        modello, modulo = definizione.get("modello"), definizione.get("modulo")
        disponibili: set[str] | None = None
        if modello:
            m = next((x for x in await _modelli_attivi(db) if x.codice == modello), None)
            if m is None:
                avvisi.append(f"Il modello {modello} non esiste o non è attivo")
            else:
                d = definizione_da_sorgente("modello", m.sorgente)
                disponibili = {c["id"] for c in capoversi_del_modello(d)}
        elif modulo:
            if modulo not in moduli:
                avvisi.append(f"La specificità {modulo} non esiste o non è attiva")
            else:
                d = moduli[modulo][0].model_dump(mode="json")
                disponibili = {c["id"] for c in capoversi_del_modulo(d)}
        scollegati = 0
        for el in definizione.get("elementi") or []:
            collegati = el.get("capoversi") or []
            if not collegati:
                scollegati += 1
            if disponibili is not None:
                for c in collegati:
                    if c not in disponibili:
                        avvisi.append(
                            f"Il controllo «{el.get('titolo')}» rimanda al capoverso {c}, "
                            "che non esiste"
                        )
            elif collegati:
                avvisi.append(
                    f"Il controllo «{el.get('titolo')}» è collegato a capoversi, ma la checklist "
                    "è generica: i collegamenti valgono solo per le checklist di un modello o di "
                    "una specificità"
                )
        if scollegati and (modello or modulo):
            avvisi.append(f"{scollegati} controlli non sono collegati a nessun capoverso")
    return {"errori": errori, "avvisi": avvisi}


# --- anteprima ---------------------------------------------------------------------------------


def _riepilogo(composto: Modello, risposte: dict, evidenzia: set[str]) -> dict:
    """L'atto con le risposte di prova e senza dati: i dati mancanti restano [[nome]], che
    l'editor mostra con l'etichetta del dato."""
    m = leggi_modello(composto.model_dump(mode="json"))
    v = Valutazione(m, DatiBozza(risposte=risposte))
    riepilogo = v.riepilogo()
    for f in riepilogo["fasi"]:
        f.pop("campi", None)
        for s in f["sezioni"]:
            for c in s["capoversi"]:
                c["evidenziato"] = c["id"] in evidenzia
                c.pop("segmenti", None)
    etichette = {n: c.etichetta for n, c in composto.campi.items()}
    for nome, c in composto.campi.items():
        for s, sc in (c.sottocampi or {}).items():
            etichette[f"{nome}.{s}"] = f"{c.etichetta}: {sc.etichetta}"
    return {
        "domande": riepilogo["domande"],
        "blocchi": riepilogo["blocchi"],
        "fasi": riepilogo["fasi"],
        "etichette": etichette,
    }


async def anteprima(
    db: AsyncSession,
    tipo: Tipo,
    definizione: dict,
    risposte: dict[str, Any],
    modello: str | None = None,
) -> dict:
    """Anteprima di un modello (composto con le specificità attive) o di una specificità
    (composta in un modello a cui si applica, con la caratteristica scelta)."""
    moduli = await moduli_attivi(db)
    try:
        if tipo == "modello":
            base = Modello.model_validate(definizione)
            composto = componi(base, [m for m, _ in moduli.values()])
            return _riepilogo(composto, risposte, set())
        nuovo = ModuloRegole.model_validate(definizione)
        codice_modello = modello or (nuovo.modelli[0] if nuovo.modelli else None)
        m = next((x for x in await _modelli_attivi(db) if x.codice == codice_modello), None)
        if m is None:
            raise ValueError(f"Modello {codice_modello} non disponibile per l'anteprima")
        base = Modello.model_validate(yaml.safe_load(m.sorgente))
        altri = [x for c, (x, _) in moduli.items() if c != nuovo.codice]
        composto = componi(base, [*altri, nuovo])
        caratteristiche = next((q.id for q in composto.domande if q.opzioni_da_regole), None)
        risposte = dict(risposte)
        if caratteristiche:
            scelte = list(risposte.get(caratteristiche) or [])
            if nuovo.fattore not in scelte:
                scelte.append(nuovo.fattore)
            risposte[caratteristiche] = scelte
        evidenzia = {c["id"] for c in capoversi_del_modulo(definizione)}
        return _riepilogo(composto, risposte, evidenzia)
    except ValidationError as e:
        raise ModelloNonValido(_errori(e)) from e


# --- confronto ---------------------------------------------------------------------------------


def _elementi(tipo: Tipo, d: dict | None) -> dict[str, tuple[str, str, Any]]:
    """{chiave: (descrizione, dove, contenuto)} degli elementi confrontabili."""
    if not d:
        return {}
    el: dict[str, tuple[str, str, Any]] = {}
    if tipo == "checklist":
        for k in ("titolo", "tipologia_atto", "modello", "modulo", "descrizione"):
            el[f"campo:{k}"] = (f"Campo «{k}»", "Checklist", d.get(k))
        for e in d.get("elementi") or []:
            el[f"elemento:{e.get('titolo')}"] = (f"Controllo «{e.get('titolo')}»", "Elementi", e)
        return el
    for k in ("titolo", "descrizione", "etichetta", "fattore", "modelli", "tipologia_atto"):
        if k in d:
            el[f"campo:{k}"] = (f"Campo «{k}»", "Generale", d.get(k))
    for q in d.get("domande") or []:
        el[f"domanda:{q.get('id')}"] = (f"Domanda «{q.get('testo')}»", "Domande", q)
    for nome, c in (d.get("campi") or {}).items():
        el[f"dato:{nome}"] = (f"Dato «{c.get('etichetta', nome)}»", "Dati", c)
    for nome, r in (d.get("derivati") or {}).items():
        el[f"derivato:{nome}"] = (f"Valore calcolato «{nome}»", "Valori calcolati", r)
    for i, s in enumerate(d.get("suggerimenti") or []):
        el[f"suggerimento:{s.get('domanda')}:{i}"] = (
            f"Suggerimento per «{s.get('domanda')}»", "Suggerimenti", s
        )
    if tipo == "modello":
        for f in d.get("fasi") or []:
            for s in f.get("sezioni") or []:
                dove = f"Fase {f.get('numero')} › {s.get('titolo')}"
                intestazione = {k: v for k, v in s.items() if k != "capoversi"}
                el[f"sezione:{f.get('numero')}:{s.get('titolo')}"] = (
                    f"Sezione «{s.get('titolo')}»", f"Fase {f.get('numero')}", intestazione
                )
                for c in s.get("capoversi") or []:
                    el[f"capoverso:{c.get('id')}"] = (f"Capoverso {c.get('id')}", dove, c)
    else:
        for ins in d.get("inserti") or []:
            for c in ins.get("capoversi") or []:
                el[f"capoverso:{c.get('id')}"] = (
                    f"Capoverso {c.get('id')}", f"Innesto {ins.get('innesto')}", c
                )
    return el


def confronta(tipo: Tipo, prima: dict | None, dopo: dict) -> list[dict]:
    """Differenze elemento per elemento: aggiunti, tolti, modificati (nell'ordine di dopo)."""
    a, b = _elementi(tipo, prima), _elementi(tipo, dopo)
    differenze = []
    for chiave, (descrizione, dove, contenuto) in b.items():
        if chiave not in a:
            differenze.append(
                {"chiave": chiave, "elemento": descrizione, "dove": dove, "stato": "aggiunto",
                 "prima": None, "dopo": contenuto}
            )  # fmt: skip
        elif a[chiave][2] != contenuto:
            differenze.append(
                {"chiave": chiave, "elemento": descrizione, "dove": dove, "stato": "modificato",
                 "prima": a[chiave][2], "dopo": contenuto}
            )  # fmt: skip
    for chiave, (descrizione, dove, contenuto) in a.items():
        if chiave not in b:
            differenze.append(
                {"chiave": chiave, "elemento": descrizione, "dove": dove, "stato": "tolto",
                 "prima": contenuto, "dopo": None}
            )  # fmt: skip
    return differenze
