# Sistema integrato di supporto al RPCT — Ricognizione dei progetti esistenti (Fase 1)

Data: 27/10/2026. Documento di lavoro: descrive lo stato attuale dei tre progetti che diventeranno
moduli del sistema, cosa hanno in comune e dove si duplicano. Non contiene ancora decisioni:
quelle sono la Fase 2.

## 1. I quattro moduli previsti (dalla relazione alla Direzione)

| Modulo | Progetto attuale | Stato |
|---|---|---|
| Assistente IA sugli atti (chatbot) | `francesco74/rag` | in esercizio (namespace `rag`) |
| Assistente alla redazione e al controllo | `atti-pa` | in sviluppo |
| Verifica di Amministrazione Trasparente | `private_zone/PApuntozeroIA` | immagini 1.1.0, in uso |
| Mappatura dei processi / anticorruzione | (in arrivo) | — |

Elemento chiave della relazione: un **catalogo comune** (tipologie di atto, processi, rischi,
misure, obblighi di pubblicazione) condiviso da tutti i moduli.

## 2. Dimensioni

| Progetto | Codice (py/dart) | Backend | Frontend |
|---|---|---|---|
| rag | ~27.000 righe | 6 servizi Python | 3 app Flutter (chat ente, chat Greenlees, revisione) |
| PApuntozeroIA | ~12.000 righe | 1 API Flask (app.py di 2.100 righe) | 1 app Flutter |
| atti-pa | ~35.000 righe | API, worker, converter, sync Normattiva | 1 app Flutter |

## 3. Scheda per progetto

### 3.1 rag — Assistente IA sugli atti

- **Cosa fa**: chat RAG sugli atti dell'ente (e su un archivio Greenlees), con citazione delle
  fonti; applicazione di **revisione** dei testi letti dall'OCR e dei metadati; download
  controllato dei file originali (archivi pubblici o riservati).
- **Acquisizione**: estrattore SOAP da Sicr@Web (con sbustamento .p7m), cartella di caricamento
  diretto, converter (PyMuPDF + OCR **Gemini Vision**, riserva Google Cloud Vision), ingest
  parent/child con embedding in **Qdrant** e documenti padre in MySQL.
- **Risposta**: API Flask → coda **Celery su Redis** → worker (riscrittura della domanda,
  dizionario dei concetti, ricerca ibrida, reranker ONNX locale, grader, cache semantica).
- **Code**: RabbitMQ (`da-convertire`, `da-indicizzare`) per l'acquisizione; Celery/Redis per la chat.
- **Database**: MySQL con `mysql-connector-python` (sincrono, SQL scritto a mano): topic,
  documenti padre, metriche, log, utenti e permessi della revisione, blocchi, storico.
- **Accesso**: chat protetta da una chiave condivisa (`API_SECRET_KEY`) che però è scritta nella
  configurazione del browser, quindi di fatto pubblica; revisione con **utenti locali**
  (password con hash, token `itsdangerous`, cookie `rag_session`), **permessi** granulari
  (`documenti.lettura/testo/metadati/stato`, `utenti.gestione`, `topic.tutti`) e archivi assegnati.
- **LLM**: astrazione propria (`llm_provider.py`: Gemini, OpenAI/vLLM, Anthropic, Mistral, Ollama),
  embedding Gemini o locali (bge-m3).
- **Installazione**: Dockerfile per servizio; manifest Kubernetes non nel repository; nginx
  "gateway" nel namespace `rag` che smista per host e percorso; Python 3.11.

### 3.2 PApuntozeroIA — Verifica di Amministrazione Trasparente

- **Cosa fa**: analisi con l'IA di pagine e documenti di Amministrazione Trasparente (da URL,
  con scraping anche via browser headless **Playwright**, o da file caricati); **schemi di
  pubblicazione** ANAC per articolo del D.Lgs. 33/2013 (`schemi/ART_*.yaml`, delibera ANAC
  495/2024) con form guidato, estrazione dei dati da una fonte, validazione, generazione del
  documento e del **verbale di validazione**; esportazione HTML → PDF/DOCX (pandoc); archivio dei
  documenti dell'utente.
- **Backend**: un'unica API Flask (`app.py`), PyMySQL, `google.generativeai` (SDK Gemini
  precedente), LibreOffice via `subprocess` per convertire i documenti, pandas/openpyxl/odfpy
  per i fogli di calcolo.
- **Accesso**: **utenti locali** (bcrypt) con **JWT** (Flask-JWT-Extended), collegati a un
  **ufficio/ente** (`offices`, con logo e "caratteristiche dell'amministrazione"): il prodotto
  è pensato anche per più enti.
- **Database**: 3 tabelle (`offices`, `users`, `user_documents`).
- **Installazione**: docker compose (nginx, phpMyAdmin, frontend, backend, MySQL).

### 3.3 atti-pa — Assistente alla redazione e al controllo

- **Cosa fa**: redazione guidata delle determine da modelli (con specificità), libreria
  normativa da Normattiva verificata alla data dell'atto, verifica con checklist su tre livelli,
  controllo successivo con verbale, editor di modelli e checklist, pacchetti di configurazione.
- **Backend**: Flask su ciclo async, **SQLAlchemy async** (aiomysql), pydantic-settings,
  **RabbitMQ** (aio-pika), verifica-worker, converter LibreOffice → Markdown, sync Normattiva.
- **Accesso**: **Active Directory** (LDAPS), ruoli dai gruppi AD, JWT in cookie HttpOnly.
- **LLM**: client proprio (Ollama, OpenAI-compatibile/vLLM, OpenAI, Gemini, Anthropic).
- **Installazione**: kustomize in `deploy/k8s`, MySQL e RabbitMQ nel namespace, registry interno,
  Python 3.12.

## 4. Cosa è duplicato (opportunità di unificazione)

| Funzione | rag | PApuntozeroIA | atti-pa | Proposta di massima |
|---|---|---|---|---|
| Autenticazione | utenti locali + itsdangerous | utenti locali + JWT | **AD + JWT** | un solo accesso con AD per il personale; utenti locali solo dove serve (es. altri enti) |
| Ruoli/permessi | **permessi granulari + archivi** | nessuno (utente/ufficio) | ruoli da gruppi AD | modello unico: ruoli per modulo → permessi; archivi come "ambito" |
| Dati dell'ente | topic | `offices` (logo, caratteristiche) | impostazioni ente | anagrafica ente unica |
| Client LLM | `llm_provider.py` | `google.generativeai` | `common/llm.py` | un solo client con tutti i provider, scelta per funzione (OCR, chat, verifica) |
| Conversione/OCR | PyMuPDF + Gemini Vision | LibreOffice via subprocess, pandoc, Playwright | LibreOffice → Markdown | un solo servizio di conversione (formati d'ufficio, PDF, OCR, HTML→PDF/DOCX) |
| Accesso al DB | mysql-connector, SQL a mano | PyMySQL | SQLAlchemy async | SQLAlchemy per tutti, schema unico con tabelle per modulo |
| Code | RabbitMQ + Celery/Redis | — | RabbitMQ | RabbitMQ comune (Celery/Redis da valutare per la chat) |
| Configurazione | dataclass da `os.environ` | `.env` | pydantic-settings | pydantic-settings, una sezione per modulo |
| Frontend | 3 app Flutter | 1 app Flutter | 1 app Flutter | **una sola app** per il personale con menu per modulo + chat pubblica separata |
| Installazione | Dockerfile + nginx gateway | docker compose | kustomize | kustomize con un componente per modulo, un solo Ingress |
| Python | 3.11 | (non indicato) | 3.12 | 3.12 per tutti |

## 5. Il catalogo comune

Oggi esiste solo a pezzi:

- **tipologie di atto**: atti-pa (`tipologie_atto`);
- **obblighi di pubblicazione**: PApuntozeroIA (`schemi/ART_*.yaml`, uno per articolo del
  D.Lgs. 33/2013, con campi e regole);
- **processi, rischi, misure**: arriveranno con il quarto modulo;
- **norme**: libreria normativa di atti-pa (Normattiva + norme manuali), utile anche agli altri;
- **archivi di atti**: topic di rag.

È il punto in cui l'integrazione porta più valore: una checklist di atti-pa può richiamare una
misura anticorruttiva o un obbligo di pubblicazione; la verifica di Trasparenza può partire
dall'atto redatto; la chat può indicizzare gli atti adottati.

## 6. Osservazioni da sistemare comunque

1. **Chiavi in chiaro nel repository**: `private_zone/PApuntozeroIA/docker/docker-compose-local.yaml`
   contiene chiavi API Google e il segreto JWT in chiaro. Il repository è privato, ma le chiavi
   vanno **revocate e rigenerate** e tolte dalla storia git.
2. **Chiave della chat nel browser**: in rag la `API_SECRET_KEY` della chat è scritta nella
   configurazione dell'app web, quindi chiunque la legge. Va bene solo se la chat è
   volutamente pubblica; per il personale serve l'accesso con AD.
3. **Sovranità dei dati**: la relazione dice che bozze e dati da pubblicare restano nell'ente.
   Oggi rag (OCR, embedding, chat) e PApuntozeroIA usano Gemini. Nel sistema integrato il
   provider va scelto **per funzione**, con on-premise per i dati non pubblici.

## 7. Domande per la Fase 2

1. **Dati in esercizio**: rag è in uso con indici Qdrant, documenti e utenti della revisione;
   PApuntozeroIA ha documenti salvati dagli utenti. Vanno conservati e migrati?
2. **Chat pubblica**: resta un punto di accesso separato, senza login, per i cittadini (con il
   personale che accede con AD)? E l'archivio **Greenlees** fa parte del sistema o è un cliente
   separato?
3. **Più enti**: PApuntozeroIA ha gli "uffici/enti". Il sistema integrato serve solo la
   Provincia o anche altri enti (ognuno con i propri utenti e dati)?
4. **Repository**: nuovo repository "cappello" (nome?) oppure atti-pa diventa il contenitore?
5. **Quarto modulo**: quando arriva, stessa ricognizione; intanto si può preparare il posto nel
   catalogo comune (processi, rischi, misure).
