"""Dati di pubblicazione dei procedimenti (art. 35 d.lgs. 33/2013, allegato 11 alla delibera
ANAC 495/2024) a partire dalla mappatura dell'anticorruzione.

Il procedimento ha i campi comuni con il processo (denominazione, descrizione, riferimenti
normativi, termine di conclusione, struttura responsabile = unità responsabile dell'istruttoria)
e, in `AcProcesso.art35`, i dati propri dell'art. 35 ([DatiArt35]): gli uffici sono strutture
organizzative, i cui recapiti (telefono, PEO, PEC, sede, orari, responsabile e qualifica) si
leggono al momento, così restano allineati in tutti i procedimenti.

[scheda] compone l'elemento nel formato dello schema ART_35 del modulo trasparenza (sezione
PROCEDIMENTI): lo usano l'indicatore di completezza, l'importazione nella scheda della
trasparenza e la pagina pubblica dei procedimenti. [mancanti] lo controlla con le stesse regole
del form della trasparenza (common/trasparenza/registro.py).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.trasparenza.registro import get_schema, valida_elemento

SCHEMA, SEZIONE = "ART_35", "PROCEDIMENTI"

# Strutture scelte nel procedimento (oltre alla struttura responsabile del processo)
STRUTTURE = ("uff_resp_struttura_id", "uff_finale_struttura_id", "ist_struttura_id", "sost_struttura_id")

_RE_URL = re.compile(r'^https?://[^\s/$.?#"<>]+[^\s"<>]*$', re.IGNORECASE)


class DatiArt35(BaseModel):
    """Dati propri del procedimento; tutti facoltativi (la completezza è un indicatore)."""

    model_config = ConfigDict(extra="forbid")

    tipologia: str | None = Field(default=None, max_length=255)
    # ufficio responsabile del procedimento (vuoto: la struttura responsabile del procedimento)
    uff_resp_struttura_id: str | None = None
    # ufficio competente all'adozione del provvedimento finale, se diverso
    uff_finale_struttura_id: str | None = None
    istanza_di_parte: Literal["SI", "NO"] | None = None
    ist_struttura_id: str | None = None  # ufficio per informazioni e istanze
    ist_modulistica: str | None = Field(default=None, max_length=2048)  # link
    modalita_info: str | None = Field(default=None, max_length=5000)
    dichiarazione_sostitutiva: Literal["SI", "NO"] | None = None
    silenzio_assenso: Literal["SI", "NO"] | None = None
    strumenti_tutela: str | None = Field(default=None, max_length=5000)
    servizio_online_link: str | None = Field(default=None, max_length=2048)
    servizio_online_tempi: str | None = Field(default=None, max_length=500)
    link_pagamenti: str | None = Field(default=None, max_length=2048)
    sost_struttura_id: str | None = None  # ufficio del titolare del potere sostitutivo
    sost_attivazione: str | None = Field(default=None, max_length=5000)

    @field_validator("*", mode="before")
    @classmethod
    def _vuoti(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("ist_modulistica", "servizio_online_link", "link_pagamenti")
    @classmethod
    def _url(cls, v):
        if v is not None and not _RE_URL.match(v):
            raise ValueError("URL non valido (deve iniziare con http:// o https://)")
        return v


def _uff(s) -> dict:
    return {"denom": s.descrizione if s else "", "tel": (s.telefono or "") if s else "",
            "peo": (s.peo or "") if s else "", "pec": (s.pec or "") if s else ""}  # fmt: skip


def scheda(p, strutture: dict) -> dict:
    """Elemento della sezione PROCEDIMENTI dello schema ART_35 per il procedimento [p]
    (AcProcesso), con i recapiti dalle [strutture] ({id: Struttura})."""
    d = DatiArt35.model_validate(p.art35 or {})
    responsabile = strutture.get(p.struttura_id)
    uff_resp = strutture.get(d.uff_resp_struttura_id or p.struttura_id)
    finale = strutture.get(d.uff_finale_struttura_id)
    diverso = finale is not None and finale is not uff_resp
    istanze = strutture.get(d.ist_struttura_id)
    sost = strutture.get(d.sost_struttura_id)
    r, f, i, so = _uff(uff_resp), _uff(finale), _uff(istanze), _uff(sost)
    elemento = {
        "tipologia": d.tipologia or "",
        "denominazione": p.denominazione or "",
        "descrizione": p.descrizione or "",
        "riferimenti_normativi": p.norma_riferimento or "",
        "unita_istruttoria": responsabile.descrizione if responsabile else "",
        "uff_resp_denom": r["denom"], "uff_resp_tel": r["tel"], "uff_resp_peo": r["peo"], "uff_resp_pec": r["pec"],
        "ufficio_finale_diverso": "SI" if diverso else "NO",
        "istanza_di_parte": d.istanza_di_parte or "",
        "modalita_info": d.modalita_info or "",
        "termine_conclusione": p.termine_conclusione or "",
        "dichiarazione_sostitutiva": d.dichiarazione_sostitutiva or "",
        "silenzio_assenso": d.silenzio_assenso or "",
        "strumenti_tutela": d.strumenti_tutela or "",
        "servizio_online_link": d.servizio_online_link or "",
        "servizio_online_tempi": d.servizio_online_tempi or "",
        "link_pagamenti": d.link_pagamenti or "",
        "sost_nominativo": (sost.responsabile or "") if sost else "",
        "sost_ufficio": so["denom"],
        "sost_qualifica": (sost.qualifica or "") if sost else "",
        "sost_tel": so["tel"], "sost_peo": so["peo"], "sost_pec": so["pec"],
        "sost_attivazione": d.sost_attivazione or "",
    }  # fmt: skip
    if diverso:
        elemento.update({"uff_finale_denom": f["denom"], "uff_finale_resp": finale.responsabile or "",
                         "uff_finale_tel": f["tel"], "uff_finale_peo": f["peo"], "uff_finale_pec": f["pec"]})  # fmt: skip
    if d.istanza_di_parte == "SI":
        elemento.update({
            "ist_ufficio": i["denom"], "ist_indirizzo": (istanze.sede or "") if istanze else "",
            "ist_telefono": i["tel"], "ist_peo": i["peo"], "ist_pec": i["pec"],
            "ist_modulistica": d.ist_modulistica or "",
            "orari": [dict(o) for o in ((istanze.orari or []) if istanze else [])],
        })  # fmt: skip
    return elemento


def mancanti(elemento: dict) -> list[str]:
    """Dati mancanti o non validi rispetto allo schema ART_35 (vuoto: completo)."""
    return valida_elemento(get_schema(SCHEMA), SEZIONE, elemento)


# --- importazione dal sito di Amministrazione trasparente o da documenti --------------------
# I procedimenti si estraggono (worker, common/trasparenza/estrazione.py, sezione PROCEDIMENTI
# dello schema ART_35) dalla pagina "Tipologie di procedimento" dell'ente o da un documento: il
# modello trascrive, non aggiunge. Qui si propongono gli abbinamenti con i procedimenti della
# mappatura e con le strutture; li conferma la persona, campo per campo.

SOGLIA_ABBINAMENTO = 0.72

# ufficio nella scheda -> campo della struttura scelta nel procedimento
UFFICI = {
    "unita_istruttoria": "struttura_id",
    "uff_resp_denom": "uff_resp_struttura_id",
    "uff_finale_denom": "uff_finale_struttura_id",
    "ist_ufficio": "ist_struttura_id",
    "sost_ufficio": "sost_struttura_id",
}


def _normalizza(testo: str) -> str:
    testo = re.sub(r"[^\w\s]", " ", (testo or "").lower())
    return re.sub(r"\s+", " ", testo).strip()


def somiglianza(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    a, b = _normalizza(a), _normalizza(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:  # "Servizi sociali" e "U.O. Servizi sociali e casa"
        return max(0.8, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def _migliore(nome: str, candidati: dict[str, str]) -> tuple[str | None, float]:
    """Id del candidato ({id: nome}) più simile a [nome], se supera la soglia."""
    migliore, valore = None, 0.0
    for chiave, testo in candidati.items():
        v = somiglianza(nome, testo)
        if v > valore:
            migliore, valore = chiave, v
    return (migliore, round(valore, 2)) if valore >= SOGLIA_ABBINAMENTO else (None, round(valore, 2))


def abbina(righe: list[dict], procedimenti: list, strutture: dict) -> list[dict]:
    """Per ogni procedimento estratto: il procedimento della mappatura più simile (se c'è) e la
    struttura proposta per ciascun ufficio citato (descrizione o codice)."""
    nomi_proc = {p.id: p.denominazione for p in procedimenti}
    nomi_strutture = {s.id: s.descrizione for s in strutture.values()}
    codici = {s.id: s.codice for s in strutture.values()}
    usati: set[str] = set()
    risultato = []
    for elemento in righe:
        liberi = {k: v for k, v in nomi_proc.items() if k not in usati}
        procedimento_id, valore = _migliore(elemento.get("denominazione") or "", liberi)
        if procedimento_id:
            usati.add(procedimento_id)
        uffici = {}
        for campo, destinazione in UFFICI.items():
            nome = (elemento.get(campo) or "").strip()
            if not nome:
                continue
            s_id, _ = _migliore(nome, nomi_strutture)
            if s_id is None:
                s_id, _ = _migliore(nome, codici)
            uffici[destinazione] = {"nome": nome, "struttura_id": s_id}
        risultato.append({"elemento": elemento, "procedimento_id": procedimento_id, "somiglianza": valore,
                          "uffici": uffici})  # fmt: skip
    return risultato
