# Sistema integrato di supporto al RPCT — Architettura (Fase 2)

Data: 27/10/2026, aggiornata il 30/10/2026.

## Stato

| Passo | Stato |
|---|---|
| 1. Nucleo multi ente in atti-pa | **fatto**: enti e domini, accesso locale e Active Directory per ente (configurazione nel database), enti gestiti solo da riga di comando (`deploy/enti.py`: domini, moduli, utente `admin` creato con l'ente e password iniziale da cambiare al primo accesso), login sempre attivo anche in locale (domini `*.localhost`), dati di atti-pa separati per ente, blocco dopo tentativi falliti, hash delle password di rag e PApuntozeroIA accettati, app con accesso per ente, menu per modulo, amministrazione di accesso e utenti dell'ente. La riorganizzazione delle cartelle in `nucleo/` e `moduli/` è rinviata a quando arriva il secondo modulo. Permessi: per ora i ruoli di atti-pa |
| 2. Client LLM e converter unici | **fatto con la trasparenza**: client LLM comune con JSON a schema libero e testo lungo; converter con HTML → PDF/DOCX e testo in Markdown via HTTP |
| 3. Modulo trasparenza | **backend e app fatti** (vedi `trasparenza.md`): catalogo, schede, documenti, verbale, esportazione, analisi ed estrazioni nel worker; app con le schede Analisi, Schede e Risultati (riprese da PApuntozeroIA); resta la migrazione dei dati |
| Modulo assistente | **fatto**: chat con l'LLM configurato per il lavoro quotidiano (email, riassunti, riformulazioni), per tutti gli utenti dell'ente. Non legge atti né norme (per quello c'è il chatbot RAG, sezione 9). Le conversazioni restano in memoria nell'app, non sul server; con un LLM esterno la chat si apre con un avviso. Documenti allegati (pdf, docx, odt, xlsx, ods, txt, md, immagini) convertiti in testo dal RAG dell'ente (sezione 9), al massimo `ASSISTENTE_MAX_CARATTERI` per conversazione: un documento più lungo si rifiuta, non si tronca |
| 4. Modulo anticorruzione | **backend, pacchetto standard e app fatti** (vedi `anticorruzione.md`, da Si.Ge.Ri.Co.): strutture organizzative nel nucleo, mappatura (aree, processi e procedimenti, attività, rischi con valutazione, misure; codici assegnati dal sistema) con valutazione, proposte dei referenti per singolo elemento limitate alla propria struttura, monitoraggio delle misure, allegati al PTPCT; PIAO e obiettivi tolti il 04/11/2026; restano i collegamenti con gli altri moduli |
| 5. Modulo performance | **backend e app fatti** (vedi `performance.md`): PIAO triennali aperti e chiusi dall'amministratore della performance, obiettivi annuali per struttura dichiarati da dirigenti e responsabili, azioni e misure (dalla mappatura dei rischi) con impegno, completamento e scadenza, completamento calcolato, storico delle modifiche, riepilogo per struttura |

Decisioni prese: dati di PApuntozeroIA conservati e migrati; installazione multi ente con
accesso locale e AD; repository atti-pa; un dominio di quarto livello per ente (Provincia:
`attipa.provincia.lucca.it`) con un certificato per ente; un solo database; tutto (moduli,
MySQL, RabbitMQ) nel namespace Kubernetes `attipa`.

**Decisione del 30/10/2026**: l'assistente IA sugli atti (chatbot e motore RAG, progetto `rag`)
**resta fuori da questo repository** e si sviluppa in parallelo: vedi la sezione 9. Sostituisce
il piano iniziale di portarlo qui come modulo.

## 1. Visione d'insieme

```
                    Ingress (un host per ente o uno comune)
                 ┌──────────────┴──────────────┐
          app web unica                    API unica (Flask)
        (menu per modulo)            nucleo + blueprint dei moduli attivi
                                                 │
     ┌────────────┬──────────────┬───────────────┴───┐
  NUCLEO       REDAZIONE     TRASPARENZA     ANTICORRUZIONE
  enti, utenti, (atti-pa)    (PApuntozeroIA)  (Si.Ge.Ri.Co.)
  accessi, catalogo,
  LLM, conversione,
  pacchetti, audit
     │
  servizi: MySQL · RabbitMQ · converter · worker verifiche · estrattore Sicr@Web · sync Normattiva

  progetto collegato (via API): assistente IA sugli atti, motore RAG (progetto `rag`)
```

Un modulo è **attivabile a due livelli**:
1. **installazione**: `MODULI_ATTIVI=redazione,trasparenza,anticorruzione` → l'API registra solo quei
   blueprint, kustomize installa solo i loro servizi (un *component* per modulo);
2. **ente**: ogni ente abilita i moduli che usa (es. Greenlees solo la trasparenza), dal database.

## 2. Multi ente

**Ente** è il contenitore di tutto: utenti, modelli, checklist, schemi, configurazione.

| Tabella | Contenuto |
|---|---|
| `enti` | codice, nome, logo, dati (oggi `impostazioni_ente` di atti-pa e `offices` di PApuntozeroIA), moduli abilitati, domini (host) |
| `enti_accesso` | modi di accesso dell'ente: `LOCALE` e/o `LDAP` (URL, dominio, base DN, certificato CA, mappatura gruppi AD → ruoli). Più enti possono avere AD diversi |
| `utenti` | ente, username, nome, email, origine (`LOCALE`/`LDAP`), hash della password (solo locali), stato, `token_version` per revocare le sessioni |
| `utenti_ruoli` | ruoli dell'utente nell'ente, per modulo |

Ogni tabella dei moduli riceve `ente_id`; ogni richiesta lavora sull'ente dell'utente.
Gli enti (domini e moduli attivi)
si gestiscono con `deploy/enti.py` nel container, senza interfaccia web; l'**amministratore di
ente** gestisce utenti, accessi e configurazione del suo ente.

**Come si individua l'ente**: dall'host (ogni ente può avere il suo dominio, registrato in
`enti`); se l'host è comune, la pagina di accesso chiede l'ente.

**Accesso**:
- utenti AD: login con le credenziali di dominio sull'AD **dell'ente**, ruoli dai gruppi
  (come atti-pa oggi, ma con la configurazione LDAP nel database invece che nelle variabili
  d'ambiente);
- utenti locali: password con hash. Si accettano gli hash esistenti (Werkzeug di rag, bcrypt di
  PApuntozeroIA) e si riconvertono al primo accesso, così **nessuno deve cambiare password**;
- sessione unica (JWT in cookie HttpOnly) valida per tutti i moduli; revoca con `token_version`.

**Permessi**: per ora i ruoli per modulo. Resta possibile passare a un modello a permessi
(endpoint e app controllano **permessi**, mai nomi di ruolo; i ruoli sono insiemi di permessi):
`redazione.*`, `controllo.*`, `modelli.*`, `trasparenza.*`, `anticorruzione.*`,
`ente.amministrazione`.

## 3. Catalogo comune

Gestito dal nucleo, per ente, con il meccanismo dei **pacchetti** già fatto in atti-pa
(standard + versione dell'ente, analisi a tre vie, editor):

| Voce | Da dove arriva | Usata da |
|---|---|---|
| tipologie di atto | atti-pa | redazione, trasparenza |
| norme (Normattiva + manuali) | atti-pa | tutti |
| modelli, specificità, checklist | atti-pa | redazione, controllo |
| obblighi di pubblicazione (schemi ANAC per articolo) | PApuntozeroIA `schemi/ART_*.yaml` | trasparenza, redazione (es. "questo atto va pubblicato in art. 23") |
| processi, fasi, rischi, misure | modulo anticorruzione | checklist, redazione, trasparenza |

I collegamenti tra voci (es. controllo di checklist ↔ misura anticorruttiva ↔ obbligo di
pubblicazione) sono il valore aggiunto del sistema integrato e si costruiscono qui.

## 4. Servizi comuni (unificati)

| Servizio | Oggi | Domani |
|---|---|---|
| Client LLM | 2 implementazioni | uno solo nel nucleo: provider ollama/vLLM/OpenAI/Gemini/Anthropic/Mistral, uscita strutturata (JSON schema), retry, registro dei consumi; **modello scelto per funzione e per ente** (verifiche, trasparenza), così il materiale non pubblico può restare on-premise |
| Conversione | LibreOffice (atti-pa), subprocess+pandoc (PApuntozeroIA) | un solo servizio `converter`: formati d'ufficio → PDF, PDF → Markdown con OCR di riserva, HTML → PDF/DOCX |
| Lettura di pagine web | Playwright (PApuntozeroIA) | servizio a parte `navigatore`, solo se il modulo trasparenza è attivo (è pesante e va isolato) |
| Code | RabbitMQ | RabbitMQ per tutto |
| Database | 2 stili | SQLAlchemy async ovunque; schema unico con prefisso per modulo |
| Configurazione | 2 stili | pydantic-settings: variabili d'installazione; tutto ciò che è per ente nel database |
| Log e audit | 2 stili | log del nucleo, audit unico (`audit_log`) |
| Email | nessuna | posta in uscita **per ente** (server SMTP in Amministrazione → Posta in uscita, password cifrata con `CHIAVE_CIFRATURA`); l'API mette le email in coda nella tabella `notifiche_email` nella stessa transazione dell'operazione, il worker le invia a ogni giro di manutenzione con nuovi tentativi ad attese crescenti (`common/posta.py`, `POSTA_*`) |

## 5. Frontend

**Un'unica app Flutter** per il personale: accesso (ente → locale o AD), menu con i moduli
abilitati per l'ente e consentiti dai ruoli: Redazione, Controllo, Modelli e checklist,
Trasparenza, Anticorruzione, Amministrazione.

## 6. Struttura del repository (atti-pa)

```
nucleo/            libreria comune (ex common/): enti, utenti, accessi, permessi, catalogo,
                   pacchetti, LLM, embedding, conversione, code, db, log
moduli/
  redazione/       redazione, controllo, modelli e checklist (oggi api/src/routers + parti di common)
  trasparenza/     schemi, analisi, verbale di validazione (da PApuntozeroIA)
  anticorruzione/  mappatura, proposte, monitoraggio (da Si.Ge.Ri.Co.)
  performance/     PIAO, obiettivi delle strutture con azioni e misure
servizi/
  api/             un'unica API: registra i blueprint dei moduli attivi
  converter/  worker/  estrattore/  normattiva-sync/  navigatore/
frontend/          un'unica app Flutter
pacchetto/         contenuti standard (modelli, checklist, schemi trasparenza, processi...)
deploy/k8s/        base + un component kustomize per modulo
migrazione/        script di migrazione dei dati da PApuntozeroIA
manuale/
```

## 7. Migrazione dei dati

Principio: **i sistemi attuali restano in funzione** finché il nuovo non è verificato; la
migrazione si può ripetere da zero quante volte serve.

| Origine | Destinazione | Note |
|---|---|---|
| PApuntozeroIA `offices` | `enti` | logo e caratteristiche nei dati dell'ente |
| PApuntozeroIA `users` | `utenti` locali | hash bcrypt conservati |
| PApuntozeroIA `user_documents` | documenti del modulo trasparenza | |
| atti-pa | aggiunta di `ente_id` = Provincia di Lucca | in sviluppo, nessun vincolo |

Per ogni migrazione: script idempotente, rapporto dei conteggi (origine/destinazione),
prova su una copia del database, poi esecuzione in esercizio con i vecchi sistemi in sola
lettura, verifica, passaggio del DNS/Ingress, spegnimento dei vecchi servizi.

## 8. Piano a passi

Ogni passo si chiude con il sistema funzionante, i test verdi e un commit.

1. **Nucleo multi ente** in atti-pa: enti, accessi locali + LDAP per ente, permessi, sessione
   unica, `ente_id` sulle tabelle di atti-pa, ristrutturazione in `nucleo/` + `moduli/redazione`.
   Frontend: accesso con scelta dell'ente, menu per modulo, amministrazione di enti e utenti.
2. **Servizi comuni**: client LLM unico (unendo le capacità di quello di rag), converter
   unico.
3. **Modulo trasparenza** (il più piccolo, ~12.000 righe): schemi nel catalogo/pacchetti,
   rotte come blueprint, schermate nell'app; migrazione di enti, utenti e documenti; servizio
   `navigatore`.
4. **Modulo anticorruzione** con processi, rischi e misure nel catalogo e i collegamenti a
   checklist e obblighi di trasparenza.
5. Dismissione di PApuntozeroIA.

## 9. Progetti collegati

L'**assistente IA sugli atti** (chatbot e motore RAG, `github.com/francesco74/rag`, in esercizio
nel namespace `rag`) è un progetto a sé: si sviluppa e si rilascia in parallelo e non entra in
questo repository, né con il codice né con i dati.

Il legame è **tramite API**: atti-pa usa le API esposte dal progetto RAG. Per esempio il controllo
degli atti acquisirà gli atti da lì. Se un'API manca, **si realizza nel progetto RAG**, non qui.

**Autenticazione**: le API del RAG sono autenticate con delle credenziali, e sono le **credenziali
a determinare i topic id** accessibili: una credenziale può dare accesso a più topic id. Anche la lettura delle **scansioni senza testo** passa da un'apposita API del RAG,
con la stessa autenticazione.

**Configurazione**: il collegamento al RAG (indirizzo del servizio e credenziali) sta nella
configurazione di ogni singolo ente, nel database, non nelle variabili d'ambiente. I topic id
non si configurano qui: dipendono dalle credenziali.

**Fatto** (client in `common/rag.py`):
- Amministrazione → *Collegamento al RAG*: indirizzo dell'API (es. `https://rag.ente.it/api`) e
  chiave in `enti.rag_json`. La chiave è cifrata con `CHIAVE_CIFRATURA` (Secret), non torna mai
  all'app e se il segreto cambia va reinserita. "Prova" elenca i topic consultabili.
- **Conversione dei documenti** (`POST /external/v1/convert`, poi `GET /external/v1/convert/<job_id>`
  finché non è `completed` o `failed`): la usa l'assistente per gli allegati. L'API di atti-pa fa
  da tramite, così la chiave resta sul server; l'app segue lo stato del lavoro. Il RAG converte
  con PyMuPDF dove c'è testo e con l'LLM solo dove ce n'è troppo poco. Cancella il file a
  conversione finita e il risultato appena lo consegna: se la risposta si perde (errore di rete)
  la richiesta successiva riceve 404 e l'assistente chiede di riallegare il documento. atti-pa
  non conserva il testo per riconsegnarlo, per non tenere copie dei documenti.
- **Da fare nel RAG**: i formati docx, odt, xlsx e ods (atti-pa li ammette già).
