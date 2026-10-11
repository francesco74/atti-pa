# Specifica tecnica — atti-pa

## 1. Obiettivo

Due strumenti con una base comune:

1. **Redazione (uso personale)** — schema guidato per la stesura delle determinazioni, con
   riferimenti normativi estratti da Normattiva e verificati alla data di adozione. Non è un
   sistema di gestione atti: niente workflow, protocollo o firma.
2. **Controllo (gruppo controllo atti)** — verifica della qualità degli atti sorteggiati per il
   controllo successivo di regolarità amministrativa (art. 147-bis TUEL).

Base comune: **libreria normativa** versionata per vigenza e **checklist** versionate, usate
sia in redazione sia in controllo.

## 2. Architettura

| Componente | Tipo Kubernetes | Tecnologia |
|---|---|---|
| api | Deployment (2 repliche) | FastAPI, SQLAlchemy async, ldap3, PyJWT |
| verifica-worker | Deployment | Python asyncio, coda su MySQL con `SKIP LOCKED` |
| documenti | Deployment, solo interno | FastAPI + LibreOffice headless |
| normattiva-sync | CronJob (03:30) | Python, client API OpenData |
| db-migrate | initContainer | Migrazioni SQL ordinate con checksum e lock |
| frontend | Deployment | Flutter Web + nginx non privilegiato |

Tutti i file (template, atti caricati) sono salvati nel database: nessun volume condiviso
tra i pod. Configurazione da ConfigMap/Secret (variabili d'ambiente, vedi `atti_common.config`).

## 3. Integrazione Normattiva

Base URL: `https://api.normattiva.it/t/normattiva.api` (test: `pre.api.normattiva.it`).

| Uso | Endpoint |
|---|---|
| Testo di un articolo a una data | `POST /bff-opendata/v1/api/v1/atto/dettaglio-atto-urn`, URN `...~artN!vig=YYYY-MM-DD` |
| Atti modificati in un intervallo | `POST /bff-opendata/v1/api/v1/ricerca/aggiornati` |

- **Chiave**: URN NIR (es. `urn:nir:stato:decreto.legislativo:2023-03-31;36~art50`); le
  citazioni con il solo anno (`D.Lgs. 36/2023`) sono risolte sulla libreria o su Normattiva.
- **Granularità**: l'HTML AKN dell'articolo è scomposto in commi e lettere; le note di
  aggiornamento sono escluse.
- **Vigenza**: ogni versione è salvata con l'intervallo `articoloDataInizioVigenza`–
  `articoloDataFineVigenza`. Gli atti si verificano alla **data di adozione**.
- **Aggiornamento**: il CronJob legge gli atti modificati dall'ultima esecuzione riuscita e
  riscarica solo gli articoli monitorati (in libreria o già scaricati). Un'esecuzione con
  errori non fa avanzare l'intervallo.
- **Risultati multipli** (ripubblicazioni in GU): si sceglie il testo principale, altrimenti
  si segnala la necessità di verifica manuale.

## 4. Verifica di un atto

Deterministica (immediata, anche nel "controllo rapido" del wizard):

- **riferimenti normativi**: estrazione delle citazioni (forme estese e abbreviate, più
  articoli, TUEL), vigenza alla data, esistenza di comma e lettera, avviso se il testo è
  cambiato nell'ultimo anno;
- **segnaposto** non compilati (`{{campo}}` o `[[campo]]`);
- **dati personali** da valutare per la pubblicazione (CF, IBAN, salute, condizione
  economica, ecc.), con generazione del documento con omissis.

Con LLM on-premise (asincrona, nel worker):

- un elemento di checklist per chiamata, con il testo vigente delle norme indicate
  nell'elemento; output JSON vincolato `{esito, motivazione, evidenza, suggerimento}`,
  esito ∈ CONFORME | NON_CONFORME | NON_APPLICABILE | DUBBIO;
- risposta non valida → un nuovo tentativo; errore del modello → l'elemento risulta ERRORE
  ma le verifiche deterministiche restano disponibili.

## 5. Ruoli e sicurezza

| Ruolo (gruppo AD) | Permessi |
|---|---|
| `REDATTORE` | Proprie bozze (isolamento per proprietario), libreria, riferimenti personali |
| `CONTROLLORE` | Sessioni di controllo, atti, revisione, report |
| `ADMIN` | Checklist, template, riferimenti condivisi, stato aggiornamenti; tutti i ruoli |

- Login: BIND LDAPS con `utente@dominio`; rifiuto di password vuote (bind anonimo) e di
  username con caratteri non ammessi; filtri LDAP con escape.
- Sessione: JWT HS256 in cookie httpOnly `SameSite=Strict` (web) o header Bearer (desktop).
- `AUTH_ENABLED=false`: uso personale senza Active Directory, con un utente locale.
- Audit di accessi, modifiche, documenti generati, revisioni.
- Kubernetes: Pod Security `restricted`, utenti non root, filesystem in sola lettura,
  NetworkPolicy (il servizio documenti accetta connessioni solo dall'API).

## 6. API principali

| Area | Endpoint |
|---|---|
| Autenticazione | `POST /api/v1/auth/login`, `POST /logout`, `GET /me` |
| Libreria | `GET/POST /api/v1/norme`, `GET /api/v1/norme/articolo?urn=&data=`, `GET/POST/DELETE /api/v1/riferimenti`, `GET /api/v1/norme/aggiornamenti` |
| Checklist | `GET/POST /api/v1/checklists`, `PUT/DELETE /api/v1/checklists/codice/{codice}` |
| Template | `GET/POST /api/v1/templates`, `PUT /{id}/campi`, `GET /{id}/file` |
| Redazione | `GET/POST/PUT/DELETE /api/v1/bozze`, `GET /{id}/controllo-rapido`, `GET /{id}/documento?formato=odt|pdf|pdfa&omissis=`, `POST /api/v1/bozze/espandi` |
| Verifiche | `POST /api/v1/verifiche`, `GET /api/v1/verifiche/{id}`, `PUT /{id}/revisione` |
| Controllo | `/api/v1/controllo/sessioni` (+ `/sorteggio`, `/atti`, `/report`, `/report.csv`, `/chiudi`), `/api/v1/controllo/atti/{id}` (+ `/testo`, `/file`, `/assegna`) |

Documentazione interattiva: `/docs` sull'API.

## 7. Limiti noti e sviluppi

- PDF scansionati: non gestiti (serve il PDF nativo o l'originale); un OCR on-premise è un
  possibile sviluppo.
- Gruppi AD annidati: si considerano solo i gruppi diretti (`memberOf`).
- Il dimensionamento del worker dipende dalla capacità del server LLM.
