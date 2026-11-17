-- Modulo performance: le azioni e le misure degli obiettivi ricordano la loro radice, la voce
-- del catalogo della mappatura (attività o misura), con il codice copiato. Dalla mappatura si
-- importano le radici: una misura usata sotto più rischi entra una volta sola.
--
-- Aggiunge colonne e collega gli elementi già presenti alla voce della loro attività o misura.
-- Si può rieseguire: ogni passo controlla prima se è già stato fatto.

SET @manca := (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pf_elementi' AND COLUMN_NAME = 'voce_id');
SET @sql := IF(@manca, 'ALTER TABLE pf_elementi ADD COLUMN voce_id CHAR(36) NULL AFTER mappatura_codice, ADD COLUMN voce_codice VARCHAR(20) NULL AFTER voce_id, ADD CONSTRAINT fk_pf_elementi_voce FOREIGN KEY (voce_id) REFERENCES ac_catalogo(id) ON DELETE SET NULL', 'DO 0');
PREPARE passo FROM @sql; EXECUTE passo; DEALLOCATE PREPARE passo;

-- elementi già presenti: la voce della loro attività (azioni) o misura
UPDATE pf_elementi e JOIN ac_attivita a ON a.id = e.attivita_id JOIN ac_catalogo v ON v.id = a.voce_id
   SET e.voce_id = v.id, e.voce_codice = v.codice
 WHERE e.voce_id IS NULL AND e.tipo = 'AZIONE';
UPDATE pf_elementi e JOIN ac_misure m ON m.id = e.misura_id JOIN ac_catalogo v ON v.id = m.voce_id
   SET e.voce_id = v.id, e.voce_codice = v.codice
 WHERE e.voce_id IS NULL AND e.tipo = 'MISURA';
