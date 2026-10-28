"""
Estrazione dei dati di una scheda dalla fonte originale (pagina web o
documenti pubblicati) per precompilare il form di generazione.

Il modello risponde in JSON con una struttura imposta (response_schema)
ricavata dallo schema YAML: id dei campi, valori ammessi per le scelte,
parametri e sezioni. I valori restituiti vengono poi normalizzati in modo
deterministico nel formato richiesto dallo schema (date, importi,
percentuali, ...): è proprio questo che corregge i dati pubblicati in un
formato non conforme.

La chiamata al modello è passata come funzione asincrona `genera(prompt, schema_json)`
così da poter verificare la logica senza il modello. Lo schema è scritto nello stile di
Gemini (nullable, format enum); `json_schema` lo traduce nel JSON Schema standard accettato
da tutti i provider. Ripreso da PApuntozeroIA (estrazione.py).
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from collections.abc import Awaitable
from typing import Callable, Optional

from .registro import Campo, Schema, Sezione, VarianteAudit, _compatibile, _visibile

# Limite del testo inviato al modello (caratteri).
MAX_TESTO = 400_000
MAX_AVVISI = 30

Genera = Callable[[str, dict], Awaitable[dict]]


class EstrazioneNonRiuscita(Exception):
    """Errore con un messaggio già pronto per l'utente."""


# ---------------------------------------------------------------------------
# Struttura della risposta
# ---------------------------------------------------------------------------

_FORMATI = {
    "data": "data (es. 15/03/2026)",
    "anno": "anno a quattro cifre",
    "importo": "importo in euro",
    "percentuale": "percentuale",
    "numero": "numero intero",
    "decimale": "numero decimale",
    "url": "indirizzo web completo (http/https), anche se presente solo come link",
    "email": "indirizzo email",
    "telefono": "numero di telefono",
    "iban": "codice IBAN",
}


def _descrizione_campo(campo: Campo) -> str:
    parti = [campo.etichetta]
    if campo.descrizione:
        parti.append(campo.descrizione)
    if campo.tipo in _FORMATI:
        parti.append(f"Tipo: {_FORMATI[campo.tipo]}")
    if campo.tipo == "scelta" and not campo.opzioni:
        parti.append("Valori ammessi: " + "; ".join(campo.tutte_le_opzioni()))
    return ". ".join(p.rstrip(".") for p in parti)


def _schema_campo(campo: Campo) -> dict:
    if campo.tipo == "elenco":
        return {
            "type": "array",
            "description": f"{campo.etichetta}: un elemento per ogni {campo.etichetta_elemento.lower()}",
            "items": _schema_oggetto(campo.campi or []),
        }
    risultato = {"type": "string", "nullable": True, "description": _descrizione_campo(campo)}
    if campo.tipo == "scelta" and campo.opzioni:
        risultato.update(format="enum", enum=list(campo.opzioni))
    return risultato


def _schema_oggetto(campi: list) -> dict:
    return {"type": "object", "properties": {c.id: _schema_campo(c) for c in campi}}


def sezioni_candidate(schema: Schema, variante: Optional[VarianteAudit]) -> list:
    fissati = variante.parametri if variante else {}
    return [
        s for s in schema.sezioni
        if (not variante or not variante.sezioni or s.id in variante.sezioni) and _compatibile(s.visibile_se, fissati)
    ]


def schema_classificazione(schema: Schema, sezioni: list, variante: Optional[VarianteAudit]) -> dict:
    fissati = variante.parametri if variante else {}
    proprieta = {}
    if schema.parametri:
        proprieta["parametri"] = {
            "type": "object",
            "properties": {
                p.id: {
                    "type": "string",
                    "nullable": True,
                    "format": "enum",
                    "enum": [o.valore for o in p.opzioni if not fissati.get(p.id) or o.valore in fissati[p.id]],
                    "description": p.etichetta + ": " + "; ".join(f"{o.valore} = {o.etichetta}" for o in p.opzioni),
                }
                for p in schema.parametri
            },
        }
    proprieta["sezione"] = {
        "type": "string",
        "nullable": True,
        "format": "enum",
        "enum": [s.id for s in sezioni],
        "description": "Sezione dello schema a cui si riferiscono i dati del documento",
    }
    return {"type": "object", "properties": proprieta}


def schema_righe(sezione: Sezione, parametri: dict) -> dict:
    # Le condizioni sui parametri sono note: i campi esclusi non si chiedono.
    campi = [c for c in sezione.campi if _visibile_parametri(c, parametri)]
    righe = {"type": "array", "items": _schema_oggetto(campi)}
    if not sezione.ripetibile:
        righe["max_items"] = 1
    return {"type": "object", "properties": {"righe": righe}, "required": ["righe"]}


def _visibile_parametri(campo: Campo, parametri: dict) -> bool:
    """Valuta solo le condizioni sui parametri (quelle sui campi fratelli dipendono dalla riga)."""
    return all(str(parametri.get(k) or "") in v for k, v in campo.visibile_se.items() if k in parametri)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_REGOLE = """REGOLE:
- Riporta SOLO valori scritti esplicitamente nel documento: non dedurre, non completare, non inventare. Se un dato
  non c'è, lascia il campo null.
- Il documento può essere il report di un controllo (audit) sui dati pubblicati: in tal caso usa SOLO i valori
  effettivamente rilevati nel documento analizzato (es. colonna "Valore rilevato"); ignora esiti, punteggi, note
  correttive, suggerimenti e valori indicati come mancanti, assenti o da integrare.
- Copia date, importi, percentuali e numeri così come compaiono: verranno convertiti automaticamente nel formato
  richiesto.
- Per i link riporta l'indirizzo completo (anche se è presente solo come destinazione di un collegamento)."""


def prompt_classificazione(schema: Schema, sezioni: list) -> str:
    elenco = "\n".join(
        f"- {s.id}: {s.gruppo + ' - ' if s.gruppo else ''}{s.titolo}" for s in sezioni
    )
    return (
        f"Il documento seguente riguarda i dati pubblicati ai sensi dell'{schema.articolo} d.lgs. 33/2013 "
        f"({schema.titolo}). Indica le caratteristiche dell'ente o dell'atto richieste e la sezione a cui si "
        f"riferiscono i dati.\nSezioni possibili:\n{elenco}\n\n"
        "Scegli un valore solo se il documento lo indica in modo chiaro; altrimenti lascia null.\n\nDocumento:"
    )


def prompt_righe(schema: Schema, sezione: Sezione) -> str:
    quanti = (
        "Crea una voce di \"righe\" per ciascun elemento distinto (es. persona, incarico, atto, documento)."
        if sezione.ripetibile else "La sezione ammette UN SOLO elemento: \"righe\" contiene al massimo una voce."
    )
    titolo = f"{sezione.gruppo} - {sezione.titolo}" if sezione.gruppo else sezione.titolo
    return (
        f"Estrai dal documento seguente i dati della sezione \"{titolo}\" dello schema \"{schema.titolo}\" "
        f"({schema.articolo} d.lgs. 33/2013).\n{quanti}\n\n{_REGOLE}\n\nDocumento:"
    )


# ---------------------------------------------------------------------------
# Normalizzazione
# ---------------------------------------------------------------------------

_MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def _data(testo: str, separatore: str) -> Optional[str]:
    t = testo.strip().lower()
    giorno = mese = anno = None
    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        anno, mese, giorno = map(int, m.groups())
    elif m := re.search(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})\b", t):
        giorno, mese, anno = map(int, m.groups())
        if anno < 100:
            anno += 2000 if anno < 70 else 1900
    elif m := re.search(r"\b(\d{1,2})(?:°|º)?\s+(" + "|".join(_MESI) + r")\s+(\d{4})\b", t):
        giorno, mese, anno = int(m.group(1)), _MESI[m.group(2)], int(m.group(3))
    if giorno is None:
        return None
    try:
        d = date(anno, mese, giorno)
    except ValueError:
        return None
    return d.strftime(f"%d{separatore}%m{separatore}%Y")


def _numero(testo: str) -> Optional[Decimal]:
    t = re.sub(r"[^\d,.\-]", "", testo.replace("−", "-"))
    if not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        decimale = "," if t.rfind(",") > t.rfind(".") else "."
        migliaia = "." if decimale == "," else ","
        t = t.replace(migliaia, "").replace(decimale, ".")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif "." in t and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")  # punti come separatori delle migliaia
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _formatta(valore: Decimal, decimali: int, migliaia: bool) -> str:
    quanto = Decimal(1).scaleb(-decimali) if decimali else Decimal(1)
    arrotondato = valore.quantize(quanto, rounding=ROUND_HALF_UP)
    testo = f"{arrotondato:,.{decimali}f}" if migliaia else f"{arrotondato:.{decimali}f}"
    return testo.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _valore(campo: Campo, grezzo: str, elemento: dict) -> tuple:
    """(valore normalizzato, motivo dello scarto)."""
    t = re.sub(r"[ \t]+", " ", grezzo).strip()
    tipo = campo.tipo
    if tipo == "testo":
        return re.sub(r"\s+", " ", t), None
    if tipo == "testo_lungo":
        return t, None
    if tipo == "data":
        d = _data(t, campo.separatore_data)
        return (d, None) if d else (None, "data non interpretabile")
    if tipo == "anno":
        m = re.search(r"\b(19|20)\d{2}\b", t)
        return (m.group(0), None) if m else (None, "anno non interpretabile")
    if tipo in ("importo", "percentuale", "numero", "decimale"):
        n = _numero(t)
        if n is None:
            return None, "numero non interpretabile"
        if tipo == "importo":
            return _formatta(n, 2, True), None
        if tipo == "percentuale":
            if not 0 <= n <= 100:
                return None, "percentuale fuori dall'intervallo 0-100"
            return _formatta(n, 2, False), None
        if tipo == "numero":
            if n != n.to_integral_value():
                return None, "non è un numero intero"
            return str(int(n)), None
        if campo.decimali is not None:
            return _formatta(n, campo.decimali, False), None
        return format(n.normalize(), "f").replace(".", ","), None
    if tipo == "url":
        if re.match(r"^www\.", t, re.IGNORECASE):
            t = "https://" + t
        return (t, None) if re.match(r'^https?://[^\s"<>]+$', t, re.IGNORECASE) else (None, "indirizzo web non valido")
    if tipo == "email":
        m = re.search(r"[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", t)
        return (m.group(0).lower(), None) if m else (None, "email non valida")
    if tipo == "iban":
        return re.sub(r"\s+", "", t).upper(), None
    if tipo == "scelta":
        ammessi = campo.opzioni_effettive(elemento)
        uguale = next((o for o in ammessi if o.lower() == t.lower()), None)
        return (uguale, None) if uguale else (None, f"valore non previsto tra le scelte")
    return t, None


def _elementi(campi: list, grezzi: list, parametri: dict, etichetta: str, multipli: bool, avvisi: list) -> list:
    """Elementi normalizzati. [etichetta] precede i nomi dei campi negli avvisi (vuota: solo il campo)."""
    risultato = []
    for n, grezzo in enumerate(g for g in grezzi if isinstance(g, dict)):
        nome = f"{etichetta} {n + 1}" if multipli else etichetta
        elemento = {}
        # Prima le scelte: i campi con opzioni dipendenti e le condizioni di
        # visibilità si valutano sul valore già normalizzato.
        for campo in sorted(campi, key=lambda c: c.tipo != "scelta"):
            valore = grezzo.get(campo.id)
            if campo.tipo == "elenco":
                prefisso = f"{nome} > {campo.etichetta_elemento}" if nome else campo.etichetta_elemento
                sotto = _elementi(campo.campi or [], valore if isinstance(valore, list) else [], parametri,
                                  prefisso, True, avvisi)
                if sotto:
                    elemento[campo.id] = sotto
                continue
            if valore is None or str(valore).strip() == "":
                continue
            normalizzato, motivo = _valore(campo, str(valore), elemento)
            if normalizzato:
                elemento[campo.id] = normalizzato
            else:
                dove = f"{nome} - {campo.etichetta}" if nome else campo.etichetta
                avvisi.append(f"{dove}: \"{str(valore).strip()[:80]}\" non caricato ({motivo}).")
        contesto = {**parametri, **{k: v for k, v in elemento.items() if isinstance(v, str)}}
        elemento = {k: v for k, v in elemento.items()
                    if _visibile(next(c for c in campi if c.id == k).visibile_se, contesto)}
        if elemento:
            risultato.append({c.id: elemento[c.id] for c in campi if c.id in elemento})
    return risultato


# ---------------------------------------------------------------------------
# Orchestrazione
# ---------------------------------------------------------------------------

async def estrai(schema: Schema, variante: Optional[VarianteAudit], genera: Genera) -> dict:
    """
    Dati per il form di generazione (stesso formato dei dati salvati, con
    'pdf_type') e avvisi su ciò che non è stato possibile caricare.
    """
    avvisi: list = []
    candidate = sezioni_candidate(schema, variante)
    fissati = variante.parametri if variante else {}

    parametri: dict = {}
    sezione: Optional[Sezione] = candidate[0] if len(candidate) == 1 else None
    if schema.parametri or len(candidate) > 1:
        classificazione = await genera(prompt_classificazione(schema, candidate),
                                 schema_classificazione(schema, candidate, variante)) or {}
        for p in schema.parametri:
            valore = (classificazione.get("parametri") or {}).get(p.id)
            ammessi = fissati.get(p.id)
            if p.opzione(valore) and (not ammessi or valore in ammessi):
                parametri[p.id] = valore
            elif ammessi and len(ammessi) == 1:
                parametri[p.id] = ammessi[0]
        scelta = schema.sezione(str(classificazione.get("sezione") or ""))
        if scelta in candidate:
            sezione = scelta
        visibili = [s for s in candidate if _visibile(s.visibile_se, parametri)]
        if sezione is None or sezione not in visibili:
            sezione = visibili[0] if len(visibili) == 1 else None
        mancanti = [p.etichetta for p in schema.parametri if p.id not in parametri]
        if mancanti:
            avvisi.append("Non è stato possibile ricavare dal documento: " + ", ".join(mancanti) + ".")

    righe: list = []
    if sezione is None:
        avvisi.append("La sezione dello schema non è stata individuata: sceglila nel modulo e inserisci i dati.")
    else:
        risposta = await genera(prompt_righe(schema, sezione), schema_righe(sezione, parametri)) or {}
        grezze = risposta.get("righe") if isinstance(risposta.get("righe"), list) else []
        if not sezione.ripetibile and len(grezze) > 1:
            avvisi.append("La sezione ammette un solo elemento: è stato caricato il primo.")
            grezze = grezze[:1]
        righe = _elementi(sezione.campi, grezze, parametri,
                          sezione.etichetta_elemento if sezione.ripetibile else "", sezione.ripetibile, avvisi)
        if not righe:
            avvisi.append("Nel documento non sono stati trovati dati da caricare per la sezione.")

    if len(avvisi) > MAX_AVVISI:
        avvisi = avvisi[:MAX_AVVISI] + [f"... e altri {len(avvisi) - MAX_AVVISI} valori non caricati."]
    return {
        "dati": {
            "pdf_type": schema.id,
            "ambito_soggettivo": "TENUTO",
            "parametri": parametri,
            "sezione": sezione.id if sezione else None,
            "righe": righe,
            "note": "",
        },
        "avvisi": avvisi,
    }


# ---------------------------------------------------------------------------
# JSON Schema standard
# ---------------------------------------------------------------------------

def json_schema(schema: dict) -> dict:
    """Traduce lo schema in stile Gemini in JSON Schema standard (OpenAI, Claude, Ollama):
    "nullable" diventa il tipo null, "format: enum" sparisce, ogni oggetto elenca tutte le
    proprietà come richieste e non ne ammette altre (output strutturati rigorosi)."""
    risultato = {k: v for k, v in schema.items() if k not in ("nullable", "format", "max_items")}
    if schema.get("type") == "object":
        proprieta = {k: json_schema(v) for k, v in (schema.get("properties") or {}).items()}
        risultato.update(properties=proprieta, required=list(proprieta), additionalProperties=False)
    elif schema.get("type") == "array":
        risultato["items"] = json_schema(schema.get("items") or {"type": "string"})
    if schema.get("nullable"):
        risultato["type"] = [schema.get("type", "string"), "null"]
        if "enum" in risultato:
            risultato["enum"] = [*risultato["enum"], None]
    return risultato
