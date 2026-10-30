# Modulo Anticorruzione — analisi di Si.Ge.Ri.Co. e piano di integrazione

Stato: **backend, pacchetto standard e app fatti** (passi 1-4: strutture organizzative, metodologia, mappatura e valutazione, proposte, monitoraggio, PIAO e obiettivi, riepilogo e allegati al PTPCT, processi standard in `pacchetto/anticorruzione` da rivedere: vedi [processi_standard.md](processi_standard.md)); resta il passo 5 (collegamenti con gli altri moduli). Decisioni al §7.
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
| `ANTICORRUZIONE_REFERENTE` | consultare la mappatura; fare proposte; compilare il monitoraggio delle misure della propria struttura; associare obiettivi |
| `ANTICORRUZIONE_RPCT` (RPCT e staff) | tutto il precedente; modifiche dirette; approvare, respingere, restituire le proposte; verificare o contestare il monitoraggio; importare gli obiettivi; esportazioni |
| `ADMIN` | tutto, come negli altri moduli |

## 5. Organizzazione

```
common/anticorruzione/   metodologia.yaml (indicatori, fattori, matrice), valutazione.py,
                         proposte.py, obiettivi.py (import Excel), esportazione.py
api/src/routers/anticorruzione.py
frontend/src/lib/ui/anticorruzione/   schede: Mappatura, Proposte, Monitoraggio, Obiettivi,
                                      Report; dettaglio con valutazione
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
5. **Obiettivi di performance**: legati al PIAO dell'ente (sottosezione 2.2), quindi per ente
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
9. **Propagazione degli obiettivi**: anche ai sottoelementi creati dopo l'associazione
   (attività, rischi e misure nuovi ereditano gli obiettivi del padre).
10. **Associazione degli obiettivi**: per ora aperta a tutti gli utenti del modulo.
11. **Struttura dei contenuti**: Processo → Attività → Rischio → Misura. I rischi
    caratterizzano le attività, le misure (anticorruttive e di trasparenza) mitigano i rischi.
    Processi, attività, rischi e misure sono **standardizzabili** (pacchetto). Le misure di
    trasparenza si collegano agli obblighi di pubblicazione (schemi ANAC del modulo trasparenza).
12. **Obiettivi**: specifici dell'ente e del suo **PIAO** (raggruppati per PIAO: anno o
    triennio, atto di approvazione). A un obiettivo si collegano **processi e attività**; un
    processo collegato porta con sé tutte le sue attività, rischi e misure, anche quelli
    aggiunti dopo (la propagazione si calcola, non si copia).
