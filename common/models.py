"""Modelli ORM condivisi. Devono restare allineati allo schema in deploy/sql/."""

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
    REDATTORE = "REDATTORE"
    CONTROLLORE = "CONTROLLORE"
    GESTORE_MODELLI = "GESTORE_MODELLI"  # modifica modelli, specificità e checklist in bozza
    ADMIN = "ADMIN"  # pubblica le modifiche ai modelli
    TUTTI = (REDATTORE, CONTROLLORE, GESTORE_MODELLI, ADMIN)


class StatoVerifica:
    IN_CODA = "IN_CODA"
    IN_CORSO = "IN_CORSO"
    COMPLETATA = "COMPLETATA"
    ERRORE = "ERRORE"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    nome_completo: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    ufficio: Mapped[str | None] = mapped_column(String(255))
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


class ImpostazioniEnte(Base):
    """Dati dell'ente usati da tutti i modelli (una sola riga, id = 1) e carta intestata."""

    __tablename__ = "impostazioni_ente"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    dati_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    carta_intestata_nome: Mapped[str | None] = mapped_column(String(255))
    carta_intestata: Mapped[bytes | None] = mapped_column(FileBinario, deferred=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Bozza(Base):
    __tablename__ = "bozze"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
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
    titolo: Mapped[str] = mapped_column(String(255))
    stato: Mapped[str] = mapped_column(String(30), default="APERTA")
    creata_da: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AttoControllato(Base):
    __tablename__ = "atti_controllati"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
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


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    user_id: Mapped[str | None] = mapped_column(String(36))
    entita: Mapped[str] = mapped_column(String(50))
    entita_id: Mapped[str] = mapped_column(String(255))
    azione: Mapped[str] = mapped_column(String(30))
    dettaglio: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
