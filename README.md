# atti-pa

Strumenti di supporto alla **redazione** e al **controllo** delle determinazioni dirigenziali
degli enti locali, pensati per girare su Kubernetes all'interno della rete dell'ente.

| Modulo        | Utenti                    | Cosa fa                                                                                                                                                                   |
| ------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Redazione** | redattori (uso personale) | Wizard guidato su template ODT, riferimenti normativi presi da Normattiva e verificati alla data di adozione, controllo rapido, documento ODT/PDF/PDF-A anche con omissis |
| **Controllo** | gruppo controllo atti | Controllo successivo (art. 147-bis TUEL) di singoli atti: per ogni controllo l'atto, la data di adozione e l'audit (verifica dei riferimenti e della loro coerenza, checklist, revisione del controllore). Il sorteggio del campione avviene fuori dal programma |

Principi:

- **Normattiva è la fonte di verità**: i testi normativi sono scaricati dalle API OpenData e
  conservati per intervallo di vigenza; ogni atto è verificato rispetto alle norme vigenti
  alla sua data di adozione.
- **LLM a scelta, on-premise per default**: con Ollama o un server compatibile OpenAI
  (vLLM, llama.cpp) nessun dato esce dall'ente. In configurazione si può scegliere un
  servizio esterno (OpenAI ChatGPT, Google Gemini, Anthropic Claude): in quel caso il testo
  degli atti, dati personali compresi, viene inviato al fornitore. Il modello valuta un
  criterio di checklist alla volta e riceve nel prompt il testo vigente delle norme: non
  cita norme a memoria.
- **L'IA propone, la persona decide**: gli esiti automatici sono proposte che il controllore
  conferma o modifica con motivazione.
- **Accesso con Active Directory**: login pass-through via LDAPS, ruoli dai gruppi AD,
  nessuna password salvata. Ogni redattore vede solo le proprie bozze.

## Componenti

Ogni componente ha la propria cartella con il `Dockerfile`, il codice in `src/` e il
`requirements.txt` usato per costruire l'immagine (versioni fissate e testate; chi usa la
libreria comune include `../common/requirements.txt`). Le immagini si costruiscono dalla
radice del repository (`docker build -f <componente>/Dockerfile .`).

| Cartella           | In Kubernetes                | Ruolo |
| ------------------ | ---------------------------- | ----- |
| `api/`             | Deployment + Service         | API REST Flask (gunicorn): autenticazione, libreria, redazione, controllo; salva i file caricati nell'archivio |
| `converter/`       | Deployment + Service interno | LibreOffice: servizio HTTP per i PDF/PDF-A delle bozze e consumatore della coda di conversione degli atti in Markdown |
| `verifica-worker/` | Deployment                   | Verifiche dalle code: riferimenti e loro coerenza, dati personali, checklist con LLM |
| `normattiva-sync/` | **CronJob** notturno         | Aggiorna i testi normativi modificati su Normattiva |
| `frontend/`        | Deployment + Service         | App Flutter Web servita da nginx |
| `common/`          | — (libreria)                 | Codice condiviso: modelli, code, archivio, client Normattiva, verifica, LLM, prompt |
| —                  | StatefulSet                  | RabbitMQ: code tra API, converter e worker |
| `deploy/`          | —                            | Manifest Kubernetes (kustomize), schema SQL, checklist, script di manutenzione |

```
               Ingress (atti.ente.local)
              /                        \
        /  frontend                /api  api ──── converter (HTTP: PDF delle bozze)
                                    │     │  \
                                    │     │   └─ Active Directory (LDAPS)
                       archivio file┤     │
                                    │  RabbitMQ ── conversione ──> converter (file -> Markdown)
                                    │     │   <── convertiti ────────┘
                                    │     └──── convertiti, verifica ──> verifica-worker ── LLM
                                    │                                      │
     normattiva-sync (CronJob) ──── MySQL ─────────────────────────────────┤
              └──────────── Normattiva ────────────────────────────────────┘
```

**Flusso di un controllo.** L'API salva il file originale nell'archivio (`ARCHIVIO_DIR`,
volume condiviso con il converter), registra atto e verifica nel database e pubblica un
messaggio sulla coda `conversione`; la risposta all'utente è immediata. Il converter
trasforma il file in Markdown (ODT/DOC/DOCX dall'XML del documento, tabelle comprese; PDF
con PyMuPDF4LLM, senza intestazioni e piè di pagina ripetuti) e pubblica il risultato su
`convertiti`; il worker salva il testo ed esegue la verifica. "Rianalizza" e le verifiche
delle bozze passano dalla coda `verifica`. Lo stato resta nel database: se un messaggio
non parte o si perde, il worker reinvia il lavoro dopo `WORKER_REINVIO_MINUTI`.

## Prova in locale

```bash
docker compose up --build
```

Apre l'applicazione su http://localhost:8080 in modalità uso personale (senza Active
Directory). L'LLM predefinito è Ollama sul computer (`ollama serve`, modello
`mistral-small`); per usare un altro provider:

```bash
LLM_PROVIDER=anthropic LLM_API_KEY=sk-ant-... docker compose up     # Claude
LLM_PROVIDER=openai    LLM_API_KEY=sk-...     docker compose up     # ChatGPT
LLM_PROVIDER=gemini    LLM_API_KEY=...        docker compose up     # Gemini
```

## Scelta del modello linguistico

| `LLM_PROVIDER` | Dove gira | Indirizzo e modello predefiniti | Note |
|---|---|---|---|
| `ollama` (predefinito) | nell'ente | `LLM_OLLAMA_URL` (localhost:11434), `mistral-small` | nessun dato esce |
| `openai_compatibile` | nell'ente | da indicare: `LLM_BASE_URL`, `LLM_MODEL` | vLLM, llama.cpp server... |
| `openai` | OpenAI | `api.openai.com`, `gpt-5-mini` | `LLM_API_KEY` obbligatoria |
| `gemini` | Google | endpoint compatibile OpenAI di Gemini, `gemini-2.5-flash` | `LLM_API_KEY` obbligatoria |
| `anthropic` | Anthropic | SDK ufficiale, `claude-opus-5-5` | chiave in `LLM_API_KEY` o `ANTHROPIC_API_KEY` |

`LLM_MODEL` e `LLM_BASE_URL` sostituiscono i predefiniti. Con Claude gli esiti delle
verifiche usano gli output strutturati (JSON conforme allo schema); `LLM_EFFORT` regola la
profondità del ragionamento (`medium` predefinito) e `LLM_FALLBACK=true` riprova
automaticamente su un altro modello Claude se la richiesta viene rifiutata dai filtri di
sicurezza. Con i servizi esterni l'API e il worker registrano all'avvio un avviso: il
testo degli atti esce dall'ente, va valutato con il responsabile della protezione dei dati.

**Coerenza dei riferimenti normativi.** Nelle verifiche, oltre al controllo formale delle
norme citate (esistenza, vigenza alla data dell'atto, comma e lettera), l'LLM valuta per ogni
riferimento vigente se la norma è pertinente e se i suoi presupposti (soglie, condizioni,
termini) risultano rispettati da quanto scritto nell'atto. Riceve l'atto intero, con le
citazioni marcate, e solo la parte citata della norma; i riferimenti sono inviati a gruppi
di `LLM_COERENZA_GRUPPO` (8). L'esito compare sotto ogni riferimento ed è una proposta da
confermare. Si disattiva con `LLM_COERENZA_RIFERIMENTI=false`.

**Dati personali.** I dati da valutare per la pubblicazione (nomi di persone fisiche,
codici fiscali, IBAN, salute, condizione economica, dati giudiziari, minori...) li rileva il
modello, che dal contesto distingue i privati da imprese, enti e funzionari nell'esercizio
delle funzioni. Un dato è accettato solo se il testo indicato si trova davvero nell'atto,
e ogni sua ripetizione viene oscurata; gli atti lunghi sono divisi in parti
(`LLM_MAX_CARATTERI_ATTO`). Il documento della bozza "con omissis" usa lo stesso
rilevamento: se il modello non risponde il documento non viene prodotto, mai con i dati in
chiaro. Il controllo rapido delle bozze, immediato e senza modello, non li cerca. Si
disattiva con `LLM_DATI_PERSONALI=false`.

I testi dei prompt inviati al modello sono file in `common/prompt/` (descritti nel
README della cartella): si modificano senza toccare il codice e valgono al riavvio. Con
`LLM_PROMPT_DIR` si indica una cartella di prompt personalizzati che sostituiscono quelli
predefiniti con lo stesso nome.

## Sviluppo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "./common[dev]" -e "./api[dev]" -e "./normattiva-sync[dev]" \
  -e "./verifica-worker[dev]" -e "./db-migrate[dev]" -e "./documenti[dev]"

# test (SQLite in memoria; con TEST_DATABASE_URL anche su MySQL migrato)
for c in common api normattiva-sync verifica-worker db-migrate documenti; do (cd $c && pytest -q); done
ruff check . && ruff format --check .
```

Il frontend è descritto in [frontend/README.md](frontend/README.md).

## Configurazione e log

Tutti i componenti, compresa l'app web, si configurano solo con variabili d'ambiente
(ConfigMap e Secret in Kubernetes, `environment` in docker compose, `.env` in sviluppo:
vedi `.env.example` e `common/src/common/config.py`).

Il livello dei log si sceglie con `LOG_LEVEL`, uguale per tutti i servizi:

| Livello   | Cosa registra                                                                                                                                                                                             |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DEBUG`   | diagnostica: ogni richiesta HTTP con tempi, chiamate a Normattiva, prompt e risposte dell'LLM (accorciati), bind LDAP e gruppi, passi delle verifiche, conversioni; con `LOG_SQL=true` anche le query SQL |
| `INFO`    | funzionamento normale: avvio, accessi, verifiche prese in carico e completate, aggiornamenti delle norme                                                                                                  |
| `WARNING` | solo anomalie: servizi esterni non raggiungibili, nuovi tentativi, risposte non valide del modello, errori                                                                                                |

Esempio in locale: `LOG_LEVEL=DEBUG docker compose up`.

API e servizio documenti sono applicazioni **Flask** servite da **gunicorn** (worker a
thread); processi, thread, porta e timeout si impostano con le variabili `WEB_*` (valori
predefiniti in `*/gunicorn_conf.py`). Davanti a tutto c'è l'Ingress del cluster, condiviso
con altri siti: le impostazioni di atti-pa sono solo annotazioni del suo Ingress
(`deploy/k8s/ingress.yaml`) e `PROXY_HOPS=1` fa fidare l'API delle intestazioni
`X-Forwarded-*` impostate dall'Ingress. Nell'app web lo stesso valore
controlla i messaggi nella console del browser.
La pipeline GitHub Actions esegue test (anche su MySQL 8), compila il frontend e costruisce
tutte le immagini.

## Installazione su Kubernetes

1. Costruire e pubblicare le immagini nel registry dell'ente; aggiornare `images` in
   `deploy/k8s/kustomization.yaml`.
2. Creare il database MySQL 8 e lo schema:
   ```bash
   mysql -u root -p -e "CREATE DATABASE atti_pa CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
   mysql -u atti_pa -p atti_pa < deploy/sql/0001_schema_iniziale.sql
   ```
3. Creare i segreti (vedi `deploy/k8s/secret.example.yaml`): `atti-pa-secret`,
   la ConfigMap `ldap-ca` con il certificato della CA di Active Directory e il Secret TLS `atti-pa-tls`.
4. Adattare `deploy/k8s/configmap.yaml` (LDAP, gruppi AD, indirizzo dell'LLM, livello dei log)
   e l'host dell'Ingress.
5. `kubectl apply -k deploy/k8s`

Le modifiche successive allo schema si distribuiscono come nuovi file in `deploy/sql/`
(`0002_...sql`), da eseguire in ordine sul database prima di aggiornare le immagini.

## Fonte dei dati normativi

Dati: Normattiva (https://www.normattiva.it), Istituto Poligrafico e Zecca dello Stato,
licenza CC BY 4.0.

### Regolamenti interni e altre norme non presenti su Normattiva

Dalla Libreria, scheda **Regolamenti e altre norme**, si caricano i regolamenti dell'ente,
le leggi regionali e ogni altra norma citata negli atti che Normattiva non contiene
(PDF, ODT, DOCX o DOC). Per ciascuna si indicano il nome con cui la si cita
("Regolamento di contabilità") e gli altri modi in cui compare negli atti
("deliberazione C.C. n. 12/2018"...).

1. Il file va nell'archivio e il converter lo trasforma in testo, come gli atti da
   controllare; il sistema lo divide in articoli, commi e lettere ("Art. N", "1.", "a)").
2. Si rivede la divisione, si corregge il testo se serve e si **conferma**: da quel
   momento le verifiche lo usano come le norme di Normattiva (esistenza dell'articolo, del
   comma e della lettera, coerenza con l'atto, checklist).
3. Dopo una modifica del regolamento si carica il **nuovo testo** con la data da cui è in
   vigore: il precedente vale fino al giorno prima, così ogni atto è verificato sul testo
   vigente alla sua data di adozione. Una norma abrogata si segna con la data di
   abrogazione.

Negli atti le citazioni sono riconosciute dai nomi indicati; se c'è un modello linguistico,
questo cerca anche le citazioni scritte in altre forme (una chiamata per verifica, solo se
ci sono norme inserite manualmente; `LLM_RICONOSCIMENTO_NORME_MANUALI=false` la disattiva).
Una citazione proposta dal modello è accettata solo se il testo si trova davvero nell'atto
ed è segnalata come da verificare. Inserire e modificare le norme è riservato a
controllori e amministratori. Schema del database: `deploy/sql/0007_norme_manuali.sql`.
