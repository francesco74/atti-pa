-- Modulo anticorruzione: l'attività che è un procedimento del catalogo può adattarne alcuni dati
-- per quel processo (unità responsabile, uffici, termine): solo i campi cambiati, in JSON; gli
-- altri restano quelli del catalogo. Il collegamento al procedimento (procedimento_id) resta,
-- quindi si vede sempre dove il procedimento è usato.
--
-- Aggiunge una colonna vuota. Si può rieseguire.

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_attivita' AND COLUMN_NAME = 'procedimento_adattato');
SET @sql := IF(@manca, 'ALTER TABLE ac_attivita ADD COLUMN procedimento_adattato JSON NULL AFTER procedimento_id', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
