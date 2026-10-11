# atti-pa

Strumenti di supporto alla **redazione** e al **controllo** delle determinazioni dirigenziali
degli enti locali, pensati per girare su Kubernetes all'interno della rete dell'ente.

| Modulo | Utenti | Cosa fa |
|---|---|---|
| **Redazione** | redattori (uso personale) | Wizard guidato su template ODT, riferimenti normativi presi da Normattiva e verificati alla data di adozione, controllo rapido, documento ODT/PDF/PDF-A anche con omissis |
| **Controllo** | gruppo controllo atti | Sessioni di controllo successivo (art. 147-bis TUEL), sorteggio riproducibile, analisi automatica degli atti, revisione umana, report |

Principi:

- **Normattiva è la fonte di verità**: i testi normativi sono scaricati dalle API OpenData e
  conservati per intervallo di vigenza; ogni atto è verificato rispetto alle norme vigenti
  alla sua data di adozione.
- **LLM on-premise**: nessun dato esce dall'ente. Il modello valuta un criterio di checklist
  alla volta e riceve nel prompt il testo vigente delle norme: non cita norme a memoria.
- **L'IA propone, la persona decide**: gli esiti automatici sono proposte che il controllore
  conferma o modifica con motivazione.
- **Accesso con Active Directory**: login pass-through via LDAPS, ruoli dai gruppi AD,
  nessuna password salvata. Ogni redattore vede solo le proprie bozze.

## Componenti

Ogni componente ha la propria cartella con il `Dockerfile` e il codice in `src/`.
Le immagini si costruiscono dalla radice del repository
(`docker build -f <componente>/Dockerfile .`).

| Cartella | In Kubernetes | Ruolo |
|---|---|---|
| `api/` | Deployment + Service | API REST FastAPI: autenticazione, libreria, redazione, controllo |
| `verifica-worker/` | Deployment | Elabora la coda delle verifiche (riferimenti, dati personali, checklist con LLM) |
| `documenti/` | Deployment + Service interno | Conversioni con LibreOffice headless (ODT→PDF/PDF-A, DOCX→ODT) |
| `normattiva-sync/` | **CronJob** notturno | Aggiorna i testi normativi modificati su Normattiva |
| `db-migrate/` | initContainer dell'API | Applica le migrazioni dello schema MySQL |
| `frontend/` | Deployment + Service | App Flutter Web servita da nginx |
| `common/` | — (libreria) | Codice condiviso: modelli, client Normattiva, estrazione riferimenti, verifica, LLM |
| `deploy/k8s/` | — | Manifest Kubernetes (kustomize) |

```
               Ingress (atti.ente.local)
              /                        \
        /  frontend                /api  api ──────── documenti (LibreOffice)
                                         │  \
                                         │   └─ Active Directory (LDAPS)
                                         │
     normattiva-sync (CronJob) ──── MySQL ──── verifica-worker ──── LLM on-premise
              │                                   │
              └──────────── Normattiva ───────────┘
```

## Prova in locale

```bash
docker compose up --build
```

Apre l'applicazione su http://localhost:8080 in modalità uso personale (senza Active
Directory). Per l'LLM indicare un server compatibile OpenAI, ad esempio Ollama:
`LLM_BASE_URL=http://host.docker.internal:11434/v1 LLM_MODEL=mistral-small docker compose up`.

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
La pipeline GitHub Actions esegue test (anche su MySQL 8), compila il frontend e costruisce
tutte le immagini.

## Installazione su Kubernetes

1. Costruire e pubblicare le immagini nel registry dell'ente; aggiornare `images` in
   `deploy/k8s/kustomization.yaml`.
2. Creare il database MySQL 8 (`CREATE DATABASE atti_pa CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`).
3. Creare i segreti (vedi `deploy/k8s/secret.example.yaml`): `atti-pa-secret`,
   la ConfigMap `ldap-ca` con il certificato della CA di Active Directory e il Secret TLS `atti-pa-tls`.
4. Adattare `deploy/k8s/configmap.yaml` (LDAP, gruppi AD, indirizzo dell'LLM, host dell'Ingress).
5. `kubectl apply -k deploy/k8s`

Le migrazioni del database girano automaticamente all'avvio dell'API.

## Fonte dei dati normativi

Dati: Normattiva (https://www.normattiva.it), Istituto Poligrafico e Zecca dello Stato,
licenza CC BY 4.0.
