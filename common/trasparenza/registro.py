"""
Registro degli schemi di pubblicazione ANAC definiti come file YAML in schemi/: il catalogo
è unico per tutti gli enti (le linee guida sono nazionali).

Ogni file è l'unica fonte di uno schema: da qui derivano
- la validazione dei dati inviati dal form di generazione (valida_dati);
- il documento HTML generato (genera_documento);
- il prompt di audit, anche nelle sue varianti (genera_prompt);
- la definizione servita all'app per costruire il form (GET /api/v1/trasparenza/schemi).

I file vengono validati all'avvio, compresi i riferimenti incrociati
(parametri, campi, sezioni): un errore in uno schema blocca il servizio
invece di emergere durante l'uso.

Formato dei dati inviati dal form:
    {
      "ambito_soggettivo": "TENUTO" | "PARZIALE" | "NON_TENUTO",
      "parametri": {"<id parametro>": "<valore>"},
      "alternativo": "<url>",            # solo se si usa l'adempimento alternativo
      "note": "<testo libero da riportare nel documento>",   # facoltativo
      "sezione": "<id sezione>",
      "righe": [{"<id campo>": "<valore>" | [{...sotto-elementi...}]}]
    }
"""
import os
import re
from datetime import datetime
from typing import Literal, Optional

import html as html_lib

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemi")

TipoCampo = Literal[
    "testo", "testo_lungo", "data", "anno", "url", "email", "telefono",
    "importo", "percentuale", "numero", "decimale", "iban", "scelta", "elenco",
]
Aggiornamento = Literal["tempestivo", "trimestrale", "semestrale", "annuale"]
VALORI_AMBITO = {"TENUTO", "PARZIALE", "NON_TENUTO"}

# Condizione di visibilità: {chiave: [valori ammessi]}. La chiave è l'id di un
# parametro dello schema o di un campo fratello dello stesso elemento.
Condizione = dict[str, list[str]]


# ---------------------------------------------------------------------------
# Modello dello schema
# ---------------------------------------------------------------------------

class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _visibile(condizione: Condizione, contesto: dict) -> bool:
    return all(str(contesto.get(chiave) or "") in valori for chiave, valori in condizione.items())


class Campo(_Base):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    etichetta: str
    descrizione: str = ""
    tipo: TipoCampo
    obbligatorio: bool = False
    # Sotto-titolo sotto cui raggruppare il campo nel form e nel documento
    # (es. "Conto economico"): i campi consecutivi con lo stesso gruppo
    # vengono presentati insieme.
    gruppo: str = ""
    opzioni: Optional[list[str]] = None
    # Opzioni che dipendono dal valore di un campo fratello di tipo 'scelta'.
    opzioni_da: Optional[str] = None
    opzioni_per: Optional[dict[str, list[str]]] = None
    max_lunghezza: Optional[int] = None
    # Solo per il tipo 'decimale': numero esatto di cifre decimali richieste.
    decimali: Optional[int] = None
    # Solo per il tipo 'data': separatore richiesto dallo schema (es. "." per GG.MM.AAAA).
    separatore_data: Literal["/", "."] = "/"
    visibile_se: Condizione = {}
    # Solo per il tipo 'elenco': i campi di ogni sotto-elemento.
    campi: Optional[list["Campo"]] = None
    etichetta_elemento: str = "Elemento"

    @model_validator(mode="after")
    def _coerenza(self):
        if self.tipo == "scelta":
            dipendenti = self.opzioni_da and self.opzioni_per
            if not self.opzioni and not dipendenti:
                raise ValueError(f"il campo '{self.id}' di tipo 'scelta' richiede 'opzioni' o 'opzioni_da' + 'opzioni_per'")
        elif self.opzioni or self.opzioni_da or self.opzioni_per:
            raise ValueError(f"il campo '{self.id}' ha opzioni ma non è di tipo 'scelta'")
        if self.separatore_data != "/" and self.tipo != "data":
            raise ValueError(f"il campo '{self.id}' ha 'separatore_data' ma non è di tipo 'data'")
        if self.decimali is not None and self.tipo != "decimale":
            raise ValueError(f"il campo '{self.id}' ha 'decimali' ma non è di tipo 'decimale'")
        if self.tipo == "elenco":
            if not self.campi:
                raise ValueError(f"il campo '{self.id}' di tipo 'elenco' richiede 'campi'")
            if any(c.tipo == "elenco" for c in self.campi):
                raise ValueError(f"il campo '{self.id}': gli elenchi annidati su più livelli non sono supportati")
            _verifica_campi_fratelli(self.campi, f"elenco '{self.id}'")
        elif self.campi:
            raise ValueError(f"il campo '{self.id}' ha 'campi' ma non è di tipo 'elenco'")
        return self

    def opzioni_effettive(self, elemento: dict) -> list:
        if self.opzioni:
            return self.opzioni
        return (self.opzioni_per or {}).get(str(elemento.get(self.opzioni_da) or ""), [])

    def tutte_le_opzioni(self) -> list:
        if self.opzioni:
            return self.opzioni
        viste = []
        for valori in (self.opzioni_per or {}).values():
            viste += [v for v in valori if v not in viste]
        return viste


Campo.model_rebuild()


def _verifica_campi_fratelli(campi: list, dove: str):
    ids = [c.id for c in campi]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{dove}: id dei campi duplicati")
    per_id = {c.id: c for c in campi}
    for c in campi:
        if c.opzioni_da:
            origine = per_id.get(c.opzioni_da)
            if not origine or origine.tipo != "scelta":
                raise ValueError(f"{dove}: 'opzioni_da' del campo '{c.id}' deve indicare un campo 'scelta' fratello")
            mancanti = set(origine.tutte_le_opzioni()) - set(c.opzioni_per or {})
            if mancanti:
                raise ValueError(f"{dove}: 'opzioni_per' del campo '{c.id}' non copre {sorted(mancanti)}")


class Sezione(_Base):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    titolo: str
    gruppo: str = ""
    collocazione: str
    aggiornamento: Aggiornamento
    norme: list[str] = []
    ripetibile: bool = True
    etichetta_elemento: str = "Elemento"
    visibile_se: Condizione = {}
    # Gruppi di campi di cui almeno uno deve essere compilato in ogni elemento.
    almeno_uno: list[list[str]] = []
    # Indicazione mostrata nel form, nel documento e nel prompt.
    nota: str = ""
    layout: Optional[Literal["tabella", "scheda"]] = None
    campi: list[Campo] = Field(min_length=1)
    # Nell'analisi IA ogni sezione è un controllo a sé. Una sezione che è solo
    # un modo alternativo di pubblicare gli stessi dati (es. collegamento al
    # Registro Nazionale degli Aiuti) indica qui l'id della sezione principale
    # e ne condivide il controllo.
    controllo: str = ""
    # Regole di audit della sezione: entrano nel prompt del suo controllo.
    # Testo, oppure elenco di blocchi (per riusare note comuni con le ancore YAML).
    note_audit: str | list[str] = ""

    @property
    def testo_note_audit(self) -> str:
        if isinstance(self.note_audit, str):
            return self.note_audit.strip()
        return "\n".join(n.strip() for n in self.note_audit)

    @model_validator(mode="after")
    def _coerenza(self):
        _verifica_campi_fratelli(self.campi, f"sezione '{self.id}'")
        ids = {c.id for c in self.campi}
        for gruppo in self.almeno_uno:
            if len(gruppo) < 2 or not set(gruppo) <= ids:
                raise ValueError(f"sezione '{self.id}': 'almeno_uno' deve elencare almeno due campi della sezione")
        return self

    @property
    def layout_effettivo(self) -> str:
        if self.layout:
            return self.layout
        semplice = self.ripetibile and len(self.campi) <= 6 and all(c.tipo != "elenco" for c in self.campi)
        return "tabella" if semplice else "scheda"


class OpzioneParametro(_Base):
    valore: str
    etichetta: str
    # Indicazione legata alla scelta (es. obblighi sospesi): form, documento e prompt.
    nota: str = ""


class Parametro(_Base):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    etichetta: str
    descrizione: str = ""
    opzioni: list[OpzioneParametro] = Field(min_length=1)

    def opzione(self, valore) -> Optional[OpzioneParametro]:
        return next((o for o in self.opzioni if o.valore == valore), None)


class AdempimentoAlternativo(_Base):
    """Obbligo assolto con il solo collegamento a una banca dati nazionale (es. Soldi pubblici, BDAP)."""
    etichetta: str
    descrizione: str
    etichetta_link: str
    testo_documento: str
    nota_audit: str = ""


class VarianteAudit(_Base):
    """Controllo dell'analisi IA dedicato a una parte dello schema (es. ART_14_POL, o un controllo generato per sezione)."""
    id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    titolo: str
    sezioni: list[str] = []
    parametri: Condizione = {}
    # Testo, oppure elenco di blocchi (permette di riusare note comuni con le ancore YAML).
    note: str | list[str] = ""

    @property
    def testo_note(self) -> str:
        return self.note if isinstance(self.note, str) else "\n".join(n.strip() for n in self.note)


class Fonte(_Base):
    # "anac": schema di pubblicazione approvato con delibera ANAC (art. 48
    # d.lgs. 33/2013). "normativa": per l'obbligo ANAC non ha approvato uno
    # schema; i dati della scheda sono ricavati direttamente da [norme].
    tipo: Literal["anac", "normativa"] = "anac"
    delibera: Optional[str] = None
    modificata_da: Optional[str] = None
    allegato: Optional[int] = None
    versione: Optional[str] = None
    norme: list[str] = []

    @model_validator(mode="after")
    def _coerenza(self):
        if self.tipo == "anac":
            if not self.delibera or self.allegato is None:
                raise ValueError("una fonte ANAC richiede 'delibera' e 'allegato'")
            if self.norme:
                raise ValueError("'norme' si indica solo per le fonti di tipo 'normativa'")
        else:
            if not self.norme:
                raise ValueError("una fonte 'normativa' richiede l'elenco delle 'norme'")
            if self.delibera or self.allegato is not None or self.modificata_da or self.versione:
                raise ValueError("una fonte 'normativa' non ha delibera, allegato, modifiche né versione ANAC")
        return self

    @property
    def anac(self) -> bool:
        return self.tipo == "anac"

    @property
    def descrizione(self) -> str:
        if not self.anac:
            return "scheda non approvata da ANAC, ricavata da: " + "; ".join(self.norme)
        testo = f"Allegato {self.allegato} alla delibera n. {self.delibera}"
        if self.modificata_da:
            testo += f", come modificato dalla delibera n. {self.modificata_da}"
        if self.versione:
            testo += f", agg. {self.versione}"
        return testo

    @property
    def breve(self) -> str:
        if not self.anac:
            return "Schema non ANAC"
        testo = f"All. {self.allegato} Del. {self.delibera.split('/')[0]}"
        if self.modificata_da:
            testo += f" (mod. Del. {self.modificata_da.split('/')[0]})"
        return testo


class Documento(_Base):
    titolo: str
    sottotitolo: str = ""
    introduzione: str


class Schema(_Base):
    id: str = Field(pattern=r"^ART_[A-Z0-9_]+$")
    articolo: str
    titolo: str
    # Sotto-sezione di primo livello di "Amministrazione trasparente" in cui lo
    # schema viene presentato; se assente si usa quella della prima sezione.
    categoria: Optional[str] = None
    fonte: Fonte
    ambito: Literal["non_applicabile", "autodichiarazione"]
    ambito_soggettivo: str = ""
    documento: Documento
    parametri: list[Parametro] = []
    adempimento_alternativo: Optional[AdempimentoAlternativo] = None
    sezioni: list[Sezione] = Field(min_length=1)
    note_audit: str = ""
    # Controlli dell'analisi IA. Negli schemi con più sezioni sono generati
    # automaticamente, uno per sezione (vedi _genera_controlli): l'utente
    # sceglie la sezione da verificare. Si scrivono a mano solo negli schemi
    # con una sezione (es. art. 14, controlli per tipo di soggetto).
    audit: list[VarianteAudit] = []
    # Eccezione alla regola "un controllo per sezione": l'analisi IA propone un
    # solo controllo per tutto lo schema (es. art. 36, dove le sezioni sono i
    # casi alternativi della stessa pagina e il modello individua quello giusto).
    controllo_unico: bool = False

    @field_validator("sezioni")
    @classmethod
    def _id_sezioni_unici(cls, sezioni):
        ids = [s.id for s in sezioni]
        if len(ids) != len(set(ids)):
            raise ValueError("id delle sezioni duplicati")
        return sezioni

    @model_validator(mode="after")
    def _riferimenti_incrociati(self):
        parametri = {p.id: {o.valore for o in p.opzioni} for p in self.parametri}

        def verifica(condizione: Condizione, fratelli: dict, dove: str):
            for chiave, valori in condizione.items():
                if chiave in parametri:
                    ammessi = parametri[chiave]
                elif chiave in fratelli and fratelli[chiave].tipo == "scelta":
                    ammessi = set(fratelli[chiave].tutte_le_opzioni())
                else:
                    raise ValueError(f"{dove}: 'visibile_se' usa '{chiave}', che non è un parametro né un campo scelta fratello")
                if not set(valori) <= ammessi:
                    raise ValueError(f"{dove}: 'visibile_se' usa valori non ammessi per '{chiave}': {sorted(set(valori) - ammessi)}")

        for s in self.sezioni:
            verifica(s.visibile_se, {}, f"sezione '{s.id}'")
            fratelli = {c.id: c for c in s.campi}
            for c in s.campi:
                verifica(c.visibile_se, fratelli, f"campo '{s.id}.{c.id}'")
                for sc in c.campi or []:
                    verifica(sc.visibile_se, {x.id: x for x in c.campi}, f"campo '{s.id}.{c.id}.{sc.id}'")

        sezioni = {s.id for s in self.sezioni}
        for s in self.sezioni:
            if s.controllo and (s.controllo not in sezioni or self.sezione(s.controllo).controllo):
                raise ValueError(f"sezione '{s.id}': 'controllo' deve indicare una sezione principale esistente")
        for v in self.audit:
            if not set(v.sezioni) <= sezioni:
                raise ValueError(f"variante '{v.id}': sezioni inesistenti {sorted(set(v.sezioni) - sezioni)}")
            verifica(v.parametri, {}, f"variante '{v.id}'")
        if self.controlli_per_sezione:
            if self.audit:
                raise ValueError(
                    "con più sezioni i controlli dell'analisi sono generati uno per sezione: "
                    "le regole vanno in 'note_audit' delle sezioni, non in 'audit'"
                )
            self.audit = self._genera_controlli()
        return self

    @property
    def controlli_per_sezione(self) -> bool:
        """Più sezioni (o gruppi di sezioni alternative): un controllo per ciascuna."""
        return not self.controllo_unico and len({s.controllo or s.id for s in self.sezioni}) > 1

    def _genera_controlli(self) -> list:
        gruppi: dict = {}
        for s in self.sezioni:
            gruppi.setdefault(s.controllo or s.id, []).append(s)
        controlli = []
        for principale_id, sezioni in gruppi.items():
            principale = self.sezione(principale_id)
            # Parametri fissati dal controllo: i valori per cui almeno una delle
            # sue sezioni è prevista (solo le chiavi comuni a tutte).
            chiavi = set.intersection(*(set(s.visibile_se) for s in sezioni))
            parametri = {}
            for chiave in chiavi:
                valori = []
                for s in sezioni:
                    valori += [v for v in s.visibile_se[chiave] if v not in valori]
                parametri[chiave] = valori
            controlli.append(VarianteAudit(
                id=f"{self.id}_{principale_id}",
                titolo=f"{principale.gruppo} - {principale.titolo}" if principale.gruppo else principale.titolo,
                sezioni=[s.id for s in sezioni],
                parametri=parametri,
            ))
        return controlli

    def sezione(self, sezione_id: str) -> Optional[Sezione]:
        return next((s for s in self.sezioni if s.id == sezione_id), None)

    def parametro(self, parametro_id: str) -> Optional[Parametro]:
        return next((p for p in self.parametri if p.id == parametro_id), None)

    def variante(self, variante_id: str) -> Optional[VarianteAudit]:
        return next((v for v in self.audit if v.id == variante_id), None)

    @property
    def riferimento(self) -> str:
        return f"{self.fonte.breve} - {self.articolo[0].upper()}{self.articolo[1:]}"

    @property
    def categoria_at(self) -> str:
        return self.categoria or self.sezioni[0].collocazione.split("->")[0].strip()

    @property
    def frasi_ambito(self) -> dict:
        """Frase riportata nel documento per ciascun valore dell'ambito soggettivo."""
        if self.ambito == "autodichiarazione":
            return {
                "TENUTO": f"Soggetto tenuto all'obbligo di pubblicazione ex {self.articolo}",
                "PARZIALE": f"Soggetto tenuto parzialmente all'obbligo di pubblicazione ex {self.articolo}",
                "NON_TENUTO": f"Soggetto non tenuto all'obbligo di pubblicazione ex {self.articolo}",
            }
        return {"NON_TENUTO": FRASE_NON_APPLICABILE}

    def per_frontend(self) -> dict:
        dati = self.model_dump()
        dati["riferimento"] = self.riferimento
        dati["categoria_at"] = self.categoria_at
        dati["fonte_descrizione"] = self.fonte.descrizione
        dati["schema_anac"] = self.fonte.anac
        dati["frasi_ambito"] = self.frasi_ambito
        # Nell'analisi si sceglie sempre uno dei controlli: niente controllo complessivo.
        dati["solo_varianti"] = self.controlli_per_sezione
        return dati


# ---------------------------------------------------------------------------
# Caricamento
# ---------------------------------------------------------------------------

def _carica_schemi(cartella: str = SCHEMI_DIR) -> dict:
    schemi = {}
    if not os.path.isdir(cartella):
        return schemi
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith((".yaml", ".yml")):
            continue
        percorso = os.path.join(cartella, nome)
        with open(percorso, encoding="utf-8") as f:
            grezzo = yaml.safe_load(f) or {}
        # Le chiavi che iniziano con '_' servono solo come ancore YAML.
        grezzo = {k: v for k, v in grezzo.items() if not str(k).startswith("_")}
        try:
            schema = Schema.model_validate(grezzo)
        except Exception as e:
            raise RuntimeError(f"Schema non valido in {nome}: {e}") from e
        if os.path.splitext(nome)[0] != schema.id:
            raise RuntimeError(f"Il file {nome} deve chiamarsi {schema.id}.yaml")
        schemi[schema.id] = schema

    varianti = [v.id for s in schemi.values() for v in s.audit]
    duplicati = {v for v in varianti if varianti.count(v) > 1 or v in schemi}
    if duplicati:
        raise RuntimeError(f"Id di varianti di audit duplicati: {sorted(duplicati)}")
    return schemi


SCHEMI: dict = _carica_schemi()


def get_schema(schema_id: str) -> Optional[Schema]:
    return SCHEMI.get(schema_id)


def trova_prompt(nome: str):
    """(schema, variante) per un nome di prompt: lo schema stesso o una sua variante di audit."""
    if nome in SCHEMI:
        return SCHEMI[nome], None
    for schema in SCHEMI.values():
        variante = schema.variante(nome)
        if variante:
            return schema, variante
    return None, None


# ---------------------------------------------------------------------------
# Validazione dei dati inviati dal form
# ---------------------------------------------------------------------------

# Niente spazi, virgolette o parentesi angolari: un URL non deve poter uscire dall'attributo href.
_RE_URL = re.compile(r'^https?://[^\s/$.?#"<>]+[^\s"<>]*$', re.IGNORECASE)
_RE_EMAIL = re.compile(r"^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_RE_TELEFONO = re.compile(r"^[+\d][\d\s./-]{4,}$")
_RE_IMPORTO = re.compile(r"^-?(0|[1-9]\d{0,2}(\.\d{3})*),\d{2}$")
_RE_PERCENTUALE = re.compile(r"^\d{1,3}(,\d{1,2})?$")


def _errore_valore(campo: Campo, valore: str, elemento: dict) -> Optional[str]:
    """Messaggio di errore se il valore non rispetta il tipo del campo, altrimenti None."""
    tipo = campo.tipo
    if tipo == "data":
        sep = campo.separatore_data
        try:
            datetime.strptime(valore, f"%d{sep}%m{sep}%Y")
        except ValueError:
            return f"data non valida (formato GG{sep}MM{sep}AAAA)"
    elif tipo == "iban":
        if not re.fullmatch(r"IT\d{2}[A-Z]\d{10}[0-9A-Z]{12}", valore.replace(" ", "").upper()):
            return "IBAN non valido (formato italiano di 27 caratteri, es. IT60X0542811101000000123456)"
    elif tipo == "anno":
        if not re.fullmatch(r"(19|20)\d\d", valore):
            return "anno non valido (4 cifre)"
    elif tipo == "url":
        if not _RE_URL.match(valore):
            return "URL non valido (deve iniziare con http:// o https://)"
    elif tipo == "email":
        if not _RE_EMAIL.match(valore):
            return "indirizzo email non valido"
    elif tipo == "telefono":
        if not _RE_TELEFONO.match(valore):
            return "recapito telefonico non valido"
    elif tipo == "importo":
        if not _RE_IMPORTO.match(valore):
            return "importo non valido (es. 1.234,56)"
    elif tipo == "percentuale":
        if not _RE_PERCENTUALE.match(valore) or float(valore.replace(",", ".")) > 100:
            return "percentuale non valida (es. 45,50)"
    elif tipo == "numero":
        if not re.fullmatch(r"\d+", valore):
            return "numero intero non valido"
    elif tipo == "decimale":
        cifre = r"\d+" if campo.decimali is None else r"\d{%d}" % campo.decimali
        if not re.fullmatch(r"-?\d{1,3}(\.\d{3})*(," + cifre + r")?|-?\d+(," + cifre + r")?", valore) or (
            campo.decimali and "," not in valore
        ):
            esempio = "18,53" if campo.decimali == 2 else "12,5"
            return f"numero non valido (es. {esempio})"
    elif tipo == "scelta":
        ammessi = campo.opzioni_effettive(elemento)
        if valore not in ammessi:
            return f"valore non ammesso (ammessi: {', '.join(ammessi) or 'nessuno'})"
    if campo.max_lunghezza and len(valore) > campo.max_lunghezza:
        return f"massimo {campo.max_lunghezza} caratteri"
    return None


def _contesto(parametri: dict, elemento: dict) -> dict:
    return {**parametri, **{k: v for k, v in elemento.items() if isinstance(v, str)}}


def _compilato(valore) -> bool:
    if isinstance(valore, list):
        return any(isinstance(x, dict) and any(str(v).strip() for v in x.values() if not isinstance(v, list)) for x in valore)
    return bool(str(valore or "").strip())


def _valida_elementi(campi, elementi, parametri, prefisso, almeno_uno, errori):
    for n, elemento in enumerate(elementi, start=1):
        nome = f"{prefisso} {n}"
        if not isinstance(elemento, dict):
            errori.append(f"{nome}: formato non valido")
            continue
        sconosciuti = set(elemento) - {c.id for c in campi}
        if sconosciuti:
            errori.append(f"{nome}: campi non previsti dallo schema ({', '.join(sorted(sconosciuti))})")
        contesto = _contesto(parametri, elemento)
        visibili = {c.id: c for c in campi if _visibile(c.visibile_se, contesto)}

        for campo in visibili.values():
            valore = elemento.get(campo.id)
            if campo.tipo == "elenco":
                sotto = valore or []
                if not isinstance(sotto, list):
                    errori.append(f"{nome} - {campo.etichetta}: formato non valido")
                    continue
                sotto = [s for s in sotto if _compilato([s])]
                if campo.obbligatorio and not sotto:
                    errori.append(f"{nome} - {campo.etichetta}: inserire almeno un elemento")
                _valida_elementi(campo.campi, sotto, parametri, f"{nome} > {campo.etichetta_elemento}", [], errori)
                continue
            testo = str(valore or "").strip()
            if not testo:
                if campo.obbligatorio:
                    errori.append(f"{nome} - {campo.etichetta}: campo obbligatorio")
                continue
            errore = _errore_valore(campo, testo, elemento)
            if errore:
                errori.append(f"{nome} - {campo.etichetta}: {errore}")

        for gruppo in almeno_uno:
            presenti = [i for i in gruppo if i in visibili]
            if presenti and not any(_compilato(elemento.get(i)) for i in presenti):
                if len(presenti) == 1:
                    errori.append(f"{nome} - {visibili[presenti[0]].etichetta}: campo obbligatorio")
                else:
                    etichette = ", ".join(visibili[i].etichetta for i in presenti)
                    errori.append(f"{nome}: compilare almeno uno tra {etichette}")


def valida_elemento(schema: Schema, sezione_id: str, elemento: dict, parametri: dict | None = None) -> list[str]:
    """Errori di un singolo elemento di una sezione (es. un procedimento dell'art. 35), con le
    stesse regole del form: obbligatori, campi visibili secondo le condizioni, formati,
    "almeno uno tra". I messaggi non hanno il prefisso con il numero dell'elemento."""
    sezione = schema.sezione(sezione_id)
    if sezione is None:
        raise ValueError(f"Sezione {sezione_id} non presente nello schema {schema.id}")
    errori: list[str] = []
    prefisso = sezione.etichetta_elemento
    _valida_elementi(sezione.campi, [elemento], parametri or {}, prefisso, sezione.almeno_uno, errori)
    nome = f"{prefisso} 1"
    return [e[len(nome) + 3:] if e.startswith(f"{nome} - ") else e[len(nome) + 2:] if e.startswith(f"{nome}: ") else e
            for e in errori]  # fmt: skip


def valida_dati(schema: Schema, dati: dict) -> list:
    """Verifica i dati inviati dal form. Restituisce l'elenco degli errori (vuoto se validi)."""
    errori = []
    ambito = str(dati.get("ambito_soggettivo") or "TENUTO").upper()
    ammessi = VALORI_AMBITO if schema.ambito == "autodichiarazione" else {"TENUTO", "NON_TENUTO"}
    if ambito not in ammessi:
        errori.append(f"Ambito soggettivo non ammesso: {ambito}")

    righe = dati.get("righe") or []
    alternativo = str(dati.get("alternativo") or "").strip()

    if alternativo:
        if not schema.adempimento_alternativo:
            errori.append("Lo schema non prevede un adempimento alternativo")
        elif not _RE_URL.match(alternativo):
            errori.append(f"{schema.adempimento_alternativo.etichetta_link}: URL non valido")
        return errori

    if ambito == "NON_TENUTO" and not righe:
        return errori

    parametri = dati.get("parametri") or {}
    for p in schema.parametri:
        if p.opzione(parametri.get(p.id)) is None:
            errori.append(f"{p.etichetta}: valore mancante o non ammesso")
    if errori:
        return errori

    sezione = schema.sezione(dati.get("sezione") or "")
    if sezione is None or not _visibile(sezione.visibile_se, parametri):
        errori.append("Sezione mancante o non prevista per i parametri scelti")
        return errori
    if not righe:
        errori.append("Inserire almeno un elemento")
    if not sezione.ripetibile and len(righe) > 1:
        errori.append("La sezione ammette un solo elemento")

    _valida_elementi(sezione.campi, righe, parametri, sezione.etichetta_elemento, sezione.almeno_uno, errori)
    return errori


# ---------------------------------------------------------------------------
# Documento generato
# ---------------------------------------------------------------------------

FRASE_NON_APPLICABILE = "L'obbligo di pubblicazione non è applicabile all'amministrazione"


def _e(value) -> str:
    """Escape HTML di un valore inserito dall'utente (None -> stringa vuota)."""
    return html_lib.escape(str(value).strip()) if value is not None else ""


def _link(url, testo=None) -> str:
    """Link HTML con href e testo escapati; 'N/D' se l'URL è vuoto."""
    url = (url or "").strip()
    if not url:
        return "N/D"
    return f"<a href='{_e(url)}'>{_e(testo) if testo else _e(url)}</a>"


def _dichiarazione_ambito(schema: "Schema", dati: dict) -> str:
    """
    Schemi con autodichiarazione (delibera 497/2025): soggetto tenuto / tenuto
    parzialmente / non tenuto. Schemi della delibera 495/2024 aggiornati al
    10.06.2026: solo la precisazione di non applicabilità, quando ricorre.
    """
    ambito = str(dati.get("ambito_soggettivo") or "TENUTO").upper()
    testo = schema.frasi_ambito.get(ambito, "")
    return f"<h4 style='color: #333; margin-bottom: 12px;'>{_e(testo)}</h4>" if testo else ""

_STILE_TABELLA = "width:100%; border-collapse: collapse; text-align:left; font-size: 13px; margin-bottom: 12px;"


def _formatta_valore(campo: Campo, valore: str) -> str:
    if not valore:
        return "N/D"
    if campo.tipo == "url":
        return _link(valore)
    if campo.tipo == "email":
        return _link(f"mailto:{valore}", valore)
    if campo.tipo == "importo":
        return f"&euro; {_e(valore)}"
    if campo.tipo == "percentuale":
        return f"{_e(valore)}%"
    if campo.tipo == "testo_lungo":
        return _e(valore).replace("\n", "<br>")
    return _e(valore)


def _tabella(campi, elementi, parametri) -> str:
    """Un elemento per riga, una colonna per campo (campi visibili in almeno un elemento)."""
    contesti = [_contesto(parametri, el) for el in elementi]
    colonne = [c for c in campi if c.tipo != "elenco" and any(_visibile(c.visibile_se, ctx) for ctx in contesti)]
    html = f"<table border='1' style='{_STILE_TABELLA}'><tr style='background-color:#f8f9fa;'>"
    html += "".join(f"<th style='padding:6px;'>{_e(c.etichetta)}</th>" for c in colonne) + "</tr>"
    for el, ctx in zip(elementi, contesti):
        html += "<tr>" + "".join(
            f"<td style='padding:6px;'>{_formatta_valore(c, str(el.get(c.id) or '').strip()) if _visibile(c.visibile_se, ctx) else '&mdash;'}</td>"
            for c in colonne
        ) + "</tr>"
    return html + "</table>"


def _scheda(campi, elemento, parametri) -> str:
    """Un elemento come scheda etichetta/valore, con gli elenchi annidati come tabelle."""
    ctx = _contesto(parametri, elemento)
    visibili = [c for c in campi if _visibile(c.visibile_se, ctx)]
    html = f"<table border='1' style='{_STILE_TABELLA}'>"
    gruppo = ""
    for c in visibili:
        if c.tipo != "elenco":
            if c.gruppo and c.gruppo != gruppo:
                html += f"<tr><th colspan='2' style='background-color:#e9ecef; padding:6px;'>{_e(c.gruppo)}</th></tr>"
            gruppo = c.gruppo
            valore = _formatta_valore(c, str(elemento.get(c.id) or "").strip())
            html += f"<tr><th style='background-color:#f8f9fa; width:35%; padding:6px;'>{_e(c.etichetta)}</th><td style='padding:6px;'>{valore}</td></tr>"
    html += "</table>"
    for c in visibili:
        if c.tipo == "elenco":
            sotto = [s for s in (elemento.get(c.id) or []) if isinstance(s, dict) and _compilato([s])]
            html += f"<p style='margin: 8px 0 4px; font-weight: bold;'>{_e(c.etichetta)}</p>"
            if not sotto:
                html += "<p style='font-style: italic; color: #666;'>Nessun elemento.</p>"
            elif len(c.campi) <= 6:
                html += _tabella(c.campi, sotto, parametri)
            else:
                # Troppi campi per una tabella leggibile: una scheda per sotto-elemento.
                for n, s in enumerate(sotto, start=1):
                    html += f"<p style='margin: 6px 0 2px;'>{_e(c.etichetta_elemento)} {n}</p>"
                    html += _scheda(c.campi, s, parametri)
    return html


def _riepilogo_parametri(schema: Schema, parametri: dict) -> str:
    if not schema.parametri:
        return ""
    righe, note = "", ""
    for p in schema.parametri:
        opzione = p.opzione(parametri.get(p.id))
        if opzione is None:
            continue
        righe += f"<tr><th style='background-color:#f8f9fa; width:35%; padding:6px;'>{_e(p.etichetta)}</th><td style='padding:6px;'>{_e(opzione.etichetta)}</td></tr>"
        if opzione.nota:
            note += (
                "<div style='background-color:#fff3e0; border:1px solid #ffb74d; border-radius:6px; padding:8px; margin-bottom:12px;'>"
                f"<span style='color:#e65100; font-size:13px;'>{_e(opzione.nota)}</span></div>"
            )
    return (f"<table border='1' style='{_STILE_TABELLA}'>{righe}</table>" if righe else "") + note


def genera_documento(schema: Schema, dati: dict) -> dict:
    """Valori dei segnaposto del template comune templates/SCHEMA."""
    ambito_html = _dichiarazione_ambito(schema, dati)
    parametri = dati.get("parametri") or {}
    righe = [r for r in (dati.get("righe") or []) if isinstance(r, dict)]
    sezione = schema.sezione(dati.get("sezione") or "")
    alternativo = str(dati.get("alternativo") or "").strip()

    if alternativo and schema.adempimento_alternativo:
        alt = schema.adempimento_alternativo
        corpo = f"<p style='font-size: 14px;'>{_e(alt.testo_documento)}</p>"
        corpo += (f"<table border='1' style='{_STILE_TABELLA}'><tr><th style='background-color:#f8f9fa; width:35%; padding:6px;'>"
                  f"{_e(alt.etichetta_link)}</th><td style='padding:6px;'>{_link(alternativo)}</td></tr></table>")
    elif not righe or sezione is None:
        corpo = "<p style='font-style: italic; color: #666;'>Nessun dato inserito.</p>"
    else:
        titolo = f"{_e(sezione.gruppo)} &ndash; {_e(sezione.titolo)}" if sezione.gruppo else _e(sezione.titolo)
        corpo = _riepilogo_parametri(schema, parametri)
        corpo += f"<h4 style='margin-top: 24px; color: #333;'>{titolo}</h4>"
        if sezione.nota:
            corpo += f"<p style='font-size: 12px; color: #666;'>{_e(sezione.nota)}</p>"
        if sezione.layout_effettivo == "tabella":
            corpo += _tabella(sezione.campi, righe, parametri)
        else:
            for n, riga in enumerate(righe, start=1):
                if len(righe) > 1:
                    corpo += f"<h5 style='margin: 16px 0 4px;'>{_e(sezione.etichetta_elemento)} {n}</h5>"
                corpo += _scheda(sezione.campi, riga, parametri)
        corpo += "<br>"

    note = str(dati.get("note") or "").strip()
    return {
        "schema_note": _e(note).replace("\n", "<br>") if note else "",
        "schema_titolo": _e(schema.documento.titolo),
        "schema_sottotitolo": _e(schema.documento.sottotitolo),
        "schema_introduzione": _e(schema.documento.introduzione),
        "tabelle_schema_complete": ambito_html + corpo,
        "schema_fonte": _e(
            f"Dati elaborati e redatti in conformità allo schema di pubblicazione ANAC ({schema.fonte.descrizione})."
            if schema.fonte.anac else
            f"Dati elaborati sulla base degli obblighi di pubblicazione previsti da: {'; '.join(schema.fonte.norme)}. "
            "Per questo obbligo ANAC non ha approvato uno schema di pubblicazione ai sensi dell'art. 48 del d.lgs. "
            "n. 33/2013: la struttura della scheda non corrisponde a un modello ufficiale."
        ),
    }


# ---------------------------------------------------------------------------
# Prompt di audit
# ---------------------------------------------------------------------------

_REGOLE_TIPO = {
    "testo": "testo",
    "testo_lungo": "testo descrittivo, chiaro e comprensibile per il cittadino",
    "data": 'data nel formato GG/MM/AAAA; un formato diverso ma univocamente interpretabile (es. "2024-05-10") è "Parziale"',
    "anno": "anno a 4 cifre (es. 2024)",
    "url": "URL valido (http/https) al documento o alla pagina pubblicata",
    "email": "indirizzo email istituzionale sintatticamente corretto",
    "telefono": "numero telefonico istituzionale",
    "importo": "importo con punto per le migliaia e virgola per i 2 decimali (es. 1.234,56)",
    "percentuale": "percentuale con virgola per i decimali (es. 45,50)",
    "numero": "numero intero",
    "decimale": "numero decimale con la virgola come separatore (es. 12,5)",
    "iban": 'codice IBAN italiano: "IT" + 2 cifre di controllo + 1 lettera CIN + 5 cifre ABI + 5 cifre CAB + 12 caratteri di conto (27 caratteri)',
}

_REGOLE_AGGIORNAMENTO = {
    "tempestivo": (
        "aggiornamento TEMPESTIVO (art. 8, co. 1, d.lgs. 33/2013): la norma non fissa un numero preciso di giorni. Confronta _ADOPTION_DATE_ e "
        "_PUB_DATE_ e valuta in modo ragionevole se l'intervallo è coerente con la tempestività, senza applicare una "
        "soglia numerica fissa. Motiva sempre la valutazione."
    ),
    "trimestrale": "aggiornamento TRIMESTRALE (art. 8, co. 2, d.lgs. 33/2013): verifica che i dati coprano il trimestre di riferimento e che la pubblicazione (_PUB_DATE_) sia coerente con tale periodicità.",
    "semestrale": "aggiornamento SEMESTRALE (art. 8, co. 2, d.lgs. 33/2013): verifica che i dati coprano il semestre di riferimento e che la pubblicazione (_PUB_DATE_) sia coerente con tale periodicità.",
    "annuale": "aggiornamento ANNUALE (art. 8, co. 2, d.lgs. 33/2013): verifica che i dati coprano l'anno di riferimento e che la pubblicazione (_PUB_DATE_) sia coerente con tale periodicità.",
}

NOTA_SCHEMA_NON_APPLICABILE = (
    "Lo schema non richiede all'ente di dichiararsi \"tenuto\", \"tenuto parzialmente\" o \"non tenuto\": quando un "
    "obbligo non è applicabile, nella sotto-sezione deve comparire la precisazione \"L'obbligo di pubblicazione non è "
    "applicabile all'amministrazione\". In tal caso l'assenza dei dati NON è un rilievo, e non lo è nemmeno l'assenza "
    "di un'autodichiarazione di ambito soggettivo."
)

NOTA_SCHEMA_AGGIORNATO = (
    "Lo schema, nella versione aggiornata, non indica limiti di lunghezza dei campi: rinvia, per i vincoli tecnici, "
    "alle specifiche tecniche pubblicate da ANAC nella \"Guida Online\" del Portale dei Servizi."
)

NOTA_SCHEMA_NORMATIVO = (
    "ATTENZIONE: per questo obbligo ANAC NON ha approvato uno schema di pubblicazione (art. 48 d.lgs. 33/2013). "
    "La checklist elenca i dati richiesti dalla norma: verifica che siano presenti e corretti, qualunque siano la "
    "struttura, l'ordine o la denominazione con cui sono pubblicati. NON segnalare come difformità la mancata "
    "aderenza a un modello e NON citare schemi ANAC inesistenti. I formati indicati per i campi (date, importi) sono "
    "indicazioni di leggibilità, non vincoli normativi: un formato diverso ma chiaro non è un rilievo. Nel report "
    "dichiara che la verifica è condotta sulla base della norma e non di uno schema approvato da ANAC."
)

NOTA_SCHEMA_AUTODICHIARAZIONE = (
    "Lo schema invita l'ente a specificare nella sotto-sezione se è \"Soggetto tenuto\", \"Soggetto tenuto "
    "parzialmente\" o \"Soggetto non tenuto\" all'obbligo: segnala come adempimento formale mancante (\"Parziale\") "
    "l'assenza di tale dichiarazione. Se l'ente si dichiara non tenuto, l'assenza dei dati NON è un rilievo."
)


def _descrivi_condizione(schema: Schema, condizione: Condizione, fratelli: dict) -> str:
    parti = []
    for chiave, valori in condizione.items():
        parametro = schema.parametro(chiave)
        if parametro:
            nomi = [o.etichetta for o in parametro.opzioni if o.valore in valori]
            parti.append(f"{parametro.etichetta} = " + " oppure ".join(f'"{n}"' for n in nomi))
        else:
            etichetta = fratelli[chiave].etichetta if chiave in fratelli else chiave
            parti.append(f"{etichetta} = " + " oppure ".join(f'"{v}"' for v in valori))
    return " e ".join(parti)


def _compatibile(condizione: Condizione, fissati: Condizione) -> bool:
    """False se la condizione esclude tutti i valori dei parametri fissati dalla variante."""
    return all(not (chiave in fissati and not set(valori) & set(fissati[chiave])) for chiave, valori in condizione.items())


def _righe_campi(schema: Schema, campi, fissati: Condizione, rientro: str) -> list:
    fratelli = {c.id: c for c in campi}
    righe = []
    for c in campi:
        if not _compatibile(c.visibile_se, fissati):
            continue
        if c.tipo == "scelta":
            if c.opzioni:
                regola = "valore vincolato, ESATTAMENTE uno tra " + ", ".join(f'"{o}"' for o in c.opzioni)
            else:
                origine = fratelli[c.opzioni_da].etichetta
                regola = f"valore vincolato, dipende da \"{origine}\": " + "; ".join(
                    f'se "{k}": uno tra ' + ", ".join(f'"{o}"' for o in v) for k, v in (c.opzioni_per or {}).items()
                )
            regola += '; un valore diverso è "Negativo"'
        elif c.tipo == "elenco":
            regola = f"elenco da replicare per ogni {c.etichetta_elemento.lower()}; per ciascuno verifica"
        else:
            regola = _REGOLE_TIPO[c.tipo]
            if c.tipo == "data" and c.separatore_data != "/":
                regola = (f'data nel formato GG{c.separatore_data}MM{c.separatore_data}AAAA; un formato diverso ma '
                          f'univocamente interpretabile è "Parziale"')
            if c.tipo == "decimale" and c.decimali is not None:
                regola = (f"numero con esattamente {c.decimali} cifre decimali e virgola come separatore (es. 18,53); "
                          f"prima di segnalare un errore conta le cifre dopo la virgola")
        if c.max_lunghezza:
            regola += f'; massimo {c.max_lunghezza} caratteri (il superamento è "Parziale")'
        stato = "obbligatorio" if c.obbligatorio else "facoltativo"
        condizione = {k: v for k, v in c.visibile_se.items() if k not in fissati}
        quando = f" [solo se {_descrivi_condizione(schema, condizione, fratelli)}]" if condizione else ""
        descrizione = f" ({c.descrizione})" if c.descrizione else ""
        righe.append(f"{rientro}* {c.etichetta}{descrizione}{quando} — {stato}: {regola}.")
        if c.tipo == "elenco":
            righe += _righe_campi(schema, c.campi, fissati, rientro + "    ")
    return righe


def _checklist_sezione(schema: Schema, sezione: Sezione, fissati: Condizione, con_tempistica: bool) -> str:
    righe = [f"   - SEZIONE \"{sezione.titolo}\""]
    condizione = {k: v for k, v in sezione.visibile_se.items() if k not in fissati}
    if condizione:
        righe.append(f"     Pertinente solo se {_descrivi_condizione(schema, condizione, {})}.")
    righe.append(f"     Collocazione: {sezione.collocazione}. Riferimenti: {'; '.join(sezione.norme) or '-'}.")
    if con_tempistica:
        righe.append(f"     Tempistica: {_REGOLE_AGGIORNAMENTO[sezione.aggiornamento]}")
    if sezione.nota:
        righe.append(f"     Nota: {sezione.nota}")
    if sezione.ripetibile:
        righe.append(f"     Da replicare per ogni {sezione.etichetta_elemento.lower()}: verifica che OGNI elemento riporti tutti i campi, non solo il primo.")
    righe += _righe_campi(schema, sezione.campi, fissati, "     ")
    fratelli = {c.id: c for c in sezione.campi}
    for gruppo in sezione.almeno_uno:
        etichette = ", ".join(f'"{fratelli[i].etichetta}"' for i in gruppo)
        righe.append(f"     Deve essere presente ALMENO UNO tra {etichette}: l'assenza di tutti è \"Negativo\", la presenza di uno solo è sufficiente.")
    return "\n".join(righe)


REGOLA_NUMERI_FOGLI_DI_CALCOLO = """VALORI NUMERICI NEI FOGLI DI CALCOLO:
- Se il documento è un foglio di calcolo, i valori numerici ti vengono forniti con i metadati di formattazione estratti dal file. Applica queste regole:
  * "X [visualizzato in Excel; formato interno: F]" (file Excel): X è il valore come lo vede l'utente; F è la maschera interna, scritta con la sintassi internazionale. Maschere come #,##0.00 sono CORRETTE per l'Italia. Se F è "General", la cella non è stata formattata: segnala "Parziale".
  * "V [Visualizzato come: X]" (file ODS): verifica che X rispetti il formato italiano (punto per le migliaia, virgola per i decimali).
  * Valore senza tag tra parentesi quadre: il dato è stato inserito come testo; verifica direttamente il formato italiano della stringa."""


def _descrivi_parametri(schema: Schema, fissati: Condizione) -> str:
    righe = []
    for p in schema.parametri:
        opzioni = [o for o in p.opzioni if p.id not in fissati or o.valore in fissati[p.id]]
        intestazione = f"   - {p.etichetta}" + (f" ({p.descrizione})" if p.descrizione else "")
        if p.id in fissati:
            intestazione += ": questo audit riguarda solo " + " / ".join(f'"{o.etichetta}"' for o in opzioni)
        else:
            intestazione += ": individua dal documento, da _NOTES_ o da _AUTHORITY_FEATURES_ quale dei seguenti casi ricorre (se non è determinabile, dichiaralo)"
        righe.append(intestazione)
        for o in opzioni:
            righe.append(f"     * \"{o.etichetta}\"" + (f": {o.nota}" if o.nota else ""))
    return "\n".join(righe)


def genera_prompt(schema: Schema, variante: Optional[VarianteAudit] = None) -> str:
    """Prompt di audit con gli stessi segnaposto dei prompt scritti a mano (vedi load_prompt in app.py)."""
    fissati = variante.parametri if variante else {}
    sezioni = [
        s for s in schema.sezioni
        if (not variante or not variante.sezioni or s.id in variante.sezioni) and _compatibile(s.visibile_se, fissati)
    ]
    nota_ambito = NOTA_SCHEMA_AUTODICHIARAZIONE if schema.ambito == "autodichiarazione" else NOTA_SCHEMA_NON_APPLICABILE
    if schema.fonte.versione:
        nota_ambito += " " + NOTA_SCHEMA_AGGIORNATO
    if not schema.fonte.anac:
        nota_ambito += "\n" + NOTA_SCHEMA_NORMATIVO
    riferimento = (
        f"seguendo rigorosamente lo schema ANAC ({schema.fonte.descrizione})"
        if schema.fonte.anac else
        f"seguendo rigorosamente gli obblighi previsti dalla norma ({'; '.join(schema.fonte.norme)}), per i quali ANAC non ha approvato uno schema di pubblicazione,"
    )
    origine_regole = "dallo schema ANAC ufficiale" if schema.fonte.anac else "dalle norme indicate (non esiste uno schema ANAC ufficiale)"

    classificazione = (
        "Inquadra il documento in UNA delle sezioni seguenti e verifica SOLO i vincoli della sezione identificata. "
        "Ignora le altre sezioni: non menzionarle e NON segnalarne l'assenza come errore."
        if len(sezioni) > 1 else "Verifica i vincoli della sezione seguente."
    )
    if variante and schema.controlli_per_sezione:
        classificazione = (
            f"Il controllo riguarda SOLO la sezione \"{variante.titolo}\", scelta dall'utente. Se il documento contiene "
            "anche altre sezioni dello schema, non considerarle e non citarle nel report, né come dati presenti né come "
            "dati assenti o incompleti. Se la sezione oggetto del controllo è assente e l'ente è tenuto, l'esito è "
            "\"Negativo\".\n" + classificazione
        )
    # Se tutte le sezioni hanno la stessa cadenza, la regola si scrive una volta sola.
    aggiornamenti = {s.aggiornamento for s in sezioni}
    tempistica_unica = len(aggiornamenti) == 1
    checklist = "\n\n".join(_checklist_sezione(schema, s, fissati, not tempistica_unica) for s in sezioni)
    if tempistica_unica:
        checklist = f"   Tempistica (tutte le sezioni): {_REGOLE_AGGIORNAMENTO[aggiornamenti.pop()]}\n\n" + checklist

    note = [schema.note_audit.strip()]
    if schema.adempimento_alternativo and schema.adempimento_alternativo.nota_audit:
        note.insert(0, schema.adempimento_alternativo.nota_audit.strip())
    if variante and variante.testo_note:
        note.append(variante.testo_note.strip())
    note += [s.testo_note_audit for s in sezioni if s.testo_note_audit]
    tipi = {c.tipo for sez in sezioni for campo in sez.campi for c in [campo, *(campo.campi or [])]}
    if tipi & {"importo", "decimale", "percentuale"}:
        note.append(REGOLA_NUMERI_FOGLI_DI_CALCOLO)
    note = "\n".join(n for n in note if n) or "Nessuna regola specifica oltre alla checklist."

    parametri = _descrivi_parametri(schema, fissati)
    blocco_parametri = f"\nCASI PREVISTI DALLO SCHEMA:\n{parametri}\n" if parametri else ""
    oggetto = f" — {variante.titolo}" if variante else ""

    return f"""<role>
Agisci come un esperto di compliance e controllo qualità dei dati della Pubblica Amministrazione italiana. Il tuo compito è validare la conformità del documento fornito rispetto all'{schema.articolo} del D.lgs 33/2013 ({schema.titolo}{oggetto}), {riferimento} e le Istruzioni operative (Allegato 4 alla delibera n. 495/2024, come modificato dalla delibera n. 481/2025)
</role>

<context>
- Estensione originale file: _FILE_EXTENSION_
- Ente: _CUSTOMER_NAME_
- Data di adozione dell'atto: _ADOPTION_DATE_
- Data di pubblicazione: _PUB_DATE_
- Data dell'analisi (oggi): _DATA_ANALISI_
- Note aggiuntive: _NOTES_
- Le date sono nel formato GG/MM/AAAA; "N/A" indica una data dichiarata non nota dall'utente: in tal caso NON dedurla né inventarla e riporta come "Non valutabile" la tempestività e ogni controllo che dipende da quella data.
</context>

<authority_features>
Queste sono le caratteristiche dell'ente per il quale verificherai i documenti:
_AUTHORITY_FEATURES_
</authority_features>

<istruzioni_analisi>
NON utilizzare tue conoscenze pregresse, ma applica RIGOROSAMENTE E SOLO le seguenti regole ricavate {origine_regole}.

1. AMBITO SOGGETTIVO:
{schema.ambito_soggettivo.strip() or "Come indicato nello schema."}
Se da _AUTHORITY_FEATURES_ risulta che l'ente non rientra nell'ambito soggettivo, l'esito è "Non Applicabile": spiegalo e ferma l'analisi.
{nota_ambito}
{blocco_parametri}
2. REGOLE SPECIFICHE DELLO SCHEMA (applicale prima della checklist; in caso di contrasto prevalgono sulle regole generali, ad esempio sulla tempistica):
{note}

3. CLASSIFICAZIONE E CHECKLIST TECNICA:
{classificazione}
Se un campo obbligatorio manca o viola i vincoli, l'esito del campo DEVE essere "Negativo"; i campi facoltativi assenti non sono un rilievo. I campi con una condizione [solo se ...] vanno verificati solo quando la condizione ricorre; altrimenti sono "Non Applicabile".

{checklist}

4. VALUTAZIONE QUALITÀ DEL DATO:
   - Integrità e completezza: il dato non deve essere parziale.
   - Comprensibilità: il contenuto deve essere chiaro e intellegibile per il cittadino.
   - Riservatezza: nessun dato personale eccedente rispetto alle finalità di trasparenza.
   - Durata della pubblicazione (art. 8, co. 3, d.lgs. 33/2013): i dati restano pubblicati per 5 anni dal 1° gennaio
     dell'anno successivo a quello da cui decorre l'obbligo di pubblicazione, e comunque finché gli atti producono i
     loro effetti; decorsi i termini restano accessibili con l'accesso civico (art. 5). Fanno eccezione i termini
     dell'art. 14, co. 2, e dell'art. 15, co. 4 (tre anni dalla cessazione) e quelli, anche più brevi, previsti dalla
     normativa sulla protezione dei dati personali: un dato personale non necessario o non più pertinente va
     rimosso anche prima dei 5 anni. Applica la regola così, rispetto alla data dell'analisi (_DATA_ANALISI_):
     * DATI E INFORMAZIONI PERIODICI (indicatori, importi, tabelle annuali, semestrali o trimestrali, ecc.): per
       ogni periodo pubblicato ricava l'anno da cui decorre l'obbligo; se il documento non lo indica, assumi l'anno
       successivo a quello di riferimento del dato (ipotesi più favorevole all'ente). Il periodo è oltre il termine
       se l'anno dell'analisi è successivo a (anno da cui decorre l'obbligo + 5). Esempio: analisi nel 2026, dati
       riferiti al 2019 -> obbligo dal 2020 -> pubblicazione dovuta fino al 31/12/2025 -> oltre il termine; dati
       riferiti al 2020 -> obbligo dal 2021 -> dovuta fino al 31/12/2026 -> ancora dovuta.
     * ATTI (provvedimenti, regolamenti, atti generali): restano pubblicati anche oltre i 5 anni finché producono
       effetti (es. un regolamento in vigore); sono oltre il termine solo se risulta che non producono più effetti.
     * ESITO: se ci sono periodi o atti oltre il termine che contengono dati personali l'esito è "Negativo" (vanno
       rimossi: principio di limitazione della conservazione, art. 5, par. 1, lett. e), Reg. UE 2016/679); se non
       contengono dati personali l'esito è "Parziale" (la pubblicazione non è più obbligatoria: vanno rimossi dalla
       sezione o collocati in un archivio distinto e indicato come tale, per non compromettere la semplicità di
       consultazione e l'aggiornamento della sezione). Se nessun dato è oltre il termine l'esito è "Positivo"; se
       gli anni di riferimento non sono determinabili, "Non valutabile".
     * Riporta SEMPRE questo controllo come riga "Durata della pubblicazione (art. 8, co. 3)" della tabella
       riepilogativa finale, indicando quanti e quali periodi o atti sono oltre il termine.

5. VINCOLO DI VERITÀ ASSOLUTA:
Valuta ESCLUSIVAMENTE le informazioni esplicite presenti nel testo analizzato. Non presumere l'esistenza di link, date o diciture se non sono testualmente riportati.
</istruzioni_analisi>

<classificazione_opendata>
_OPEN_DATA_RULES_
</classificazione_opendata>

<output_rules>
_OUTPUT_RULES_

_ADDITIONAL_REQUESTS_
</output_rules>

Ecco il testo del documento da analizzare:"""
