-- Modulo performance: un'azione di un obiettivo si può copiare da un'attività della mappatura
-- dei rischi (modulo anticorruzione): attivita_id è l'attività, processo_id il processo da cui
-- viene, mappatura_codice il codice dell'attività copiato. È una copia: se poi l'attività o il
-- processo vengono eliminati dalla mappatura l'azione resta, con il codice.
--
-- Aggiunge solo colonne vuote (le azioni e misure esistenti restano come sono). Si può
-- rieseguire: ogni passo controlla prima se è già stato fatto.

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pf_elementi' AND COLUMN_NAME = 'processo_id');
SET @sql := IF(@manca, 'ALTER TABLE pf_elementi ADD COLUMN processo_id CHAR(36) NULL AFTER misura_codice', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pf_elementi' AND COLUMN_NAME = 'attivita_id');
SET @sql := IF(@manca, 'ALTER TABLE pf_elementi ADD COLUMN attivita_id CHAR(36) NULL AFTER processo_id', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pf_elementi' AND COLUMN_NAME = 'mappatura_codice');
SET @sql := IF(@manca, 'ALTER TABLE pf_elementi ADD COLUMN mappatura_codice VARCHAR(70) NULL AFTER attivita_id', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

-- chiavi esterne (con il loro indice): eliminando il processo o l'attività il riferimento si svuota
SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.TABLE_CONSTRAINTS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pf_elementi' AND CONSTRAINT_NAME = 'fk_pf_elementi_processo');
SET @sql := IF(@manca, 'ALTER TABLE pf_elementi ADD CONSTRAINT fk_pf_elementi_processo FOREIGN KEY (processo_id) REFERENCES ac_processi(id) ON DELETE SET NULL', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.TABLE_CONSTRAINTS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pf_elementi' AND CONSTRAINT_NAME = 'fk_pf_elementi_attivita');
SET @sql := IF(@manca, 'ALTER TABLE pf_elementi ADD CONSTRAINT fk_pf_elementi_attivita FOREIGN KEY (attivita_id) REFERENCES ac_attivita(id) ON DELETE SET NULL', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
