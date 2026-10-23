# atti-pa

Strumenti di supporto alla **redazione** e al **controllo** delle determinazioni dirigenziali
degli enti locali, pensati per girare su Kubernetes all'interno della rete dell'ente.

| Modulo        | Utenti                    | Cosa fa                                                                                                                                                                   |
| ------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Redazione** | redattori (uso personale) | Percorso guidato in 4 fasi (intestazione, preambolo e motivazione, dispositivo, chiusura) secondo un modello di atto, riferimenti normativi presi da Normattiva e verificati alla data di adozione, controllo rapido, documento ODT/PDF/PDF-A anche con omissis |
| **Controllo** | gruppo controllo atti | Controllo successivo (art. 147-bis TUEL) di singoli atti: per ogni controllo l'atto, la data di adozione e l'audit (verifica dei riferimenti e della loro coerenza, checklist, revisione del controllore) e il verbale del controllo in PDF, PDF/A o ODT, esportabile anche prima della revisione. Il sorteggio del campione avviene fuori dal programma |

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
| —                  | StatefulSet                  | MySQL 8: database (schema in `deploy/k8s/sql/`, creato al primo avvio) |
| `deploy/`          | —                            | Manifest Kubernetes (kustomize), schema SQL, script del pacchetto e di manutenzione |
| `pacchetto/`       | —                            | Sorgenti del pacchetto standard: modelli di atto, specificità, checklist (da cui si crea lo zip) |
| `manuale/`         | —                            | Manuali d'uso |

```
     Ingress (attipa.provincia.lucca.it)
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

## Modelli di atto

La redazione segue un **modello** per ogni tipo di atto (`pacchetto/modelli/*.yaml`): la
determina di affidamento diretto di servizi e forniture (costruita sugli schemi ANCI), quella
di affidamento diretto di lavori, il conferimento di un incarico di patrocinio legale e la
concessione di un contributo.
Un modello contiene:

- le **domande iniziali** (importo, strumento di acquisto, PNRR...), che decidono quali
  capoversi entrano nell'atto;
- le **4 fasi** dell'atto, divise in sezioni e capoversi con il testo standard, i dati da
  compilare (`{{campo}}`), le condizioni che li attivano, l'aiuto con la base normativa;
- i **campi**, con tipo e controlli (CIG, CUP, codice fiscale e partita IVA, importi, date).

L'utente sceglie il modello con "Nuova bozza", risponde alle domande e compila una fase per
volta: può togliere o aggiungere i capoversi facoltativi e riscrivere quelli modificabili. Si
passa alla fase successiva solo con i dati obbligatori compilati. I dati che si ripetono in
ogni atto (delibere di DUP, bilancio e PEG, luogo, sezione del TAR...) li inserisce una volta
l'amministratore in **Amministrazione → Modelli e dati dell'ente**, dove si carica anche la
**carta intestata**: un ODT con i segnaposto `{{intestazione}}`, `{{preambolo}}`,
`{{dispositivo}}` e `{{chiusura}}`, uno per fase (senza, si usa un'impaginazione semplice).

**Moduli di regole.** Le specificità tecniche o normative stanno in moduli separati
(nel pacchetto: `modelli/regole/*.yaml`), uno per casistica. Ogni modulo è una delle
**caratteristiche dell'affidamento** che l'utente spunta tra le domande iniziali e, solo
quando è scelto:

- aggiunge le sue domande e i suoi campi (per il cloud: modello di servizio, classificazione
  dei dati, servizio qualificato nel Catalogo ACN, CPV);
- inietta capoversi nei **punti di innesto** del modello, distribuiti nelle 4 fasi: oggetto,
  visti, "dato atto che", clausole essenziali dell'art. 192 TUEL, garanzia, dispositivo;
- **suggerisce** risposte con la loro ragione (per il cloud: richiedere la garanzia
  definitiva), che l'utente applica con un clic.

**Checklist su tre livelli.** A ogni elemento della redazione corrisponde la sua scheda di
controllo (`pacchetto/checklist/*.json`):

| Livello | Redazione | Checklist |
|---|---|---|
| Tipologia di atto (Determinazione dirigenziale) | — | `scheda_determine.json`, generica, per ogni determina |
| Modello: affidamento diretto di servizi e forniture | `determina_affidamento_diretto.yaml` | `scheda_affidamento_diretto_sf.json` |
| Modello: affidamento diretto di lavori | `determina_affidamento_lavori.yaml` | `scheda_affidamento_lavori.json` |
| Modello: incarico di patrocinio legale | `determina_patrocinio_legale.yaml` | `scheda_patrocinio_legale.json` |
| Modello: concessione di un contributo | `determina_concessione_contributo.yaml` | `scheda_concessione_contributo.json` |
| Specificità: servizi / forniture cloud ICT | `regole/ict_cloud.yaml` | `scheda_ict_cloud.json` |
| Specificità: merceologia soggetta a CAM (servizi, forniture e lavori) | `regole/cam.yaml` | `scheda_cam.json` |
| Specificità: alta intensità di manodopera | `regole/manodopera.yaml` | `scheda_manodopera.json` |
| Specificità: utenze (energia, gas, carburanti, telefonia) | `regole/utenze.yaml` | `scheda_utenze.json` |
| Specificità: servizi di ingegneria e architettura | `regole/servizi_tecnici_sia.yaml` | `scheda_sia.json` |
| Specificità: servizi sociali e alla persona | `regole/servizi_sociali.yaml` | `scheda_servizi_sociali.json` |
| Specificità: immobile vincolato (lavori) | `regole/immobile_vincolato.yaml` | `scheda_immobile_vincolato.json` |

La verifica di una bozza applica la scheda generica, quella del modello e quelle delle
specificità scelte; il controllo di un atto caricato fa lo stesso con la tipologia, il
modello a cui l'atto corrisponde e le specificità indicate dal controllore. Gli esiti sono
raggruppati per scheda. All'importazione di un pacchetto l'app segnala le incoerenze: un modello o una
specificità senza checklist, una tipologia senza scheda generica, una checklist che rimanda
a un modello o a una specificità inesistenti. Gli stessi controlli sono nei test
(`python -m unittest discover -s common/tests -t .`), insieme a quelli del motore.

Il modello e i moduli che gli si applicano sono composti in un'unica versione: cambiare un
modulo crea una nuova versione dei modelli che lo usano.

**Il database comanda.** Modelli di atto, specificità e checklist si modificano nell'app:
l'ente ne è padrone e resta autonomo anche senza sottoscrizione. I contenuti standard che
forniamo arrivano come **pacchetto**, uno zip con il manifesto `pacchetto.yaml` e le cartelle
`modelli/` e `checklist/`. I sorgenti del pacchetto standard sono nella cartella
[`pacchetto/`](pacchetto/) del repository: non servono al sistema in funzione, servono a
produrre lo zip (`python deploy/pacchetto.py crea` → `atti-pa-modelli-<versione>.zip`), che
si consegna con l'installazione.

- **prima installazione**: il sistema parte vuoto; l'amministratore, in Amministrazione →
  Pacchetti, carica lo zip standard: tutti gli oggetti risultano nuovi e si importano;
- **aggiornamenti**: allo stesso modo si carica il nuovo pacchetto. L'app
  confronta, oggetto per oggetto, lo standard da cui deriva la versione dell'ente, la
  versione dell'ente e il nuovo standard, e propone cosa fare:

| Stato | Significato | Proposta |
|---|---|---|
| Nuovo | non presente nell'ente | aggiungere |
| Aggiornabile | l'ente non l'ha modificato, lo standard sì | aggiornare |
| Conflitto | modificato sia dall'ente sia nello standard | mantenere la versione dell'ente (oppure sostituirla) |
| Invariato / allineato | niente da fare | — |
| Disattivato | l'ente l'aveva disattivato | lasciarlo disattivato (oppure riattivarlo) |
| Rimosso | tolto dallo standard | mantenerlo (oppure disattivarlo) |

  Ogni aggiornamento crea una nuova versione; le bozze e le verifiche restano legate a
  quella usata. Le specificità si compongono nei modelli: quando ne cambia una, i modelli
  che la usano ricevono una nuova versione;
- **esportazione**: tutto ciò che è attivo nell'ente si scarica come pacchetto zip (backup,
  passaggio a un altro ente, lavoro fuori dall'app) e si reimporta allo stesso modo.

**Editor nell'app** (voce *Modelli e checklist*; manuale d'uso completo in
[manuale/editor_modelli_e_checklist.md](manuale/editor_modelli_e_checklist.md)). Modelli,
specificità e checklist si modificano senza scrivere YAML:

- **modelli e specificità**: a sinistra la struttura (domande, fasi, sezioni, capoversi, dati,
  valori calcolati, risposte consigliate, scenari di prova), al centro l'elemento scelto, a
  destra l'anteprima dell'atto con risposte di prova. I dati si inseriscono nel testo con
  *Inserisci un dato* o digitando `@`; *Quando compare* si imposta con menu a tendina
  (domanda, condizione, valore); per una specificità si scelgono i modelli a cui si applica
  e il punto in cui inserire i testi, e l'anteprima evidenzia i capoversi aggiunti;
- **checklist**: ogni controllo ha campi separati (cosa verificare, è conforme / non
  conforme / dubbio / non si applica se, note), le norme dalla libreria e i capoversi del
  modello che lo soddisfano (*Collegato a*);
- **controllo continuo**: errori (bloccano la pubblicazione: dati o domande inesistenti,
  condizioni non valide) e avvisi (dati non usati, capoversi senza controlli, collegamenti
  rotti tra checklist e capoversi);
- **bozza e pubblicazione**: le modifiche si salvano in una bozza invisibile agli atti; la
  pubblica un amministratore e diventa la nuova versione. Si confronta con la versione
  pubblicata o con lo standard, si ripristina lo standard capoverso per capoverso, si
  consultano le versioni precedenti; *Sorgente* mostra il YAML (JSON per le checklist) per
  le modifiche avanzate;
- **proposte**: chi scrive un atto e ha riscritto un capoverso può proporlo come testo del
  modello (*Proponi come testo del modello*); chi gestisce i modelli la trova sul capoverso
  e la applica alla bozza o la respinge.

| Ruolo | Gruppo AD (default) | Cosa può fare |
|---|---|---|
| Gestore dei modelli | `ATTI-PA-Gestori-Modelli` (`LDAP_GRUPPO_GESTORI_MODELLI`) | modifica modelli, specificità e checklist in bozza, gestisce le proposte |
| Amministratore | gruppo amministratori | tutto, compresa la pubblicazione e i pacchetti |
| Redattore | gruppo redattori | propone modifiche ai capoversi |

Da riga di comando:

```bash
python deploy/pacchetto.py prova                 # controlla il pacchetto in pacchetto/
python deploy/pacchetto.py crea                  # crea lo zip standard da consegnare
python deploy/pacchetto.py analizza FILE.zip     # cosa cambierebbe nel database
python deploy/pacchetto.py importa FILE.zip      # importa con le azioni proposte
python deploy/pacchetto.py esporta FILE.zip      # esporta la configurazione dell'ente
```

## Prova in locale

```bash
docker compose up --build
```

Apre l'applicazione su http://localhost:8080 in modalità uso personale (senza Active
Directory). Il sistema parte vuoto: per avere i modelli standard crea lo zip
(`python deploy/pacchetto.py crea`) e caricalo in Amministrazione → Pacchetti, oppure
importalo da riga di comando (`python deploy/pacchetto.py importa pacchetto/`). L'LLM predefinito è Ollama sul computer (`ollama serve`, modello
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
La pipeline GitHub Actions (`.github/workflows/ci.yml`) esegue i test, applica lo schema su
MySQL 8, crea lo zip del pacchetto standard (tra gli artefatti dell'esecuzione), compila il
frontend e costruisce tutte le immagini senza pubblicarle.

## Installazione su Kubernetes

1. Costruire e pubblicare le immagini nel registry interno
   (`registry.intranet.provincia.lucca/atti.pa`), da una macchina della rete interna dopo
   `docker login`:
   ```bash
   deploy/immagini.sh 0.1.0
   ```
   e aggiornare `newTag` in `deploy/k8s/kustomization.yaml`. GitHub Actions costruisce le
   immagini solo per controllo: non raggiunge il registry interno.
2. Il database MySQL 8 gira nel namespace (`deploy/k8s/mysql.yaml`, volume
   `rook-ceph-block`): al primo avvio crea da solo database, utente e schema
   (`deploy/k8s/sql/`).
3. Creare i segreti (vedi `deploy/k8s/secret.example.yaml`): `atti-pa-secret`,
   `mysql-secret`, `rabbitmq-secret`, `atti-pa-registry` (credenziali per scaricare le immagini dal registry
   interno), la ConfigMap `ldap-ca` con il certificato della CA di Active Directory e il
   Secret TLS `attipa-tls-secret`. I file con i valori reali non vanno versionati (`.gitignore`
   esclude `deploy/k8s/secret.yaml` e `deploy/k8s/*-secret.yaml`).
4. Adattare `deploy/k8s/configmap.yaml` (LDAP, gruppi AD, indirizzo dell'LLM, livello dei log)
   e l'host dell'Ingress.
5. `kubectl apply -k deploy/k8s`
6. Accedere come amministratore e, in Amministrazione → Pacchetti, caricare il pacchetto
   standard `atti-pa-modelli-<versione>.zip` (creato con `python deploy/pacchetto.py crea`).

Le modifiche successive allo schema si distribuiscono come nuovi file in `deploy/k8s/sql/`
(`0002_...sql`), da eseguire in ordine sul database prima di aggiornare le immagini:

```bash
kubectl -n atti-pa exec -i mysql-0 -- sh -c 'mysql -uatti_pa -p"$MYSQL_PASSWORD" atti_pa' \
  < deploy/k8s/sql/0002_....sql
```

e da aggiungere a `configMapGenerator` in `deploy/k8s/kustomization.yaml`, così le nuove
installazioni li eseguono al primo avvio.

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
controllori e amministratori. Tabelle: `norme_atti` (fonte `MANUALE`) e `norme_testi_caricati` in `deploy/k8s/sql/0001_schema.sql`.
