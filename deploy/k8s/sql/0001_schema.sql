-- atti-pa — schema del database (MySQL 8.0+)
-- Da eseguire una volta in installazione, sul database vuoto:
--   CREATE DATABASE atti_pa CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--   mysql -u atti_pa -p atti_pa < deploy/k8s/sql/0001_schema.sql
-- Le modifiche successive allo schema vanno in nuovi file (0002_...sql), da eseguire in
-- ordine, e riportate nei modelli ORM (common/models.py).
-- In Kubernetes (mysql.yaml) e in docker compose MySQL lo esegue da solo alla prima
-- inizializzazione, con il volume dei dati vuoto.
--
-- Il database nasce senza modelli, specificità e checklist: si caricano con il pacchetto
-- standard (Amministrazione → Pacchetti, oppure python deploy/pacchetto.py importa).

-- ---------------------------------------------------------------------------
-- Utenti: sincronizzati da Active Directory al login, nessuna password salvata
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id                CHAR(36) PRIMARY KEY,
    username          VARCHAR(100) NOT NULL UNIQUE,
    nome_completo     VARCHAR(255),
    email             VARCHAR(255),
    ufficio           VARCHAR(255),
    decreto_incarico  VARCHAR(255),           -- precompila gli atti
    ruoli             JSON NOT NULL,          -- REDATTORE, CONTROLLORE, GESTORE_MODELLI, ADMIN
    attivo            BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_accesso    TIMESTAMP NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE tipologie_atto (
    codice       VARCHAR(50) PRIMARY KEY,
    descrizione  VARCHAR(255) NOT NULL,
    ordine       INT NOT NULL DEFAULT 0
) ENGINE=InnoDB;

INSERT INTO tipologie_atto (codice, descrizione, ordine) VALUES
    ('DETERMINA', 'Determinazione dirigenziale', 10);

-- ---------------------------------------------------------------------------
-- Libreria normativa: atti e articoli per intervallo di vigenza (Normattiva o caricati)
-- ---------------------------------------------------------------------------
CREATE TABLE norme_atti (
    urn                 VARCHAR(255) PRIMARY KEY,
    fonte               VARCHAR(20) NOT NULL DEFAULT 'NORMATTIVA',  -- NORMATTIVA, MANUALE
    denominazione       VARCHAR(100) NOT NULL,
    data_provvedimento  DATE NOT NULL,
    numero              VARCHAR(20) NOT NULL,
    titolo              TEXT,
    citazione           VARCHAR(255) NOT NULL,
    codice_redazionale  VARCHAR(20),
    data_gu             DATE,
    denominazioni_json  JSON,
    abrogata_dal        DATE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_fonte (fonte)
) ENGINE=InnoDB;

CREATE TABLE norme_articoli_versioni (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    urn_atto        VARCHAR(255) NOT NULL,
    articolo        VARCHAR(30) NOT NULL,
    rubrica         TEXT,
    vigenza_inizio  DATE,
    vigenza_fine    DATE,
    struttura_json  JSON NOT NULL,
    testo_html      LONGTEXT NOT NULL,
    hash_testo      CHAR(64) NOT NULL,
    rinvii_json     JSON,
    scaricato_il    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_articolo_versione (urn_atto, articolo, vigenza_inizio),
    KEY ix_vigenza (urn_atto, articolo, vigenza_inizio, vigenza_fine),
    FOREIGN KEY (urn_atto) REFERENCES norme_atti(urn) ON DELETE CASCADE
) ENGINE=InnoDB;

-- testi di norme non presenti su Normattiva (regolamenti interni), caricati come file
CREATE TABLE norme_testi_caricati (
    id               CHAR(36) PRIMARY KEY,
    urn_atto         VARCHAR(255) NOT NULL,
    vigenza_inizio   DATE NOT NULL,
    file_nome        VARCHAR(255) NOT NULL,
    file_mime        VARCHAR(100) NOT NULL,
    file_percorso    VARCHAR(500) NOT NULL,
    file_sha256      CHAR(64) NOT NULL,
    file_dimensione  INT NOT NULL,
    stato            VARCHAR(30) NOT NULL DEFAULT 'IN_CONVERSIONE',
    testo            LONGTEXT,
    errore           TEXT,
    caricato_da      CHAR(36),
    confermato_il    TIMESTAMP NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_norma (urn_atto, vigenza_inizio),
    KEY ix_stato (stato, created_at),
    FOREIGN KEY (urn_atto) REFERENCES norme_atti(urn) ON DELETE CASCADE,
    FOREIGN KEY (caricato_da) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- riferimenti normativi salvati dagli utenti (articolo, comma, lettera)
CREATE TABLE riferimenti (
    id              CHAR(36) PRIMARY KEY,
    urn_atto        VARCHAR(255) NOT NULL,
    articolo        VARCHAR(30) NOT NULL,
    comma           VARCHAR(20),
    lettera         VARCHAR(20),
    citazione       VARCHAR(500) NOT NULL,
    tipologie_atto  JSON,
    note            TEXT,
    owner_id        CHAR(36),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_articolo (urn_atto, articolo),
    FOREIGN KEY (urn_atto) REFERENCES norme_atti(urn),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE normattiva_sync (
    id                   BIGINT AUTO_INCREMENT PRIMARY KEY,
    intervallo_da        DATETIME NOT NULL,
    intervallo_a         DATETIME NOT NULL,
    atti_modificati      INT DEFAULT 0,
    articoli_aggiornati  INT DEFAULT 0,
    esito                VARCHAR(20) NOT NULL,
    dettaglio            TEXT,
    eseguito_il          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Configurazione dell'ente: modelli di atto, specificità, checklist (il database comanda;
-- ogni modifica è una nuova versione, attivo/attiva indica quella in uso)
-- ---------------------------------------------------------------------------
CREATE TABLE impostazioni_ente (
    id                    INT PRIMARY KEY,      -- sempre 1
    dati_json             JSON NOT NULL,
    carta_intestata_nome  VARCHAR(255),
    carta_intestata       LONGBLOB,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

INSERT INTO impostazioni_ente (id, dati_json) VALUES (1, JSON_OBJECT());

-- modello composto con le specificità attive (definizione_json); sorgente: YAML dell'ente;
-- pacchetto, impronta_base e base_sorgente: lo standard da cui deriva
CREATE TABLE modelli_atto (
    id                CHAR(36) PRIMARY KEY,
    codice            VARCHAR(100) NOT NULL,
    versione          INT NOT NULL DEFAULT 1,
    titolo            VARCHAR(255) NOT NULL,
    provvedimento     VARCHAR(100) NOT NULL,
    tipologia_atto    VARCHAR(50) NOT NULL,
    descrizione       TEXT,
    definizione_json  JSON NOT NULL,
    sorgente          LONGTEXT NOT NULL,
    moduli_json       JSON,                    -- {codice specificità: impronta} composte
    impronta          CHAR(64),
    pacchetto         VARCHAR(150),
    impronta_base     CHAR(64),
    base_sorgente     LONGTEXT,
    attivo            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_modello_versione (codice, versione),
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice)
) ENGINE=InnoDB;

-- specificità (moduli di regole)
CREATE TABLE moduli_regole (
    id                CHAR(36) PRIMARY KEY,
    codice            VARCHAR(100) NOT NULL,
    versione          INT NOT NULL DEFAULT 1,
    etichetta         VARCHAR(255) NOT NULL,
    definizione_json  JSON NOT NULL,
    sorgente          LONGTEXT NOT NULL,
    impronta          CHAR(64),
    pacchetto         VARCHAR(150),
    impronta_base     CHAR(64),
    base_sorgente     LONGTEXT,
    attivo            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_modulo_versione (codice, versione)
) ENGINE=InnoDB;

-- checklist generica della tipologia, oppure di un modello o di una specificità
CREATE TABLE checklists (
    id              CHAR(36) PRIMARY KEY,
    codice          VARCHAR(100) NOT NULL,
    versione        INT NOT NULL DEFAULT 1,
    titolo          VARCHAR(255) NOT NULL,
    tipologia_atto  VARCHAR(50) NOT NULL,
    modello         VARCHAR(100),
    modulo          VARCHAR(100),
    descrizione     TEXT,
    attiva          BOOLEAN NOT NULL DEFAULT TRUE,
    impronta        CHAR(64),
    pacchetto       VARCHAR(150),
    impronta_base   CHAR(64),
    base_sorgente   LONGTEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_codice_versione (codice, versione),
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice)
) ENGINE=InnoDB;

CREATE TABLE checklist_elementi (
    id                CHAR(36) PRIMARY KEY,
    checklist_id      CHAR(36) NOT NULL,
    ordine            INT NOT NULL DEFAULT 0,
    titolo            VARCHAR(255) NOT NULL,
    regola            TEXT NOT NULL,
    riferimenti_json  JSON,                    -- URN degli articoli passati all'LLM
    obbligatorio      BOOLEAN NOT NULL DEFAULT TRUE,
    capoversi_json    JSON,                    -- capoversi che soddisfano il controllo
    FOREIGN KEY (checklist_id) REFERENCES checklists(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- pacchetti caricati: analisi a tre vie e resoconto dell'importazione
CREATE TABLE pacchetti (
    id              CHAR(36) PRIMARY KEY,
    nome            VARCHAR(150) NOT NULL,
    versione        VARCHAR(50) NOT NULL,
    descrizione     TEXT,
    stato           VARCHAR(20) NOT NULL,
    contenuto       LONGBLOB,
    analisi_json    JSON,
    resoconto_json  JSON,
    caricato_da     CHAR(36),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    importato_il    TIMESTAMP NULL,
    FOREIGN KEY (caricato_da) REFERENCES users(id)
) ENGINE=InnoDB;

-- bozza dell'editor (una per oggetto): l'oggetto è in redazione da autore_id
CREATE TABLE bozze_configurazione (
    id                 CHAR(36) PRIMARY KEY,
    tipo               VARCHAR(20) NOT NULL,     -- modello, modulo, checklist
    codice             VARCHAR(100) NOT NULL,
    definizione_json   JSON NOT NULL,
    versione_partenza  INT,
    autore_id          CHAR(36),
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bozza_oggetto (tipo, codice),
    FOREIGN KEY (autore_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- modifiche ai capoversi proposte da chi scrive gli atti
CREATE TABLE proposte_modello (
    id              CHAR(36) PRIMARY KEY,
    modello         VARCHAR(100) NOT NULL,
    versione        INT NOT NULL,
    capoverso       VARCHAR(100) NOT NULL,
    testo_attuale   TEXT NOT NULL,
    testo_proposto  TEXT NOT NULL,
    motivazione     TEXT,
    stato           VARCHAR(20) NOT NULL DEFAULT 'APERTA',   -- APERTA, ACCOLTA, RESPINTA
    autore_id       CHAR(36) NOT NULL,
    gestita_da      CHAR(36),
    nota_gestione   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    gestita_il      TIMESTAMP NULL,
    KEY ix_proposte_modello (modello, stato),
    FOREIGN KEY (autore_id) REFERENCES users(id),
    FOREIGN KEY (gestita_da) REFERENCES users(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Redazione: bozze personali di atti
-- ---------------------------------------------------------------------------
CREATE TABLE bozze (
    id                      CHAR(36) PRIMARY KEY,
    owner_id                CHAR(36) NOT NULL,
    modello_id              CHAR(36) NOT NULL,    -- versione del modello con cui è nata
    oggetto                 TEXT NOT NULL,
    tipologia_atto          VARCHAR(50) NOT NULL,
    data_adozione_prevista  DATE,
    risposte_json           JSON NOT NULL,
    valori_json             JSON NOT NULL,
    personalizzazioni_json  JSON NOT NULL,
    riferimenti_json        JSON NOT NULL,
    fasi_complete           INT,
    contenuto_testo         LONGTEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY ix_owner (owner_id, updated_at),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice),
    CONSTRAINT fk_bozze_modello FOREIGN KEY (modello_id) REFERENCES modelli_atto(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Controllo successivo: un controllo = un atto, file nell'archivio su filesystem
-- ---------------------------------------------------------------------------
CREATE TABLE controlli_sessioni (
    id          CHAR(36) PRIMARY KEY,
    titolo      VARCHAR(255) NOT NULL,
    stato       VARCHAR(30) NOT NULL DEFAULT 'APERTA',
    creata_da   CHAR(36) NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creata_da) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE atti_controllati (
    id               CHAR(36) PRIMARY KEY,
    sessione_id      CHAR(36) NOT NULL,
    numero_registro  VARCHAR(50),
    data_adozione    DATE NOT NULL,
    settore          VARCHAR(255),
    tipologia_atto   VARCHAR(50),
    modello          VARCHAR(100),             -- modello e specificità: scelgono le schede
    moduli_json      JSON,
    oggetto          TEXT,
    file_nome        VARCHAR(255) NOT NULL,
    file_mime        VARCHAR(100) NOT NULL,
    file_percorso    VARCHAR(500),
    file_sha256      CHAR(64),
    file_dimensione  INT,
    contenuto_testo  LONGTEXT,                 -- Markdown
    stato            VARCHAR(30) NOT NULL DEFAULT 'IN_CONVERSIONE',
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_sessione (sessione_id, stato),
    FOREIGN KEY (sessione_id) REFERENCES controlli_sessioni(id) ON DELETE CASCADE,
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Verifiche: di una bozza o di un atto controllato, eseguite dal worker
-- ---------------------------------------------------------------------------
CREATE TABLE verifiche (
    id                   CHAR(36) PRIMARY KEY,
    bozza_id             CHAR(36),
    atto_controllato_id  CHAR(36),
    checklist_ids        JSON,                 -- schede applicate (generica, modello, specificità)
    data_riferimento     DATE NOT NULL,
    stato                VARCHAR(20) NOT NULL DEFAULT 'IN_CODA',
    tentativi            INT NOT NULL DEFAULT 0,
    errore               TEXT,
    worker               VARCHAR(100),
    avviata_il           TIMESTAMP NULL,
    completata_il        TIMESTAMP NULL,
    esito_riferimenti    JSON,
    esito_automatico     JSON,
    esito_finale         JSON,
    motivazione          TEXT,
    revisore_id          CHAR(36),
    richiesta_da         CHAR(36) NOT NULL,
    modello_llm          VARCHAR(100),
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY ix_coda (stato, created_at),
    FOREIGN KEY (bozza_id) REFERENCES bozze(id) ON DELETE CASCADE,
    FOREIGN KEY (atto_controllato_id) REFERENCES atti_controllati(id) ON DELETE CASCADE,
    FOREIGN KEY (revisore_id) REFERENCES users(id),
    FOREIGN KEY (richiesta_da) REFERENCES users(id),
    CHECK ((bozza_id IS NULL) <> (atto_controllato_id IS NULL))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Registro delle operazioni
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
