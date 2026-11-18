-- Modulo anticorruzione: i procedimenti amministrativi non sono più un tipo di processo ma un
-- catalogo dell'ente (ac_procedimenti, codici P.n), condiviso con la trasparenza; nella mappatura
-- un'attività può essere un procedimento (ac_attivita.procedimento_id) invece di una voce del
-- catalogo delle attività. Termine di conclusione, riferimenti normativi e dati dell'art. 35
-- stanno solo nel procedimento.
--
-- Conversione dei dati:
-- 1. i processi di tipo PROCEDIMENTO senza attività (quelli della sola trasparenza, o
--    dell'anticorruzione senza mappatura) diventano procedimenti del catalogo con lo stesso id
--    (restano validi i link della pagina pubblica) e si tolgono dai processi;
-- 2. quelli con attività restano processi con la loro mappatura; nel catalogo entra una copia
--    del procedimento (id nuovo, ricavato da quello del processo); il collegamento a
--    un'attività lo rifà il RPCT;
-- 3. tutti i procedimenti prendono un codice P.n: chi lo ha già lo tiene, gli altri seguono;
-- 4. le proposte non ancora decise sui procedimenti (e sugli elementi dei processi del punto 1)
--    si chiudono come respinte;
-- 5. si ELIMINANO da ac_processi le colonne tipo, termine_conclusione, norma_riferimento e
--    art35, dopo averne copiato il contenuto nel catalogo.
--
-- Si può rieseguire: ogni passo controlla prima se è già stato fatto (i passi sui dati solo
-- finché ac_processi ha la colonna tipo).

CREATE TABLE IF NOT EXISTS ac_procedimenti (
    id                   CHAR(36) PRIMARY KEY,
    ente_id              CHAR(36) NOT NULL,
    codice               VARCHAR(50) NOT NULL,      -- P.1, P.2...
    denominazione        VARCHAR(500) NOT NULL,
    descrizione          TEXT,
    termine_conclusione  VARCHAR(255),
    norma_riferimento    TEXT,
    struttura_id         CHAR(36),                  -- unità responsabile dell'istruttoria
    art35                JSON,                      -- dati propri dell'art. 35 d.lgs. 33/2013
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ac_procedimento (ente_id, codice),
    FOREIGN KEY (ente_id) REFERENCES enti(id) ON DELETE CASCADE,
    FOREIGN KEY (struttura_id) REFERENCES strutture(id) ON DELETE SET NULL
) ENGINE=InnoDB;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_attivita' AND COLUMN_NAME = 'procedimento_id');
SET @sql := IF(@manca, 'ALTER TABLE ac_attivita ADD COLUMN procedimento_id CHAR(36) NULL AFTER voce_id, ADD CONSTRAINT fk_ac_attivita_procedimento FOREIGN KEY (procedimento_id) REFERENCES ac_procedimenti(id) ON DELETE SET NULL', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

-- i passi sui dati: solo se ac_processi ha ancora il tipo
SET @da_convertire := (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_processi' AND COLUMN_NAME = 'tipo');

-- 1. procedimenti senza attività: stesso id
SET @sql := IF(@da_convertire, '
    INSERT INTO ac_procedimenti (id, ente_id, codice, denominazione, descrizione, termine_conclusione,
                                 norma_riferimento, struttura_id, art35, created_at, updated_at)
    SELECT p.id, p.ente_id, p.codice, p.denominazione, p.descrizione, p.termine_conclusione,
           p.norma_riferimento, p.struttura_id, p.art35, p.created_at, p.updated_at
    FROM ac_processi p
    WHERE p.tipo = ''PROCEDIMENTO''
      AND NOT EXISTS (SELECT 1 FROM ac_attivita a WHERE a.processo_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM ac_procedimenti x WHERE x.id = p.id)', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

-- 2. procedimenti con attività: una copia nel catalogo (id ricavato da quello del processo)
SET @sql := IF(@da_convertire, '
    INSERT INTO ac_procedimenti (id, ente_id, codice, denominazione, descrizione, termine_conclusione,
                                 norma_riferimento, struttura_id, art35, created_at, updated_at)
    SELECT n.nuovo, p.ente_id, p.codice, p.denominazione, p.descrizione, p.termine_conclusione,
           p.norma_riferimento, p.struttura_id, p.art35, p.created_at, p.updated_at
    FROM ac_processi p
    JOIN (SELECT id, CONCAT(SUBSTR(h, 1, 8), ''-'', SUBSTR(h, 9, 4), ''-'', SUBSTR(h, 13, 4), ''-'',
                            SUBSTR(h, 17, 4), ''-'', SUBSTR(h, 21, 12)) AS nuovo
          FROM (SELECT id, MD5(CONCAT(''procedimento:'', id)) AS h FROM ac_processi) q) n ON n.id = p.id
    WHERE p.tipo = ''PROCEDIMENTO''
      AND EXISTS (SELECT 1 FROM ac_attivita a WHERE a.processo_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM ac_procedimenti x WHERE x.id = n.nuovo)', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

-- 3. codici P.n: chi non lo ha prende il numero successivo al più alto dell'ente (anche tra
-- quelli già assegnati ai processi senza area, contatore "P.")
UPDATE ac_procedimenti x
JOIN (SELECT id, ente_id, ROW_NUMBER() OVER (PARTITION BY ente_id ORDER BY codice) AS n
      FROM ac_procedimenti WHERE codice NOT REGEXP '^P[.][0-9]+$') r ON r.id = x.id
LEFT JOIN (SELECT ente_id, MAX(CAST(SUBSTRING(codice, 3) AS UNSIGNED)) AS m
           FROM ac_procedimenti WHERE codice REGEXP '^P[.][0-9]+$' GROUP BY ente_id) u ON u.ente_id = x.ente_id
LEFT JOIN ac_contatori c ON c.ente_id = x.ente_id AND c.prefisso = 'P.'
SET x.codice = CONCAT('P.', GREATEST(COALESCE(u.m, 0), COALESCE(c.ultimo, 0)) + r.n);

INSERT INTO ac_contatori (ente_id, prefisso, ultimo)
SELECT ente_id, 'P.', MAX(CAST(SUBSTRING(codice, 3) AS UNSIGNED)) FROM ac_procedimenti GROUP BY ente_id
ON DUPLICATE KEY UPDATE ultimo = GREATEST(ultimo, VALUES(ultimo));

-- 4. proposte non decise sui procedimenti e sugli elementi dei procedimenti che lasciano i processi
SET @sql := IF(@da_convertire, '
    UPDATE ac_proposte SET stato = ''RESPINTA'', decisa_il = NOW(),
           motivazione = ''Riorganizzazione della mappatura: i procedimenti sono ora un catalogo a sé e un''''attività può essere un procedimento. Se serve, ripresenta la proposta.''
    WHERE stato IN (''INVIATA'', ''RESTITUITA'')
      AND (JSON_UNQUOTE(JSON_EXTRACT(dati, ''$.tipo'')) = ''PROCEDIMENTO''
           OR processo_id IN (SELECT id FROM ac_processi WHERE tipo = ''PROCEDIMENTO''))', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

-- 1 (fine). i procedimenti copiati con lo stesso id lasciano i processi
SET @sql := IF(@da_convertire, '
    DELETE p FROM ac_processi p JOIN ac_procedimenti x ON x.id = p.id
    WHERE p.tipo = ''PROCEDIMENTO'' AND NOT EXISTS (SELECT 1 FROM ac_attivita a WHERE a.processo_id = p.id)', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

-- 5. colonne del procedimento tolte dai processi (il contenuto è nel catalogo)
SET @c := (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_processi' AND COLUMN_NAME = 'art35');
SET @sql := IF(@c, 'ALTER TABLE ac_processi DROP COLUMN art35', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @c := (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_processi' AND COLUMN_NAME = 'norma_riferimento');
SET @sql := IF(@c, 'ALTER TABLE ac_processi DROP COLUMN norma_riferimento', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @c := (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_processi' AND COLUMN_NAME = 'termine_conclusione');
SET @sql := IF(@c, 'ALTER TABLE ac_processi DROP COLUMN termine_conclusione', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @c := (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_processi' AND COLUMN_NAME = 'tipo');
SET @sql := IF(@c, 'ALTER TABLE ac_processi DROP COLUMN tipo', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
