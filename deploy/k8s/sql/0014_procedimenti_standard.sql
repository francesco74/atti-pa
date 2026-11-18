-- Modulo anticorruzione: i pacchetti portano anche un catalogo di procedimenti standard
-- (anticorruzione/procedimenti.yaml, codici PRC-0001...). Nell'ente il procedimento prende il
-- suo codice P.n e ricorda quello standard (standard) e il pacchetto da cui viene, così le
-- attività dei processi standard lo ritrovano e i pacchetti successivi non lo duplicano.
--
-- Aggiunge due colonne vuote e un indice. Si può rieseguire.

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_procedimenti' AND COLUMN_NAME = 'standard');
SET @sql := IF(@manca, 'ALTER TABLE ac_procedimenti ADD COLUMN standard VARCHAR(20) NULL AFTER art35, ADD COLUMN pacchetto VARCHAR(150) NULL AFTER standard', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_procedimenti' AND INDEX_NAME = 'ix_ac_procedimento_standard');
SET @sql := IF(@manca, 'CREATE INDEX ix_ac_procedimento_standard ON ac_procedimenti (ente_id, standard)', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
