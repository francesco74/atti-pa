# Modulo Trasparenza — analisi di PApuntozeroIA e piano di integrazione

Stato: **backend e app fatti** (passi 1-4); da fare la migrazione dei dati (5). Decisioni al §5. Fonte: `private_zone/PApuntozeroIA`
(commit `ed245a5`, 20/10/2026).

## 1. Cosa fa oggi

PApuntozeroIA aiuta l'ente a pubblicare e verificare i dati di **Amministrazione Trasparente**
secondo gli schemi ANAC (delibere 495/2024, 481/2025, 497/2025). L'app ha tre schede.

| Scheda | Funzione | Endpoint |
|---|---|---|
| **Analisi IA** | verifica con l'LLM una pagina pubblicata (URL) o uno o più file (PDF, DOC/DOCX/ODT, XLS/XLSX/ODS, CSV) rispetto a uno schema o a un suo controllo; produce un report HTML con analisi, livello Open Data, **esito di validazione** (Pubblicabile / Pubblicabile provvisoriamente / Non pubblicabile) e tabella dei rilievi | `POST /ai_analyze` |
| **Generatore** | form guidato costruito dallo schema (parametri, sezioni, campi, elenchi, condizioni di visibilità); validazione dei dati sul server; genera il documento HTML da pubblicare. Il form si può **precompilare** estraendo i dati da una pagina o da documenti con l'LLM (risposta JSON con struttura imposta, normalizzata nei formati dello schema) | `GET /schemi`, `POST /doc_create`, `POST /estrai_dati` |
| **Risultato** | editor HTML (html_editor_enhanced) del report o del documento; salvataggio nell'archivio personale; **verbale di validazione** (modello fisso + documenti scelti); esportazione PDF (LibreOffice) e DOCX (pandoc, con `custom-reference.docx`) | `POST /save_document`, `GET /load_documents`, `POST /load_document`, `POST /delete_document`, `POST /crea_verbale`, `POST /html2pdf`, `POST /html2docx` |

Inoltre: `POST /auth`, `POST /change_password`, `GET /status`.

### Componenti del backend (≈ 3.700 righe Python)

- `app.py` (2.100): endpoint, scraping, chiamate a Gemini, conversioni, archivio documenti.
- `schema_registry.py` (1.070): modello pydantic degli schemi YAML, validazione dei dati,
  generazione del documento HTML e dei **prompt** di audit (anche per sezione).
- `estrazione.py` (360): estrazione strutturata per precompilare il form.
- `security.py` (225): sanificazione HTML (nh3), protezione SSRF (`get_sicuro`, `verifica_url`),
  percorsi sicuri.
- `schemi/ART_*.yaml`: **19 schemi** (artt. 4-bis, 12, 13, 14, 15, 15-bis, 15-ter, 20, 23,
  26-27, 29, 31, 32, 33, 35, 36, 39, 41, 42).
- `templates/SCHEMA`, `templates/VERBALEDIVALIDAZIONE`: HTML con segnaposto `_xxx_`.

### Frontend (≈ 7.100 righe Dart)

Login, tre schede, form dinamico dagli schemi (`schema_form.dart`, 1.000 righe), editor dei
risultati (`result_tab.dart`, 1.580 righe), selettore dello schema, precompilazione da fonte.

### Database

| Tabella | Contenuto |
|---|---|
| `offices` | ente: `name`, `description` (usata nei prompt come nome del cliente), `logo` (percorso di un'immagine in `static/sc`), `authority_features` (caratteristiche dell'amministrazione, testo libero per i prompt) |
| `users` | `username` (unico globale), `password_hash` bcrypt, `description`, `office_id` |
| `user_documents` | documenti salvati, **privati dell'utente**: `description`, `html_content`, `esito`, `dati_schema` (JSON del form, per rigenerare) |

### Uso dell'LLM

Solo Gemini, con l'SDK `google.generativeai` (deprecato). Usa due funzioni specifiche di Gemini:
1. **PDF inviati come file** (multimodale, `upload_file`): il modello legge il PDF con
   l'impaginazione, anche se è una scansione;
2. **output JSON con schema imposto** (`response_schema`) per l'estrazione.

Le chiamate sono **sincrone** nella richiesta HTTP (anche minuti).

## 2. Come entra in atti-pa

Stesso backend (API Flask), stessa app Flutter, stesso database e stessa installazione: il
modulo si chiama `trasparenza` e si attiva per ente con `enti.py moduli CODICE ...,trasparenza`.

| Aspetto | PApuntozeroIA | Nel sistema integrato |
|---|---|---|
| Enti | `offices` | `enti`: il nome dall'ente; logo e caratteristiche dell'amministrazione nei **dati dell'ente** (Amministrazione → Dati dell'ente), usati da tutti i moduli |
| Utenti | locali bcrypt, username unico globale | `users` dell'ente (locali o AD); gli hash bcrypt sono già accettati e rigenerati al login |
| Accesso | JWT in localStorage | cookie HttpOnly, ente dal dominio, ruoli |
| Rotte | `/ai_analyze`, `/doc_create`... | `/api/v1/trasparenza/...`, solo con il modulo attivo |
| Codice | `app.py` unico | `moduli/trasparenza/` (vedi §4): schemi, registro, estrazione, prompt, viste |
| LLM | SDK Gemini | client LLM comune (`common/llm`), quindi qualunque provider configurato |
| Conversioni | `soffice` e `pandoc` nel container dell'API | servizio `converter` già esistente (LibreOffice), con in più HTML → PDF/DOCX |
| Lavori lunghi | sincroni | **in coda** (RabbitMQ) come le verifiche degli atti: l'app crea il lavoro e ne segue lo stato |
| Scraping | `requests` + Playwright nel container dell'API | nel **worker**, che ha il browser; l'immagine dell'API resta leggera |
| Sicurezza | `security.py` | ripreso così com'è (nh3, SSRF) |
| Editor dei risultati | `html_editor_enhanced` (Summernote in un iframe `srcdoc` con script inline) | Summernote servito come pagina statica (`frontend/src/web/editor`), in un iframe della stessa origine con una CSP propria senza script inline; l'app gli parla con `postMessage`. Così la CSP dell'app resta senza `'unsafe-inline'` |
| Documenti salvati | `user_documents` | `trasparenza_documenti` con `ente_id` |

### Tabelle nuove (`deploy/k8s/sql/0002_trasparenza.sql`)

- `trasparenza_documenti`: `id`, `ente_id`, `utente_id`, `tipo` (ANALISI / SCHEDA / VERBALE),
  `schema_id`, `descrizione`, `html`, `esito`, `dati_schema` (JSON), date.
- `trasparenza_lavori`: analisi ed estrazioni in coda (`tipo`, `stato`, richiesta, risultato,
  errore, durata), come `verifiche` per gli atti.
- File caricati per un'analisi: nell'archivio comune (`archivio_dir`), cancellati a lavoro finito.

### Endpoint nuovi

| Metodo e percorso | Sostituisce |
|---|---|
| `GET /api/v1/trasparenza/schemi` | `/schemi` |
| `POST /api/v1/trasparenza/schede` (genera dal form) | `/doc_create` |
| `POST /api/v1/trasparenza/analisi` (URL o file) → lavoro | `/ai_analyze` |
| `POST /api/v1/trasparenza/estrazioni` (URL o file) → lavoro | `/estrai_dati` |
| `GET /api/v1/trasparenza/lavori/<id>` | — (stato e risultato) |
| `GET/POST/PUT/DELETE /api/v1/trasparenza/documenti[/<id>]` | `load_documents`, `load_document`, `save_document`, `delete_document` |
| `POST /api/v1/trasparenza/verbale` | `/crea_verbale` |
| `POST /api/v1/trasparenza/esporta?formato=pdf\|docx` | `/html2pdf`, `/html2docx` |

`/auth`, `/change_password` e `/status` sono già nel nucleo.

## 3. Migrazione dei dati di produzione

Script `deploy/migra_trasparenza.py`, da eseguire una volta nel container dell'API, dopo aver
creato gli enti con `enti.py`. Legge il database di PApuntozeroIA (`TRASPARENZA_DATABASE_URL`)
e una tabella di corrispondenza `offices.id → codice ente`.

1. **Enti**: per ogni `office` copia `authority_features` e `description` nei dati dell'ente e
   il logo (dai file di `static/sc`) nel logo dell'ente.
2. **Utenti**: crea l'utente locale nell'ente con lo stesso username e lo stesso hash bcrypt
   (si rigenera al primo login); ruolo di operatore della trasparenza. Se nell'ente esiste
   già un utente con quel nome (es. di Active Directory) lo segnala e collega i documenti a
   quello esistente.
3. **Documenti**: copia `user_documents` in `trasparenza_documenti` mantenendo date, esito e
   dati del form; il tipo si ricava (dati del form → SCHEDA, esito → ANALISI, altrimenti
   VERBALE). L'HTML viene sanificato.
4. Riepilogo finale: enti, utenti creati o collegati, documenti, anomalie. Si può rilanciare
   senza duplicare (`--prova` per vedere cosa farebbe).

Si prova prima su una copia del database di produzione.

## 4. Organizzazione del codice

Con il secondo modulo si separa il nucleo dai moduli (passo a sé, senza cambiare funzioni):

```
nucleo/            (oggi common/ e la parte comune di api/src)
  modelli enti/utenti, accesso, LLM, documenti, coda, archivio, audit
moduli/
  redazione/       redazione e controllo degli atti (oggi il resto di atti-pa)
  trasparenza/
    schemi/ART_*.yaml   registro.py   estrazione.py   sicurezza.py   prompt/
    viste.py (blueprint)   lavori.py (worker)   modelli.py (ORM)
api/               avvio Flask: registra i blueprint dei moduli
worker/            un solo worker per le code di tutti i moduli (con Playwright)
frontend/src/lib/moduli/trasparenza/   pagine dell'app
```

## 5. Decisioni

1. **Ruoli**: nuovo ruolo `TRASPARENZA` (analisi, schede, verbali); ADMIN può tutto.
2. **Documenti salvati**: privati dell'utente; l'amministratore dell'ente li vede tutti.
3. **Schemi ANAC**: catalogo unico nel codice del modulo, uguale per tutti gli enti (le linee
   guida sono nazionali), aggiornato con le versioni; le specificità dell'ente passano dalle
   "caratteristiche dell'amministrazione".
4. **PDF all'LLM**: in sospeso, si decide con il modulo RAG (che ha il suo convertitore dei
   PDF). Nel frattempo i file vanno all'LLM come testo estratto dal converter: funziona con
   tutti i provider, ma le scansioni senza testo non si leggono.
5. **Output JSON con schema imposto**: aggiunto al client LLM comune per i provider che lo
   supportano; per gli altri JSON libero, validato.
6. **Playwright**: resta, nel worker.
7. **DOCX**: con LibreOffice del converter al posto di pandoc; da verificare la resa delle
   tabelle.
