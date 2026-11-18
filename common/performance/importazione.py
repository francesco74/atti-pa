"""Obiettivi di performance letti da un documento (PIAO o Piano della performance) con l'LLM.

Il modello trascrive, parte per parte, le schede degli obiettivi: codice, titolo, descrizione,
struttura e responsabile, fasi (azioni) con la data di fine e indicatori con il valore atteso
come scritto (common/importazione). Qui, senza modello:

- `unisci`: lo stesso obiettivo letto in più parti (la scheda continua su più pagine, le parti
  si sovrappongono) diventa uno, con tutte le azioni e gli indicatori senza ripetizioni;
- `proposta`: l'obiettivo nella forma di atti-pa per un anno del PIAO. Le fasi diventano azioni
  (scadenza: la data di fine, o il 31/12 dell'anno); ogni indicatore va all'azione con più parole
  in comune (o alla prima) e il tipo si ricava dal valore atteso: una data è un indicatore DATA,
  "100%" PERCENTUALE, "6 n." NUMERO, altrimenti sì/no con un avviso. Senza fasi l'obiettivo ha
  una sola azione, con il suo titolo. Gli impegni partono da 0: li distribuisce chi importa;
- `abbina_struttura`: la struttura dell'ente più simile a quella scritta nel documento.

Nulla si salva senza la conferma di chi importa (api/src/routers/performance.py).
"""

from __future__ import annotations

import re
from datetime import date

from common.anticorruzione.art35 import somiglianza
from common.anticorruzione.catalogo import normalizza
from common.importazione import estrai_a_parti
from common.ricerca import somiglianza_parole

COSA = "obiettivi di performance"
SOGLIA_STRUTTURA = 0.6

_TESTO = {"type": "string"}
_FORSE = {"type": "string", "nullable": True}
SCHEMA = {
    "type": "object",
    "properties": {
        "obiettivi": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codice": _FORSE, "titolo": _TESTO, "descrizione": _FORSE, "struttura": _FORSE, "responsabile": _FORSE,
                    "azioni": {"type": "array", "items": {"type": "object", "properties": {"descrizione": _TESTO, "fine": _FORSE}}},
                    "indicatori": {"type": "array", "items": {"type": "object", "properties": {
                        "descrizione": _TESTO, "tipo": _FORSE, "valore_atteso": _FORSE}}},
                },
            },
        },
    },
}  # fmt: skip


def pertinente(parte: str) -> bool:
    """Una parte che può contenere schede di obiettivi (non il resto del PIAO)."""
    return bool(re.search(r"obiettiv", parte, re.I) and re.search(r"indicator|fas[ei]\b|azion|target|valore atteso", parte, re.I))


async def estrai(testo: str, llm, avanza=None) -> dict:
    """Gli obiettivi trovati nel documento (come trascritti, uniti) e gli avvisi."""
    risposte, avvisi = await estrai_a_parti(testo, llm, prompt="importazione_obiettivi", schema=SCHEMA,
                                            pertinente=pertinente, cosa=COSA, avanza=avanza)  # fmt: skip
    obiettivi = unisci([o for r in risposte for o in r.get("obiettivi") or [] if isinstance(o, dict)])
    if not obiettivi:
        avvisi.append("Nel documento non sono stati trovati obiettivi di performance")
    return {"obiettivi": obiettivi, "avvisi": avvisi}


# --- unione delle parti -----------------------------------------------------------------------


def _testo(v) -> str:
    return re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else ""


def _chiave(o: dict) -> str:
    codice = _testo(o.get("codice")).upper()
    return f"codice:{codice}" if codice else f"titolo:{normalizza(o.get('titolo'))}"


def unisci(grezzi: list[dict]) -> list[dict]:
    """Un obiettivo per codice (o, senza codice, per titolo), nell'ordine in cui compare: i campi
    dalla prima lettura che li ha, azioni e indicatori di tutte le letture senza ripetizioni."""
    per_chiave: dict[str, dict] = {}
    for g in grezzi:
        if not _testo(g.get("titolo")) and not _testo(g.get("codice")):
            continue
        o = per_chiave.setdefault(_chiave(g), {"codice": None, "titolo": "", "descrizione": None, "struttura": None,
                                                 "responsabile": None, "azioni": [], "indicatori": []})  # fmt: skip
        for campo in ("codice", "titolo", "struttura", "responsabile"):
            if not o[campo] and _testo(g.get(campo)):
                o[campo] = _testo(g.get(campo))
        descrizione = (g.get("descrizione") or "").strip() if isinstance(g.get("descrizione"), str) else ""
        if len(descrizione) > len(o["descrizione"] or ""):  # la più completa
            o["descrizione"] = descrizione
        for lista, campi in (("azioni", ("descrizione", "fine")), ("indicatori", ("descrizione", "tipo", "valore_atteso"))):
            for x in g.get(lista) or []:
                if not isinstance(x, dict) or not _testo(x.get("descrizione")):
                    continue
                nuovo = {c: _testo(x.get(c)) or None for c in campi}
                if not any(_stesso(nuovo["descrizione"], y["descrizione"]) for y in o[lista]):
                    o[lista].append(nuovo)
    for o in per_chiave.values():
        # un indicatore trascritto per errore anche come fase (succede in una delle letture
        # sovrapposte): la fase si toglie, se ne restano altre
        fasi = [a for a in o["azioni"] if not any(_uguale(a["descrizione"], i["descrizione"]) for i in o["indicatori"])]
        if fasi:
            o["azioni"] = fasi
    return list(per_chiave.values())


def _uguale(a: str, b: str) -> bool:
    return normalizza(a) == normalizza(b) or somiglianza_parole(a, b) >= 0.9


def _stesso(a: str, b: str) -> bool:
    """Due trascrizioni della stessa azione o dello stesso indicatore (da parti sovrapposte):
    stesso testo, uno l'inizio dell'altro (troncato a fine parte) o quasi le stesse parole."""
    na, nb = normalizza(a), normalizza(b)
    if na == nb:
        return True
    corto, lungo = sorted((na, nb), key=len)
    return (len(corto) >= 30 and lungo.startswith(corto)) or somiglianza_parole(a, b) >= 0.8


# --- forma di atti-pa ---------------------------------------------------------------------------

_RE_DATA = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b")
_RE_DATA_SENZA_ANNO = re.compile(r"\b(\d{1,2})[/.](\d{1,2})\b(?![/.\-]?\d)")
_RE_NUMERO = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")
_UNITA_VUOTE = {"", "n", "nr", "num", "numero", "n°"}


def data_da_testo(testo: str | None, anno: int | None = None) -> date | None:
    """La prima data del testo (GG/MM/AAAA, anche con punti o trattini); con [anno] anche GG/MM."""
    if not testo:
        return None
    if m := _RE_DATA.search(testo):
        g, mese, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = a + 2000 if a < 100 else a
    elif anno and (m := _RE_DATA_SENZA_ANNO.search(testo)):
        g, mese, a = int(m.group(1)), int(m.group(2)), anno
    else:
        return None
    try:
        return date(a, mese, g)
    except ValueError:
        return None


def _numero(testo: str) -> tuple[float, str] | None:
    """Il primo numero del testo in forma italiana (1.558.203 · 2,5 · 95,00) e il resto del testo."""
    m = _RE_NUMERO.search(testo)
    if m is None:
        return None
    cifre = m.group(0)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", cifre):
        cifre = cifre.replace(".", "")
    try:
        valore = float(cifre.replace(",", "."))
    except ValueError:
        return None
    return valore, (testo[: m.start()] + " " + testo[m.end():]).strip()


def indicatore(grezzo: dict, anno: int) -> tuple[dict, str | None]:
    """L'indicatore di atti-pa dal valore atteso scritto nel documento, con l'avviso se non si è
    capito che valore raggiungere."""
    descrizione = _testo(grezzo.get("descrizione"))[:2000]
    valore = _testo(grezzo.get("valore_atteso"))
    base = {"descrizione": descrizione, "tipo": "SI_NO", "unita": None, "partenza": None, "target": None,
            "target_data": None, "verso": "CRESCENTE", "fonte": None}  # fmt: skip
    if (d := data_da_testo(valore)) is not None:
        return {**base, "tipo": "DATA", "target_data": d.isoformat()}, None
    if re.fullmatch(r"(?i)s[iì]|no|fatto|realizzat[oa]", valore):
        return base, None
    if (n := _numero(valore)) is not None:
        target, resto = n
        if "%" in resto and 0 <= target <= 100:
            return {**base, "tipo": "PERCENTUALE", "target": target}, None
        unita = resto.replace("%", " %").strip(" .:")
        return {**base, "tipo": "NUMERO", "target": target,
                "unita": None if unita.lower().strip(" .°") in _UNITA_VUOTE else unita[:50]}, None  # fmt: skip
    avviso = f"«{descrizione[:80]}»: valore atteso {'«' + valore + '» ' if valore else ''}non riconosciuto, impostato come sì/no"
    return base, avviso


def proposta(o: dict, anno: int) -> dict:
    """L'obiettivo letto nella forma di atti-pa per l'[anno]: azioni dalle fasi, ciascuna con
    i suoi indicatori, impegni a 0, e gli avvisi su ciò che si è dovuto supporre."""
    fine_anno = date(anno, 12, 31)
    avvisi: list[str] = []
    azioni = []
    for a in o.get("azioni") or []:
        scadenza = data_da_testo(a.get("fine"), anno) or fine_anno
        azioni.append({"descrizione": a["descrizione"], "scadenza": scadenza.isoformat(), "indicatori": []})
    if not azioni:
        azioni.append({"descrizione": o.get("titolo") or o.get("codice") or "Obiettivo", "scadenza": fine_anno.isoformat(),
                       "indicatori": []})  # fmt: skip
    for g in o.get("indicatori") or []:
        ind, avviso = indicatore(g, anno)
        if avviso:
            avvisi.append(avviso)
        vicina = max(azioni, key=lambda a: somiglianza_parole(ind["descrizione"], a["descrizione"]))
        if somiglianza_parole(ind["descrizione"], vicina["descrizione"]) == 0:
            vicina = azioni[0]
        vicina["indicatori"].append(ind)
    return {
        "codice": (o.get("codice") or None) and o["codice"][:100],
        "titolo": (o.get("titolo") or o.get("codice") or "")[:500],
        "descrizione": o.get("descrizione"),
        "tipo": "OPERATIVO",
        "struttura": o.get("struttura"),
        "responsabile": o.get("responsabile"),
        "elementi": azioni,
        "avvisi": avvisi,
    }


def abbina_struttura(nome: str | None, strutture: list) -> str | None:
    """L'id della struttura (oggetti con id, codice, descrizione) più simile al [nome] scritto
    nel documento, se abbastanza simile."""
    if not nome:
        return None
    migliore, valore = None, 0.0
    for s in strutture:
        v = max(somiglianza(nome, s.descrizione), somiglianza(nome, f"{s.codice} {s.descrizione}"),
                somiglianza_parole(nome, f"{s.codice} {s.descrizione}"))  # fmt: skip
        if v > valore:
            migliore, valore = s.id, v
    return migliore if valore >= SOGLIA_STRUTTURA else None
