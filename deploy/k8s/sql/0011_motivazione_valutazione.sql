-- Motivazione della valutazione del rischio (giudizio sintetico motivato, PNA 2019 All. 1),
-- oltre a quella dell'eventuale correzione di probabilità e impatto; la può proporre
-- l'intelligenza artificiale, la conferma chi valuta. Aggiunge solo una colonna vuota; si può
-- rieseguire.

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ac_rischi' AND COLUMN_NAME = 'motivazione_valutazione');
SET @sql := IF(@manca, 'ALTER TABLE ac_rischi ADD COLUMN motivazione_valutazione TEXT NULL AFTER motivazione_correzione', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;
