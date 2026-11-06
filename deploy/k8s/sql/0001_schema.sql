-- atti-pa — schema del database (MySQL 8.0+)
-- Da eseguire una volta in installazione, sul database vuoto:
--   CREATE DATABASE atti_pa CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--   mysql -u atti_pa -p atti_pa < deploy/k8s/sql/0001_schema.sql
-- Le modifiche successive allo schema vanno in nuovi file (0002_...sql), da eseguire in
-- ordine, e riportate nei modelli ORM (common/models.py).
-- In Kubernetes (mysql.yaml) e in docker compose MySQL lo esegue da solo alla prima
-- inizializzazione, con il volume dei dati vuoto.
--
-- Il database nasce senza enti, modelli, specificità e checklist: gli enti (ciascuno con il
-- suo utente admin) si creano con python deploy/enti.py; i modelli si caricano per ente con
-- il pacchetto standard (Amministrazione → Pacchetti).

-- ---------------------------------------------------------------------------
-- Enti: ogni ente ha utenti, configurazione e dati propri e si riconosce dal dominio
-- della richiesta. I dati dell'ente (campi con fonte "ente" dei modelli) e la carta
-- intestata stanno qui. Accesso: utenti locali e/o Active Directory (ldap_json).
-- ---------------------------------------------------------------------------
CREATE TABLE enti (
    id                    CHAR(36) PRIMARY KEY,
    codice                VARCHAR(50) NOT NULL UNIQUE,
    nome                  VARCHAR(255) NOT NULL,
    attivo                BOOLEAN NOT NULL DEFAULT TRUE,
    moduli_json           JSON NOT NULL,          -- moduli abilitati, es. ["redazione", "trasparenza"]
    dati_json             JSON NOT NULL,
    carta_intestata_nome  VARCHAR(255),
    carta_intestata       LONGBLOB,
    logo_mime             VARCHAR(50),            -- profilo dell'ente: logo nei documenti
    logo                  LONGBLOB,
    caratteristiche       TEXT,                   -- caratteristiche dell'amministrazione (contesto per l'LLM)
    assistenza            TEXT,                   -- testo per l'assistenza agli utenti (login, menu, aiuto)
    accesso_locale        BOOLEAN NOT NULL DEFAULT TRUE,
    ldap_json             JSON,                   -- url, dominio, base_dn, ca_pem, gruppi...
    rag_json              JSON,                   -- collegamento al RAG: url, chiave_cifrata
    smtp_json             JSON,                   -- posta in uscita: host, porta, utente, password_cifrata, mittente...
    mappatura_pubblica    BOOLEAN NOT NULL DEFAULT FALSE, -- mappatura consultabile su /pubblico/mappatura
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE enti_domini (
    dominio   VARCHAR(255) PRIMARY KEY,           -- es. attipa.provincia.lucca.it
    ente_id   CHAR(36) NOT NULL,
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Strutture organizzative dell'ente (staff, settori, U.O.), con la gerarchia: usate da
-- tutti i moduli; chi è assegnato a una struttura opera anche su quelle sottostanti
-- ---------------------------------------------------------------------------
CREATE TABLE strutture (
    id           CHAR(36) PRIMARY KEY,
    ente_id      CHAR(36) NOT NULL,
    codice       VARCHAR(50) NOT NULL,          -- es. SETTORE 2, U.O. 2.2
    descrizione  VARCHAR(255) NOT NULL,
    padre_id     CHAR(36),                      -- struttura superiore
    ordine       INT NOT NULL DEFAULT 0,
    attiva       BOOLEAN NOT NULL DEFAULT TRUE, -- soppressa: resta per lo storico
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_struttura_ente (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (padre_id) REFERENCES strutture(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Utenti di un ente: da Active Directory (al login, password mai salvata) o locali
-- (password con hash). Ogni ente nasce con l'utente locale admin (deploy/enti.py).
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id                CHAR(36) PRIMARY KEY,
    ente_id           CHAR(36) NOT NULL,
    username          VARCHAR(100) NOT NULL,
    origine           VARCHAR(10) NOT NULL DEFAULT 'LDAP',   -- LDAP, LOCALE
    password_hash     VARCHAR(255),
    token_version     INT NOT NULL DEFAULT 0,    -- cresce a ogni revoca delle sessioni
    cambio_password   BOOLEAN NOT NULL DEFAULT FALSE,  -- password da cambiare al primo accesso
    nome_completo     VARCHAR(255),
    email             VARCHAR(255),
    ufficio           VARCHAR(255),
    struttura_id      CHAR(36),               -- struttura organizzativa (strutture)
    decreto_incarico  VARCHAR(255),           -- precompila gli atti
    ruoli             JSON NOT NULL,          -- REDATTORE, CONTROLLORE, GESTORE_MODELLI, TRASPARENZA,
                                              -- ANTICORRUZIONE_REFERENTE, ANTICORRUZIONE_RPCT, ADMIN
    attivo            BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_accesso    TIMESTAMP NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_utente_ente (ente_id, username),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (struttura_id) REFERENCES strutture(id) ON DELETE SET NULL
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
    ente_id             CHAR(36),               -- solo norme manuali: Normattiva è comune
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
    KEY ix_fonte (fonte),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
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
    ente_id         CHAR(36) NOT NULL,
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
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
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
-- modello composto con le specificità attive (definizione_json); sorgente: YAML dell'ente;
-- pacchetto, impronta_base e base_sorgente: lo standard da cui deriva
CREATE TABLE modelli_atto (
    id                CHAR(36) PRIMARY KEY,
    ente_id           CHAR(36) NOT NULL,
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
    UNIQUE KEY uq_modello_versione (ente_id, codice, versione),
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- specificità (moduli di regole)
CREATE TABLE moduli_regole (
    id                CHAR(36) PRIMARY KEY,
    ente_id           CHAR(36) NOT NULL,
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
    UNIQUE KEY uq_modulo_versione (ente_id, codice, versione),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- checklist generica della tipologia, oppure di un modello o di una specificità
CREATE TABLE checklists (
    id              CHAR(36) PRIMARY KEY,
    ente_id         CHAR(36) NOT NULL,
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
    UNIQUE KEY uq_codice_versione (ente_id, codice, versione),
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
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
    ente_id         CHAR(36) NOT NULL,
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
    FOREIGN KEY (caricato_da) REFERENCES users(id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- bozza dell'editor (una per oggetto): l'oggetto è in redazione da autore_id
CREATE TABLE bozze_configurazione (
    id                 CHAR(36) PRIMARY KEY,
    ente_id            CHAR(36) NOT NULL,
    tipo               VARCHAR(20) NOT NULL,     -- modello, modulo, checklist
    codice             VARCHAR(100) NOT NULL,
    definizione_json   JSON NOT NULL,
    versione_partenza  INT,
    autore_id          CHAR(36),
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bozza_oggetto (ente_id, tipo, codice),
    FOREIGN KEY (autore_id) REFERENCES users(id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- modifiche ai capoversi proposte da chi scrive gli atti
CREATE TABLE proposte_modello (
    id              CHAR(36) PRIMARY KEY,
    ente_id         CHAR(36) NOT NULL,
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
    KEY ix_proposte_modello (ente_id, modello, stato),
    FOREIGN KEY (autore_id) REFERENCES users(id),
    FOREIGN KEY (gestita_da) REFERENCES users(id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Redazione: bozze personali di atti
-- ---------------------------------------------------------------------------
CREATE TABLE bozze (
    id                      CHAR(36) PRIMARY KEY,
    ente_id                 CHAR(36) NOT NULL,
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
    CONSTRAINT fk_bozze_modello FOREIGN KEY (modello_id) REFERENCES modelli_atto(id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Controllo successivo: un controllo = un atto, file nell'archivio su filesystem
-- ---------------------------------------------------------------------------
CREATE TABLE controlli_sessioni (
    id          CHAR(36) PRIMARY KEY,
    ente_id     CHAR(36) NOT NULL,
    titolo      VARCHAR(255) NOT NULL,
    stato       VARCHAR(30) NOT NULL DEFAULT 'APERTA',
    creata_da   CHAR(36) NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creata_da) REFERENCES users(id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE atti_controllati (
    id               CHAR(36) PRIMARY KEY,
    ente_id          CHAR(36) NOT NULL,
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
    FOREIGN KEY (tipologia_atto) REFERENCES tipologie_atto(codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Verifiche: di una bozza o di un atto controllato, eseguite dal worker
-- ---------------------------------------------------------------------------
CREATE TABLE verifiche (
    id                   CHAR(36) PRIMARY KEY,
    ente_id              CHAR(36) NOT NULL,
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
    CHECK ((bozza_id IS NULL) <> (atto_controllato_id IS NULL)),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Modulo trasparenza: documenti salvati (schede, report di analisi, verbali), privati di
-- chi li salva e visibili all'amministratore dell'ente
-- ---------------------------------------------------------------------------
CREATE TABLE trasparenza_documenti (
    id           CHAR(36) PRIMARY KEY,
    ente_id      CHAR(36) NOT NULL,
    utente_id    CHAR(36) NOT NULL,
    tipo         VARCHAR(10) NOT NULL,       -- SCHEDA, ANALISI, VERBALE
    schema_id    VARCHAR(50),                -- es. ART_23
    descrizione  VARCHAR(255) NOT NULL,
    html         LONGTEXT NOT NULL,
    esito        VARCHAR(40),                -- esito di validazione dei report di analisi
    dati_schema  JSON,                       -- dati del form, per rigenerare la scheda
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY ix_utente (ente_id, utente_id, updated_at),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (utente_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Analisi ed estrazioni eseguite dal worker (coda "trasparenza")
CREATE TABLE trasparenza_lavori (
    id             CHAR(36) PRIMARY KEY,
    ente_id        CHAR(36) NOT NULL,
    utente_id      CHAR(36) NOT NULL,
    tipo           VARCHAR(10) NOT NULL,        -- ANALISI, ESTRAZIONE
    stato          VARCHAR(20) NOT NULL DEFAULT 'IN_CODA',  -- IN_CODA, IN_CORSO, COMPLETATA, ERRORE
    richiesta      JSON NOT NULL,               -- controllo/schema, url, opzioni, file nell'archivio, note
    risultato      JSON,                        -- {"html"} o {"dati", "avvisi"}
    errore         TEXT,
    modello_llm    VARCHAR(100),
    tentativi      INT NOT NULL DEFAULT 0,
    worker         VARCHAR(100),
    avviato_il     TIMESTAMP NULL,
    completato_il  TIMESTAMP NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_stato (stato, created_at),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (utente_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Modulo anticorruzione: processo -> attività -> rischio -> misura
-- ---------------------------------------------------------------------------
CREATE TABLE ac_metodologie (
    ente_id        CHAR(36) PRIMARY KEY,
    dati           JSON NOT NULL,          -- indicatori, scala, matrice, livelli
    impronta       VARCHAR(64),
    pacchetto      VARCHAR(150),
    impronta_base  VARCHAR(64),
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE ac_aree (
    id                 CHAR(36) PRIMARY KEY,
    ente_id            CHAR(36) NOT NULL,
    codice             VARCHAR(20) NOT NULL,
    descrizione        VARCHAR(500) NOT NULL,
    descrizione_breve  VARCHAR(255),           -- le aree si elencano in ordine alfabetico di questa
    UNIQUE KEY uq_ac_area (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE ac_processi (
    id              CHAR(36) PRIMARY KEY,
    ente_id         CHAR(36) NOT NULL,
    codice          VARCHAR(50) NOT NULL,
    tipo            VARCHAR(20) NOT NULL DEFAULT 'PROCESSO',  -- PROCESSO, PROCEDIMENTO
    area_id         CHAR(36),
    denominazione   VARCHAR(500) NOT NULL,
    descrizione     TEXT,
    tempi           TEXT,
    attori_esterni  TEXT,
    termine_conclusione  VARCHAR(255),      -- procedimento
    norma_riferimento    TEXT,              -- procedimento
    struttura_id    CHAR(36),               -- responsabile; vuota: trasversale
    impronta        VARCHAR(64),
    pacchetto       VARCHAR(150),
    impronta_base   VARCHAR(64),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ac_processo (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (area_id) REFERENCES ac_aree(id) ON DELETE SET NULL,
    FOREIGN KEY (struttura_id) REFERENCES strutture(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE ac_attivita (
    id                   CHAR(36) PRIMARY KEY,
    ente_id              CHAR(36) NOT NULL,
    processo_id          CHAR(36) NOT NULL,
    codice               VARCHAR(50) NOT NULL,
    descrizione          TEXT NOT NULL,
    strutture_coinvolte  TEXT,
    UNIQUE KEY uq_ac_attivita (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (processo_id) REFERENCES ac_processi(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE ac_rischi (
    id                      CHAR(36) PRIMARY KEY,
    ente_id                 CHAR(36) NOT NULL,
    attivita_id             CHAR(36) NOT NULL,
    codice                  VARCHAR(60) NOT NULL,
    evento                  TEXT NOT NULL,
    fattore_abilitante      VARCHAR(500),
    valori_probabilita      JSON,           -- {id indicatore: valore}
    valori_impatto          JSON,
    probabilita_calcolata   VARCHAR(50),    -- moda (a parità il più alto)
    impatto_calcolato       VARCHAR(50),
    probabilita             VARCHAR(50),    -- eventualmente corretta con motivazione
    impatto                 VARCHAR(50),
    livello                 VARCHAR(50),    -- dalla matrice
    motivazione_correzione  TEXT,
    valutato_il             TIMESTAMP NULL,
    UNIQUE KEY uq_ac_rischio (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (attivita_id) REFERENCES ac_attivita(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE ac_misure (
    id                   CHAR(36) PRIMARY KEY,
    ente_id              CHAR(36) NOT NULL,
    rischio_id           CHAR(36) NOT NULL,
    codice               VARCHAR(70) NOT NULL,
    descrizione          TEXT NOT NULL,
    tipo                 VARCHAR(20) NOT NULL DEFAULT 'SPECIFICA',  -- GENERALE, SPECIFICA
    categoria            VARCHAR(255),
    obbligo_trasparenza  VARCHAR(100),       -- schema ANAC (modulo trasparenza)
    fasi                 TEXT,
    tempi                TEXT,
    struttura_id         CHAR(36),           -- responsabile dell'attuazione
    indicatore           TEXT,
    target               TEXT,
    UNIQUE KEY uq_ac_misura (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (rischio_id) REFERENCES ac_rischi(id) ON DELETE CASCADE,
    FOREIGN KEY (struttura_id) REFERENCES strutture(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Codici della mappatura: l'ultimo numero assegnato per prefisso (es. "A.1." per le attività
-- del processo A.1), così un codice non si riusa nemmeno dopo l'eliminazione dell'elemento
CREATE TABLE ac_contatori (
    ente_id   CHAR(36) NOT NULL,
    prefisso  VARCHAR(100) NOT NULL,
    ultimo    INT NOT NULL,
    PRIMARY KEY (ente_id, prefisso),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Proposte dei referenti: creazione, modifica o eliminazione di un elemento della mappatura
CREATE TABLE ac_proposte (
    id                  CHAR(36) PRIMARY KEY,
    ente_id             CHAR(36) NOT NULL,
    utente_id           CHAR(36) NOT NULL,
    tipo                VARCHAR(10) NOT NULL,        -- CREA, MODIFICA, ELIMINA
    oggetto             VARCHAR(20) NOT NULL,        -- AREA, PROCESSO, ATTIVITA, RISCHIO, MISURA
    elemento_id         CHAR(36),                    -- elemento modificato, eliminato o (approvata) creato
    padre_id            CHAR(36),                    -- creazione: processo, attività o rischio di destinazione
    processo_id         CHAR(36),                    -- processo interessato (struttura del referente)
    dati                JSON NOT NULL,               -- elemento proposto (eliminazione: com'era)
    prima               JSON,                        -- modifica: l'elemento alla creazione della proposta
    contesto            JSON,                        -- percorso e codice, per gli elenchi
    stato               VARCHAR(20) NOT NULL DEFAULT 'INVIATA',  -- INVIATA, APPROVATA, RESPINTA, RESTITUITA
    nota                TEXT,                        -- del referente
    motivazione         TEXT,                        -- del RPCT
    deciso_da           CHAR(36),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    inviata_il          TIMESTAMP NULL,
    decisa_il           TIMESTAMP NULL,
    KEY ix_ac_proposte_stato (ente_id, stato),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (utente_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (processo_id) REFERENCES ac_processi(id) ON DELETE SET NULL,
    FOREIGN KEY (deciso_da) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Monitoraggio annuale delle misure: dichiarazione della struttura e verifica del RPCT
CREATE TABLE ac_monitoraggi (
    id                   CHAR(36) PRIMARY KEY,
    ente_id              CHAR(36) NOT NULL,
    anno                 INT NOT NULL,
    misura_id            CHAR(36),
    struttura_id         CHAR(36),
    contesto             JSON NOT NULL,      -- copia di misura, rischio, attività, processo, struttura
    stato_attuazione     VARCHAR(20) NOT NULL,  -- ATTUATA, PARZIALE, NON_ATTUATA
    motivazione          TEXT,
    indicatore_rilevato  TEXT,
    target               TEXT,
    evidenze             TEXT,
    dichiarato_da        CHAR(36),
    dichiarato_il        TIMESTAMP NULL,
    stato_verifica       VARCHAR(20) NOT NULL DEFAULT 'DA_VERIFICARE',  -- VERIFICATA, CONTESTATA
    note_rpct            TEXT,
    verificato_da        CHAR(36),
    verificato_il        TIMESTAMP NULL,
    UNIQUE KEY uq_ac_monitoraggio (ente_id, anno, misura_id, struttura_id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (misura_id) REFERENCES ac_misure(id) ON DELETE SET NULL,
    FOREIGN KEY (struttura_id) REFERENCES strutture(id) ON DELETE SET NULL,
    FOREIGN KEY (dichiarato_da) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (verificato_da) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Modulo performance: PIAO triennali, obiettivi annuali per struttura con azioni e
-- misure (della mappatura dei rischi), storico delle modifiche
-- ---------------------------------------------------------------------------
CREATE TABLE pf_piao (
    id           CHAR(36) PRIMARY KEY,
    ente_id      CHAR(36) NOT NULL,
    anno_inizio  INT NOT NULL,                    -- triennio: anno_inizio .. anno_inizio + 2
    titolo       VARCHAR(255) NOT NULL,
    atto         VARCHAR(255),                    -- es. DGC n. 59 del 26/03/2026
    stato        VARCHAR(10) NOT NULL DEFAULT 'APERTO', -- CHIUSO: sola lettura
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pf_piao (ente_id, anno_inizio),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE pf_obiettivi (
    id            CHAR(36) PRIMARY KEY,
    ente_id       CHAR(36) NOT NULL,
    piao_id       CHAR(36) NOT NULL,
    anno          INT NOT NULL,
    struttura_id  CHAR(36) NOT NULL,
    codice        VARCHAR(100),                   -- codice nel PIAO
    titolo        VARCHAR(500) NOT NULL,
    descrizione   TEXT,
    tipo          VARCHAR(20) NOT NULL DEFAULT 'OPERATIVO', -- FUNZIONAMENTO, MIGLIORAMENTO
    impegno       INT NOT NULL DEFAULT 0,         -- % sugli obiettivi della struttura nell'anno
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY ix_pf_obiettivi (piao_id, anno, struttura_id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (piao_id) REFERENCES pf_piao(id) ON DELETE CASCADE,
    FOREIGN KEY (struttura_id) REFERENCES strutture(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE pf_elementi (
    id             CHAR(36) PRIMARY KEY,
    ente_id        CHAR(36) NOT NULL,
    obiettivo_id   CHAR(36) NOT NULL,
    tipo           VARCHAR(10) NOT NULL,          -- AZIONE, MISURA
    descrizione    TEXT NOT NULL,                 -- dell'azione, o copia di quella della misura
    misura_id      CHAR(36),
    misura_codice  VARCHAR(70),
    impegno        INT NOT NULL DEFAULT 0,        -- % sulle azioni e misure dell'obiettivo
    completamento  INT NOT NULL DEFAULT 0,        -- %
    scadenza       DATE NOT NULL,
    ordine         INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (obiettivo_id) REFERENCES pf_obiettivi(id) ON DELETE CASCADE,
    FOREIGN KEY (misura_id) REFERENCES ac_misure(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE pf_modifiche (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    ente_id       CHAR(36) NOT NULL,
    piao_id       CHAR(36),
    obiettivo_id  CHAR(36),                       -- anche per azioni e misure
    oggetto       VARCHAR(10) NOT NULL,           -- PIAO, OBIETTIVO, AZIONE, MISURA
    oggetto_id    CHAR(36) NOT NULL,
    azione        VARCHAR(15) NOT NULL,           -- CREATO, MODIFICATO, ELIMINATO
    descrizione   VARCHAR(500) NOT NULL,
    campi         JSON,                           -- {campo: [prima, dopo]}
    nota          TEXT,
    utente_id     CHAR(36),
    utente_nome   VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_pf_modifiche_obiettivo (obiettivo_id, created_at),
    KEY ix_pf_modifiche_piao (piao_id, created_at),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (utente_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Coda di invio delle email (common/posta.py): scritta dall'API, inviata dal worker
-- ---------------------------------------------------------------------------
CREATE TABLE notifiche_email (
    id                  CHAR(36) PRIMARY KEY,
    ente_id             CHAR(36) NOT NULL,
    destinatario        VARCHAR(255) NOT NULL,
    oggetto             VARCHAR(255) NOT NULL,
    testo               TEXT NOT NULL,
    origine             VARCHAR(100),             -- es. ac_proposta:<id>
    stato               VARCHAR(20) NOT NULL DEFAULT 'DA_INVIARE', -- INVIATA, ERRORE
    tentativi           INT NOT NULL DEFAULT 0,
    prossimo_tentativo  DATETIME,
    errore              TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    inviata_il          DATETIME,
    KEY ix_da_inviare (stato, prossimo_tentativo),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Registro delle operazioni
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    ente_id     CHAR(36),
    user_id     CHAR(36),
    entita      VARCHAR(50) NOT NULL,
    entita_id   VARCHAR(255) NOT NULL,
    azione      VARCHAR(30) NOT NULL,
    dettaglio   JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_entita (entita, entita_id),
    KEY ix_ente (ente_id, created_at)
) ENGINE=InnoDB;
