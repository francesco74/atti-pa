-- Messaggio dell'amministratore dell'ente nella pagina iniziale (Home) di tutti gli utenti
-- (Amministrazione -> Profilo dell'ente). Aggiunge solo una colonna vuota; si può rieseguire.

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'enti' AND COLUMN_NAME = 'benvenuto');
SET @sql := IF(@manca, 'ALTER TABLE enti ADD COLUMN benvenuto TEXT NULL AFTER assistenza', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
