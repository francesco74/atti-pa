-- Modulo performance: iter di approvazione degli obiettivi. Il responsabile propone la
-- creazione, la modifica o l'eliminazione di un obiettivo (con le azioni e misure);
-- l'approvatore (ruolo PERFORMANCE_APPROVATORE) approva, respinge o restituisce.
CREATE TABLE pf_proposte (
    id            CHAR(36) PRIMARY KEY,
    ente_id       CHAR(36) NOT NULL,
    piao_id       CHAR(36) NOT NULL,
    anno          INT NOT NULL,
    struttura_id  CHAR(36) NOT NULL,
    obiettivo_id  CHAR(36),                       -- creazione: assegnato all'approvazione
    tipo          VARCHAR(10) NOT NULL,           -- CREA, MODIFICA, ELIMINA
    titolo        VARCHAR(600) NOT NULL,          -- dell'obiettivo, per gli elenchi
    dati          JSON,                           -- obiettivo con azioni e misure proposto
    prima         JSON,                           -- modifica, eliminazione: com'era
    stato         VARCHAR(20) NOT NULL DEFAULT 'BOZZA', -- INVIATA, APPROVATA, RESPINTA, RESTITUITA
    utente_id     CHAR(36),                       -- chi l'ha inviata
    nota          TEXT,                           -- di chi propone
    motivazione   TEXT,                           -- dell'approvatore
    deciso_da     CHAR(36),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    inviata_il    TIMESTAMP NULL,
    decisa_il     TIMESTAMP NULL,
    KEY ix_pf_proposte_stato (ente_id, stato),
    KEY ix_pf_proposte_obiettivo (obiettivo_id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (piao_id) REFERENCES pf_piao(id) ON DELETE CASCADE,
    FOREIGN KEY (struttura_id) REFERENCES strutture(id) ON DELETE RESTRICT,
    FOREIGN KEY (utente_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (deciso_da) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;
