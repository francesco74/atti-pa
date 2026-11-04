# Modulo Anticorruzione — analisi di Si.Ge.Ri.Co. e piano di integrazione

Stato: **backend, pacchetto standard e app fatti** (passi 1-4: strutture organizzative, metodologia, mappatura e valutazione, proposte, monitoraggio, riepilogo e allegati al PTPCT, processi standard in `pacchetto/anticorruzione` da rivedere: vedi [processi_standard.md](processi_standard.md)); resta il passo 5 (collegamenti con gli altri moduli, sospeso). Decisioni al §7; quelle del 04/11/2026 (proposte per elemento, procedimenti, codici, niente PIAO) dalla 13.
del 29/10/2026, v1.4). Si.Ge.Ri.Co. = Sistema Gestione Rischi Corruttivi, nato per il Comune di
Lucca.

## 1. Cosa fa oggi

Gestisce la **mappatura dei processi** e la **gestione del rischio corruttivo** del PTPCT/PIAO.

| Funzione | Contenuto |
|---|---|
| **Mappatura** | gerarchia Processo → Attività → Rischio (evento rischioso) → Misura; processo con area di rischio, responsabilità (U.O.), tempi, attori esterni; attività con strutture coinvolte |
| **Valutazione del rischio** | 9 indicatori di probabilità e 4 di impatto (Basso/Medio/Alto), moda dei valori, matrice → livello (Minimo, Basso, Medio, Critico, Alto), fattore abilitante (8 predefiniti) |
| **Proposte** | gli utenti non amministratori non modificano: propongono la creazione, modifica o eliminazione di un processo intero (JSON con attività, rischi, misure, valutazioni); l'amministratore approva, respinge o restituisce |
| **Monitoraggio delle misure** | per annualità: ogni U.O. dichiara lo stato di attuazione delle proprie misure (attuata, parzialmente, non attuata, con motivazione, indicatore, target, evidenze); il RPCT verifica o contesta; la dichiarazione conserva una copia dei dati della misura; cruscotto per U.O. e confronto tra anni; esportazione Excel |
| **Obiettivi di performance** | importati da Excel del Piano della performance; collegati alle U.O. (derivate dal centro del Piano: "STAFF B" → U.O. B.*) e associati a processi, attività, rischi o misure, con propagazione ai sottoelementi |
| **Backup annuale** | copia del file SQLite per annualità, con l'atto di approvazione del PIAO e l'MD5 |
| **Report** | totali e distribuzione per livello di rischio; **esportazione Excel per l'allegato al PTPCT** |
| **Log** | registro delle azioni |

### Componenti

- `app.py` (3.240 righe, Flask con pagine Jinja + Bootstrap), `models.py` (13 modelli),
  `indicatori_config.py`, `import_data.py` (caricamento dai CSV iniziali), 51 template.
- Da scartare: `app_old*.py`, `app old *.py`, `models_old.py`, `import_data_old.py`,
  `fix_encoding.py`, `venv/`, `backups/`.
- Dati di Lucca nel file `instance/risk_management.db`: 130 processi, 437 attività, 252 rischi,
  258 misure, 259 valutazioni, 21 proposte, 4 utenti (hash scrypt di Werkzeug, già accettati
  da atti-pa), 4 obiettivi, 28 associazioni.

### Specificità di Lucca nel codice

- `CENTRI_RESPONSABILITA`: le 33 U.O. del Comune di Lucca scritte nel codice.
- `AREE_DESCRIZIONI`: aree di rischio del PNA più alcune del Comune (es. "EXL").
- Logo `stemma_lucca.png`; derivazione delle U.O. dal centro del Piano basata sulla loro
  nomenclatura ("STAFF B", "SETTORE 5").

## 2. Come entra in atti-pa

Stesso backend, stessa app Flutter, stesso database: modulo `anticorruzione`, attivabile per
ente con `enti.py moduli CODICE ...,anticorruzione`. Tutto diventa **per ente**.

| Aspetto | Si.Ge.Ri.Co. | Nel sistema integrato |
|---|---|---|
| Interfaccia | pagine Jinja + Bootstrap | **app Flutter**, voce di menu "Anticorruzione" con le sue schede, stile del resto dell'app (Material, sfondo con il logo dell'ente) |
| Chiamate | form HTML e redirect | API JSON `/api/v1/anticorruzione/...` |
| Enti | uno solo (Lucca) | `ente_id` su tutte le tabelle |
| Identificativi | codici come chiave (`A.1.1_R.1_M.1`) | chiave tecnica (UUID) + **codice** unico per ente, modificabile; l'ordinamento naturale dei codici resta |
| U.O. (centri di responsabilità) | lista fissa nel codice | **strutture organizzative dell'ente** in una tabella del nucleo, gestite da Amministrazione, con gerarchia (settore → U.O.); servono anche agli altri moduli |
| Aree di rischio | dizionario nel codice | elenco per ente, inizializzato con le aree del PNA |
| Indicatori, fattori, matrice | nel codice | file di configurazione del modulo (metodologia PNA, uguale per tutti come gli schemi ANAC); eventuali personalizzazioni per ente in un secondo momento. Ordine dei livelli e parità della moda come nel PIAO (§7) |
| Dati di partenza | CSV di Lucca caricati con `import_data.py` | **processi standard nel pacchetto** (`pacchetto/processi/`), ricavati dai dati di Lucca senza le specificità del Comune; l'ente li importa da Amministrazione → Pacchetti come modelli e checklist e poi li adatta (§6) |
| Utenti e ruoli | `is_admin` + `centro_responsabilita` | utenti dell'ente (locali o AD); ruoli nuovi (§4) e **struttura dell'utente** |
| Proposte | JSON del processo intero | stesso meccanismo (è il cuore del flusso), con l'editor nell'app |
| Backup | copia del file SQLite | **per ora non si porta** (il backup del database è compito dell'installazione); eventuali versioni annuali della mappatura in un secondo momento |
| Log | tabella propria | `audit_log` comune |
| Excel | pandas | openpyxl (già nell'API); i `.xls` vecchi si convertono con il converter |

### Collegamenti con gli altri moduli (il valore aggiunto)

Processi, rischi e misure entrano nel **catalogo comune** (architettura.md §3). Primi
collegamenti possibili, da fare dopo il porting:
- **redazione/controllo**: tipologia di atto ↔ processo, così i controlli delle checklist
  richiamano le misure del processo (es. rotazione, conflitto di interessi);
- **trasparenza**: misura di trasparenza ↔ obbligo di pubblicazione (schema ANAC);
- **IA**: proposte di rischi e misure per un processo nuovo, controllo di coerenza tra rischio
  e misure (con il client LLM comune).

## 3. Tabelle nuove

Nel nucleo: `strutture` (`ente_id`, `codice`, `descrizione`, `padre_id`, `attiva`, `ordine`) e
`users.struttura_id`.

Nel modulo (prefisso `ac_`): `ac_aree`, `ac_processi`, `ac_attivita`, `ac_rischi`,
`ac_misure`, `ac_valutazioni`, `ac_proposte`, `ac_monitoraggi`, `ac_obiettivi`,
`ac_obiettivi_strutture`, `ac_associazioni_obiettivo`.

## 4. Ruoli

| Ruolo | Può |
|---|---|
| `ANTICORRUZIONE_REFERENTE` (referente / dirigente) | consultare la mappatura; fare proposte sugli elementi della propria struttura (decisione 14); compilare il monitoraggio delle misure della propria struttura |
| `ANTICORRUZIONE_RPCT` (RPCT e staff) | tutto il precedente; modifiche dirette; approvare, respingere, restituire le proposte; verificare o contestare il monitoraggio; esportazioni |
| `ADMIN` | tutto, come negli altri moduli |

## 5. Organizzazione

```
common/anticorruzione/   metodologia (indicatori, fattori, matrice), pacchetto standard, Excel
api/src/routers/anticorruzione.py
frontend/src/lib/ui/anticorruzione/   schede: Mappatura, Proposte, Monitoraggio, Riepilogo
api/src/routers/pubblico.py            mappatura pubblica, senza accesso (decisione 18)
frontend/src/lib/ui/pubblico/          pagina /pubblico/mappatura
```

## 6. Piano

1. **Nucleo**: strutture organizzative (tabella, API, pagina in Amministrazione), struttura
   dell'utente, modulo e ruoli nuovi.
2. **Backend del modulo**: modelli, mappatura con valutazione, proposte, monitoraggio,
   obiettivi, esportazione PTPCT; test.
3. **Processi standard**: script che ricava dai dati di Lucca i file del pacchetto
   (`pacchetto/processi/*.yaml`: processo con area di rischio, attività, rischi, misure e
   valutazione proposta), togliendo le U.O. e gli altri riferimenti al Comune; revisione dei
   contenuti; importazione con il meccanismo dei pacchetti (standard + versione dell'ente,
   aggiornamenti scelti dall'ente).
4. **App**: le schede, partendo da mappatura e valutazione.
5. Collegamenti con gli altri moduli (§2).

## 7. Decisioni

Riferimento: PIAO 2026-2028 del Comune di Lucca (`docs/Allegato_1_PIAO.pdf`), sottosezione 2.3
"Rischi corruttivi e trasparenza", §§ 2.3-2.7 (metodologia dell'Allegato 1 al PNA 2019).

1. **Matrice del rischio**: resta quella del PIAO (§ 2.5), che Si.Ge.Ri.Co. riporta
   correttamente. "Critico" è il livello **sotto** "Alto": dal più basso Minimo, Basso, Medio,
   Critico, Alto. Nel codice originale mancava solo l'ordine dei livelli (serve per
   ordinare, filtrare e colorare).

   | Probabilità \ Impatto | Basso | Medio | Alto |
   |---|---|---|---|
   | **Alto** | Medio | Critico | Alto |
   | **Medio** | Basso | Medio | Critico |
   | **Basso** | Minimo | Basso | Medio |

2. **Parità nella moda**: vince il valore più alto, come prevede il PIAO (§ 2.5, nota 6:
   "si preferisce, salvo motivata indicazione, quello più alto"); il codice originale faceva
   vincere il primo valore incontrato. La "motivata indicazione" diventa una correzione
   manuale del valore finale con la motivazione obbligatoria.
3. **Metodologia per ente**: indicatori, scala, fattori abilitanti, matrice ed etichette dei
   livelli sono quelli che ogni ente adotta nel proprio PIAO. Lo standard (PNA 2019 come nel
   PIAO di Lucca) va nel pacchetto; l'ente può adattarlo.
4. **Strutture**: l'organigramma del PIAO (§ 1.4) conferma due livelli: Staff A/B e Settori
   1-8, articolati in U.O.; gli obiettivi di performance sono assegnati a Staff e Settori
   (`PERF_ORG_SETTORE 2`, `PERF_ORG_STAFF B`) e da lì passano alle loro U.O. (è la
   "derivazione" di Si.Ge.Ri.Co., che con la gerarchia diventa generale).
5. ~~**Obiettivi di performance**~~ (superata dalla 16): legati al PIAO dell'ente (sottosezione 2.2), quindi per ente
   e mai nel pacchetto standard.
6. **Misure**: il PIAO distingue misure **generali** (§ 3: trasparenza, codice di
   comportamento, rotazione, conflitto di interessi, incarichi extra-istituzionali,
   inconferibilità, pantouflage, commissioni, whistleblowing, formazione, patti di integrità,
   sensibilizzazione) e **specifiche** (§ 4: controlli interni, tempi dei procedimenti,
   antiriciclaggio...). Le misure che richiedono atti nel triennio hanno fasi, tempi e ufficio
   responsabile (Allegato 2 al PTPCT): campi da aggiungere alla misura. Le misure generali sono
   un catalogo standard, da collegare ai controlli delle checklist (conflitto di interessi,
   pantouflage, rotazione).
7. **Backup**: per ora non si porta.
8. **Dati di Lucca**: non si importano; servono a definire i processi standard del pacchetto.
9. ~~**Propagazione degli obiettivi**~~ (superata dalla 16): anche ai sottoelementi creati dopo l'associazione
   (attività, rischi e misure nuovi ereditano gli obiettivi del padre).
10. ~~**Associazione degli obiettivi**~~ (superata dalla 16): per ora aperta a tutti gli utenti del modulo.
11. **Struttura dei contenuti**: Processo → Attività → Rischio → Misura (con l'area sopra e il
    procedimento accanto al processo: decisione 13). I rischi
    caratterizzano le attività, le misure (anticorruttive e di trasparenza) mitigano i rischi.
    Processi, attività, rischi e misure sono **standardizzabili** (pacchetto). Le misure di
    trasparenza si collegano agli obblighi di pubblicazione (schemi ANAC del modulo trasparenza).
12. ~~**Obiettivi**~~ (superata dalla 16): specifici dell'ente e del suo **PIAO** (raggruppati per PIAO: anno o
    triennio, atto di approvazione). A un obiettivo si collegano **processi e attività**; un
    processo collegato porta con sé tutte le sue attività, rischi e misure, anche quelli
    aggiunti dopo (la propagazione si calcola, non si copia).

Decisioni del 04/11/2026:

13. **Gerarchia**: area → processo o procedimento → attività → rischio (con la valutazione) →
    misura, ciascuno uno a molti. Il **procedimento** sta allo stesso livello del processo: è un
    processo con `tipo = PROCEDIMENTO` e due campi in più, termine di conclusione e norma di
    riferimento. Così attività, rischi, misure, monitoraggio ed esportazioni valgono per
    entrambi; nella mappatura si distinguono e si filtrano.
14. **Profili e proposte**: due profili, RPCT (con il suo staff) e referente, uno per dirigente.
    Il referente propone su un **singolo elemento**: nuova area, nuovo processo o procedimento,
    nuova attività, nuova analisi del rischio, nuova misura, e la modifica o l'eliminazione di
    ciascuno (una rivalutazione è la modifica di un rischio). Una creazione può portare con sé
    gli elementi sottostanti (es. un'attività con i suoi rischi e misure), così non servono
    approvazioni in sequenza. Il RPCT approva, respinge o restituisce ogni proposta; approvando,
    la mappatura si aggiorna con le stesse operazioni delle modifiche dirette. Se l'elemento è
    cambiato dopo la proposta, l'approvazione chiede conferma; se è sparito, non si approva.
    Nell'app il referente usa gli stessi pulsanti del RPCT, con le etichette "Proponi...". La
    proposta va al RPCT appena creata (non ci sono bozze); finché il RPCT non decide, il
    referente la ritrova nella scheda Proposte, dove la corregge, la completa o la ritira. Una
    proposta restituita, corretta e salvata, torna da sola al RPCT.
15. **Struttura del referente**: propone solo sui processi della propria struttura (dal
    profilo utente) e delle sottostanti, perché il referente rappresenta il dirigente e i
    processi possono essere assegnati alle U.O. del settore. Senza struttura nel profilo non
    propone; i processi trasversali restano al RPCT; le aree, che non hanno struttura, le può
    proporre ogni referente. La struttura la assegna l'amministratore (Amministrazione →
    Utenti); l'utente che non ce l'ha la può scegliere da sé, **una sola volta**, in "Il mio
    profilo" tra quelle attive: dopo, per cambiarla, serve l'amministratore, perché da lei
    dipendono proposte e monitoraggio.
16. **PIAO e obiettivi**: tolti dal modulo (tabelle, importazione, collegamenti, monitoraggio,
    scheda). Il monitoraggio riguarda solo le misure.
17. **Codici**: li assegna solo il sistema, alla creazione (per le proposte all'approvazione):
    aree con lettere (A, B... Z, AA), processi e procedimenti `<area>.<n>` (`P.<n>` senza
    area), attività `<processo>.<n>`, rischi `<attività>_R.<n>`, misure `<rischio>_M.<n>`. Per
    ogni prefisso il numero è il successivo al più alto mai assegnato (tabella
    `ac_contatori`), quindi un codice non si riusa nemmeno dopo un'eliminazione; i codici del
    pacchetto standard contano come assegnati. Il codice resta anche se l'elemento cambia
    area. Limite noto: un aggiornamento del pacchetto standard che aggiunge un elemento con un
    codice già assegnato dall'ente a un proprio elemento lo abbinerebbe a quello (il pacchetto
    abbina per codice).
18. **Mappatura pubblica** (4/11/2026): la mappatura è consultabile dai cittadini, senza
    accesso, su `https://<dominio dell'ente>/pubblico/mappatura`: una pagina a sé della stessa
    app (non incorporata in un iframe: le regole di nginx restano quelle dell'app) a cui il
    sito dell'ente rimanda con un link. Stessa navigazione della scheda Mappatura (aree →
    processi e procedimenti → attività → rischi e misure), con la ricerca e i filtri, in sola
    lettura. La pubblica il RPCT con l'interruttore nella scheda Mappatura
    (`enti.mappatura_pubblica`, spento di default; `PUT /api/v1/anticorruzione/pubblicazione`,
    registrato nell'audit), che dà anche il link da copiare. Le API pubbliche
    (`/api/v1/pubblico/mappatura`, `.../processi`, `.../processi/<id>`, `/api/v1/pubblico/logo`)
    riconoscono l'ente dal dominio e rispondono 404 se il modulo non è attivo o la mappatura
    non è pubblicata. Si pubblica un **dettaglio ridotto**: per i rischi evento, fattore
    abilitante e livello; per le misure descrizione, tipo, categoria, obbligo di
    pubblicazione, fasi, tempi, struttura, indicatore e target; per le strutture solo codice e
    descrizione. Restano riservati i valori degli indicatori, probabilità e impatto, le
    correzioni con la loro motivazione, l'origine dal pacchetto e le date di aggiornamento.
19. **Notifiche email delle proposte** (4/11/2026): quando un referente invia una proposta, o
    la reinvia corretta dopo una restituzione, gli utenti dell'ente con ruolo
    `ANTICORRUZIONE_RPCT` che hanno un indirizzo ricevono un'email (chi propone e la sua
    struttura, cosa, dove nella mappatura, la nota, il link all'app sul dominio dell'ente).
    Quando il RPCT approva, respinge o restituisce, l'esito con la motivazione va al referente
    autore. Correggere una proposta ancora in attesa non notifica di nuovo. Le email partono dal
    server SMTP dell'ente (Amministrazione → Posta in uscita); senza posta configurata o senza
    indirizzo del destinatario non si invia nulla e la proposta funziona come prima. L'API le
    mette in coda (`notifiche_email`) nella stessa transazione della proposta e il worker le
    invia entro un minuto, riprovando se il server non risponde (`common/posta.py`).
