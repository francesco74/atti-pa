# Sistema integrato di supporto al RPCT — Architettura (Fase 2)

Data: 27/10/2026, aggiornata il 28/10/2026.

## Stato

| Passo | Stato |
|---|---|
| 1. Nucleo multi ente in atti-pa | **fatto**: enti e domini, accesso locale e Active Directory per ente (configurazione nel database), enti gestiti solo da riga di comando (`deploy/enti.py`: domini, moduli, utente `admin` creato con l'ente e password iniziale da cambiare al primo accesso), login sempre attivo anche in locale (domini `*.localhost`), dati di atti-pa separati per ente, blocco dopo tentativi falliti, hash delle password di rag e PApuntozeroIA accettati, app con accesso per ente, menu per modulo, amministrazione di accesso e utenti dell'ente. La riorganizzazione delle cartelle in `nucleo/` e `moduli/` è rinviata a quando arriva il secondo modulo. Permessi: per ora i ruoli di atti-pa; il modello a permessi di rag si introduce con il modulo chat |
| 2. Client LLM e converter unici | **fatto con la trasparenza**: client LLM comune con JSON a schema libero e testo lungo; converter con HTML → PDF/DOCX e testo in Markdown via HTTP; i PDF all'LLM come file restano da decidere con il modulo chat |
| 3. Modulo trasparenza | **backend e app fatti** (vedi `trasparenza.md`): catalogo, schede, documenti, verbale, esportazione, analisi ed estrazioni nel worker; app con le schede Analisi, Schede e Risultati (riprese da PApuntozeroIA); resta la migrazione dei dati |
| 4. Modulo chat | da fare |
| 5. Modulo anticorruzione | **backend, pacchetto standard e app fatti** (vedi `anticorruzione.md`, da Si.Ge.Ri.Co.): strutture organizzative nel nucleo, mappatura con valutazione, proposte, monitoraggio, PIAO e obiettivi, allegati al PTPCT; restano i collegamenti con gli altri moduli |

Decisioni prese: dati di rag e PApuntozeroIA conservati e migrati; accesso agli archivi
configurabile nel database; installazione multi ente con accesso locale e AD; repository
atti-pa; chat con un frontend configurabile; ordine trasparenza → chat; motore della chat
portato com'è; un dominio di quarto livello per ente (Provincia: `attipa.provincia.lucca.it`)
con un certificato per ente; un solo database; tutto (moduli, MySQL, RabbitMQ e in futuro
Qdrant e Redis della chat) nel namespace Kubernetes `attipa`.

Decisioni già prese:
- i dati in esercizio di rag e PApuntozeroIA si **conservano**, con un piano di migrazione;
- l'accesso ai documenti resta **configurabile nel database** (archivi pubblici o riservati);
- l'installazione è **multi ente** (Provincia di Lucca, Comune di Lucca, Greenlees/BiblioLucca...),
  con accessi **locali** e tramite **Active Directory**;
- il repository è **atti-pa**;
- la chat ha **un solo frontend configurabile**, non un'app per ente.

## 1. Visione d'insieme

```
                    Ingress (un host per ente o uno comune)
                 ┌──────────────┴──────────────┐
          app web unica                    API unica (Flask)
   (personale: menu per modulo;      nucleo + blueprint dei moduli attivi
    cittadini: chat pubblica)                    │
                                                 │
     ┌────────────┬──────────────┬───────────────┼──────────────┬──────────────┐
  NUCLEO       REDAZIONE        CHAT          TRASPARENZA     ANTICORRUZIONE
  enti, utenti, (atti-pa)       (rag)         (PApuntozeroIA)  (in arrivo)
  accessi, catalogo,
  LLM, conversione,
  pacchetti, audit
     │
  servizi: MySQL · RabbitMQ · Qdrant (chat) · Redis (cache chat) · converter ·
           worker verifiche · worker chat · ingest · estrattore Sicr@Web · sync Normattiva
```

Un modulo è **attivabile a due livelli**:
1. **installazione**: `MODULI_ATTIVI=redazione,chat,trasparenza` → l'API registra solo quei
   blueprint, kustomize installa solo i loro servizi (un *component* per modulo);
2. **ente**: ogni ente abilita i moduli che usa (es. Greenlees solo la chat), dal database.

## 2. Multi ente

**Ente** è il contenitore di tutto: utenti, archivi, modelli, checklist, schemi, configurazione.

| Tabella | Contenuto |
|---|---|
| `enti` | codice, nome, logo, dati (oggi `impostazioni_ente` di atti-pa e `offices` di PApuntozeroIA), moduli abilitati, domini (host) |
| `enti_accesso` | modi di accesso dell'ente: `LOCALE` e/o `LDAP` (URL, dominio, base DN, certificato CA, mappatura gruppi AD → ruoli). Più enti possono avere AD diversi |
| `utenti` | ente, username, nome, email, origine (`LOCALE`/`LDAP`), hash della password (solo locali), stato, `token_version` per revocare le sessioni |
| `utenti_ruoli` | ruoli dell'utente nell'ente, per modulo |
| `archivi` (ex `topics`) | ente, codice, descrizione, **accesso pubblico/riservato**, prompt, configurazione della chat |
| `archivi_utenti` | archivi assegnati agli utenti riservati (ex `review_user_topics`) |

Ogni tabella dei moduli riceve `ente_id`; ogni richiesta lavora sull'ente dell'utente
(o, per la chat pubblica, sull'ente dell'archivio). Gli enti (domini e moduli attivi)
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

**Permessi**: si adotta il modello di rag (endpoint e app controllano **permessi**, mai nomi di
ruolo; i ruoli sono insiemi di permessi), esteso a tutti i moduli:
`redazione.*`, `controllo.*`, `modelli.*`, `chat.revisione.*`, `trasparenza.*`,
`anticorruzione.*`, `ente.amministrazione`.

## 3. Catalogo comune

Gestito dal nucleo, per ente, con il meccanismo dei **pacchetti** già fatto in atti-pa
(standard + versione dell'ente, analisi a tre vie, editor):

| Voce | Da dove arriva | Usata da |
|---|---|---|
| tipologie di atto | atti-pa | redazione, chat (metadati), trasparenza |
| norme (Normattiva + manuali) | atti-pa | tutti |
| modelli, specificità, checklist | atti-pa | redazione, controllo |
| obblighi di pubblicazione (schemi ANAC per articolo) | PApuntozeroIA `schemi/ART_*.yaml` | trasparenza, redazione (es. "questo atto va pubblicato in art. 23") |
| processi, fasi, rischi, misure | modulo anticorruzione | checklist, redazione, trasparenza |
| archivi e dizionario dei concetti | rag | chat |

I collegamenti tra voci (es. controllo di checklist ↔ misura anticorruttiva ↔ obbligo di
pubblicazione) sono il valore aggiunto del sistema integrato e si costruiscono qui.

## 4. Servizi comuni (unificati)

| Servizio | Oggi | Domani |
|---|---|---|
| Client LLM | 3 implementazioni | uno solo nel nucleo: provider ollama/vLLM/OpenAI/Gemini/Anthropic/Mistral, uscita strutturata (JSON schema), retry, registro dei consumi; **modello scelto per funzione e per ente** (OCR, chat, grader, verifiche, trasparenza), così il materiale non pubblico può restare on-premise |
| Embedding | rag | nel nucleo (Gemini o locali) |
| Conversione | LibreOffice (atti-pa), PyMuPDF+OCR (rag), subprocess+pandoc (PApuntozeroIA) | un solo servizio `converter`: formati d'ufficio → PDF, PDF → Markdown con OCR di riserva, HTML → PDF/DOCX |
| Lettura di pagine web | Playwright (PApuntozeroIA) | servizio a parte `navigatore`, solo se il modulo trasparenza è attivo (è pesante e va isolato) |
| Code | RabbitMQ + Celery/Redis | RabbitMQ per tutto; per la chat si valuta se tenere Celery all'inizio e sostituirlo poi |
| Database | 3 stili | SQLAlchemy async ovunque; schema unico con prefisso per modulo |
| Configurazione | 3 stili | pydantic-settings: variabili d'installazione; tutto ciò che è per ente nel database |
| Log e audit | 3 stili | log del nucleo, audit unico (`audit_log`) |

## 5. Frontend

**Un'unica app Flutter** con due ingressi:

1. **area del personale**: accesso (ente → locale o AD), menu con i moduli abilitati per l'ente
   e consentiti dai permessi: Redazione, Controllo, Modelli e checklist, Chat, Revisione dei
   documenti, Trasparenza, Anticorruzione, Amministrazione;
2. **chat pubblica configurabile**: indirizzo del tipo `/chat/<ente>/<archivio>` (o il dominio
   dell'ente). All'avvio chiede la configurazione all'API (`GET /api/v1/chat/<ente>/<archivio>`)
   e si presenta di conseguenza: nome, logo, icona, colori, testo di benvenuto (con l'elenco
   delle serie), lingue, filtri, archivi selezionabili, accesso facoltativo per i documenti
   riservati. Le due app attuali (Provincia e Greenlees) differiscono **solo** in questo:
   diventano due righe di configurazione nel database, modificabili dall'amministratore
   dell'ente senza ricompilare nulla.

La chiave condivisa della chat (oggi visibile nel browser) sparisce: la chat pubblica è
pubblica per configurazione dell'archivio, quella riservata usa la sessione dell'utente.

## 6. Struttura del repository (atti-pa)

```
nucleo/            libreria comune (ex common/): enti, utenti, accessi, permessi, catalogo,
                   pacchetti, LLM, embedding, conversione, code, db, log
moduli/
  redazione/       redazione, controllo, modelli e checklist (oggi api/src/routers + parti di common)
  chat/            motore RAG, revisione, file, archivi (da rag)
  trasparenza/     schemi, analisi, verbale di validazione (da PApuntozeroIA)
  anticorruzione/  (in arrivo)
servizi/
  api/             un'unica API: registra i blueprint dei moduli attivi
  converter/  worker/  chat-worker/  ingest/  estrattore/  normattiva-sync/  navigatore/
frontend/          un'unica app Flutter (area personale + chat pubblica)
pacchetto/         contenuti standard (modelli, checklist, schemi trasparenza, processi...)
deploy/k8s/        base + un component kustomize per modulo
migrazione/        script di migrazione dei dati da rag e PApuntozeroIA
manuale/
```

## 7. Migrazione dei dati

Principio: **i sistemi attuali restano in funzione** finché il nuovo non è verificato; la
migrazione si può ripetere da zero quante volte serve.

| Origine | Destinazione | Note |
|---|---|---|
| rag `topics`, `sub_topics` | `archivi` (+ serie) con l'ente | `public_access` → accesso pubblico/riservato |
| rag `parent_documents`, metriche, feedback, log | tabelle del modulo chat | stessi identificativi, così gli indici Qdrant restano validi |
| rag Qdrant | **riusato così com'è** | nessun ricalcolo degli embedding; l'ente si ricava dall'archivio |
| rag `review_users`, ruoli, archivi | `utenti` locali, `utenti_ruoli`, `archivi_utenti` | hash delle password conservati |
| rag `review_status/locks/audit` | tabelle del modulo chat | |
| rag file in `/data/processed` | stesso volume | nessuno spostamento |
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
4. **Modulo chat** (il più grande e in esercizio): archivi e accessi nel nucleo, revisione e
   file come blueprint, motore RAG e ingest come servizi, chat pubblica configurabile;
   migrazione di MySQL con Qdrant riusato; periodo in parallelo, poi passaggio.
5. **Modulo anticorruzione** con processi, rischi e misure nel catalogo e i collegamenti a
   checklist e obblighi di trasparenza.
6. Dismissione di rag e PApuntozeroIA.

## 9. Scelte su cui serve il tuo parere

1. **Ordine**: trasparenza prima della chat (meno rischio) o il contrario?
2. **Motore della chat**: all'inizio lo porto quasi com'è (Celery/Redis, accesso al DB attuale
   dentro un adattatore) e lo modernizzo dopo, oppure lo riscrivo subito sul nucleo?
   Consiglio la prima: è in esercizio e funziona.
3. **Ente dall'host o dal percorso**: ogni ente con il suo dominio (es.
   `attipa.provincia.lucca.it`, `archivio.greenlees.it`) o un dominio unico con scelta
   dell'ente? Si possono avere entrambi.
4. **Un solo database** MySQL per tutti gli enti (con `ente_id`, consigliato) o un database per ente?
