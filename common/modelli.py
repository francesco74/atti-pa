"""Modelli di atto a 4 fasi (deploy/modelli/*.yaml): definizione, condizioni, composizione.

Un modello descrive un tipo di atto (es. determina di affidamento diretto) con:
- domande iniziali, che decidono quali capoversi entrano nell'atto;
- valori derivati dalle risposte (es. fascia di importo);
- campi da compilare, definiti una volta sola;
- fasi (intestazione, preambolo, dispositivo, chiusura) > sezioni > capoversi, con il testo
  standard e i segnaposto {{campo}}.

Le condizioni ("se") sono espressioni semplici (and, or, not, ==, !=, <, <=, >, >=, in,
implica) valutate da un piccolo interprete: non sono mai eseguite come codice Python.

Le specificità tecniche o normative (servizi cloud, CAM, lavori su immobili vincolati...)
stanno in moduli di regole separati (deploy/modelli/regole/*.yaml). Ogni modulo ha un
fattore abilitante, scelto tra le "caratteristiche" dell'atto, e inietta capoversi nei punti
di innesto del modello (oggetto, visti, dato atto, dispositivo...), aggiunge domande e
campi e suggerisce risposte. Il modello e i suoi moduli sono composti in un'unica
definizione al caricamento (componi). I controlli stanno nelle checklist (deploy/checklist):
una generica per tipologia di atto, una per modello e una per ogni modulo di regole.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# ---------------------------------------------------------------------------------------
# Condizioni
# ---------------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>\"[^\"]*\")"
    r"|(?P<op>==|!=|<=|>=|<|>|\(|\)|\[|\]|,)|(?P<nome>[A-Za-z_][A-Za-z_0-9]*))"
)
_PAROLE = {"and", "or", "not", "in", "implica", "true", "false"}


class ErroreCondizione(ValueError):
    pass


class Condizione:
    """Espressione analizzata una volta e valutata su un dizionario di variabili."""

    def __init__(self, testo: str):
        self.testo = testo
        self._tokens = self._tokenizza(testo)
        self._i = 0
        self.albero = self._espressione()
        if self._i != len(self._tokens):
            raise ErroreCondizione(f"Condizione non valida: {testo!r}")
        self.nomi = self._nomi(self.albero)

    # --- analisi ---
    @staticmethod
    def _tokenizza(testo: str) -> list[tuple[str, Any]]:
        tokens, pos = [], 0
        testo = testo.strip()
        while pos < len(testo):
            m = _TOKEN.match(testo, pos)
            if not m or m.end() == pos:
                raise ErroreCondizione(f"Carattere non ammesso in {testo!r}: {testo[pos:]!r}")
            pos = m.end()
            if m["num"]:
                tokens.append(("val", Decimal(m["num"])))
            elif m["str"]:
                tokens.append(("val", m["str"][1:-1]))
            elif m["op"]:
                tokens.append(("op", m["op"]))
            elif m["nome"] in ("true", "false"):
                tokens.append(("val", m["nome"] == "true"))
            elif m["nome"] in _PAROLE:
                tokens.append(("op", m["nome"]))
            else:
                tokens.append(("nome", m["nome"]))
        return tokens

    def _guarda(self) -> tuple[str, Any] | None:
        return self._tokens[self._i] if self._i < len(self._tokens) else None

    def _prendi(self, atteso: str | None = None) -> tuple[str, Any]:
        t = self._guarda()
        if t is None or (atteso is not None and t != ("op", atteso)):
            raise ErroreCondizione(f"Condizione non valida: {self.testo!r}")
        self._i += 1
        return t

    def _espressione(self):
        sinistra = self._o()
        if self._guarda() == ("op", "implica"):
            self._prendi()
            return ("implica", sinistra, self._o())
        return sinistra

    def _o(self):
        nodo = self._e()
        while self._guarda() == ("op", "or"):
            self._prendi()
            nodo = ("or", nodo, self._e())
        return nodo

    def _e(self):
        nodo = self._non()
        while self._guarda() == ("op", "and"):
            self._prendi()
            nodo = ("and", nodo, self._non())
        return nodo

    def _non(self):
        if self._guarda() == ("op", "not"):
            self._prendi()
            return ("not", self._non())
        return self._confronto()

    def _confronto(self):
        sinistra = self._atomo()
        t = self._guarda()
        if t and t[0] == "op" and t[1] in ("==", "!=", "<", "<=", ">", ">="):
            self._prendi()
            return ("cmp", t[1], sinistra, self._atomo())
        if t == ("op", "in"):
            self._prendi()
            return ("in", sinistra, self._atomo())
        return sinistra

    def _atomo(self):
        t = self._prendi()
        if t[0] in ("val", "nome"):
            return t
        if t == ("op", "("):
            nodo = self._espressione()
            self._prendi(")")
            return nodo
        if t == ("op", "["):
            elementi = []
            while self._guarda() != ("op", "]"):
                elementi.append(self._atomo())
                if self._guarda() == ("op", ","):
                    self._prendi()
            self._prendi("]")
            return ("lista", elementi)
        raise ErroreCondizione(f"Condizione non valida: {self.testo!r}")

    def _nomi(self, nodo) -> set[str]:
        if nodo[0] == "nome":
            return {nodo[1]}
        if nodo[0] == "lista":
            return set().union(*(self._nomi(n) for n in nodo[1])) if nodo[1] else set()
        if nodo[0] == "val":
            return set()
        return set().union(*(self._nomi(n) for n in nodo[1:] if isinstance(n, tuple)))

    # --- valutazione ---
    def valuta(self, variabili: dict[str, Any]) -> bool:
        return _vero(self._valore(self.albero, variabili))

    def _valore(self, nodo, v: dict[str, Any]):
        tipo = nodo[0]
        if tipo == "val":
            return nodo[1]
        if tipo == "nome":
            return v.get(nodo[1])
        if tipo == "lista":
            return [self._valore(n, v) for n in nodo[1]]
        if tipo == "not":
            return not _vero(self._valore(nodo[1], v))
        if tipo == "and":
            return _vero(self._valore(nodo[1], v)) and _vero(self._valore(nodo[2], v))
        if tipo == "or":
            return _vero(self._valore(nodo[1], v)) or _vero(self._valore(nodo[2], v))
        if tipo == "implica":
            return (not _vero(self._valore(nodo[1], v))) or _vero(self._valore(nodo[2], v))
        if tipo == "in":
            return self._valore(nodo[1], v) in (self._valore(nodo[2], v) or [])
        a, b = self._valore(nodo[2], v), self._valore(nodo[3], v)
        op = nodo[1]
        if op in ("==", "!="):
            uguali = _numero(a) == _numero(b) if _numerici(a, b) else a == b
            return uguali if op == "==" else not uguali
        if not _numerici(a, b):
            return False  # confronto con un valore mancante o non numerico
        a, b = _numero(a), _numero(b)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def _vero(valore: Any) -> bool:
    return valore not in (None, False, "", 0, [])


def _numero(valore: Any) -> Decimal | None:
    if isinstance(valore, bool):
        return None
    if isinstance(valore, (int, float, Decimal)):
        return Decimal(str(valore))
    if isinstance(valore, str):
        return importo_da_testo(valore)
    return None


def _numerici(a: Any, b: Any) -> bool:
    return _numero(a) is not None and _numero(b) is not None


# ---------------------------------------------------------------------------------------
# Definizione del modello
# ---------------------------------------------------------------------------------------

TipoCampo = Literal[
    "testo", "testo_lungo", "data", "importo", "numero", "cig", "cup", "codice_fiscale_piva",
    "elenco",
]  # fmt: skip


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Domanda(_Base):
    id: str
    testo: str
    # scelta_multipla: ogni opzione scelta è anche una variabile vera nelle condizioni
    tipo: Literal["si_no", "scelta", "scelta_multipla", "importo", "numero", "testo"]
    opzioni: dict[str, str] | None = None
    descrizioni: dict[str, str] | None = None  # spiegazione di ciascuna opzione
    opzioni_da_regole: bool = False  # le opzioni sono i fattori dei moduli di regole
    aiuto: str | None = None
    se: str | None = None
    blocca_se: str | None = None
    messaggio_blocco: str | None = None
    vincolo: str | None = None


class Campo(_Base):
    etichetta: str
    tipo: TipoCampo = "testo"
    obbligatorio: bool = True
    aiuto: str | None = None
    # utente: compilato nell'atto; ente: dai "Dati dell'ente" (modificabile nell'atto);
    # profilo: dall'utente (modificabile); sistema: assegnato fuori dal percorso
    fonte: Literal["utente", "ente", "profilo", "sistema"] = "utente"
    predefinito: str | None = None
    sottocampi: dict[str, Campo] | None = None
    minimo: int | None = None


class Capoverso(_Base):
    id: str
    testo: str
    se: str | None = None
    facoltativo: bool = False
    incluso: bool = True  # per i facoltativi: presente finché l'utente non lo toglie
    modificabile: bool = True
    aiuto: str | None = None
    norme: list[str] = []
    fonte: str | None = None  # provenienza del testo (es. ANCI-1)
    ripeti_per: str | None = None  # campo "elenco": un capoverso per riga


class Sezione(_Base):
    titolo: str
    se: str | None = None
    formula: str | None = None  # es. "Premesso che": i capoversi diventano un elenco
    aiuto: str | None = None
    oggetto: bool = False  # i capoversi formano l'oggetto dell'atto
    innesto: str | None = None  # punto in cui i moduli di regole aggiungono capoversi
    riferimenti_libreria: bool = False  # qui si aggiungono i riferimenti scelti dalla libreria
    capoversi: list[Capoverso]


class Fase(_Base):
    numero: int
    titolo: str
    descrizione: str | None = None
    formula: str | None = None  # es. DETERMINA
    premessa: str | None = None
    numerazione: Literal["automatica"] | None = None
    sezioni: list[Sezione]


class Suggerimento(_Base):
    """Risposta consigliata a una domanda, con la ragione mostrata all'istruttore."""

    domanda: str
    valore: Any
    se: str | None = None
    messaggio: str


class Specificita(_Base):
    """Modulo di regole composto nel modello: si attiva scegliendo il suo fattore."""

    codice: str
    fattore: str
    etichetta: str


class Scenario(_Base):
    """Risposte di prova per l'anteprima nell'editor dei modelli."""

    nome: str
    risposte: dict[str, Any] = {}


class Modello(_Base):
    codice: str
    versione: int = 1
    titolo: str
    descrizione: str | None = None
    tipologia_atto: str
    provvedimento: str
    organo: str
    formula_dispositivo: str
    domande: list[Domanda] = []
    derivati: dict[str, str | list[dict[str, Any]]] = {}
    campi: dict[str, Campo]
    fasi: list[Fase] = Field(min_length=1)
    suggerimenti: list[Suggerimento] = []
    regole: list[Specificita] = []  # moduli di regole composti nel modello
    scenari: list[Scenario] = []  # per l'anteprima nell'editor


class Inserto(_Base):
    innesto: str
    prima_di: str | None = None  # id di un capoverso della sezione (predefinito: in fondo)
    capoversi: list[Capoverso] = Field(min_length=1)


class ModuloRegole(_Base):
    """Specificità iniettata nei modelli quando il fattore abilitante è scelto."""

    codice: str
    fattore: str  # variabile vera quando la caratteristica è scelta
    etichetta: str  # come compare tra le caratteristiche dell'atto
    descrizione: str | None = None  # cosa attiva (es. "Qualifica ACN, CAD, Regolamento cloud")
    modelli: list[str] = Field(min_length=1)  # codici dei modelli a cui si applica
    domande: list[Domanda] = []
    derivati: dict[str, str | list[dict[str, Any]]] = {}
    campi: dict[str, Campo] = {}
    inserti: list[Inserto] = []
    suggerimenti: list[Suggerimento] = []


class ModelloNonValido(ValueError):
    def __init__(self, errori: list[str]):
        self.errori = errori
        super().__init__("Modello non valido:\n- " + "\n- ".join(errori))


SEGNAPOSTO = re.compile(r"\{\{\s*([A-Za-z_]\w*)(?:\.(\d+))?(?:\.([A-Za-z_]\w*))?\s*\}\}")


@dataclass
class ModelloCompilato:
    """Modello con le condizioni già analizzate."""

    definizione: Modello
    condizioni: dict[str, Condizione] = field(default_factory=dict)

    @property
    def d(self) -> Modello:
        return self.definizione

    def condizione(self, testo: str | None) -> Condizione | None:
        if not testo:
            return None
        if testo not in self.condizioni:
            self.condizioni[testo] = Condizione(testo)
        return self.condizioni[testo]

    def vero(self, testo: str | None, variabili: dict[str, Any]) -> bool:
        c = self.condizione(testo)
        return True if c is None else c.valuta(variabili)


def _yaml(sorgente: str | dict) -> Any:
    try:
        return yaml.safe_load(sorgente) if isinstance(sorgente, str) else sorgente
    except yaml.YAMLError as e:
        raise ModelloNonValido([f"YAML non valido: {e}"]) from e


def _errori_validazione(e: ValidationError, prefisso: str = "") -> list[str]:
    return [f"{prefisso}{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]


def leggi_modulo(sorgente: str | dict) -> ModuloRegole:
    """Legge un modulo di regole (YAML o dizionario). Solleva ModelloNonValido."""
    try:
        return ModuloRegole.model_validate(_yaml(sorgente))
    except ValidationError as e:
        raise ModelloNonValido(_errori_validazione(e)) from e


def _e(fattore: str, se: str | None) -> str:
    return f"{fattore} and ({se})" if se else fattore


def componi(modello: Modello, moduli: list[ModuloRegole]) -> Modello:
    """Il modello con i moduli che gli si applicano: le loro domande seguono quella delle
    caratteristiche, i capoversi vanno nei punti di innesto e tutto ciò che portano vale
    solo quando il fattore è scelto. Solleva ModelloNonValido."""
    moduli = [mo for mo in moduli if modello.codice in mo.modelli]
    if not moduli:
        return modello
    d = modello.model_copy(deep=True)
    errori: list[str] = []
    caratteristiche = next((q for q in d.domande if q.opzioni_da_regole), None)
    if caratteristiche is None:
        raise ModelloNonValido(["il modello non ha una domanda con opzioni_da_regole"])
    caratteristiche.opzioni = dict(caratteristiche.opzioni or {})
    caratteristiche.descrizioni = dict(caratteristiche.descrizioni or {})
    innesti = {s.innesto: s for f in d.fasi for s in f.sezioni if s.innesto}
    posizione = d.domande.index(caratteristiche) + 1
    for mo in moduli:
        dove = f"modulo {mo.codice}"
        if mo.fattore in caratteristiche.opzioni:
            errori.append(f"{dove}: il fattore {mo.fattore!r} è già usato")
        caratteristiche.opzioni[mo.fattore] = mo.etichetta
        if mo.descrizione:
            caratteristiche.descrizioni[mo.fattore] = mo.descrizione
        for q in mo.domande:
            d.domande.insert(posizione, q.model_copy(update={"se": _e(mo.fattore, q.se)}))
            posizione += 1
        for nome, regola in mo.derivati.items():
            if nome in d.derivati:
                errori.append(f"{dove}: il derivato {nome!r} esiste già")
            d.derivati[nome] = regola
        for nome, campo in mo.campi.items():
            if nome in d.campi and d.campi[nome] != campo:
                errori.append(f"{dove}: il campo {nome!r} esiste già con un'altra definizione")
            d.campi[nome] = campo
        for ins in mo.inserti:
            sezione = innesti.get(ins.innesto)
            if sezione is None:
                errori.append(f"{dove}: punto di innesto {ins.innesto!r} inesistente")
                continue
            nuovi = [
                c.model_copy(update={"se": _e(mo.fattore, c.se), "fonte": c.fonte or mo.codice})
                for c in ins.capoversi
            ]
            ids = [c.id for c in sezione.capoversi]
            if ins.prima_di is None:
                sezione.capoversi.extend(nuovi)
            elif ins.prima_di in ids:
                i = ids.index(ins.prima_di)
                sezione.capoversi[i:i] = nuovi
            else:
                errori.append(f"{dove}: capoverso {ins.prima_di!r} non presente in {ins.innesto}")
        d.suggerimenti += [
            s.model_copy(update={"se": _e(mo.fattore, s.se)}) for s in mo.suggerimenti
        ]
        d.regole.append(Specificita(codice=mo.codice, fattore=mo.fattore, etichetta=mo.etichetta))
    if errori:
        raise ModelloNonValido(errori)
    return d


def leggi_modello(
    sorgente: str | dict, moduli: list[ModuloRegole] | None = None
) -> ModelloCompilato:
    """Legge e controlla un modello (YAML o dizionario), composto con i moduli di regole che
    gli si applicano. Solleva ModelloNonValido."""
    try:
        modello = Modello.model_validate(_yaml(sorgente))
    except ValidationError as e:
        raise ModelloNonValido(_errori_validazione(e)) from e
    compilato = ModelloCompilato(componi(modello, moduli or []))
    errori = _controlla(compilato)
    if errori:
        raise ModelloNonValido(errori)
    return compilato


def _controlla(m: ModelloCompilato) -> list[str]:
    d = m.d
    errori: list[str] = []
    domande = {q.id for q in d.domande}
    opzioni_multiple = {
        o for q in d.domande if q.tipo == "scelta_multipla" for o in (q.opzioni or {})
    }
    nomi = domande | set(d.derivati) | opzioni_multiple
    for nome in sorted(opzioni_multiple & (domande | set(d.derivati))):
        errori.append(f"opzione {nome!r}: è anche il nome di una domanda o di un derivato")

    def condizione(testo: str | None, dove: str) -> None:
        try:
            c = m.condizione(testo)
        except ErroreCondizione as e:
            errori.append(f"{dove}: {e}")
            return
        if c is not None:
            for n in c.nomi - nomi:
                errori.append(f"{dove}: '{n}' non è una domanda né un valore derivato")

    def segnaposto(testo: str, dove: str, elenco: str | None = None) -> None:
        for nome, _, sotto in SEGNAPOSTO.findall(testo):
            if nome in d.campi:
                campo = d.campi[nome]
                if sotto and (campo.tipo != "elenco" or sotto not in (campo.sottocampi or {})):
                    errori.append(f"{dove}: '{nome}.{sotto}' non è un sottocampo")
                if campo.tipo == "elenco" and not sotto:
                    errori.append(f"{dove}: l'elenco '{nome}' va usato con un sottocampo")
            elif nome not in nomi:
                errori.append(f"{dove}: '{{{{{nome}}}}}' non è un campo, una domanda o un derivato")

    for q in d.domande:
        for chiave in ("se", "blocca_se", "vincolo"):
            condizione(getattr(q, chiave), f"domanda {q.id} ({chiave})")
        if q.tipo == "scelta" and not q.opzioni:
            errori.append(f"domanda {q.id}: le domande a scelta hanno le opzioni")
        if q.opzioni_da_regole and q.tipo != "scelta_multipla":
            errori.append(f"domanda {q.id}: opzioni_da_regole vale per le scelte multiple")
    for nome, regola in d.derivati.items():
        if isinstance(regola, str):
            condizione(regola, f"derivato {nome}")
        else:
            for caso in regola:
                condizione(caso.get("se"), f"derivato {nome}")
                if "valore" not in caso:
                    errori.append(f"derivato {nome}: ogni caso ha un 'valore'")
    for nome, campo in d.campi.items():
        if campo.predefinito:
            segnaposto(campo.predefinito, f"campo {nome} (predefinito)")
        if campo.tipo == "elenco" and not campo.sottocampi:
            errori.append(f"campo {nome}: un elenco ha i sottocampi")
    numeri = [f.numero for f in d.fasi]
    if len(set(numeri)) != len(numeri):
        errori.append("fasi: numeri duplicati")
    visti: set[str] = set()
    for f in d.fasi:
        for s in f.sezioni:
            condizione(s.se, f"sezione {s.titolo!r}")
            for c in s.capoversi:
                if c.id in visti:
                    errori.append(f"capoverso {c.id}: identificativo duplicato")
                visti.add(c.id)
                condizione(c.se, f"capoverso {c.id}")
                segnaposto(c.testo, f"capoverso {c.id}")
                if c.ripeti_per and d.campi.get(c.ripeti_per, Campo(etichetta="")).tipo != "elenco":
                    errori.append(f"capoverso {c.id}: ripeti_per deve indicare un campo elenco")
    per_id = {q.id: q for q in d.domande}
    for s in d.suggerimenti:
        condizione(s.se, f"suggerimento per {s.domanda}")
        q = per_id.get(s.domanda)
        if q is None:
            errori.append(f"suggerimento: {s.domanda!r} non è una domanda")
        elif _risposta(q, s.valore) != (s.valore if q.tipo != "importo" else _numero(s.valore)):
            errori.append(f"suggerimento per {s.domanda}: valore {s.valore!r} non ammesso")
    return errori


# ---------------------------------------------------------------------------------------
# Formati dei campi
# ---------------------------------------------------------------------------------------

# valori dei caratteri in posizione dispari per il carattere di controllo del codice fiscale
_DISPARI = dict(zip("0123456789", [1, 0, 5, 7, 9, 13, 15, 17, 19, 21], strict=True)) | dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        [
            1,
            0,
            5,
            7,
            9,
            13,
            15,
            17,
            19,
            21,
            2,
            4,
            18,
            20,
            11,
            3,
            6,
            8,
            12,
            14,
            16,
            10,
            22,
            25,
            24,
            23,
        ],
        strict=True,
    )
)
_PARI = {
    c: (int(c) if c.isdigit() else ord(c) - ord("A"))
    for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
}


def codice_fiscale_valido(cf: str) -> bool:
    cf = cf.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{15}[A-Z]", cf):
        return False
    somma = sum((_DISPARI if i % 2 == 0 else _PARI)[c] for i, c in enumerate(cf[:15]))
    return chr(ord("A") + somma % 26) == cf[15]


def partita_iva_valida(numero: str) -> bool:
    numero = numero.strip()
    if not re.fullmatch(r"\d{11}", numero) or numero == "0" * 11:
        return False
    cifre = [int(c) for c in numero]
    somma = sum(cifre[i] for i in range(0, 10, 2))
    for i in range(1, 10, 2):
        doppio = cifre[i] * 2
        somma += doppio - 9 if doppio > 9 else doppio
    return (10 - somma % 10) % 10 == cifre[10]


def importo_da_testo(testo: str) -> Decimal | None:
    """ "1.234,56", "1234,56", "1234.56", "1234" -> Decimal."""
    t = str(testo).strip().replace("€", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def formato_importo(valore: Decimal) -> str:
    intero, _, decimali = f"{valore:.2f}".partition(".")
    gruppi = re.sub(r"(?<=\d)(?=(\d{3})+$)", ".", intero.lstrip("-"))
    return f"{'-' if valore < 0 else ''}{gruppi},{decimali}"


def codice_normalizzato(tipo: str, valore: Any) -> str:
    """CIG, CUP, codice fiscale e partita IVA senza spazi, punti, trattini e prefisso IT."""
    testo = re.sub(r"[\s.\-/]", "", str(valore)).upper()
    if tipo == "codice_fiscale_piva" and re.fullmatch(r"IT\d{11}", testo):
        testo = testo[2:]
    return testo


def errore_formato(tipo: str, valore: Any) -> str | None:
    """Messaggio se il valore non rispetta il formato del tipo di campo."""
    if valore in (None, ""):
        return None
    testo = str(valore).strip()
    if tipo == "cig" and not re.fullmatch(r"[A-Z0-9]{10}", codice_normalizzato(tipo, testo)):
        return "Il CIG è di 10 caratteri, lettere e cifre"
    if tipo == "cup" and not re.fullmatch(r"[A-Z0-9]{15}", codice_normalizzato(tipo, testo)):
        return "Il CUP è di 15 caratteri, lettere e cifre"
    if tipo == "codice_fiscale_piva":
        t = codice_normalizzato(tipo, testo)
        if re.fullmatch(r"\d{11}", t):
            if not partita_iva_valida(t):
                return (
                    "L'ultima cifra della partita IVA non corrisponde: controlla di aver "
                    "copiato correttamente il numero"
                )
        elif re.fullmatch(r"[A-Z0-9]{16}", t):
            if not codice_fiscale_valido(t):
                return (
                    "L'ultimo carattere del codice fiscale non corrisponde: controlla di "
                    "averlo copiato correttamente"
                )
        else:
            return "La partita IVA ha 11 cifre, il codice fiscale 16 caratteri"
    if tipo == "importo":
        v = importo_da_testo(testo)
        if v is None or v < 0:
            return "Importo non valido (es. 1.234,56)"
    if tipo == "numero" and not re.fullmatch(r"\d+", testo):
        return "Indicare un numero intero"
    if tipo == "data":
        try:
            date.fromisoformat(testo[:10])
        except ValueError:
            return "Data non valida"
    return None


def _testo_valore(tipo: str, valore: Any) -> str:
    if isinstance(valore, bool):
        return "sì" if valore else "no"
    if tipo == "importo" or isinstance(valore, Decimal):
        v = importo_da_testo(str(valore))
        return formato_importo(v) if v is not None else str(valore)
    if tipo == "data":
        try:
            return date.fromisoformat(str(valore)[:10]).strftime("%d/%m/%Y")
        except ValueError:
            return str(valore)
    if tipo in ("cig", "cup", "codice_fiscale_piva"):
        return codice_normalizzato(tipo, valore)
    return str(valore).strip()


# ---------------------------------------------------------------------------------------
# Valutazione di una bozza
# ---------------------------------------------------------------------------------------

MANCANTE = "[[{}]]"  # segnaposto non compilato: riconosciuto dal controllo dei segnaposto
NON_ASSEGNATO = "……"  # dato assegnato fuori dal percorso (es. numero dell'atto)


@dataclass
class DatiBozza:
    risposte: dict[str, Any] = field(default_factory=dict)
    valori: dict[str, Any] = field(default_factory=dict)
    esclusi: set[str] = field(default_factory=set)  # capoversi facoltativi tolti
    inclusi: set[str] = field(default_factory=set)  # facoltativi non inclusi in origine, aggiunti
    testi: dict[str, str] = field(default_factory=dict)  # capoversi riscritti
    riferimenti: list[dict] = field(default_factory=list)  # dalla libreria normativa
    ente: dict[str, Any] = field(default_factory=dict)
    profilo: dict[str, Any] = field(default_factory=dict)
    sistema: dict[str, Any] = field(default_factory=dict)


def _risposta(domanda: Domanda, valore: Any) -> Any:
    if valore in (None, ""):
        return None
    if domanda.tipo == "si_no":
        return valore if isinstance(valore, bool) else str(valore).lower() in ("true", "si", "sì")
    if domanda.tipo in ("importo", "numero"):
        return _numero(valore)
    if domanda.tipo == "scelta":
        return valore if valore in (domanda.opzioni or {}) else None
    if domanda.tipo == "scelta_multipla":
        scelte = valore if isinstance(valore, list) else []
        return [o for o in (domanda.opzioni or {}) if o in scelte]
    return str(valore)


def _derivati(m: ModelloCompilato, variabili: dict[str, Any]) -> None:
    for nome, regola in m.d.derivati.items():
        if isinstance(regola, str):
            variabili[nome] = m.vero(regola, variabili)
        else:
            variabili[nome] = next(
                (c["valore"] for c in regola if m.vero(c.get("se"), variabili)), None
            )


def variabili(m: ModelloCompilato, risposte: dict[str, Any]) -> dict[str, Any]:
    """Risposte (solo delle domande visibili) e valori derivati."""
    v = {q.id: _risposta(q, risposte.get(q.id)) for q in m.d.domande}
    _opzioni_scelte(m, v)
    _derivati(m, v)
    for q in m.d.domande:
        if not m.vero(q.se, v):
            v[q.id] = None  # domanda nascosta: la risposta non conta
    _opzioni_scelte(m, v)
    _derivati(m, v)
    return v


def _opzioni_scelte(m: ModelloCompilato, v: dict[str, Any]) -> None:
    """Ogni opzione di una scelta multipla è una variabile: vera se è stata scelta."""
    for q in m.d.domande:
        if q.tipo == "scelta_multipla":
            for o in q.opzioni or {}:
                v[o] = o in (v.get(q.id) or [])


class Valutazione:
    """Stato di una bozza secondo il modello: domande, fasi, capoversi, campi, testo."""

    def __init__(self, m: ModelloCompilato, dati: DatiBozza):
        self.m = m
        self.dati = dati
        self.v = variabili(m, dati.risposte)

    # --- valori dei campi ---
    def proposto(self, nome: str) -> tuple[Any, str | None]:
        """Valore proposto dalla configurazione e sua provenienza: ente, profilo, modello."""
        campo = self.m.d.campi[nome]
        valore, origine = None, None
        if campo.fonte == "ente":
            valore, origine = self.dati.ente.get(nome), "ente"
        elif campo.fonte == "profilo":
            valore, origine = self.dati.profilo.get(nome), "profilo"
        elif campo.fonte == "sistema":
            valore, origine = self.dati.sistema.get(nome), "sistema"
        if valore in (None, "", []) and campo.predefinito:
            proposto = self._sostituisci(campo.predefinito, grezzo=True)
            if proposto.strip():
                valore, origine = proposto, "modello"
        return valore, origine

    def valore(self, nome: str) -> Any:
        """Valore del campo: quello dell'atto (anche vuoto, se l'utente l'ha svuotato),
        altrimenti quello proposto dalla configurazione."""
        campo = self.m.d.campi.get(nome)
        if campo is None:
            return self.v.get(nome)
        if nome in self.dati.valori:
            return self.dati.valori[nome]
        return self.proposto(nome)[0]

    def _riga_elenco(self, nome: str, indice: int) -> dict:
        righe = self.valore(nome) or []
        return righe[indice] if isinstance(righe, list) and indice < len(righe) else {}

    def _testo(self, nome: str, indice: str, sotto: str, riga: dict | None, grezzo: bool) -> str:
        campo = self.m.d.campi.get(nome)
        if campo is None:  # domanda o derivato
            valore = self.v.get(nome)
            return "" if valore is None else _testo_valore("", valore)
        if campo.tipo == "elenco":
            dati_riga = (
                riga
                if riga is not None and not indice
                else self._riga_elenco(nome, int(indice or 0))
            )
            sottocampo = (campo.sottocampi or {}).get(sotto)
            valore = (dati_riga or {}).get(sotto)
            if valore in (None, ""):
                return "" if grezzo else MANCANTE.format(f"{nome}.{sotto}")
            return _testo_valore(sottocampo.tipo if sottocampo else "testo", valore)
        valore = self.valore(nome)
        if valore in (None, ""):
            if grezzo:
                return ""
            return (
                NON_ASSEGNATO
                if (campo.fonte == "sistema" or not campo.obbligatorio)
                else MANCANTE.format(nome)
            )
        return _testo_valore(campo.tipo, valore)

    def _sostituisci(self, testo: str, riga: dict | None = None, grezzo: bool = False) -> str:
        return SEGNAPOSTO.sub(
            lambda mm: self._testo(mm.group(1), mm.group(2) or "", mm.group(3) or "", riga, grezzo),
            testo,
        )

    # --- domande ---
    def domande(self) -> list[dict]:
        risultato = []
        for q in self.m.d.domande:
            if not self.m.vero(q.se, self.v):
                continue
            suggerimento = next(
                (
                    {"valore": s.valore, "messaggio": s.messaggio.strip()}
                    for s in self.m.d.suggerimenti
                    if s.domanda == q.id and self.m.vero(s.se, self.v)
                ),
                None,
            )
            risultato.append(
                {
                    **q.model_dump(exclude={"se", "blocca_se", "vincolo", "opzioni_da_regole"}),
                    "risposta": self.dati.risposte.get(q.id),
                    # nessuna caratteristica scelta è una risposta valida
                    "mancante": q.tipo != "scelta_multipla" and self.v.get(q.id) is None,
                    "suggerimento": suggerimento,
                }
            )
        return risultato

    def moduli_attivi(self) -> list[str]:
        """Codici delle specificità scelte: le loro schede si aggiungono alla verifica."""
        return [r.codice for r in self.m.d.regole if self.v.get(r.fattore)]

    def blocchi(self) -> list[str]:
        """Messaggi che impediscono di proseguire (es. importo oltre la soglia)."""
        messaggi = []
        for q in self.m.d.domande:
            if q.blocca_se and self.m.vero(q.se, self.v) and self.m.vero(q.blocca_se, self.v):
                messaggi.append(q.messaggio_blocco or f"Risposta non ammessa: {q.testo}")
            if q.vincolo and not self.m.vero(q.vincolo, self.v):
                messaggi.append(f"Risposta incoerente: {q.testo}")
        return messaggi

    def domande_complete(self) -> bool:
        return not self.blocchi() and not any(q["mancante"] for q in self.domande())

    # --- capoversi ---
    def _capoversi_attivi(self, fase: Fase):
        for s in fase.sezioni:
            if not self.m.vero(s.se, self.v):
                continue
            attivi = [c for c in s.capoversi if self.m.vero(c.se, self.v)]
            if attivi or s.riferimenti_libreria:
                yield s, attivi

    def _testo_capoverso(self, c: Capoverso) -> str:
        """Testo del capoverso (anche riscritto) con i segnaposto sostituiti."""
        base = self.dati.testi.get(c.id) if c.modificabile else None
        base = base or c.testo
        if c.ripeti_per:
            righe = self.valore(c.ripeti_per) or [{}]
            return "\n".join(self._sostituisci(base, riga=r) for r in righe)
        return self._sostituisci(base)

    def segmenti(self, c: Capoverso) -> list[dict] | None:
        """Testo del capoverso diviso in testo fisso e dati, per la modifica diretta nell'app:
        al salvataggio i dati rimasti uguali tornano segnaposto e restano collegati ai campi.
        Anche i capoversi non modificabili hanno i segmenti: nell'app un clic su un dato porta
        alla sua casella. None per i capoversi ripetuti per riga (es. impegni)."""
        if c.ripeti_per:
            return None
        base = (self.dati.testi.get(c.id) if c.modificabile else None) or c.testo
        segmenti, da = [], 0
        for m in SEGNAPOSTO.finditer(base):
            if m.start() > da:
                segmenti.append({"testo": base[da : m.start()]})
            segmenti.append(
                {"testo": self._sostituisci(m.group(0)), "segnaposto": m.group(0)}
            )
            da = m.end()
        if da < len(base):
            segmenti.append({"testo": base[da:]})
        return segmenti

    def testi_effettivi(self) -> dict[str, str]:
        """Testi riscritti senza quelli tornati uguali al testo standard del modello."""
        standard = {c.id: c.testo for f in self.m.d.fasi for s in f.sezioni for c in s.capoversi}
        return {
            k: v for k, v in self.dati.testi.items() if k in standard and v.strip() != standard[k]
        }

    def escluso(self, c: Capoverso) -> bool:
        if not c.facoltativo:
            return False
        if c.incluso:
            return c.id in self.dati.esclusi
        return c.id not in self.dati.inclusi

    def _campi_di(self, testo: str) -> list[str]:
        nomi = []
        for nome, _, _ in SEGNAPOSTO.findall(testo):
            if nome in self.m.d.campi and nome not in nomi:
                nomi.append(nome)
        return nomi

    def campo(self, nome: str) -> dict:
        campo = self.m.d.campi[nome]
        valore = self.valore(nome)
        proposto, origine = self.proposto(nome)
        errore = None
        if campo.tipo == "elenco":
            righe = valore if isinstance(valore, list) else []
            mancante = len(righe) < (campo.minimo or (1 if campo.obbligatorio else 0)) or any(
                sc.obbligatorio and r.get(s) in (None, "")
                for r in righe
                for s, sc in (campo.sottocampi or {}).items()
            )
            errori = [
                f"riga {i + 1}, {sc.etichetta}: {err}"
                for i, r in enumerate(righe)
                for s, sc in (campo.sottocampi or {}).items()
                if (err := errore_formato(sc.tipo, r.get(s)))
            ]
            errore = "; ".join(errori) or None
        else:
            mancante = campo.obbligatorio and campo.fonte != "sistema" and valore in (None, "")
            errore = errore_formato(campo.tipo, valore)
        return {
            "nome": nome,
            **campo.model_dump(exclude={"predefinito"}),
            "valore": self.dati.valori.get(nome),
            # l'app precompila la casella con il valore proposto finché l'atto non ne ha uno
            "impostato": nome in self.dati.valori,
            "proposto": proposto,
            "origine": origine,
            "mancante": mancante,
            "errore": errore,
        }

    def fase(self, numero: int) -> dict:
        fase = next(f for f in self.m.d.fasi if f.numero == numero)
        sezioni, nomi_campi = [], []
        for s, attivi in self._capoversi_attivi(fase):
            capoversi = []
            for c in attivi:
                escluso = self.escluso(c)
                base = (self.dati.testi.get(c.id) if c.modificabile else None) or c.testo
                campi = self._campi_di(base)
                if c.ripeti_per and c.ripeti_per not in campi:
                    campi.insert(0, c.ripeti_per)
                if not escluso:
                    nomi_campi += [n for n in campi if n not in nomi_campi]
                capoversi.append(
                    {
                        "id": c.id,
                        "testo": self._testo_capoverso(c),
                        "personalizzato": c.id in self.dati.testi and c.modificabile,
                        "facoltativo": c.facoltativo,
                        "incluso_predefinito": c.incluso,
                        "escluso": escluso,
                        "modificabile": c.modificabile,
                        "aiuto": c.aiuto,
                        "norme": c.norme,
                        "fonte": c.fonte,
                        "campi": campi,
                        "segmenti": self.segmenti(c),
                    }
                )
            sezioni.append(
                {
                    "titolo": s.titolo,
                    "formula": s.formula,
                    "aiuto": s.aiuto,
                    "riferimenti_libreria": s.riferimenti_libreria,
                    "oggetto": s.oggetto,
                    "capoversi": capoversi,
                }
            )
        campi = [self.campo(n) for n in nomi_campi if self.m.d.campi[n].fonte != "sistema"]
        return {
            "numero": fase.numero,
            "titolo": fase.titolo,
            "descrizione": fase.descrizione,
            "formula": fase.formula,
            "premessa": fase.premessa.strip() if fase.premessa else None,
            "numerazione": fase.numerazione,
            "sezioni": sezioni,
            "campi": campi,
            "completa": not any(c["mancante"] or c["errore"] for c in campi),
        }

    # --- composizione ---
    def testo_fase(self, numero: int) -> str:
        fase = next(f for f in self.m.d.fasi if f.numero == numero)
        blocchi: list[str] = []
        if fase.formula:
            blocchi.append(fase.formula)
        if fase.premessa:
            blocchi.append(fase.premessa.strip())
        progressivo = 0
        for s, attivi in self._capoversi_attivi(fase):
            testi = [self._testo_capoverso(c) for c in attivi if not self.escluso(c)]
            if s.riferimenti_libreria:
                testi += [
                    f"l'{r['citazione']};" for r in self.dati.riferimenti if r.get("citazione")
                ]
            testi = [t for t in testi if t.strip()]
            if not testi:
                continue
            if s.oggetto:
                blocchi.append(f"Oggetto: {' '.join(testi)}")
            elif fase.numerazione == "automatica":
                for t in testi:
                    progressivo += 1
                    blocchi.append(f"{progressivo}) {t}")
            elif s.formula:
                blocchi.append(f"{s.formula}:\n" + "\n".join(f"- {t}" for t in testi))
            else:
                blocchi.append("\n".join(testi))
        return "\n\n".join(blocchi)

    def oggetto(self) -> str:
        for f in self.m.d.fasi:
            for s, attivi in self._capoversi_attivi(f):
                if s.oggetto:
                    return " ".join(self._testo_capoverso(c) for c in attivi).strip()
        return ""

    def parti(self) -> dict[str, str]:
        """Testo per fase, nei segnaposto della carta intestata."""
        nomi = {1: "intestazione", 2: "preambolo", 3: "dispositivo", 4: "chiusura"}
        return {
            nomi.get(f.numero, f"fase_{f.numero}"): self.testo_fase(f.numero) for f in self.m.d.fasi
        }

    def testo(self) -> str:
        return "\n\n".join(t for t in self.parti().values() if t)

    def riepilogo(self) -> dict:
        fasi = [self.fase(f.numero) for f in sorted(self.m.d.fasi, key=lambda f: f.numero)]
        return {
            "domande": self.domande(),
            "blocchi": self.blocchi(),
            "domande_complete": self.domande_complete(),
            "fasi": fasi,
            "completa": self.domande_complete() and all(f["completa"] for f in fasi),
        }


def campi_ente(modelli: list[ModelloCompilato]) -> dict[str, dict]:
    """Campi con fonte "ente" dei modelli indicati: sono i "Dati dell'ente"."""
    risultato: dict[str, dict] = {}
    for m in modelli:
        for nome, campo in m.d.campi.items():
            if campo.fonte == "ente" and nome not in risultato:
                risultato[nome] = {
                    "nome": nome,
                    **campo.model_dump(include={"etichetta", "tipo", "aiuto"}),
                }
    return risultato
