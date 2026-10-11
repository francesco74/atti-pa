-- atti-pa — schema MySQL 8.0+
CREATE DATABASE IF NOT EXISTS atti_pa CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE atti_pa;

-- ---------------------------------------------------------------------------
-- Utenti (sincronizzati da AD al login, nessuna password salvata)
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    username        VARCHAR(100) NOT NULL UNIQUE,          -- sAMAccountName
    nome_completo   VARCHAR(255),
    email           VARCHAR(255),
    ufficio         VARCHAR(255),
    ruoli           JSON NOT NULL,                          -- ["REDATTORE","CONTROLLORE","ADMIN"], da gruppi AD
    ultimo_accesso  TIMESTAMP NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Libreria normativa (fonte: Normattiva)
-- ---------------------------------------------------------------------------
CREATE TABLE norme_atti (
    urn                 VARCHAR(255) PRIMARY KEY,           -- urn:nir:stato:decreto.legislativo:2023-03-31;36
    denominazione       VARCHAR(100) NOT NULL,              -- DECRETO LEGISLATIVO
    data_provvedimento  DATE NOT NULL,
    numero              VARCHAR(20) NOT NULL,
    titolo              TEXT,
    codice_redazionale  VARCHAR(20),
    data_gu             DATE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Una riga per ogni versione vigente di un articolo
CREATE TABLE norme_articoli_versioni (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    urn_atto        VARCHAR(255) NOT NULL,
    articolo        VARCHAR(30) NOT NULL,                   -- "50", "13-bis", "1:2" (allegato:articolo)
    rubrica         TEXT,
    vigenza_inizio  DATE NULL,
    vigenza_fine    DATE NULL,                              -- NULL = ancora in vigore
    struttura_json  JSON NOT NULL,                          -- commi e lettere estratti dal parser
    testo_html      LONGTEXT NOT NULL,                      -- HTML originale Normattiva
    hash_testo      CHAR(64) NOT NULL,                      -- sha256 del testo normalizzato
    rinvii_json     JSON,                                   -- URN citate nel testo
    scaricato_il    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_articolo_versione (urn_atto, articolo, vigenza_inizio),
    KEY ix_vigenza (urn_atto, articolo, vigenza_inizio, vigenza_fine),
    FOREIGN KEY (urn_atto) REFERENCES norme_atti(urn) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Riferimenti pronti all'uso nella redazione (es. "art. 50, comma 1, lett. b)")
CREATE TABLE riferimenti (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    urn_atto            VARCHAR(255) NOT NULL,
    articolo            VARCHAR(30) NOT NULL,
    comma               VARCHAR(20),
    lettera             VARCHAR(20),
    citazione           VARCHAR(500) NOT NULL,              -- formula estesa da inserire nell'atto
    citazione_breve     VARCHAR(255),
    tipologie_atto      JSON,                               -- tipologie in cui è tipicamente usato
    note                TEXT,
    owner_id            CHAR(36) NULL,                      -- NULL = riferimento condiviso
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (urn_atto) REFERENCES norme_atti(urn),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE normattiva_sync (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    intervallo_da   DATETIME NOT NULL,
    intervallo_a    DATETIME NOT NULL,
    atti_modificati INT DEFAULT 0,
    articoli_aggiornati INT DEFAULT 0,
    esito           VARCHAR(20) NOT NULL,                   -- OK, ERRORE
    dettaglio       TEXT,
    eseguito_il     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Checklist (versionate: una verifica punta sempre alla versione usata)
-- ---------------------------------------------------------------------------
CREATE TABLE checklists (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    codice          VARCHAR(100) NOT NULL,                  -- stabile tra le versioni
    versione        INT NOT NULL DEFAULT 1,
    titolo          VARCHAR(255) NOT NULL,
    tipologia_atto  VARCHAR(100) NOT NULL,
    descrizione     TEXT,
    attiva          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_codice_versione (codice, versione)
) ENGINE=InnoDB;

CREATE TABLE checklist_elementi (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    checklist_id        CHAR(36) NOT NULL,
    ordine              INT DEFAULT 0,
    titolo              VARCHAR(255) NOT NULL,
    regola              TEXT NOT NULL,                      -- criterio passato all'LLM
    riferimenti_json    JSON,                               -- URN dei commi pertinenti da includere nel prompt
    obbligatorio        BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (checklist_id) REFERENCES checklists(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Modulo Redazione (bozze personali)
-- ---------------------------------------------------------------------------
CREATE TABLE templates (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    nome            VARCHAR(255) NOT NULL,
    tipologia_atto  VARCHAR(100) NOT NULL,
    versione        INT NOT NULL DEFAULT 1,
    file_path       VARCHAR(512) NOT NULL,
    struttura_json  JSON NOT NULL,                          -- sezioni e campi del wizard
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE bozze (
    id                      CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    owner_id                CHAR(36) NOT NULL,
    template_id             CHAR(36),
    oggetto                 TEXT NOT NULL,
    tipologia_atto          VARCHAR(100) NOT NULL,
    data_adozione_prevista  DATE,
    dati_strutturati        JSON NOT NULL,
    contenuto_testo         LONGTEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Modulo Controllo
-- ---------------------------------------------------------------------------
CREATE TABLE controlli_sessioni (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    titolo              VARCHAR(255) NOT NULL,              -- es. "Controllo 1° semestre 2026"
    periodo_da          DATE NOT NULL,
    periodo_a           DATE NOT NULL,
    criteri_sorteggio   JSON,
    stato               VARCHAR(30) DEFAULT 'APERTA',       -- APERTA, CHIUSA
    creata_da           CHAR(36) NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creata_da) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE atti_controllati (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    sessione_id         CHAR(36) NOT NULL,
    numero_registro     VARCHAR(50),
    data_adozione       DATE NOT NULL,                      -- data di riferimento per la vigenza
    settore             VARCHAR(255),
    tipologia_atto      VARCHAR(100),
    oggetto             TEXT,
    file_path           VARCHAR(512) NOT NULL,
    contenuto_testo     LONGTEXT,
    assegnato_a         CHAR(36),
    stato               VARCHAR(30) DEFAULT 'DA_ANALIZZARE', -- DA_ANALIZZARE, ANALIZZATO, IN_REVISIONE, CHIUSO
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sessione_id) REFERENCES controlli_sessioni(id) ON DELETE CASCADE,
    FOREIGN KEY (assegnato_a) REFERENCES users(id)
) ENGINE=InnoDB;

-- Verifiche: valgono sia per bozze (autovalutazione) sia per atti controllati
CREATE TABLE verifiche (
    id                  CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    bozza_id            CHAR(36) NULL,
    atto_controllato_id CHAR(36) NULL,
    checklist_id        CHAR(36) NOT NULL,                  -- punta alla versione esatta
    data_riferimento    DATE NOT NULL,                      -- data usata per la vigenza
    esito_riferimenti   JSON,                               -- verifica deterministica dei riferimenti normativi
    esito_automatico    JSON,                               -- proposta LLM per elemento
    esito_finale        JSON,                               -- esito confermato/modificato dal controllore
    motivazione         TEXT,
    revisore_id         CHAR(36),
    modello_llm         VARCHAR(100),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (bozza_id) REFERENCES bozze(id) ON DELETE CASCADE,
    FOREIGN KEY (atto_controllato_id) REFERENCES atti_controllati(id) ON DELETE CASCADE,
    FOREIGN KEY (checklist_id) REFERENCES checklists(id),
    FOREIGN KEY (revisore_id) REFERENCES users(id),
    CHECK ((bozza_id IS NULL) <> (atto_controllato_id IS NULL))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     CHAR(36),
    entita      VARCHAR(50) NOT NULL,
    entita_id   VARCHAR(255) NOT NULL,
    azione      VARCHAR(30) NOT NULL,
    dettaglio   JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_entita (entita, entita_id)
) ENGINE=InnoDB;
