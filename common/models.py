"""Modelli ORM condivisi. Devono restare allineati allo schema in deploy/k8s/sql/."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TestoLungo = Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb")
FileBinario = LargeBinary().with_variant(LONGBLOB(), "mysql").with_variant(LONGBLOB(), "mariadb")


def nuovo_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {dict[str, Any]: JSON, list[Any]: JSON}


class Ruolo:
    """Ruoli nell'ente. ADMIN amministra l'ente (pubblica i modelli, gestisce utenti e
    accessi). Gli enti si creano con deploy/enti.py, senza un utente dell'app."""

    REDATTORE = "REDATTORE"
    CONTROLLORE = "CONTROLLORE"
    GESTORE_MODELLI = "GESTORE_MODELLI"  # modifica modelli, specificità e checklist in bozza
    ADMIN = "ADMIN"  # amministratore dell'ente: pubblica le modifiche ai modelli
    TRASPARENZA = "TRASPARENZA"  # modulo trasparenza: analisi, schede, verbali
    # modulo anticorruzione: il referente propone e compila il monitoraggio della sua
    # struttura; il RPCT (e il suo staff) modifica, approva e verifica
    ANTICORRUZIONE_REFERENTE = "ANTICORRUZIONE_REFERENTE"
    ANTICORRUZIONE_RPCT = "ANTICORRUZIONE_RPCT"
    # modulo performance: il responsabile (dirigente di un servizio o responsabile di un
    # ufficio) dichiara e aggiorna gli obiettivi della sua struttura; l'amministratore apre e
    # chiude i PIAO e vede e corregge tutto
    PERFORMANCE_RESPONSABILE = "PERFORMANCE_RESPONSABILE"
    PERFORMANCE_AMMINISTRATORE = "PERFORMANCE_AMMINISTRATORE"
    # consulta le ricerche senza risposta e i feedback di cittadini e utenti (es. l'ufficio
    # statistica): non dipende da un modulo
    ANALISI_RICERCHE = "ANALISI_RICERCHE"
    TUTTI = (
        REDATTORE, CONTROLLORE, GESTORE_MODELLI, TRASPARENZA,
        ANTICORRUZIONE_REFERENTE, ANTICORRUZIONE_RPCT,
        PERFORMANCE_RESPONSABILE, PERFORMANCE_AMMINISTRATORE, ANALISI_RICERCHE, ADMIN,
    )  # fmt: skip


class Modulo:
    """Moduli del sistema, abilitati per ente (Ente.moduli_json, con deploy/enti.py)."""

    REDAZIONE = "redazione"  # redazione e controllo degli atti, modelli e checklist
    TRASPARENZA = "trasparenza"  # verifica e schede di Amministrazione Trasparente
    ANTICORRUZIONE = "anticorruzione"  # mappatura dei processi e gestione del rischio corruttivo
    ASSISTENTE = "assistente"  # chat con l'LLM per il lavoro quotidiano (email, riassunti...)
    PERFORMANCE = "performance"  # obiettivi del PIAO per struttura, con azioni e misure
    TUTTI = (REDAZIONE, TRASPARENZA, ANTICORRUZIONE, PERFORMANCE, ASSISTENTE)


UTENTE_ADMIN = "admin"  # amministratore creato con l'ente (deploy/enti.py)


class OrigineUtente:
    LDAP = "LDAP"  # Active Directory dell'ente: password mai salvata
    LOCALE = "LOCALE"  # password con hash nel database


class StatoVerifica:
    IN_CODA = "IN_CODA"
    IN_CORSO = "IN_CORSO"
    COMPLETATA = "COMPLETATA"
    ERRORE = "ERRORE"


class Ente(Base):
    """Ente dell'installazione: utenti, configurazione e dati sono separati per ente.
    Si riconosce dal dominio della richiesta (EnteDominio)."""

    __tablename__ = "enti"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    codice: Mapped[str] = mapped_column(String(50), unique=True)  # es. provincialucca
    nome: Mapped[str] = mapped_column(String(255))
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    moduli_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # dati dell'ente usati dai modelli (campi con fonte "ente") e carta intestata
    dati_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    carta_intestata_nome: Mapped[str | None] = mapped_column(String(255))
    carta_intestata: Mapped[bytes | None] = mapped_column(FileBinario, deferred=True)
    # profilo dell'ente, per tutti i moduli: logo (immagine) nei documenti generati e
    # caratteristiche dell'amministrazione (testo libero dato all'LLM come contesto)
    logo_mime: Mapped[str | None] = mapped_column(String(50))
    logo: Mapped[bytes | None] = mapped_column(FileBinario, deferred=True)
    caratteristiche: Mapped[str | None] = mapped_column(Text)
    # testo per l'assistenza agli utenti (login, menu dell'app, pagine di aiuto), es. a chi
    # scrivere o chi chiamare
    assistenza: Mapped[str | None] = mapped_column(Text)
    # indirizzo della dichiarazione di accessibilità dell'ente (AgID, form.agid.gov.it),
    # linkata in fondo alle pagine pubbliche
    dichiarazione_accessibilita: Mapped[str | None] = mapped_column(String(500))
    # accesso: utenti locali e/o Active Directory (url, dominio, base_dn, ca_pem,
    # verifica_certificato, timeout, gruppi {ruolo: gruppo})
    accesso_locale: Mapped[bool] = mapped_column(Boolean, default=True)
    ldap_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # collegamento al RAG (common/rag.py): url e chiave_cifrata
    rag_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # posta in uscita (common/posta.py): host, porta, sicurezza, utente, password_cifrata,
    # mittente, rispondi_a
    smtp_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # anticorruzione: la mappatura è consultabile dai cittadini su /pubblico/mappatura
    mappatura_pubblica: Mapped[bool] = mapped_column(Boolean, default=False)
    # i procedimenti (art. 35) sono consultabili dai cittadini su /pubblico/procedimenti
    procedimenti_pubblici: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def modulo_attivo(self, modulo: str) -> bool:
        return modulo in (self.moduli_json or [])


class EnteDominio(Base):
    """Dominio (host) con cui si raggiunge l'ente, es. attipa.provincia.lucca.it."""

    __tablename__ = "enti_domini"

    dominio: Mapped[str] = mapped_column(String(255), primary_key=True)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))


class Struttura(Base):
    """Struttura organizzativa dell'ente (settore, staff, U.O.), con la gerarchia: un utente
    assegnato a una struttura opera anche su quelle sottostanti. Usata da tutti i moduli.
    Una struttura soppressa si disattiva: lo storico può richiamarla."""

    __tablename__ = "strutture"
    __table_args__ = (UniqueConstraint("ente_id", "codice", name="uq_struttura_ente"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    codice: Mapped[str] = mapped_column(String(50))  # es. "SETTORE 2", "U.O. 2.2"
    descrizione: Mapped[str] = mapped_column(String(255))
    padre_id: Mapped[str | None] = mapped_column(ForeignKey("strutture.id", ondelete="RESTRICT"))
    ordine: Mapped[int] = mapped_column(Integer, default=0)
    attiva: Mapped[bool] = mapped_column(Boolean, default=True)
    # recapiti istituzionali (procedimenti, art. 35 d.lgs. 33/2013): ufficio responsabile, ufficio
    # del provvedimento finale, ufficio per le istanze, potere sostitutivo
    telefono: Mapped[str | None] = mapped_column(String(50))
    peo: Mapped[str | None] = mapped_column(String(255))
    pec: Mapped[str | None] = mapped_column(String(255))
    sede: Mapped[str | None] = mapped_column(String(255))  # indirizzo
    orari: Mapped[list[Any] | None] = mapped_column(JSON)  # [{giorni, ora_inizio, ora_fine}]
    responsabile: Mapped[str | None] = mapped_column(String(255))  # nominativo
    qualifica: Mapped[str | None] = mapped_column(String(255))  # del responsabile
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    """Utente di un ente (Active Directory o locale). Ogni ente nasce con l'utente locale
    admin (UTENTE_ADMIN), con la password iniziale da cambiare al primo accesso."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("ente_id", "username", name="uq_utente_ente"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    username: Mapped[str] = mapped_column(String(100))
    origine: Mapped[str] = mapped_column(String(10), default=OrigineUtente.LDAP)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # cresce a ogni cambio di password o disattivazione: invalida le sessioni aperte
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # password iniziale o scelta dall'amministratore: finché non la cambia, l'utente può solo
    # cambiarla (deps.autenticato)
    cambio_password: Mapped[bool] = mapped_column(Boolean, default=False)
    nome_completo: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    ufficio: Mapped[str | None] = mapped_column(String(255))
    # struttura organizzativa, assegnata dall'amministratore (anche agli utenti di AD)
    struttura_id: Mapped[str | None] = mapped_column(ForeignKey("strutture.id", ondelete="SET NULL"))
    # decreto di conferimento dell'incarico (es. "del Sindaco n. 12 del 3 gennaio 2026"):
    # precompila la competenza negli atti
    decreto_incarico: Mapped[str | None] = mapped_column(String(255))
    ruoli: Mapped[list[Any]] = mapped_column(JSON, default=list)
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_accesso: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def ha_ruolo(self, *ruoli: str) -> bool:
        return any(r in (self.ruoli or []) for r in ruoli)


class TipologiaAtto(Base):
    __tablename__ = "tipologie_atto"

    codice: Mapped[str] = mapped_column(String(50), primary_key=True)
    descrizione: Mapped[str] = mapped_column(String(255))
    ordine: Mapped[int] = mapped_column(Integer, default=0)


class FonteNorma:
    NORMATTIVA = "NORMATTIVA"
    MANUALE = "MANUALE"  # regolamenti interni e altre fonti caricate dagli utenti


class NormaAtto(Base):
    __tablename__ = "norme_atti"

    urn: Mapped[str] = mapped_column(String(255), primary_key=True)
    fonte: Mapped[str] = mapped_column(String(20), default=FonteNorma.NORMATTIVA)
    # solo per le norme manuali (Normattiva è comune a tutti gli enti)
    ente_id: Mapped[str | None] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    denominazione: Mapped[str] = mapped_column(String(100))
    data_provvedimento: Mapped[date] = mapped_column(Date)
    numero: Mapped[str] = mapped_column(String(20))
    titolo: Mapped[str | None] = mapped_column(Text)
    citazione: Mapped[str] = mapped_column(String(255))
    codice_redazionale: Mapped[str | None] = mapped_column(String(20))
    data_gu: Mapped[date | None] = mapped_column(Date)
    # solo norme manuali: come le si cita negli atti, e data di abrogazione dell'intero atto
    denominazioni_json: Mapped[list[Any] | None] = mapped_column(JSON)
    abrogata_dal: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NormaArticoloVersione(Base):
    __tablename__ = "norme_articoli_versioni"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    urn_atto: Mapped[str] = mapped_column(ForeignKey("norme_atti.urn", ondelete="CASCADE"))
    articolo: Mapped[str] = mapped_column(String(30))
    rubrica: Mapped[str | None] = mapped_column(Text)
    vigenza_inizio: Mapped[date | None] = mapped_column(Date)
    vigenza_fine: Mapped[date | None] = mapped_column(Date)
    struttura_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    testo_html: Mapped[str] = mapped_column(TestoLungo)
    hash_testo: Mapped[str] = mapped_column(String(64))
    rinvii_json: Mapped[list[Any] | None] = mapped_column(JSON)
    scaricato_il: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StatoTestoNorma:
    IN_CONVERSIONE = "IN_CONVERSIONE"
    DA_CONFERMARE = "DA_CONFERMARE"
    ATTIVO = "ATTIVO"
    SOSTITUITO = "SOSTITUITO"  # confermato un altro testo con la stessa data di vigenza
    ERRORE_CONVERSIONE = "ERRORE_CONVERSIONE"


class NormaTestoCaricato(Base):
    """File caricato di una norma manuale: un testo vigente da `vigenza_inizio`."""

    __tablename__ = "norme_testi_caricati"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    urn_atto: Mapped[str] = mapped_column(ForeignKey("norme_atti.urn", ondelete="CASCADE"))
    vigenza_inizio: Mapped[date] = mapped_column(Date)
    file_nome: Mapped[str] = mapped_column(String(255))
    file_mime: Mapped[str] = mapped_column(String(100))
    file_percorso: Mapped[str] = mapped_column(String(500))
    file_sha256: Mapped[str] = mapped_column(String(64))
    file_dimensione: Mapped[int] = mapped_column(Integer)
    stato: Mapped[str] = mapped_column(String(30), default=StatoTestoNorma.IN_CONVERSIONE)
    # testo in Markdown prodotto dal converter, correggibile prima della conferma
    testo: Mapped[str | None] = mapped_column(TestoLungo, deferred=True)
    errore: Mapped[str | None] = mapped_column(Text)
    caricato_da: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confermato_il: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Riferimento(Base):
    __tablename__ = "riferimenti"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    urn_atto: Mapped[str] = mapped_column(ForeignKey("norme_atti.urn"))
    articolo: Mapped[str] = mapped_column(String(30))
    comma: Mapped[str | None] = mapped_column(String(20))
    lettera: Mapped[str | None] = mapped_column(String(20))
    citazione: Mapped[str] = mapped_column(String(500))
    tipologie_atto: Mapped[list[Any] | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    atto: Mapped[NormaAtto] = relationship(lazy="joined")


class NormattivaSync(Base):
    __tablename__ = "normattiva_sync"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    intervallo_da: Mapped[datetime] = mapped_column(DateTime)
    intervallo_a: Mapped[datetime] = mapped_column(DateTime)
    atti_modificati: Mapped[int] = mapped_column(Integer, default=0)
    articoli_aggiornati: Mapped[int] = mapped_column(Integer, default=0)
    esito: Mapped[str] = mapped_column(String(20))
    dettaglio: Mapped[str | None] = mapped_column(Text)
    eseguito_il: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Checklist(Base):
    __tablename__ = "checklists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    codice: Mapped[str] = mapped_column(String(100))
    versione: Mapped[int] = mapped_column(Integer, default=1)
    titolo: Mapped[str] = mapped_column(String(255))
    tipologia_atto: Mapped[str] = mapped_column(ForeignKey("tipologie_atto.codice"))
    # livello della scheda: generica della tipologia (entrambi vuoti), di un modello di atto
    # o di una specificità (modulo di regole); sono codici, validi per tutte le versioni
    modello: Mapped[str | None] = mapped_column(String(100))
    modulo: Mapped[str | None] = mapped_column(String(100))
    descrizione: Mapped[str | None] = mapped_column(Text)
    attiva: Mapped[bool] = mapped_column(Boolean, default=True)
    # provenienza (common/pacchetti.py): impronta del contenuto e, se deriva da un pacchetto
    # standard, il pacchetto e la versione standard di riferimento per gli aggiornamenti
    impronta: Mapped[str | None] = mapped_column(String(64))
    pacchetto: Mapped[str | None] = mapped_column(String(150))
    impronta_base: Mapped[str | None] = mapped_column(String(64))
    base_sorgente: Mapped[str | None] = mapped_column(TestoLungo, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    elementi: Mapped[list[ChecklistElemento]] = relationship(
        order_by="ChecklistElemento.ordine",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ChecklistElemento(Base):
    __tablename__ = "checklist_elementi"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    checklist_id: Mapped[str] = mapped_column(ForeignKey("checklists.id", ondelete="CASCADE"))
    ordine: Mapped[int] = mapped_column(Integer, default=0)
    titolo: Mapped[str] = mapped_column(String(255))
    regola: Mapped[str] = mapped_column(Text)
    riferimenti_json: Mapped[list[Any] | None] = mapped_column(JSON)
    obbligatorio: Mapped[bool] = mapped_column(Boolean, default=True)
    # capoversi del modello o della specificità che soddisfano il controllo (id)
    capoversi_json: Mapped[list[Any] | None] = mapped_column(JSON)


class ModelloAtto(Base):
    """Modello di atto a 4 fasi, con versioni come le checklist. Il database comanda: i
    modelli standard arrivano con i pacchetti (common/pacchetti.py) e l'ente li modifica."""

    __tablename__ = "modelli_atto"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    codice: Mapped[str] = mapped_column(String(100))
    versione: Mapped[int] = mapped_column(Integer, default=1)
    titolo: Mapped[str] = mapped_column(String(255))
    provvedimento: Mapped[str] = mapped_column(String(100))
    tipologia_atto: Mapped[str] = mapped_column(ForeignKey("tipologie_atto.codice"))
    descrizione: Mapped[str | None] = mapped_column(Text)
    # definizione composta con le specificità attive e già controllata (common/modelli.py),
    # sorgente YAML del modello senza specificità, specificità usate {codice: impronta}
    definizione_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    sorgente: Mapped[str] = mapped_column(TestoLungo, deferred=True)
    moduli_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # provenienza: come per le checklist
    impronta: Mapped[str | None] = mapped_column(String(64))
    pacchetto: Mapped[str | None] = mapped_column(String(150))
    impronta_base: Mapped[str | None] = mapped_column(String(64))
    base_sorgente: Mapped[str | None] = mapped_column(TestoLungo, deferred=True)
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModuloDiRegole(Base):
    """Specificità (modulo di regole) che si compone nei modelli: versionata come i modelli."""

    __tablename__ = "moduli_regole"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    codice: Mapped[str] = mapped_column(String(100))
    versione: Mapped[int] = mapped_column(Integer, default=1)
    etichetta: Mapped[str] = mapped_column(String(255))
    definizione_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    sorgente: Mapped[str] = mapped_column(TestoLungo, deferred=True)
    impronta: Mapped[str | None] = mapped_column(String(64))
    pacchetto: Mapped[str | None] = mapped_column(String(150))
    impronta_base: Mapped[str | None] = mapped_column(String(64))
    base_sorgente: Mapped[str | None] = mapped_column(TestoLungo, deferred=True)
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BozzaConfigurazione(Base):
    """Modifica in corso di un modello, di una specificità o di una checklist: invisibile a
    chi scrive gli atti finché non viene pubblicata (nuova versione)."""

    __tablename__ = "bozze_configurazione"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(20))  # modello, modulo, checklist
    codice: Mapped[str] = mapped_column(String(100))
    definizione_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    versione_partenza: Mapped[int | None] = mapped_column(Integer)  # None: oggetto nuovo
    autore_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PropostaModello(Base):
    """Modifica a un capoverso proposta da chi scrive un atto, per il gestore dei modelli."""

    __tablename__ = "proposte_modello"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    modello: Mapped[str] = mapped_column(String(100))  # codice del modello
    versione: Mapped[int] = mapped_column(Integer)
    capoverso: Mapped[str] = mapped_column(String(100))
    testo_attuale: Mapped[str] = mapped_column(Text)
    testo_proposto: Mapped[str] = mapped_column(Text)
    motivazione: Mapped[str | None] = mapped_column(Text)
    stato: Mapped[str] = mapped_column(String(20), default="APERTA")  # ACCOLTA, RESPINTA
    autore_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    gestita_da: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    nota_gestione: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    gestita_il: Mapped[datetime | None] = mapped_column(DateTime)


class PacchettoImportato(Base):
    """Pacchetto di modelli, specificità e checklist caricato dall'amministratore: prima
    analizzato (cosa cambia rispetto all'ente), poi importato con le decisioni prese."""

    __tablename__ = "pacchetti"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    nome: Mapped[str] = mapped_column(String(150))
    versione: Mapped[str] = mapped_column(String(50))
    descrizione: Mapped[str | None] = mapped_column(Text)
    stato: Mapped[str] = mapped_column(String(20))  # ANALIZZATO, IMPORTATO, ANNULLATO
    contenuto: Mapped[bytes | None] = mapped_column(FileBinario, deferred=True)
    analisi_json: Mapped[list[Any] | None] = mapped_column(JSON)
    resoconto_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    caricato_da: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    importato_il: Mapped[datetime | None] = mapped_column(DateTime)


class Bozza(Base):
    __tablename__ = "bozze"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    modello_id: Mapped[str] = mapped_column(ForeignKey("modelli_atto.id"))
    # ricavati dal testo composto, per l'elenco e la ricerca
    oggetto: Mapped[str] = mapped_column(Text, default="")
    tipologia_atto: Mapped[str] = mapped_column(ForeignKey("tipologie_atto.codice"))
    data_adozione_prevista: Mapped[date | None] = mapped_column(Date)
    # compilazione: risposte alle domande, valori dei campi, capoversi facoltativi tolti o
    # aggiunti e testi riscritti ({"esclusi": [...], "inclusi": [...], "testi": {...}})
    risposte_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    valori_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    personalizzazioni_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    riferimenti_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # avanzamento per l'elenco: fasi senza dati mancanti; None finché le domande iniziali
    # non hanno risposta
    fasi_complete: Mapped[int | None] = mapped_column(Integer)
    contenuto_testo: Mapped[str | None] = mapped_column(TestoLungo)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    modello: Mapped[ModelloAtto] = relationship(lazy="joined")


class SessioneControllo(Base):
    __tablename__ = "controlli_sessioni"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    titolo: Mapped[str] = mapped_column(String(255))
    stato: Mapped[str] = mapped_column(String(30), default="APERTA")
    creata_da: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AttoControllato(Base):
    __tablename__ = "atti_controllati"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    sessione_id: Mapped[str] = mapped_column(
        ForeignKey("controlli_sessioni.id", ondelete="CASCADE")
    )
    numero_registro: Mapped[str | None] = mapped_column(String(50))
    data_adozione: Mapped[date] = mapped_column(Date)
    settore: Mapped[str | None] = mapped_column(String(255))
    tipologia_atto: Mapped[str | None] = mapped_column(ForeignKey("tipologie_atto.codice"))
    # modello a cui l'atto corrisponde e specificità: scelgono le schede di controllo
    modello: Mapped[str | None] = mapped_column(String(100))
    moduli_json: Mapped[list[Any] | None] = mapped_column(JSON)
    oggetto: Mapped[str | None] = mapped_column(Text)
    file_nome: Mapped[str] = mapped_column(String(255))
    file_mime: Mapped[str] = mapped_column(String(100))
    # file originale nell'archivio su filesystem (ARCHIVIO_DIR), non nel database
    file_percorso: Mapped[str | None] = mapped_column(String(500))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_dimensione: Mapped[int | None] = mapped_column(Integer)
    # testo dell'atto in Markdown, prodotto dal converter
    contenuto_testo: Mapped[str | None] = mapped_column(TestoLungo, deferred=True)
    # IN_CONVERSIONE -> IN_ANALISI -> ANALIZZATO -> IN_REVISIONE -> CHIUSO
    # (ERRORE_CONVERSIONE se il file non è convertibile)
    stato: Mapped[str] = mapped_column(String(30), default="IN_CONVERSIONE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Verifica(Base):
    __tablename__ = "verifiche"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    bozza_id: Mapped[str | None] = mapped_column(ForeignKey("bozze.id", ondelete="CASCADE"))
    atto_controllato_id: Mapped[str | None] = mapped_column(
        ForeignKey("atti_controllati.id", ondelete="CASCADE")
    )
    # schede di controllo applicate: generica della tipologia, del modello, delle specificità
    checklist_ids: Mapped[list[Any] | None] = mapped_column(JSON)
    data_riferimento: Mapped[date] = mapped_column(Date)
    stato: Mapped[str] = mapped_column(String(20), default=StatoVerifica.IN_CODA)
    tentativi: Mapped[int] = mapped_column(Integer, default=0)
    errore: Mapped[str | None] = mapped_column(Text)
    worker: Mapped[str | None] = mapped_column(String(100))
    avviata_il: Mapped[datetime | None] = mapped_column(DateTime)
    completata_il: Mapped[datetime | None] = mapped_column(DateTime)
    esito_riferimenti: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    esito_automatico: Mapped[list[Any] | None] = mapped_column(JSON)
    esito_finale: Mapped[list[Any] | None] = mapped_column(JSON)
    motivazione: Mapped[str | None] = mapped_column(Text)
    revisore_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    richiesta_da: Mapped[str] = mapped_column(ForeignKey("users.id"))
    modello_llm: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TrasparenzaDocumento(Base):
    """Documento del modulo trasparenza (scheda, report di analisi, verbale): privato di chi
    lo salva, visibile in lettura all'amministratore dell'ente."""

    __tablename__ = "trasparenza_documenti"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    utente_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(10))  # SCHEDA, ANALISI, VERBALE
    schema_id: Mapped[str | None] = mapped_column(String(50))  # es. ART_23
    descrizione: Mapped[str] = mapped_column(String(255))
    html: Mapped[str] = mapped_column(TestoLungo, deferred=True)
    esito: Mapped[str | None] = mapped_column(String(40))  # esito di validazione (analisi)
    dati_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, deferred=True)  # form della scheda
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TrasparenzaLavoro(Base):
    """Analisi o estrazione del modulo trasparenza, eseguita dal worker (coda "trasparenza").
    I file caricati stanno nell'archivio finché il lavoro non è concluso."""

    __tablename__ = "trasparenza_lavori"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    utente_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(10))  # ANALISI, ESTRAZIONE
    stato: Mapped[str] = mapped_column(String(20), default=StatoVerifica.IN_CODA)  # come le verifiche
    # controllo o schema, fonte (url, opzioni, file nell'archivio), note e date
    richiesta: Mapped[dict[str, Any]] = mapped_column(JSON)
    risultato: Mapped[dict[str, Any] | None] = mapped_column(JSON, deferred=True)
    errore: Mapped[str | None] = mapped_column(Text)
    modello_llm: Mapped[str | None] = mapped_column(String(100))
    tentativi: Mapped[int] = mapped_column(Integer, default=0)
    worker: Mapped[str | None] = mapped_column(String(100))
    avviato_il: Mapped[datetime | None] = mapped_column(DateTime)
    completato_il: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())



# --- modulo anticorruzione (progettazione/anticorruzione.md) --------------------------------


class AcMetodologia(Base):
    """Metodologia di valutazione del rischio adottata dall'ente nel PIAO (indicatori, scala,
    matrice, livelli; common/anticorruzione/metodologia.py). Senza riga vale lo standard."""

    __tablename__ = "ac_metodologie"

    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"), primary_key=True)
    dati: Mapped[dict[str, Any]] = mapped_column(JSON)
    impronta: Mapped[str | None] = mapped_column(String(64))
    pacchetto: Mapped[str | None] = mapped_column(String(150))
    impronta_base: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# Modulo anticorruzione. Le relationship(lazy="raise") verso le tabelle "padre" non servono
# per leggere (si usano gli id) ma dicono alla sessione in che ordine scrivere: senza, una misura
# può essere inserita prima del suo rischio e MySQL rifiuta la chiave esterna.


class AcArea(Base):
    """Area di rischio (PNA: A, B, C... più quelle dell'ente)."""

    __tablename__ = "ac_aree"
    __table_args__ = (UniqueConstraint("ente_id", "codice", name="uq_ac_area"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    codice: Mapped[str] = mapped_column(String(20))
    descrizione: Mapped[str] = mapped_column(String(500))
    descrizione_breve: Mapped[str | None] = mapped_column(String(255))


class AcProcesso(Base):
    """Processo mappato: si compone di attività, che hanno rischi, mitigati da misure. Senza
    struttura responsabile è trasversale (tutti i servizi). La provenienza (pacchetto) è del
    processo intero, con le sue attività, rischi e misure."""

    __tablename__ = "ac_processi"
    __table_args__ = (UniqueConstraint("ente_id", "codice", name="uq_ac_processo"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    codice: Mapped[str] = mapped_column(String(50))  # es. A.1
    tipo: Mapped[str] = mapped_column(String(20), default="PROCESSO")  # PROCESSO, PROCEDIMENTO
    area_id: Mapped[str | None] = mapped_column(ForeignKey("ac_aree.id", ondelete="SET NULL"))
    area: Mapped["AcArea | None"] = relationship(lazy="raise")
    denominazione: Mapped[str] = mapped_column(String(500))
    descrizione: Mapped[str | None] = mapped_column(Text)
    tempi: Mapped[str | None] = mapped_column(Text)
    attori_esterni: Mapped[str | None] = mapped_column(Text)
    termine_conclusione: Mapped[str | None] = mapped_column(String(255))  # procedimento
    norma_riferimento: Mapped[str | None] = mapped_column(Text)  # procedimento
    # procedimento: dati propri dell'art. 35 d.lgs. 33/2013 (common/anticorruzione/art35.py)
    art35: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    struttura_id: Mapped[str | None] = mapped_column(ForeignKey("strutture.id", ondelete="SET NULL"))
    impronta: Mapped[str | None] = mapped_column(String(64))
    pacchetto: Mapped[str | None] = mapped_column(String(150))
    impronta_base: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AcAttivita(Base):
    __tablename__ = "ac_attivita"
    __table_args__ = (UniqueConstraint("ente_id", "codice", name="uq_ac_attivita"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    processo_id: Mapped[str] = mapped_column(ForeignKey("ac_processi.id", ondelete="CASCADE"))
    processo: Mapped["AcProcesso"] = relationship(lazy="raise")
    codice: Mapped[str] = mapped_column(String(50))  # es. A.1.1
    descrizione: Mapped[str] = mapped_column(Text)
    strutture_coinvolte: Mapped[str | None] = mapped_column(Text)


class AcRischio(Base):
    """Evento rischioso di un'attività, con la valutazione: valori degli indicatori,
    probabilità e impatto calcolati (moda) ed eventualmente corretti con motivazione, livello
    dalla matrice della metodologia."""

    __tablename__ = "ac_rischi"
    __table_args__ = (UniqueConstraint("ente_id", "codice", name="uq_ac_rischio"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    attivita_id: Mapped[str] = mapped_column(ForeignKey("ac_attivita.id", ondelete="CASCADE"))
    attivita: Mapped["AcAttivita"] = relationship(lazy="raise")
    codice: Mapped[str] = mapped_column(String(60))  # es. A.1.1_R.1
    evento: Mapped[str] = mapped_column(Text)
    fattore_abilitante: Mapped[str | None] = mapped_column(String(500))
    valori_probabilita: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # {id indicatore: valore}
    valori_impatto: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    probabilita_calcolata: Mapped[str | None] = mapped_column(String(50))
    impatto_calcolato: Mapped[str | None] = mapped_column(String(50))
    probabilita: Mapped[str | None] = mapped_column(String(50))
    impatto: Mapped[str | None] = mapped_column(String(50))
    livello: Mapped[str | None] = mapped_column(String(50))
    motivazione_correzione: Mapped[str | None] = mapped_column(Text)
    valutato_il: Mapped[datetime | None] = mapped_column(DateTime)


class AcMisura(Base):
    """Misura che mitiga un rischio: generale o specifica, con la categoria (PNA), l'eventuale
    obbligo di pubblicazione (schema ANAC del modulo trasparenza) e l'attuazione programmata."""

    __tablename__ = "ac_misure"
    __table_args__ = (UniqueConstraint("ente_id", "codice", name="uq_ac_misura"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    rischio_id: Mapped[str] = mapped_column(ForeignKey("ac_rischi.id", ondelete="CASCADE"))
    rischio: Mapped["AcRischio"] = relationship(lazy="raise")
    codice: Mapped[str] = mapped_column(String(70))  # es. A.1.1_R.1_M.1
    descrizione: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), default="SPECIFICA")  # GENERALE, SPECIFICA
    categoria: Mapped[str | None] = mapped_column(String(255))
    obbligo_trasparenza: Mapped[str | None] = mapped_column(String(100))  # schema ANAC, es. ART_23
    fasi: Mapped[str | None] = mapped_column(Text)
    tempi: Mapped[str | None] = mapped_column(Text)
    struttura_id: Mapped[str | None] = mapped_column(ForeignKey("strutture.id", ondelete="SET NULL"))
    indicatore: Mapped[str | None] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)



class AcContatore(Base):
    """Ultimo numero assegnato a un prefisso di codice (es. "A.1." per le attività del
    processo A.1): i codici della mappatura non si riusano, nemmeno dopo un'eliminazione."""

    __tablename__ = "ac_contatori"

    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"), primary_key=True)
    prefisso: Mapped[str] = mapped_column(String(100), primary_key=True)
    ultimo: Mapped[int] = mapped_column(Integer)


class AcProposta(Base):
    """Proposta di un referente su un elemento della mappatura (area, processo o
    procedimento, attività, rischio con la valutazione, misura): creazione, modifica o
    eliminazione. La creazione può portare con sé gli elementi sottostanti (es. un'attività
    con i suoi rischi e misure). Stati: INVIATA (alla creazione) -> APPROVATA (applicata) |
    RESPINTA | RESTITUITA (si corregge e torna INVIATA); finché non è decisa si ritira."""

    __tablename__ = "ac_proposte"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    utente_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(10))  # CREA, MODIFICA, ELIMINA
    oggetto: Mapped[str] = mapped_column(String(20))  # AREA, PROCESSO, ATTIVITA, RISCHIO, MISURA
    elemento_id: Mapped[str | None] = mapped_column(String(36))  # modificato, eliminato o creato
    padre_id: Mapped[str | None] = mapped_column(String(36))  # creazione: dove si aggiunge
    # processo interessato: la struttura del referente si controlla su questo
    processo_id: Mapped[str | None] = mapped_column(ForeignKey("ac_processi.id", ondelete="SET NULL"))
    processo: Mapped["AcProcesso | None"] = relationship(lazy="raise")
    dati: Mapped[dict[str, Any]] = mapped_column(JSON)  # eliminazione: l'elemento com'era
    prima: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # modifica: com'era alla proposta
    contesto: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # percorso e codice
    stato: Mapped[str] = mapped_column(String(20), default="INVIATA")
    nota: Mapped[str | None] = mapped_column(Text)  # del referente
    motivazione: Mapped[str | None] = mapped_column(Text)  # del RPCT (respinta, restituita, approvata)
    deciso_da: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    inviata_il: Mapped[datetime | None] = mapped_column(DateTime)
    decisa_il: Mapped[datetime | None] = mapped_column(DateTime)



class AcMonitoraggio(Base):
    """Dichiarazione annuale sull'attuazione di una misura da parte di una struttura, con la
    verifica del RPCT. Conserva una copia della misura e del suo contesto (processo, attività,
    rischio, struttura) com'erano al momento della dichiarazione: resta anche se la mappatura
    cambia. Una misura trasversale (senza struttura responsabile) la dichiara ogni struttura."""

    __tablename__ = "ac_monitoraggi"
    __table_args__ = (UniqueConstraint("ente_id", "anno", "misura_id", "struttura_id", name="uq_ac_monitoraggio"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    anno: Mapped[int] = mapped_column(Integer)
    misura_id: Mapped[str | None] = mapped_column(ForeignKey("ac_misure.id", ondelete="SET NULL"))
    misura: Mapped["AcMisura | None"] = relationship(lazy="raise")
    struttura_id: Mapped[str | None] = mapped_column(ForeignKey("strutture.id", ondelete="SET NULL"))
    contesto: Mapped[dict[str, Any]] = mapped_column(JSON)  # copia di misura, rischio, attività, processo, struttura
    stato_attuazione: Mapped[str] = mapped_column(String(20))  # ATTUATA, PARZIALE, NON_ATTUATA
    motivazione: Mapped[str | None] = mapped_column(Text)
    indicatore_rilevato: Mapped[str | None] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    evidenze: Mapped[str | None] = mapped_column(Text)
    dichiarato_da: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    dichiarato_il: Mapped[datetime | None] = mapped_column(DateTime)
    stato_verifica: Mapped[str] = mapped_column(String(20), default="DA_VERIFICARE")  # VERIFICATA, CONTESTATA
    note_rpct: Mapped[str | None] = mapped_column(Text)
    verificato_da: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verificato_il: Mapped[datetime | None] = mapped_column(DateTime)



# --- performance ---------------------------------------------------------------------------


class PfPiao(Base):
    """PIAO triennale (anno_inizio, +1, +2) aperto dall'amministratore della performance. Gli
    obiettivi si dichiarano e si aggiornano solo con il PIAO APERTO; CHIUSO è in sola lettura
    (l'amministratore può riaprirlo)."""

    __tablename__ = "pf_piao"
    __table_args__ = (UniqueConstraint("ente_id", "anno_inizio", name="uq_pf_piao"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    anno_inizio: Mapped[int] = mapped_column(Integer)
    titolo: Mapped[str] = mapped_column(String(255))
    atto: Mapped[str | None] = mapped_column(String(255))  # es. DGC n. 59 del 26/03/2026
    stato: Mapped[str] = mapped_column(String(10), default="APERTO")  # APERTO, CHIUSO
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PfObiettivo(Base):
    """Obiettivo annuale di una struttura (servizio o ufficio) nel PIAO, con la percentuale di
    impegno rispetto agli altri obiettivi della struttura nello stesso anno (in totale 100). Il
    completamento si calcola dalle azioni e dalle misure (common/performance)."""

    __tablename__ = "pf_obiettivi"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    piao_id: Mapped[str] = mapped_column(ForeignKey("pf_piao.id", ondelete="CASCADE"))
    anno: Mapped[int] = mapped_column(Integer)
    struttura_id: Mapped[str] = mapped_column(ForeignKey("strutture.id", ondelete="RESTRICT"))
    codice: Mapped[str | None] = mapped_column(String(100))  # codice nel PIAO, es. P2_OS3_OO1_OG1_26_2
    titolo: Mapped[str] = mapped_column(String(500))
    descrizione: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), default="OPERATIVO")  # OPERATIVO, FUNZIONAMENTO, MIGLIORAMENTO
    impegno: Mapped[int] = mapped_column(Integer, default=0)  # percentuale
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PfElemento(Base):
    """Azione (descrittiva) o misura (della mappatura dei rischi) di un obiettivo, con la
    percentuale di impegno rispetto alle altre dello stesso obiettivo (in totale 100), quella di
    completamento e la data massima di completamento. Della misura si tiene una copia di codice e
    descrizione: il riferimento resta anche se la mappatura cambia."""

    __tablename__ = "pf_elementi"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    obiettivo_id: Mapped[str] = mapped_column(ForeignKey("pf_obiettivi.id", ondelete="CASCADE"))
    tipo: Mapped[str] = mapped_column(String(10))  # AZIONE, MISURA
    descrizione: Mapped[str] = mapped_column(Text)  # dell'azione, o copia di quella della misura
    misura_id: Mapped[str | None] = mapped_column(ForeignKey("ac_misure.id", ondelete="SET NULL"))
    misura_codice: Mapped[str | None] = mapped_column(String(70))
    impegno: Mapped[int] = mapped_column(Integer, default=0)  # percentuale
    completamento: Mapped[int] = mapped_column(Integer, default=0)  # percentuale
    scadenza: Mapped[date] = mapped_column(Date)
    ordine: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PfModifica(Base):
    """Storico delle modifiche alla performance: creazione, modifica (campi con il valore prima
    e dopo) ed eliminazione di PIAO, obiettivi, azioni e misure, con chi e quando e una nota
    facoltativa. Resta anche dopo l'eliminazione dell'elemento."""

    __tablename__ = "pf_modifiche"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    piao_id: Mapped[str | None] = mapped_column(String(36))
    obiettivo_id: Mapped[str | None] = mapped_column(String(36))  # anche per azioni e misure
    oggetto: Mapped[str] = mapped_column(String(10))  # PIAO, OBIETTIVO, AZIONE, MISURA
    oggetto_id: Mapped[str] = mapped_column(String(36))
    azione: Mapped[str] = mapped_column(String(15))  # CREATO, MODIFICATO, ELIMINATO
    descrizione: Mapped[str] = mapped_column(String(500))  # dell'elemento, al momento della modifica
    campi: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # {campo: [prima, dopo]}
    nota: Mapped[str | None] = mapped_column(Text)
    utente_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    utente_nome: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NotificaEmail(Base):
    """Email da inviare (coda di invio, common/posta.py): la scrive l'API nella stessa
    transazione dell'operazione che la genera; il worker la invia con l'SMTP dell'ente,
    riprovando con attese crescenti fino a POSTA_TENTATIVI volte. Stati: DA_INVIARE ->
    INVIATA | ERRORE."""

    __tablename__ = "notifiche_email"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    destinatario: Mapped[str] = mapped_column(String(255))
    oggetto: Mapped[str] = mapped_column(String(255))
    testo: Mapped[str] = mapped_column(Text)
    origine: Mapped[str | None] = mapped_column(String(100))  # es. ac_proposta:<id>
    stato: Mapped[str] = mapped_column(String(20), default="DA_INVIARE")
    tentativi: Mapped[int] = mapped_column(Integer, default=0)
    prossimo_tentativo: Mapped[datetime | None] = mapped_column(DateTime)
    errore: Mapped[str | None] = mapped_column(Text)  # dell'ultimo tentativo
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    inviata_il: Mapped[datetime | None] = mapped_column(DateTime)


class RicercaVettore(Base):
    """Vettore di embedding di un record per la ricerca semantica (common/ricerca.py): uno per
    record e modello, ricalcolato quando cambia l'impronta del testo indicizzato. Float32 in
    binario, già normalizzato. Si ricostruisce da solo: si può svuotare in ogni momento."""

    __tablename__ = "ricerca_vettori"
    __table_args__ = (UniqueConstraint("oggetto_id", "modello", name="uq_ricerca_vettore"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    oggetto_id: Mapped[str] = mapped_column(String(36))  # es. id di AcProcesso
    modello: Mapped[str] = mapped_column(String(200))
    impronta: Mapped[str] = mapped_column(String(64))
    vettore: Mapped[bytes] = mapped_column(FileBinario)


class RicercaRegistrata(Base):
    """Ricerca conclusa (common/registro_ricerche.py): l'app la registra quando la persona
    apre un risultato (TROVATA) o resta senza aprirne (NESSUN_RISULTATO, RISULTATI_DEBOLI,
    NON_APERTI). Senza utente né IP; dati personali del testo oscurati. Le ricerche senza
    risposta con la stessa `chiave` (radici delle parole) si consultano insieme e si segnano
    gestite con una nota. Si cancellano dopo RICERCHE_CONSERVAZIONE_MESI."""

    __tablename__ = "ricerche_registro"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    ambito: Mapped[str] = mapped_column(String(50))  # es. PROCEDIMENTI
    pubblica: Mapped[bool] = mapped_column(Boolean)  # cittadino (pagina pubblica) o utente
    testo: Mapped[str] = mapped_column(String(300))
    chiave: Mapped[str] = mapped_column(String(300))
    risultati: Mapped[int] = mapped_column(Integer)
    esito: Mapped[str] = mapped_column(String(20))
    posizione: Mapped[int | None] = mapped_column(Integer)  # del risultato aperto (da 1)
    semantica: Mapped[bool] = mapped_column(Boolean, default=False)
    gestita_il: Mapped[datetime | None] = mapped_column(DateTime)
    gestita_da: Mapped[str | None] = mapped_column(String(255))
    nota: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RicercaFeedback(Base):
    """Feedback facoltativo: sui risultati di una ricerca (RICERCA, con la ricerca), su una
    scheda (SCHEDA, es. un procedimento pubblico) o segnalazione di un problema di
    accessibilità di una pagina (ACCESSIBILITA, meccanismo di feedback richiesto dalle linee
    guida AgID), con l'email facoltativa per la risposta (`contatto`). Commento con i dati
    personali oscurati."""

    __tablename__ = "ricerche_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    ente_id: Mapped[str] = mapped_column(ForeignKey("enti.id", ondelete="CASCADE"))
    ambito: Mapped[str] = mapped_column(String(50))
    pubblica: Mapped[bool] = mapped_column(Boolean)
    tipo: Mapped[str] = mapped_column(String(20))  # RICERCA, SCHEDA, ACCESSIBILITA
    ricerca_id: Mapped[str | None] = mapped_column(ForeignKey("ricerche_registro.id", ondelete="SET NULL"))
    testo: Mapped[str | None] = mapped_column(String(300))  # della ricerca
    riferimento_id: Mapped[str | None] = mapped_column(String(36))  # della scheda
    riferimento: Mapped[str | None] = mapped_column(String(500))  # titolo della scheda allora
    utile: Mapped[bool] = mapped_column(Boolean)
    commento: Mapped[str | None] = mapped_column(Text)
    contatto: Mapped[str | None] = mapped_column(String(255))  # ACCESSIBILITA: email per la risposta
    gestito_il: Mapped[datetime | None] = mapped_column(DateTime)
    gestito_da: Mapped[str | None] = mapped_column(String(255))
    nota: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    ente_id: Mapped[str | None] = mapped_column(String(36))
    user_id: Mapped[str | None] = mapped_column(String(36))
    entita: Mapped[str] = mapped_column(String(50))
    entita_id: Mapped[str] = mapped_column(String(255))
    azione: Mapped[str] = mapped_column(String(30))
    dettaglio: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
