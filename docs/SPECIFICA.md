# Specifica tecnica — atti-pa

## 1. Obiettivo

Due strumenti, una base comune:

1. **Redazione (uso personale)** — schema guidato per la stesura delle determinazioni dirigenziali, con riferimenti normativi estratti da Normattiva e verificati alla data di adozione. Non è un sistema di gestione atti: niente workflow, protocollo o firma.
2. **Controllo (gruppo controllo atti)** — verifica della qualità degli atti sorteggiati per il controllo successivo di regolarità amministrativa (art. 147-bis TUEL), con checklist e supporto LLM.

La base comune è composta da:

- **Libreria normativa**: norme e articoli scaricati da Normattiva, versionati per intervallo di vigenza.
- **Checklist**: criteri di qualità per tipologia di atto, versionati, usati sia in redazione sia in controllo.

## 2. Stack

| Livello | Tecnologia |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, httpx |
| Database | MySQL 8.0+ |
| Documenti | py3o.template / odfpy, LibreOffice headless (ODT → PDF/A) |
| LLM | On-premise (vLLM o Ollama) via LiteLLM, output JSON vincolato da schema |
| Fonti | API OpenData Normattiva |
| Frontend | Flutter (Web/Desktop) |
| Auth | LDAP/AD (ldap3) + JWT — necessaria per il modulo Controllo |

## 3. Integrazione Normattiva

Base URL esercizio: `https://api.normattiva.it/t/normattiva.api` (test: `https://pre.api.normattiva.it/t/normattiva.api`).

| Uso | Endpoint |
|---|---|
| Testo di un articolo a una data | `POST /bff-opendata/v1/api/v1/atto/dettaglio-atto-urn` con URN `...~artN!vig=YYYY-MM-DD` |
| Atti modificati in un intervallo | `POST /bff-opendata/v1/api/v1/ricerca/aggiornati` |
| Ricerca atti | `POST /bff-opendata/v1/api/v1/ricerca/semplice` / `avanzata` |
| Export massivo (ZIP AKN/JSON) | flusso asincrono `ricerca-asincrona/nuova-ricerca` → `conferma-ricerca` → `check-status` |

Regole:

- **Chiave**: URN NIR (es. `urn:nir:stato:decreto.legislativo:2023-03-31;36~art50`).
- **Granularità**: l'API restituisce l'articolo in HTML con classi AKN; il backend lo scompone in **commi e lettere** (`app/normattiva/parser.py`).
- **Vigenza**: ogni versione di articolo è salvata con `articoloDataInizioVigenza` / `articoloDataFineVigenza`. Un atto si verifica rispetto alla norma **vigente alla data di adozione**, non a oggi.
- **Aggiornamento**: un job giornaliero interroga `ricerca/aggiornati` e riscarica solo le norme presenti in libreria che risultano modificate; segnala i template che citano testi cambiati.
- **Risultati multipli**: se la URN restituisce una lista (es. ripubblicazioni in GU), si sceglie il testo principale o si chiede all'utente.
- **Rinvii**: i link `urn:nir` presenti nel testo vengono estratti per suggerire norme collegate.
- **Attribuzione**: i dati sono IPZS in licenza CC BY 4.0; la fonte va citata.

## 4. Uso dell'LLM

- Modello on-premise, servito da vLLM/Ollama; il backend lo chiama tramite LiteLLM.
- L'LLM **non cita norme a memoria**: riceve nel prompt il testo vigente dei commi pertinenti.
- I riferimenti normativi nell'atto sono estratti in modo **deterministico** (regex + normalizzazione in URN); l'LLM valuta pertinenza e qualità.
- Checklist valutate **un elemento (o pochi) per chiamata**, con output JSON vincolato da schema: `{esito: CONFORME|NON_CONFORME|NON_APPLICABILE|DUBBIO, motivazione, evidenza}`.
- Ogni esito automatico è una proposta: il controllore conferma o modifica con motivazione.

## 5. Modulo Redazione

1. Scelta tipologia (affidamento diretto, impegno, liquidazione, ...).
2. Wizard per sezioni: premesse, "visto" normativi (dalla libreria), "considerato", dispositivo.
3. Controllo in tempo reale: segnaposto non compilati, riferimenti non vigenti alla data prevista di adozione, autovalutazione con la checklist della tipologia.
4. Generazione ODT dal template; esportazione PDF ed eventuale versione con omissis.

## 6. Modulo Controllo

1. **Sessione di controllo**: periodo, criteri e percentuale di sorteggio.
2. **Caricamento atti** sorteggiati (PDF/ODT dal gestionale dell'ente), estrazione testo.
3. **Assegnazione** a un controllore.
4. **Analisi automatica**: riferimenti normativi (vigenza alla data di adozione), checklist con LLM, dati personali da oscurare.
5. **Revisione umana** ed esito finale motivato.
6. **Report** di sessione aggregato per settore e criterio.

## 7. Ruoli

| Ruolo | Permessi |
|---|---|
| `REDATTORE` | Proprie bozze, libreria normativa in lettura |
| `CONTROLLORE` | Sessioni e atti assegnati, revisione esiti |
| `ADMIN` | Template, checklist, sessioni, libreria normativa |

I ruoli derivano dai **gruppi AD** al login (nessuna password salvata). In uso solo personale l'autenticazione può essere disattivata (`AUTH_ENABLED=false`).

## 8. Sicurezza

- LDAPS obbligatorio, escape dell'input, timeout.
- JWT a breve scadenza; su Flutter Web cookie httpOnly invece di storage locale.
- Audit log delle modifiche su bozze ed esiti di controllo.

## 9. Roadmap

1. ✅ Client Normattiva, URN, parser commi/lettere.
2. Cache MySQL delle versioni normative + job di aggiornamento.
3. Libreria riferimenti e API di consultazione.
4. Checklist versionate (CRUD).
5. Estrazione deterministica dei riferimenti da un testo di atto.
6. Integrazione LLM on-premise per la valutazione delle checklist.
7. Modulo Controllo: sessioni, caricamento atti, revisione, report.
8. Modulo Redazione: template ODT, wizard, generazione documenti.
9. Auth LDAP/JWT e frontend Flutter.
