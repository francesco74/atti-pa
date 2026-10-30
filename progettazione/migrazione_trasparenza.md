# Migrazione manuale dei dati di PApuntozeroIA

Promemoria per portare a mano in atti-pa i dati di produzione di PApuntozeroIA (database
`trasparenza`): cosa corrisponde a cosa e quali sono le differenze da gestire. Non c'è una
procedura automatica.

Si portano **uffici, utenti e documenti salvati**. Non si portano i lavori: in
PApuntozeroIA le analisi erano sincrone e non ne resta traccia. Gli schemi ANAC non si
portano perché sono nel codice (`common/trasparenza/schemi`).

## 1. Corrispondenze

| PApuntozeroIA | atti-pa | Note |
|---|---|---|
| `offices` | `enti` | l'ente si crea con `enti.py`, non con una INSERT (§2) |
| `offices.name` | `enti.nome` | nome nell'intestazione di schede e verbali e nel prompt (`- Ente:`) |
| `offices.description` | `enti.caratteristiche` (prima riga) | in PApuntozeroIA indicava la tipologia dell'ente ai prompt (§3) |
| `offices.authority_features` | `enti.caratteristiche` (dopo la descrizione) | |
| `offices.logo` (percorso `/sc/...`) | `enti.logo`, `enti.logo_mime` | si carica dall'app (§2) |
| `users` | `users` | §4 |
| `user_documents` | `trasparenza_documenti` | §5 |

**Gli id sono diversi.** In PApuntozeroIA gli id sono interi `AUTO_INCREMENT`, in atti-pa
sono UUID di 36 caratteri (`CHAR(36)`, in MySQL `UUID()`). Le chiavi esterne (`office_id`,
`user_id`) vanno tradotte con una tabella di corrispondenza (§7).

## 2. Preparazione degli enti

Per ogni ufficio:

1. Crea l'ente con il modulo trasparenza (e `redazione` se serve):
   `python deploy/enti.py crea CODICE "Nome" DOMINIO --moduli trasparenza`.
2. Accedi come `admin` dal dominio dell'ente e cambia la password iniziale.
3. In **Amministrazione → Profilo dell'ente**:
   - carica il logo, cioè il file indicato da `offices.logo`. Si trova in `static/sc` dentro
     il container `rest` di PApuntozeroIA: `docker cp <container-rest>:/app/static/sc ./sc`.
     L'app accetta PNG o JPEG di al massimo 2 MB;
   - compila le **caratteristiche** come indicato al §3, oppure con la query del §7.
4. Se gli utenti di PApuntozeroIA diventano utenti locali, l'**accesso con utenti locali**
   dell'ente deve restare attivo (Amministrazione → Accesso). Senza, gli utenti migrati non
   potranno entrare.

## 3. Tipologia dell'ente nei prompt

La normativa distingue gli obblighi per tipo di ente, quindi l'LLM deve sapere che ente è
(per esempio "ente con più di 15.000 abitanti").

- **In PApuntozeroIA:** `_CUSTOMER_NAME_` = `offices.description` e
  `_AUTHORITY_FEATURES_` = `offices.authority_features`.
- **In atti-pa:** `_CUSTOMER_NAME_` = `enti.nome` e `_AUTHORITY_FEATURES_` =
  `enti.caratteristiche`. È la sezione che i prompt usano per l'ambito soggettivo e per le
  regole che dipendono dal tipo di ente (ART_14, ART_15_TER, ART_29, ART_32, ART_4_BIS...).

Quindi la `description` dell'ufficio va **all'inizio delle caratteristiche**, seguita da
`authority_features`:

```
Comune con più di 15.000 abitanti.
<testo di authority_features>
```

## 4. Utenti

| `users` di PApuntozeroIA | `users` di atti-pa |
|---|---|
| `id` (intero) | `id` = nuovo UUID |
| `office_id` | `ente_id` dell'ente corrispondente (obbligatorio) |
| `username` | `username` |
| `password_hash` | `password_hash` così com'è |
| `description` | `nome_completo` |
| `created_at` | `created_at` |
| — | `origine` = `'LOCALE'` (il predefinito della colonna è `'LDAP'`) |
| — | `ruoli` = `JSON_ARRAY('TRASPARENZA')` |
| — | `cambio_password` = `FALSE`, `token_version` = `0`, `attivo` = `TRUE` |

Particolarità:

- **Password:** gli hash sono di `flask_bcrypt` (`$2b$...`). atti-pa li accetta (`api/src/auth/password.py`)
  e al primo accesso li rigenera nel suo formato, quindi gli utenti entrano con la password
  di sempre. Non impostare `cambio_password`.
- **Unicità del nome utente:** in PApuntozeroIA `username` è unico in tutta l'installazione,
  in atti-pa per ente (`uq_utente_ente`). Se nell'ente esiste già un utente con quel nome
  (l'`admin` creato da `enti.py`, o uno di Active Directory), non crearne un altro: collega i
  documenti a quello esistente e aggiungigli il ruolo `TRASPARENZA` se non ce l'ha.
- **Utenti senza ufficio:** se `office_id` è NULL l'utente non ha un ente. Decidi a quale ente
  assegnarlo, oppure non migrarlo.
- **Collation:** le tabelle di PApuntozeroIA sono `utf8mb4_0900_ai_ci`, quelle di atti-pa
  `utf8mb4_unicode_ci`. Nei confronti tra stringhe dei due database indica la collation
  (`... = u.username COLLATE utf8mb4_unicode_ci`), altrimenti MySQL dà "Illegal mix of
  collations".

## 5. Documenti salvati

| `user_documents` | `trasparenza_documenti` |
|---|---|
| `id` (intero) | `id` = nuovo UUID |
| `user_id` | `utente_id` = UUID dell'utente migrato; `ente_id` = ente dell'utente |
| `description` | `descrizione`: obbligatoria (NOT NULL) e al massimo 255 caratteri |
| `html_content` | `html`: obbligatorio (NOT NULL) |
| `esito` | `esito` così com'è |
| `dati_schema` (testo) | `dati_schema`: colonna JSON, quindi JSON valido o NULL, **mai stringa vuota** |
| — | `schema_id` = `pdf_type` dei dati del form, se ci sono |
| — | `tipo` = SCHEDA, ANALISI o VERBALE (vedi sotto) |
| `created_at`, `updated_at` | `created_at`, `updated_at` |

### Il tipo

PApuntozeroIA non salvava il tipo, e la regola che l'API usa per i documenti nuovi (dati
del form → SCHEDA, esito → ANALISI, altrimenti VERBALE) sbaglierebbe sui vecchi:

- le schede salvate prima che esistesse la colonna `dati_schema` non hanno i dati del form;
- le analisi senza badge dell'esito non hanno l'esito.

Il tipo conta perché l'app tratta i verbali in modo diverso. Per i documenti migrati
ricavalo dal contenuto, **in quest'ordine**:

1. **VERBALE** se l'HTML contiene `DI VALIDAZIONE DEI DATI E DELLE INFORMAZIONI DA PUBBLICARE`
   (dal modello `VERBALEDIVALIDAZIONE`). Va controllato per primo, perché un verbale contiene
   anche le schede che lo seguono;
2. **SCHEDA** se ci sono i dati del form, oppure se l'HTML contiene `alt="Logo ente"` (il logo
   con cui si apre il modello `SCHEMA`);
3. **ANALISI** negli altri casi (report dell'LLM).

Prima di copiare i documenti, controlla il risultato con una SELECT (§7).

### Esito

I valori di `esito` sono già quelli di atti-pa: `Pubblicabile`, `Pubblicabile provvisoriamente`,
`Non pubblicabile`, oppure NULL.

### Sanificazione

L'HTML inserito con SQL non passa dalla sanificazione dell'API al salvataggio. Il rischio
è basso per due motivi:

- PApuntozeroIA sanificava già con le stesse regole (nh3);
- l'API sanifica anche in lettura (`GET /api/v1/trasparenza/documenti/<id>`).

## 6. Immagini del logo nei documenti

Schede e verbali di PApuntozeroIA contengono il logo come **percorso**,
`<img src="/sc/logo.jpg">`, che PApuntozeroIA trasformava in immagine solo all'esportazione.
In atti-pa quel percorso non esiste, quindi l'immagine non si vede nell'editor e sparisce in
PDF e DOCX, perché l'esportazione tiene solo le immagini `data:`. I documenti generati da
atti-pa hanno invece il logo incorporato (`data:image/...;base64,...`).

Dopo aver caricato il logo nell'ente (§2), sostituisci i percorsi con il logo incorporato.
Tutte le immagini `/sc/` dei documenti venivano dal segnaposto `_logo_` dei modelli, quindi
erano tutte il logo dell'ufficio:

```sql
-- quanti documenti hanno ancora il logo come percorso
SELECT ente_id, COUNT(*) FROM trasparenza_documenti
WHERE html LIKE '%src="/sc/%' GROUP BY ente_id;

UPDATE trasparenza_documenti d
JOIN enti e ON e.id = d.ente_id
SET d.html = REGEXP_REPLACE(
      d.html,
      'src="/sc/[^"]*"',
      CONCAT('src="data:', e.logo_mime, ';base64,',
             REPLACE(TO_BASE64(e.logo), CHAR(10), ''), '"'))
WHERE d.html LIKE '%src="/sc/%'
  AND e.logo IS NOT NULL;
```

`TO_BASE64` va a capo ogni 76 caratteri: il `REPLACE` su `CHAR(10)` toglie gli a capo. Il
resto del documento resta com'è, comprese le modifiche fatte a mano dopo la generazione.

**In alternativa, dall'app:**

- **schede con i dati del form:** "Modifica i dati della scheda" e rigenera. Nasce un
  **nuovo** documento; le modifiche manuali successive alla generazione si perdono e il
  vecchio documento va eliminato;
- **altri documenti:** nell'editor si cancella l'immagine rotta e si inserisce il logo con
  il pulsante immagine.

## 7. Traccia in SQL

Ipotesi: il dump di PApuntozeroIA è importato in uno schema `papuntozero` sullo stesso
server MySQL di atti-pa, e i comandi si eseguono sul database di atti-pa. Adatta i nomi e
prova prima su una copia.

```sql
-- Corrispondenza uffici → enti (una riga per ufficio, enti già creati con enti.py)
CREATE TABLE papuntozero.mig_enti (office_id INT PRIMARY KEY, ente_id CHAR(36) NOT NULL);
INSERT INTO papuntozero.mig_enti SELECT 1, id FROM enti WHERE codice = 'provincia-lucca';
-- ... una INSERT per ogni ufficio

-- Caratteristiche: descrizione + authority_features, solo dove sono ancora vuote
UPDATE enti e
JOIN papuntozero.mig_enti m ON m.ente_id = e.id
JOIN papuntozero.offices o ON o.id = m.office_id
SET e.caratteristiche = CONCAT_WS(CHAR(10), NULLIF(TRIM(o.description), ''),
                                  NULLIF(TRIM(o.authority_features), ''))
WHERE e.caratteristiche IS NULL OR e.caratteristiche = '';

-- Corrispondenza utenti: prima quelli già presenti nell'ente (es. admin), poi i nuovi
CREATE TABLE papuntozero.mig_utenti (
    user_id INT PRIMARY KEY, utente_id CHAR(36) NOT NULL, nuovo BOOLEAN NOT NULL);
INSERT INTO papuntozero.mig_utenti
SELECT u.id, x.id, FALSE
FROM papuntozero.users u
JOIN papuntozero.mig_enti m ON m.office_id = u.office_id
JOIN users x ON x.ente_id = m.ente_id
            AND x.username = u.username COLLATE utf8mb4_unicode_ci;
INSERT INTO papuntozero.mig_utenti
SELECT u.id, UUID(), TRUE
FROM papuntozero.users u
JOIN papuntozero.mig_enti m ON m.office_id = u.office_id
WHERE u.id NOT IN (SELECT user_id FROM papuntozero.mig_utenti);
-- Restano fuori gli utenti senza ufficio o con un ufficio non mappato: controllali
SELECT u.id, u.username, u.office_id FROM papuntozero.users u
WHERE u.id NOT IN (SELECT user_id FROM papuntozero.mig_utenti);

-- Utenti nuovi
INSERT INTO users (id, ente_id, username, origine, password_hash, token_version,
                   cambio_password, nome_completo, ruoli, attivo, created_at)
SELECT mu.utente_id, m.ente_id, u.username, 'LOCALE', u.password_hash, 0,
       FALSE, u.description, JSON_ARRAY('TRASPARENZA'), TRUE, COALESCE(u.created_at, NOW())
FROM papuntozero.users u
JOIN papuntozero.mig_utenti mu ON mu.user_id = u.id AND mu.nuovo
JOIN papuntozero.mig_enti m ON m.office_id = u.office_id;

-- Utenti già presenti: ruolo TRASPARENZA se manca
UPDATE users x
JOIN papuntozero.mig_utenti mu ON mu.utente_id = x.id AND NOT mu.nuovo
SET x.ruoli = JSON_ARRAY_APPEND(x.ruoli, '$', 'TRASPARENZA')
WHERE NOT JSON_CONTAINS(x.ruoli, '"TRASPARENZA"');

-- Controllo del tipo prima di copiare i documenti
SELECT tipo, COUNT(*) FROM (
  SELECT CASE
    WHEN d.html_content LIKE '%DI VALIDAZIONE DEI DATI E DELLE INFORMAZIONI DA PUBBLICARE%' THEN 'VERBALE'
    WHEN JSON_VALID(d.dati_schema) OR d.html_content LIKE '%alt="Logo ente"%' THEN 'SCHEDA'
    ELSE 'ANALISI' END AS tipo
  FROM papuntozero.user_documents d) t
GROUP BY tipo;

-- Documenti
INSERT INTO trasparenza_documenti (id, ente_id, utente_id, tipo, schema_id, descrizione,
                                   html, esito, dati_schema, created_at, updated_at)
SELECT UUID(), m.ente_id, mu.utente_id,
       CASE
         WHEN d.html_content LIKE '%DI VALIDAZIONE DEI DATI E DELLE INFORMAZIONI DA PUBBLICARE%' THEN 'VERBALE'
         WHEN JSON_VALID(d.dati_schema) OR d.html_content LIKE '%alt="Logo ente"%' THEN 'SCHEDA'
         ELSE 'ANALISI'
       END,
       CASE WHEN JSON_VALID(d.dati_schema)
            THEN LEFT(JSON_UNQUOTE(JSON_EXTRACT(d.dati_schema, '$.pdf_type')), 50) END,
       LEFT(COALESCE(NULLIF(TRIM(d.description), ''), CONCAT('Documento ', d.id)), 255),
       COALESCE(d.html_content, ''),
       d.esito,
       CASE WHEN JSON_VALID(d.dati_schema) THEN CAST(d.dati_schema AS JSON) END,
       COALESCE(d.created_at, NOW()),
       COALESCE(d.updated_at, d.created_at, NOW())
FROM papuntozero.user_documents d
JOIN papuntozero.mig_utenti mu ON mu.user_id = d.user_id
JOIN papuntozero.users u ON u.id = d.user_id
JOIN papuntozero.mig_enti m ON m.office_id = u.office_id;

-- Poi le immagini del logo (§6)
```

Le INSERT non si possono rilanciare: `UUID()` genera id nuovi a ogni esecuzione e i documenti
verrebbero duplicati. Se qualcosa va storto, cancella e ripeti:
- i documenti degli enti migrati (`DELETE FROM trasparenza_documenti WHERE ente_id IN (...)`);
- gli utenti con `mig_utenti.nuovo`.

## 8. Verifiche

- **Conteggi:** utenti e documenti per ente uguali a quelli di partenza, meno gli esclusi
  voluti.
- **Accesso:** un utente migrato entra dal dominio dell'ente con la sua vecchia password e
  vede la voce **Trasparenza**.
- **Documenti:** in **Risultati** l'elenco mostra i documenti con le date originali. Una
  scheda si apre con il logo visibile e, se aveva i dati del form, "Modifica i dati della
  scheda" riapre il form compilato.
- **Esportazione:** PDF e DOCX di una scheda e di un verbale contengono il logo.
- **Amministratore:** l'admin dell'ente vede i documenti di tutti gli utenti.
- **Analisi:** un'analisi di prova restituisce un report coerente con il tipo di ente (§3).
- **Pulizia finale:** elimina lo schema `papuntozero`, o almeno le tabelle `mig_*`.
