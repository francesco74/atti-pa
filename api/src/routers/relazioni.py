"""Relazioni di sintesi costruite sui dati del sistema (common/relazioni.py).

- RPCT: relazione annuale del RPCT (mappatura, attuazione delle misure dal monitoraggio,
  proposte dei referenti, trasparenza) - RPCT (e amministratore), modulo anticorruzione;
- PIAO: sottosezione "Rischi corruttivi e trasparenza" (mappatura per area, misure, rischi più
  gravi) - come sopra;
- PERFORMANCE: relazione sulla performance di un anno del PIAO (obiettivi per struttura,
  completamento, ritardi, misure anticorruzione collegate) - amministratore della performance.

GET restituisce le sezioni con i dati e le tabelle calcolati; POST .../testo fa scrivere al
modello il testo di una sezione dai soli suoi dati e segnala i numeri del testo che nei dati non
ci sono; POST /esporta converte la bozza rivista in DOCX o ODT.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from http import HTTPStatus
from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, Field
from sqlalchemy import select

from deps import autenticato, db, ente, ente_id, risorse, utente
from routers import anticorruzione as ac
from web import ErroreApi, allegato, corpo, parametri
from common.anticorruzione import art35 as dati_art35
from common.anticorruzione.metodologia import chiave_naturale
from common.documenti import DocumentiError
from common.llm import LlmError, testo_prompt
from common.models import (
    AcAttivita, AcMisura, AcProcesso, AcProposta, AcRischio, Modulo, PfElemento, PfObiettivo, PfPiao, Ruolo, Struttura,
)  # fmt: skip
from common.performance import TOTALE, in_ritardo, media_pesata
from common.relazioni import Sezione, Tabella, html_relazione, numeri_da_verificare, percentuale

bp = Blueprint("relazioni", __name__, url_prefix="/api/v1/relazioni")

TIPI = {
    "RPCT": ("Relazione annuale del RPCT", Modulo.ANTICORRUZIONE, (Ruolo.ANTICORRUZIONE_RPCT,)),
    "PIAO": ("PIAO - Sottosezione Rischi corruttivi e trasparenza", Modulo.ANTICORRUZIONE, (Ruolo.ANTICORRUZIONE_RPCT,)),
    "PERFORMANCE": ("Relazione sulla performance", Modulo.PERFORMANCE, (Ruolo.PERFORMANCE_AMMINISTRATORE,)),
}
MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "odt": "application/vnd.oasis.opendocument.text"}  # fmt: skip


def _ammesso(tipo: str) -> bool:
    _, modulo, ruoli = TIPI[tipo]
    return ente().modulo_attivo(modulo) and utente().ha_ruolo(Ruolo.ADMIN, *ruoli)


def _controlla(tipo: str) -> None:
    if tipo not in TIPI or not _ammesso(tipo):
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Relazione non disponibile")


class Parametri(BaseModel):
    anno: int = Field(default_factory=lambda: datetime.now().year, ge=2000, le=2100)
    piao_id: str | None = None  # relazione sulla performance


# --- relazione annuale del RPCT --------------------------------------------------------------


async def _mappatura() -> Sezione:
    r = await ac.riepilogo()
    t = r["totali"]
    livelli = [x for x in r["livelli"] if x != "None"]
    processi = list(await db().scalars(select(AcProcesso.tipo).where(AcProcesso.ente_id == ente_id())))
    dati = {
        "processi_e_procedimenti": t["processi"], "di_cui_procedimenti": sum(x == "PROCEDIMENTO" for x in processi),
        "attivita": t["attivita"], "rischi": t["rischi"], "rischi_non_valutati": t["rischi_non_valutati"],
        "misure": t["misure"], "misure_generali": t["misure_generali"], "misure_specifiche": t["misure"] - t["misure_generali"],
        "rischi_per_livello_dal_piu_grave": {liv: r["per_livello"][liv] for liv in livelli},
        "aree_di_rischio": len(r["per_area"]),
    }  # fmt: skip
    tabella = Tabella("Rischi per area e livello", ["Area", "Rischi", *livelli, "Non valutati"], [
        [f"{a['codice']} - {a['descrizione']}" if a["codice"] else a["descrizione"], a["rischi"],
         *[a["per_livello"][liv] for liv in livelli], a["per_livello"]["None"]] for a in r["per_area"]
    ])  # fmt: skip
    return Sezione("mappatura", "Mappatura dei processi e valutazione del rischio", dati, [tabella])


async def _monitoraggio(anno: int) -> Sezione:
    c = await ac.cruscotto(anno)
    tot = c["totale"]
    attese = sum(s["attese"] for s in c["strutture"])
    precedente = next((a for a in c["anni"] if a["anno"] == anno - 1), None)
    dati = {
        "anno": anno, "misure_attese_dalle_strutture": attese, "dichiarazioni": tot["totale"],
        "attuate": tot["attuate"], "parzialmente_attuate": tot["parziali"], "non_attuate": tot["non_attuate"],
        "percentuale_attuate": tot["percentuale_attuate"], "verificate_dal_rpct": tot["verificate"],
        "contestate_dal_rpct": tot["contestate"], "da_verificare": tot["totale"] - tot["verificate"] - tot["contestate"],
        "strutture_con_misure_non_dichiarate": [f"{s['codice']} - {s['descrizione']}" for s in c["strutture"]
                                               if s["totale"] < s["attese"]],
    }  # fmt: skip
    if precedente and precedente["totale"]:
        dati["anno_precedente"] = {"anno": anno - 1, "dichiarazioni": precedente["totale"],
                                   "percentuale_attuate": precedente["percentuale_attuate"]}  # fmt: skip
    tabella = Tabella(f"Attuazione delle misure per struttura ({anno})",
                      ["Struttura", "Attese", "Dichiarate", "Attuate", "Parziali", "Non attuate", "% attuate"], [
        [f"{s['codice']} - {s['descrizione']}", s["attese"], s["totale"], s["attuate"], s["parziali"], s["non_attuate"],
         s["percentuale_attuate"]] for s in c["strutture"]
    ])  # fmt: skip
    return Sezione("monitoraggio", f"Attuazione delle misure di prevenzione ({anno})", dati, [tabella])


_ESITI = {"APPROVATA": "approvate", "RESPINTA": "respinte", "RESTITUITA": "restituite", "INVIATA": "in_attesa"}
_TIPI_PROPOSTA = {"CREA": "creazione", "MODIFICA": "modifica", "ELIMINA": "eliminazione"}
_OGGETTI = {"AREA": "aree", "PROCESSO": "processi", "ATTIVITA": "attività", "RISCHIO": "rischi", "MISURA": "misure"}


async def _proposte(anno: int) -> Sezione:
    righe = [p for p in await db().scalars(select(AcProposta).where(AcProposta.ente_id == ente_id()))
             if (p.inviata_il or p.created_at) and (p.inviata_il or p.created_at).year == anno]  # fmt: skip
    dati = {
        "anno": anno, "proposte_dei_referenti": len(righe),
        "per_esito": {v: sum(p.stato == k for p in righe) for k, v in _ESITI.items()},
        "per_tipo": {v: sum(p.tipo == k for p in righe) for k, v in _TIPI_PROPOSTA.items()},
        "per_oggetto": {v: sum(p.oggetto == k for p in righe) for k, v in _OGGETTI.items()},
    }
    return Sezione("proposte", f"Partecipazione dei referenti: proposte di aggiornamento ({anno})", dati)


async def _trasparenza() -> Sezione:
    sessione = db()
    e = ente()
    procedimenti = list(await sessione.scalars(
        select(AcProcesso).where(AcProcesso.ente_id == ente_id(), AcProcesso.tipo == "PROCEDIMENTO")))  # fmt: skip
    strutture = {s.id: s for s in await sessione.scalars(select(Struttura).where(Struttura.ente_id == ente_id()))}
    completi = sum(not dati_art35.mancanti(dati_art35.scheda(p, strutture)) for p in procedimenti)
    misure = list(await sessione.scalars(select(AcMisura).where(AcMisura.ente_id == ente_id())))
    trasparenza = [m for m in misure if m.obbligo_trasparenza or "traspar" in (m.categoria or "").lower()]
    dati = {
        "misure_di_trasparenza": len(trasparenza),
        "misure_collegate_a_un_obbligo_di_pubblicazione": sum(bool(m.obbligo_trasparenza) for m in trasparenza),
        "obblighi_di_pubblicazione_collegati": sorted({m.obbligo_trasparenza for m in trasparenza if m.obbligo_trasparenza}),
        "procedimenti_mappati": len(procedimenti), "procedimenti_con_dati_art35_completi": completi,
        "mappatura_pubblicata_sul_sito": bool(e.mappatura_pubblica),
        "procedimenti_pubblicati_sul_sito": bool(e.procedimenti_pubblici),
        "riferimento_normativo_procedimenti": "art. 35 d.lgs. 33/2013",
    }  # fmt: skip
    return Sezione("trasparenza", "Trasparenza", dati)


# --- PIAO: rischi corruttivi e trasparenza ----------------------------------------------------


async def _misure_piao() -> Sezione:
    misure = list(await db().scalars(select(AcMisura).where(AcMisura.ente_id == ente_id())))
    generali = Counter((m.categoria or "Senza categoria") for m in misure if m.tipo == "GENERALE")
    specifiche = [m for m in misure if m.tipo != "GENERALE"]
    dati = {
        "misure": len(misure), "misure_generali": sum(generali.values()), "misure_specifiche": len(specifiche),
        "misure_generali_per_categoria": dict(sorted(generali.items())),
        "misure_con_struttura_responsabile": sum(bool(m.struttura_id) for m in misure),
        "misure_con_indicatore_e_target": sum(bool(m.indicatore and m.target) for m in misure),
    }  # fmt: skip
    tabella = Tabella("Misure generali per categoria", ["Categoria", "Misure"], [[k, v] for k, v in sorted(generali.items())])
    return Sezione("misure", "Misure di prevenzione", dati, [tabella])


async def _rischi_gravi() -> Sezione:
    sessione = db()
    m = await ac.metodologia_ente()
    gravi = m.livelli[-2:]
    processi = {p.id: p for p in await sessione.scalars(select(AcProcesso).where(AcProcesso.ente_id == ente_id()))}
    attivita = {a.id: a for a in await sessione.scalars(select(AcAttivita).where(AcAttivita.ente_id == ente_id()))}
    misure = Counter(await sessione.scalars(select(AcMisura.rischio_id).where(AcMisura.ente_id == ente_id())))
    rischi = [r for r in await sessione.scalars(select(AcRischio).where(AcRischio.ente_id == ente_id())) if r.livello in gravi]
    rischi.sort(key=lambda r: (-m.livelli.index(r.livello), chiave_naturale(r.codice)))
    righe = []
    for r in rischi:
        p = processi[attivita[r.attivita_id].processo_id]
        righe.append([r.codice, f"{p.codice} - {p.denominazione}", r.evento, r.livello, misure.get(r.id, 0)])
    dati = {
        "livelli_considerati": list(reversed(gravi)), "rischi": len(rischi),
        "per_livello": {liv: sum(r.livello == liv for r in rischi) for liv in reversed(gravi)},
        "rischi_senza_misure": sum(misure.get(r.id, 0) == 0 for r in rischi),
        "processi_interessati": len({attivita[r.attivita_id].processo_id for r in rischi}),
    }  # fmt: skip
    tabella = Tabella("Rischi di livello più elevato", ["Codice", "Processo", "Evento rischioso", "Livello", "Misure"], righe)
    return Sezione("rischi_gravi", "Rischi di livello più elevato", dati, [tabella])


# --- relazione sulla performance -------------------------------------------------------------


async def _performance(piao_id: str | None, anno: int) -> list[Sezione]:
    sessione = db()
    piao = await sessione.get(PfPiao, piao_id) if piao_id else None
    if piao is None or piao.ente_id != ente_id():
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Scegli il PIAO")
    obiettivi = list(await sessione.scalars(select(PfObiettivo).where(PfObiettivo.piao_id == piao.id, PfObiettivo.anno == anno)))
    ids = [o.id for o in obiettivi]
    elementi: dict[str, list[PfElemento]] = {i: [] for i in ids}
    if ids:
        for x in await sessione.scalars(select(PfElemento).where(PfElemento.obiettivo_id.in_(ids))):
            elementi[x.obiettivo_id].append(x)
    strutture = {s.id: s for s in await sessione.scalars(select(Struttura).where(Struttura.ente_id == ente_id()))}
    fine_anno = min(date.today(), date(anno, 12, 31))
    completamento = {o.id: media_pesata((x.impegno, x.completamento) for x in elementi[o.id]) for o in obiettivi}
    ritardi = {o.id: sum(in_ritardo(x.scadenza, x.completamento, fine_anno) for x in elementi[o.id]) for o in obiettivi}
    per_struttura: dict[str, list[PfObiettivo]] = {}
    for o in obiettivi:
        per_struttura.setdefault(o.struttura_id, []).append(o)
    righe = []
    for sid, elenco in sorted(per_struttura.items(), key=lambda kv: chiave_naturale(strutture[kv[0]].codice if kv[0] in strutture else "")):
        s = strutture.get(sid)
        righe.append([f"{s.codice} - {s.descrizione}" if s else "—", len(elenco), sum(o.impegno for o in elenco),
                      media_pesata((o.impegno, completamento[o.id]) for o in elenco), sum(ritardi[o.id] for o in elenco)])  # fmt: skip
    tutti = [x for o in obiettivi for x in elementi[o.id]]
    sintesi = {
        "piao": piao.titolo, "anno": anno, "obiettivi": len(obiettivi), "strutture": len(per_struttura),
        "obiettivi_completati_al_100": sum((completamento[o.id] or 0) >= TOTALE for o in obiettivi),
        "completamento_medio_delle_strutture": media_pesata((1, r[3]) for r in righe),
        "azioni": sum(x.tipo == "AZIONE" for x in tutti), "misure_anticorruzione_collegate": sum(x.tipo == "MISURA" for x in tutti),
        "azioni_e_misure_in_ritardo": sum(ritardi.values()),
        "strutture_con_impegni_non_al_100": [r[0] for r in righe if r[2] != TOTALE],
    }  # fmt: skip
    tabella = Tabella(f"Obiettivi per struttura ({anno})", ["Struttura", "Obiettivi", "Impegno %", "Completamento %", "In ritardo"], righe)
    elenco = Tabella("Obiettivi", ["Struttura", "Codice", "Obiettivo", "Tipo", "Impegno %", "Completamento %"], [
        [strutture[o.struttura_id].codice if o.struttura_id in strutture else "—", o.codice or "", o.titolo, o.tipo.capitalize(),
         o.impegno, completamento[o.id]]
        for o in sorted(obiettivi, key=lambda o: (chiave_naturale(strutture[o.struttura_id].codice if o.struttura_id in strutture else ""),
                                                  chiave_naturale(o.codice or ""), o.titolo))
    ])  # fmt: skip
    per_tipo = Counter(o.tipo for o in obiettivi)
    return [
        Sezione("sintesi", "Sintesi dei risultati", sintesi, [tabella]),
        Sezione("obiettivi", "Obiettivi assegnati", {"anno": anno, "per_tipo": {k.lower(): v for k, v in per_tipo.items()},
                                                    "obiettivi": len(obiettivi)}, [elenco]),  # fmt: skip
    ]


# --- API -------------------------------------------------------------------------------------


async def _sezioni(tipo: str, p: Parametri) -> tuple[str, list[Sezione]]:
    if tipo == "RPCT":
        return f"Anno {p.anno}", [await _mappatura(), await _monitoraggio(p.anno), await _proposte(p.anno), await _trasparenza()]
    if tipo == "PIAO":
        return f"Triennio {p.anno}-{p.anno + 2}", [await _mappatura(), await _rischi_gravi(), await _misure_piao(), await _trasparenza()]
    piao = await db().get(PfPiao, p.piao_id) if p.piao_id else None
    return (f"{piao.titolo} - anno {p.anno}" if piao else f"Anno {p.anno}"), await _performance(p.piao_id, p.anno)


@bp.get("")
@autenticato(modulo=None)
async def tipi():
    """Relazioni che l'utente può preparare."""
    return [{"id": t, "titolo": titolo, "piao": t == "PERFORMANCE"} for t, (titolo, _, _) in TIPI.items() if _ammesso(t)]


@bp.get("/<tipo>")
@autenticato(modulo=None)
async def relazione(tipo: str):
    """Sezioni della relazione con i dati e le tabelle calcolati (senza testo)."""
    _controlla(tipo)
    sottotitolo, sezioni = await _sezioni(tipo, parametri(Parametri))
    return {"tipo": tipo, "titolo": TIPI[tipo][0], "sottotitolo": sottotitolo, "ente": ente().nome,
            "sezioni": [s.per_api() for s in sezioni]}  # fmt: skip


class TestoIn(Parametri):
    sezione: str = Field(min_length=1, max_length=50)


@bp.post("/<tipo>/testo")
@autenticato(modulo=None)
async def testo(tipo: str):
    """Testo di una sezione scritto dal modello dai soli dati della sezione, con i numeri che
    nei dati non compaiono (da verificare)."""
    _controlla(tipo)
    dati = corpo(TestoIn)
    _, sezioni = await _sezioni(tipo, dati)
    sezione = next((s for s in sezioni if s.id == dati.sezione), None)
    if sezione is None:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Sezione non trovata")
    llm = risorse().llm
    if llm is None:
        raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, "Modello linguistico non configurato")
    fatti = {**sezione.dati, **{f"tabella {i + 1}: {t.titolo}": {"intestazioni": t.intestazioni, "righe": t.righe[:60]}
                                for i, t in enumerate(sezione.tabelle)}}  # fmt: skip
    prompt = testo_prompt("relazione_utente", ente=ente().nome, relazione=TIPI[tipo][0], sezione=sezione.titolo,
                          dati=json.dumps(fatti, ensure_ascii=False, indent=1))  # fmt: skip
    try:
        scritto = (await llm.scrivi(testo_prompt("relazione_sistema"), prompt)).strip()
    except LlmError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    return {"sezione": sezione.id, "testo": scritto, "numeri_da_verificare": numeri_da_verificare(scritto, fatti)}


class SezioneEsportata(BaseModel):
    titolo: str = Field(max_length=500)
    testo: str = Field(default="", max_length=50_000)
    tabelle: list[dict] = Field(default_factory=list, max_length=20)


class EsportaIn(BaseModel):
    titolo: str = Field(min_length=1, max_length=500)
    sottotitolo: str = Field(default="", max_length=500)
    formato: Literal["docx", "odt"] = "docx"
    sezioni: list[SezioneEsportata] = Field(max_length=30)


@bp.post("/esporta")
@autenticato(modulo=None)
async def esporta():
    """La bozza rivista (titoli, testi, tabelle) in DOCX o ODT."""
    if not any(_ammesso(t) for t in TIPI):
        raise ErroreApi(HTTPStatus.FORBIDDEN, "Operazione non consentita")
    dati = corpo(EsportaIn)
    pagina = html_relazione(dati.titolo, f"{ente().nome} - {dati.sottotitolo}".strip(" -"),
                            [s.model_dump() for s in dati.sezioni])  # fmt: skip
    try:
        contenuto = await risorse().documenti.converti(pagina.encode(), "relazione.html", dati.formato)
    except DocumentiError as e:
        raise ErroreApi(HTTPStatus.BAD_GATEWAY, str(e)) from e
    nome = "".join(c if c.isalnum() else "-" for c in dati.titolo.lower()).strip("-")[:60] or "relazione"
    return allegato(contenuto, MIME[dati.formato], f"{nome}.{dati.formato}")
