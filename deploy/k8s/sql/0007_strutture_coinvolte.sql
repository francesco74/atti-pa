-- Modulo anticorruzione: strutture coinvolte nei processi e nelle attività, scelte
-- dall'anagrafica (elenco di id in JSON), oltre alla struttura responsabile del processo.
-- Servono a trovare il processo tra quelli di una struttura (filtri, elenco, Excel), non a
-- proporne modifiche. Il testo libero delle attività (strutture_coinvolte) resta come nota:
-- deploy/manutenzione/strutture_coinvolte.py ne ricava le strutture riconosciute.
--
-- Aggiunge solo colonne vuote. Si può rieseguire: ogni passo controlla prima se è già stato fatto.

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_processi' AND COLUMN_NAME = 'coinvolte');
SET @sql := IF(@manca, 'ALTER TABLE ac_processi ADD COLUMN coinvolte JSON NULL AFTER struttura_id', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_attivita' AND COLUMN_NAME = 'coinvolte');
SET @sql := IF(@manca, 'ALTER TABLE ac_attivita ADD COLUMN coinvolte JSON NULL AFTER strutture_coinvolte', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
