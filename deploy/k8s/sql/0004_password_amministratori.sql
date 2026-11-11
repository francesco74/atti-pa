-- Password degli amministratori: dalla versione con le lunghezze minime differenziate (8
-- caratteri per gli utenti, 16 per il ruolo ADMIN) gli amministratori locali scelgono una
-- nuova password al prossimo accesso, perché quella attuale può essere più corta di 16
-- caratteri (si conserva solo l'hash, la lunghezza non si può controllare).
-- Non cancella dati e si può rilanciare. Gli utenti di Active Directory non sono toccati.
UPDATE users
SET cambio_password = TRUE
WHERE origine = 'LOCALE'
  AND attivo = TRUE
  AND cambio_password = FALSE
  AND JSON_CONTAINS(ruoli, '"ADMIN"');
