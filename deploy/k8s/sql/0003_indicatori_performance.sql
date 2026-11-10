-- Modulo performance: indicatori delle azioni e misure degli obiettivi. La definizione
-- (descrizione, tipo, partenza, target, verso) fa parte dell'obiettivo e segue l'iter di
-- approvazione; il valore rilevato è avanzamento e si aggiorna senza approvazione. Con almeno
-- un indicatore il completamento dell'azione o misura si calcola dal loro raggiungimento.
CREATE TABLE pf_indicatori (
    id             CHAR(36) PRIMARY KEY,
    ente_id        CHAR(36) NOT NULL,
    elemento_id    CHAR(36) NOT NULL,
    descrizione    TEXT NOT NULL,
    tipo           VARCHAR(12) NOT NULL,          -- NUMERO, PERCENTUALE, SI_NO, DATA
    unita          VARCHAR(50),                   -- numero: es. eventi, giorni, euro
    partenza       DOUBLE,                        -- valore di partenza (numero, percentuale)
    target         DOUBLE,                        -- valore da raggiungere (numero, percentuale)
    target_data    DATE,                          -- data: entro quando
    verso          VARCHAR(12) NOT NULL DEFAULT 'CRESCENTE', -- DECRESCENTE: più basso è meglio
    fonte          VARCHAR(255),                  -- fonte del dato
    rilevato       DOUBLE,                        -- numero, percentuale; sì/no: 1 o 0
    rilevato_data  DATE,                          -- data: quando è stato raggiunto
    rilevato_il    TIMESTAMP NULL,                -- ultima rilevazione
    ordine         INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY ix_pf_indicatori_elemento (elemento_id),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (elemento_id) REFERENCES pf_elementi(id) ON DELETE CASCADE
) ENGINE=InnoDB;
