-- atti-pa — schema iniziale (MySQL 8.0+)
-- Il database va creato in precedenza con:
--   CREATE DATABASE atti_pa CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Utenti: sincronizzati da Active Directory al login, nessuna password salvata
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id              CHAR(36) PRIMARY KEY,
    username        VARCHAR(100) NOT NULL UNIQUE,
    nome_completo   VARCHAR(255),
    email           VARCHAR(255),
    ufficio         VARCHAR(255),
    ruoli           JSON NOT NULL,
    attivo          BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_accesso  TIMESTAMP NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE tipologie_atto (
    codice          VARCHAR(50) PRIMARY KEY,
    descrizione     VARCHAR(255) NOT NULL,
    ordine          INT NOT NULL DEFAULT 0
) ENGINE=InnoDB;

INSERT INTO tipologie_atto (codice, descrizione, ordine) VALUES
    ('AFFIDAMENTO_DIRETTO', 'Affidamento diretto di lavori, servizi e forniture', 10),
    ('IMPEGNO_SPESA', 'Impegno di spesa', 20),
    ('LIQUIDAZIONE', 'Liquidazione di spesa', 30),
    ('ACCERTAMENTO_ENTRATA', 'Accertamento di entrata', 40),
    ('CONTRIBUTO', 'Concessione di contributi e vantaggi economici', 50),
    ('INCARICO_PROFESSIONALE', 'Conferimento di incarico professionale', 60),
    ('PERSONALE', 'Gestione del personale', 70),
    ('ALTRO', 'Altra tipologia', 999);

-- ---------------------------------------------------------------------------
-- Libreria normativa (fonte: Normattiva)
-- ---------------------------------------------------------------------------
CREATE TABLE norme_atti (
    urn                 VARCHAR(255) PRIMARY KEY,
    denominazione       VARCHAR(100) NOT NULL,
    data_provvedimento  DATE NOT NULL,
    numero              VARCHAR(20) NOT NULL,
    titolo              TEXT,
    citazione           VARCHAR(255) NOT NULL,
    codice_redazionale  VARCHAR(20),
    data_gu             DATE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Una riga per ogni versione vigente di un articolo
CREATE TABLE norme_articoli_versioni (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    urn_atto        VARCHAR(255) NOT NULL,
    articolo        VARCHAR(30) NOT NULL,
    rubrica         TEXT,
    vigenza_inizio  DATE NULL,
    vigenza_fine    DATE NULL,
    struttura_json  JSON NOT NULL,
    testo_html      LONGTEXT NOT NULL,
    hash_testo      CHAR(64) NOT NULL,
    rinvii_json     JSON,
    scaricato_il    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_articolo_versione (urn_atto, articolo, vigenza_inizio),
    KEY ix_vigenza (urn_atto, articolo, vigenza_inizio, vigenza_fine),
    FOREIGN KEY (urn_atto) REFERENCES norme_atti(urn) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Riferimenti pronti all'uso nella redazione (es. "art. 50, comma 1, lett. b)")
CREATE TABLE riferimenti (
    id              CHAR(36) PRIMARY KEY,
    urn_atto        VARCHAR(255) NOT NULL,
    articolo        VARCHAR(30) NOT NULL,
    comma           VARCHAR(20),
    lettera         VARCHAR(20),
    citazione       VARCHAR(500) NOT NULL,
    tipologie_atto  JSON,
    note            TEXT,
    owner_id        CHAR(36) NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_articolo (urn_atto, articolo),
    FOREIGN KEY (urn_atto) REFERENCES norme_atti(urn),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE normattiva_sync (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    intervallo_da       DATETIME NOT NULL,
    intervallo_a        DATETIME NOT NULL,
    atti_modificati     INT DEFAULT 0,
    articoli_aggiornati INT DEFAULT 0,
    esito               VARCHAR(20) NOT NULL,
    dettaglio           TEXT,
    eseguito_il         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Checklist versionate: una verifica punta sempre alla versione usata
-- ---------------------------------------------------------------------------
CREATE TABLE checklists (
    id              CHAR(36) PRIMARY KEY,
    codice          VARCHAR(100) NOT NULL,
    versione        INT NOT NULL DEFAULT 1,
    titolo          VARCHAR(255) NOT NULL,
    tipologia_atto  VARCHAR(50) NOT NULL,
    descrizione     TEXT,
    attiva          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_codice_versione (codice, versione),
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice)
) ENGINE=InnoDB;

CREATE TABLE checklist_elementi (
    id                  CHAR(36) PRIMARY KEY,
    checklist_id        CHAR(36) NOT NULL,
    ordine              INT NOT NULL DEFAULT 0,
    titolo              VARCHAR(255) NOT NULL,
    regola              TEXT NOT NULL,
    riferimenti_json    JSON,
    obbligatorio        BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (checklist_id) REFERENCES checklists(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Modulo Redazione
-- I file sono salvati nel database: nessun volume condiviso tra i pod
-- ---------------------------------------------------------------------------
CREATE TABLE templates (
    id              CHAR(36) PRIMARY KEY,
    nome            VARCHAR(255) NOT NULL,
    tipologia_atto  VARCHAR(50) NOT NULL,
    versione        INT NOT NULL DEFAULT 1,
    attivo          BOOLEAN NOT NULL DEFAULT TRUE,
    file_nome       VARCHAR(255) NOT NULL,
    file_contenuto  LONGBLOB NOT NULL,
    campi_json      JSON NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice)
) ENGINE=InnoDB;

CREATE TABLE bozze (
    id                      CHAR(36) PRIMARY KEY,
    owner_id                CHAR(36) NOT NULL,
    template_id             CHAR(36),
    oggetto                 TEXT NOT NULL,
    tipologia_atto          VARCHAR(50) NOT NULL,
    data_adozione_prevista  DATE,
    dati_json               JSON NOT NULL,
    riferimenti_json        JSON NOT NULL,
    contenuto_testo         LONGTEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY ix_owner (owner_id, updated_at),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE SET NULL,
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Modulo Controllo
-- ---------------------------------------------------------------------------
CREATE TABLE controlli_sessioni (
    id                  CHAR(36) PRIMARY KEY,
    titolo              VARCHAR(255) NOT NULL,
    periodo_da          DATE NOT NULL,
    periodo_a           DATE NOT NULL,
    criteri_sorteggio   JSON,
    stato               VARCHAR(30) NOT NULL DEFAULT 'APERTA',
    creata_da           CHAR(36) NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creata_da) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE atti_controllati (
    id                  CHAR(36) PRIMARY KEY,
    sessione_id         CHAR(36) NOT NULL,
    numero_registro     VARCHAR(50),
    data_adozione       DATE NOT NULL,
    settore             VARCHAR(255),
    tipologia_atto      VARCHAR(50),
    oggetto             TEXT,
    file_nome           VARCHAR(255) NOT NULL,
    file_mime           VARCHAR(100) NOT NULL,
    file_contenuto      LONGBLOB NOT NULL,
    contenuto_testo     LONGTEXT,
    assegnato_a         CHAR(36),
    stato               VARCHAR(30) NOT NULL DEFAULT 'DA_ANALIZZARE',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_sessione (sessione_id, stato),
    FOREIGN KEY (sessione_id) REFERENCES controlli_sessioni(id) ON DELETE CASCADE,
    FOREIGN KEY (assegnato_a) REFERENCES users(id),
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Verifiche: valgono per bozze (autovalutazione) e atti controllati.
-- Fungono anche da coda di lavoro per il worker di verifica.
-- ---------------------------------------------------------------------------
CREATE TABLE verifiche (
    id                  CHAR(36) PRIMARY KEY,
    bozza_id            CHAR(36) NULL,
    atto_controllato_id CHAR(36) NULL,
    checklist_id        CHAR(36) NULL,
    data_riferimento    DATE NOT NULL,
    stato               VARCHAR(20) NOT NULL DEFAULT 'IN_CODA',
    tentativi           INT NOT NULL DEFAULT 0,
    errore              TEXT,
    worker              VARCHAR(100),
    avviata_il          TIMESTAMP NULL,
    completata_il       TIMESTAMP NULL,
    esito_riferimenti   JSON,
    esito_automatico    JSON,
    esito_finale        JSON,
    motivazione         TEXT,
    revisore_id         CHAR(36),
    richiesta_da        CHAR(36) NOT NULL,
    modello_llm         VARCHAR(100),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY ix_coda (stato, created_at),
    FOREIGN KEY (bozza_id) REFERENCES bozze(id) ON DELETE CASCADE,
    FOREIGN KEY (atto_controllato_id) REFERENCES atti_controllati(id) ON DELETE CASCADE,
    FOREIGN KEY (checklist_id) REFERENCES checklists(id),
    FOREIGN KEY (revisore_id) REFERENCES users(id),
    FOREIGN KEY (richiesta_da) REFERENCES users(id),
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
