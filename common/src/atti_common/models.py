"""Modelli ORM condivisi. Devono restare allineati alle migrazioni in db-migrate."""

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
    ADMIN = "ADMIN"
    TUTTI = (REDATTORE, CONTROLLORE, ADMIN)


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


class NormaAtto(Base):
    __tablename__ = "norme_atti"

    urn: Mapped[str] = mapped_column(String(255), primary_key=True)
    denominazione: Mapped[str] = mapped_column(String(100))
    data_provvedimento: Mapped[date] = mapped_column(Date)
    numero: Mapped[str] = mapped_column(String(20))
    titolo: Mapped[str | None] = mapped_column(Text)
    citazione: Mapped[str] = mapped_column(String(255))
    codice_redazionale: Mapped[str | None] = mapped_column(String(20))
    data_gu: Mapped[date | None] = mapped_column(Date)
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
    descrizione: Mapped[str | None] = mapped_column(Text)
    attiva: Mapped[bool] = mapped_column(Boolean, default=True)
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


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    nome: Mapped[str] = mapped_column(String(255))
    tipologia_atto: Mapped[str] = mapped_column(ForeignKey("tipologie_atto.codice"))
    versione: Mapped[int] = mapped_column(Integer, default=1)
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    file_nome: Mapped[str] = mapped_column(String(255))
    file_contenuto: Mapped[bytes] = mapped_column(FileBinario, deferred=True)
    campi_json: Mapped[list[Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Bozza(Base):
    __tablename__ = "bozze"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    template_id: Mapped[str | None] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"))
    oggetto: Mapped[str] = mapped_column(Text)
    tipologia_atto: Mapped[str] = mapped_column(ForeignKey("tipologie_atto.codice"))
    data_adozione_prevista: Mapped[date | None] = mapped_column(Date)
    dati_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    riferimenti_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    contenuto_testo: Mapped[str | None] = mapped_column(TestoLungo)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SessioneControllo(Base):
    __tablename__ = "controlli_sessioni"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    titolo: Mapped[str] = mapped_column(String(255))
    periodo_da: Mapped[date] = mapped_column(Date)
    periodo_a: Mapped[date] = mapped_column(Date)
    criteri_sorteggio: Mapped[dict[str, Any] | None] = mapped_column(JSON)
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
    oggetto: Mapped[str | None] = mapped_column(Text)
    file_nome: Mapped[str] = mapped_column(String(255))
    file_mime: Mapped[str] = mapped_column(String(100))
    file_contenuto: Mapped[bytes] = mapped_column(FileBinario, deferred=True)
    contenuto_testo: Mapped[str | None] = mapped_column(TestoLungo, deferred=True)
    assegnato_a: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    stato: Mapped[str] = mapped_column(String(30), default="DA_ANALIZZARE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Verifica(Base):
    __tablename__ = "verifiche"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuovo_id)
    bozza_id: Mapped[str | None] = mapped_column(ForeignKey("bozze.id", ondelete="CASCADE"))
    atto_controllato_id: Mapped[str | None] = mapped_column(
        ForeignKey("atti_controllati.id", ondelete="CASCADE")
    )
    checklist_id: Mapped[str | None] = mapped_column(ForeignKey("checklists.id"))
    data_riferimento: Mapped[date] = mapped_column(Date)
    stato: Mapped[str] = mapped_column(String(20), default=StatoVerifica.IN_CODA)
    tentativi: Mapped[int] = mapped_column(Integer, default=0)
    errore: Mapped[str | None] = mapped_column(Text)
    worker: Mapped[str | None] = mapped_column(String(100))
    avviata_il: Mapped[datetime | None] = mapped_column(DateTime)
    completata_il: Mapped[datetime | None] = mapped_column(DateTime)
    esito_riferimenti: Mapped[list[Any] | None] = mapped_column(JSON)
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
