-- Assistente: azioni sui documenti della conversazione (Riassumi, Confronta, Estrai), eseguite
-- dal worker sulla coda "assistente" (progettazione/assistente_documenti.md). Il risultato
-- contiene testo dei documenti: il worker cancella i lavori dopo un giorno.
-- Tabella nuova, nessun dato esistente toccato: si può rilanciare.
CREATE TABLE IF NOT EXISTS assistente_lavori (
    id             CHAR(36) PRIMARY KEY,
    ente_id        CHAR(36) NOT NULL,
    utente_id      CHAR(36) NOT NULL,
    tipo           VARCHAR(12) NOT NULL,        -- RIASSUNTO, CONFRONTO, ESTRAZIONE
    stato          VARCHAR(20) NOT NULL DEFAULT 'IN_CODA',  -- IN_CODA, IN_CORSO, COMPLETATA, ERRORE
    richiesta      JSON NOT NULL,               -- sessione del RAG, documenti, istruzioni
    avanzamento    JSON,                        -- {"fatti", "totale"}
    risultato      MEDIUMTEXT,                  -- Markdown
    errore         TEXT,
    modello_llm    VARCHAR(100),
    tentativi      INT NOT NULL DEFAULT 0,
    worker         VARCHAR(100),
    avviato_il     TIMESTAMP NULL,
    aggiornato_il  TIMESTAMP NULL,               -- ultimo avanzamento: fermo da troppo = worker caduto
    completato_il  TIMESTAMP NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_assistente_lavori_stato (stato, created_at),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (utente_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Verifica: la tabella deve comparire
SHOW TABLES LIKE 'assistente_lavori';
