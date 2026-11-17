-- Modulo anticorruzione: catalogo della mappatura, le voci (radici) di attività, rischi
-- (evento) e misure da cui nascono gli elementi dei processi; attività, rischi e misure
-- ricordano la loro voce (voce_id). Le voci standard vengono dal pacchetto
-- (anticorruzione/catalogo.yaml); per collegare la mappatura già presente:
-- deploy/manutenzione/catalogo_mappatura.py.
--
-- Crea una tabella e aggiunge colonne vuote. Si può rieseguire: ogni passo controlla prima se
-- è già stato fatto.

CREATE TABLE IF NOT EXISTS ac_catalogo (
    id           CHAR(36) PRIMARY KEY,
    ente_id      CHAR(36) NOT NULL,
    tipo         VARCHAR(10) NOT NULL,          -- ATTIVITA, RISCHIO, MISURA
    codice       VARCHAR(20) NOT NULL,          -- ATT-0001 (pacchetto), ATT-E001 (ente)
    descrizione  TEXT NOT NULL,                 -- per il rischio l'evento
    tipo_misura  VARCHAR(20),                   -- misure: GENERALE, SPECIFICA
    categoria    VARCHAR(255),
    indicatore   TEXT,
    target       TEXT,
    attiva       BOOLEAN NOT NULL DEFAULT TRUE, -- disattivata: non si sceglie più
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ac_catalogo (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE
) ENGINE=InnoDB;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_attivita' AND COLUMN_NAME = 'voce_id');
SET @sql := IF(@manca, 'ALTER TABLE ac_attivita ADD COLUMN voce_id CHAR(36) NULL AFTER coinvolte, ADD CONSTRAINT fk_ac_attivita_voce FOREIGN KEY (voce_id) REFERENCES ac_catalogo(id) ON DELETE SET NULL', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_rischi' AND COLUMN_NAME = 'voce_id');
SET @sql := IF(@manca, 'ALTER TABLE ac_rischi ADD COLUMN voce_id CHAR(36) NULL AFTER evento, ADD CONSTRAINT fk_ac_rischi_voce FOREIGN KEY (voce_id) REFERENCES ac_catalogo(id) ON DELETE SET NULL', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_misure' AND COLUMN_NAME = 'voce_id');
SET @sql := IF(@manca, 'ALTER TABLE ac_misure ADD COLUMN voce_id CHAR(36) NULL AFTER descrizione, ADD CONSTRAINT fk_ac_misure_voce FOREIGN KEY (voce_id) REFERENCES ac_catalogo(id) ON DELETE SET NULL', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
