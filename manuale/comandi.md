# Comandi di atti-pa

Tutti i comandi per sviluppare, rilasciare e gestire atti-pa, divisi per ambiente. Dove non
indicato diversamente, si lanciano dalla radice del repository.

Guide collegate: [installazione_docker.md](installazione_docker.md) (server Docker), sezione
"Installazione su Kubernetes" del `README.md` (cluster).

| Ambiente | Dove si lancia | Prefisso per i comandi dentro l'API |
|---|---|---|
| Sviluppo locale | radice del repository | `docker compose exec api` |
| Server Docker | `/opt/atti-pa/deploy/docker` | `docker compose exec api` |
| Cluster Kubernetes | qualsiasi macchina con `kubectl` | `kubectl -n attipa exec -it deploy/api --` |

---

## 1. Sviluppo locale

Ambiente completo con `docker-compose.yml` della radice (immagini costruite dal codice).
App su <http://localhost:8080>, API su <http://localhost:8000/api/v1/health>, phpMyAdmin su
<http://localhost:8081>, RabbitMQ su <http://localhost:15673>.

Avviare tutto, ricostruendo le immagini dopo una modifica al codice:
```bash
docker compose up --build
```

Avviare in background:
```bash
docker compose up -d --build
```

Avviare con log dettagliati (anche le query SQL):
```bash
LOG_LEVEL=DEBUG LOG_SQL=true docker compose up --build
```

Seguire i log di un servizio (`atti-pa-api`, `atti-pa-worker`, `atti-pa-converter`...):
```bash
docker logs -f atti-pa-worker
```

Fermare tutto, tenendo i dati:
```bash
docker compose down
```

Fermare tutto e **cancellare i dati** (database, code, file): al riavvio lo schema si ricrea da
`deploy/k8s/sql`:
```bash
docker compose down -v
```

Aggiornare a mano le norme da Normattiva:
```bash
docker compose run --rm normattiva-sync
```

Creare un ente di prova raggiungibile su <http://provincia.localhost:8080>:
```bash
docker compose exec api python enti.py crea provincia "Provincia di prova" provincia.localhost
```

---

## 2. Test

I test di API e worker usano SQLite: non serve il database. Si lanciano con il Python in cui
sono installate le dipendenze (`pip install -r api/requirements.txt -r worker/requirements.txt aiosqlite`).

Test della libreria comune:
```bash
python -m unittest discover -s common/tests -t .
```

Un file di test dell'API (es. multi-ente):
```bash
cd api/tests && python test_multi_ente_api.py
```

Tutti i test dell'API:
```bash
cd api/tests && for f in test_*.py; do echo "== $f"; python "$f" || break; done
```

Test del worker:
```bash
cd worker/tests && python test_trasparenza_worker.py
```

Controllo del pacchetto standard (modelli e checklist in `pacchetto/`):
```bash
python deploy/pacchetto.py prova
```

Analisi e test del frontend, senza Flutter installato (con il container ufficiale). Si lavora
su una copia in `/tmp/w`, perché il container crea file di proprietà di root che non si
cancellerebbero dal repository:
```bash
docker run --rm -v /tmp:/t alpine rm -rf /t/w     # pulisce la copia precedente
mkdir -p /tmp/w && cp -r frontend/src/. /tmp/w/
docker run --rm -v /tmp/w:/app -w /app ghcr.io/cirruslabs/flutter:stable \
  bash -c "flutter pub get && flutter analyze && flutter test"
```

Un solo file di test del frontend (stessa copia):
```bash
docker run --rm -v /tmp/w:/app -w /app ghcr.io/cirruslabs/flutter:stable \
  bash -c "flutter pub get && flutter test test/utenti_ente_test.dart"
```

La CI (`.github/workflows/ci.yml`) esegue questi controlli a ogni push e costruisce le immagini
senza pubblicarle.

---

## 3. Immagini (rilascio di una versione)

Lo script `deploy/immagini.sh` costruisce le immagini dei 5 componenti (api, converter, worker,
normattiva-sync, frontend) e le pubblica. **La destinazione dipende dal nome**: `REGISTRY` e
`PREFISSO` lo compongono come `REGISTRY/PREFISSO` + componente + `:versione`.

Registry privato, per il cluster (`registry.intranet.provincia.lucca/atti.pa/api:0.2.0`...):
```bash
docker login registry.intranet.provincia.lucca
deploy/immagini.sh 0.2.0
```

Docker Hub, per il server Docker (`francesco74/atti-pa-api:0.2.0`...):
```bash
docker login
REGISTRY=francesco74 PREFISSO=atti-pa- deploy/immagini.sh 0.2.0
```

Solo costruzione, senza pubblicare (per provare):
```bash
deploy/immagini.sh 0.2.0 --solo-build
```

Per un rilascio su entrambi si lanciano i due comandi con la stessa versione: la seconda
costruzione riusa la cache.

---

## 4. Cluster Kubernetes

Namespace `attipa`. Manifest in `deploy/k8s/` (kustomize).

### Installazione e aggiornamento

Creare i segreti (valori di esempio in `deploy/k8s/secret.example.yaml`):
```bash
kubectl -n attipa create secret generic atti-pa-secret --from-env-file=secret.env
kubectl -n attipa create secret docker-registry atti-pa-registry \
  --docker-server=registry.intranet.provincia.lucca --docker-username=UTENTE --docker-password=PASSWORD
kubectl -n attipa create secret tls attipa-tls-secret --cert=certificato.crt --key=chiave.key
```

Applicare i manifest (prima installazione, o dopo aver cambiato `newTag` in
`deploy/k8s/kustomization.yaml` per una nuova versione):
```bash
kubectl apply -k deploy/k8s
```

Vedere cosa cambierebbe, senza applicare:
```bash
kubectl diff -k deploy/k8s
```

Seguire l'aggiornamento di un componente:
```bash
kubectl -n attipa rollout status deploy/api
```

Riavviare un componente (es. dopo aver cambiato la ConfigMap):
```bash
kubectl -n attipa rollout restart deploy/api deploy/worker
```

Tornare alla versione precedente di un componente:
```bash
kubectl -n attipa rollout undo deploy/api
```

### Controllo

Stato dei pod:
```bash
kubectl -n attipa get pods
```

Log (il converter ha due container: `converter` e `consumatore`):
```bash
kubectl -n attipa logs -f deploy/api
kubectl -n attipa logs -f deploy/worker
kubectl -n attipa logs -f deploy/converter -c consumatore
```

Eventi recenti (pod che non partono, immagini non scaricate):
```bash
kubectl -n attipa get events --sort-by=.lastTimestamp | tail -20
```

### Normattiva

Esecuzioni del CronJob notturno (03:30):
```bash
kubectl -n attipa get jobs
```

Aggiornamento manuale, subito:
```bash
kubectl -n attipa create job --from=cronjob/normattiva-sync sync-manuale-$(date +%s)
```

### Database

Console MySQL:
```bash
kubectl -n attipa exec -it mysql-0 -- sh -c 'mysql -uatti_pa -p"$MYSQL_PASSWORD" atti_pa'
```

Applicare una modifica allo schema:
```bash
kubectl -n attipa exec -i mysql-0 -- sh -c 'mysql -uatti_pa -p"$MYSQL_PASSWORD" atti_pa' \
  < deploy/k8s/sql/0002_....sql
```

Dump del database:
```bash
kubectl -n attipa exec mysql-0 -- sh -c \
  'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction atti_pa' | gzip > atti_pa-$(date +%F).sql.gz
```

---

## 5. Server Docker

Da `/opt/atti-pa/deploy/docker`, con il `.env` compilato. Guida completa:
[installazione_docker.md](installazione_docker.md).

### Avvio e aggiornamento

Avviare (o applicare modifiche a `.env` e `docker-compose.yml`):
```bash
docker compose up -d
```

Passare a una nuova versione (dopo aver cambiato `VERSIONE` nel `.env`):
```bash
docker compose pull && docker compose up -d
```

Fermare tutto, tenendo i dati:
```bash
docker compose down
```

Riavviare un servizio:
```bash
docker compose restart api
```

Rimuovere le immagini vecchie che non servono più:
```bash
docker image prune -a
```

### Controllo

Stato dei servizi:
```bash
docker compose ps
```

Log (`api`, `worker`, `converter`, `converter-consumatore`, `frontend`, `caddy`,
`normattiva-sync`, `mysql`, `rabbitmq`):
```bash
docker compose logs -f api
docker compose logs --since 1h worker
```

Problemi con i certificati:
```bash
docker compose logs caddy | grep -i error
```

Configurazione effettiva, con le variabili del `.env` sostituite (attenzione: mostra le password):
```bash
docker compose config
```

### Normattiva

Prossima esecuzione e esiti dell'aggiornamento notturno:
```bash
docker compose logs normattiva-sync
```

Aggiornamento manuale, subito:
```bash
docker compose run --rm normattiva-sync python /app
```

### Database

Console MySQL:
```bash
docker compose exec mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" atti_pa'
```

Applicare una modifica allo schema:
```bash
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" atti_pa' < modifica.sql
```

phpMyAdmin (solo dal server; dal proprio computer con il tunnel SSH, poi
<http://localhost:8081>, utente `root`):
```bash
docker compose --profile strumenti up -d phpmyadmin
ssh -L 8081:localhost:8081 utente@server
docker compose stop phpmyadmin
```

### Backup e ripristino

Backup manuale (database e file caricati; predefinito in `/var/backups/atti-pa`, 14 giorni):
```bash
./backup.sh
./backup.sh /altra/cartella
GIORNI=30 ./backup.sh
```

Backup ogni notte alle 02:00 (riga da aggiungere con `crontab -e`):
```
0 2 * * * /opt/atti-pa/deploy/docker/backup.sh >> /var/log/atti-pa-backup.log 2>&1
```

Ripristino del database (**sostituisce i dati attuali**):
```bash
gunzip -c atti_pa-DATA.sql.gz | docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" atti_pa'
```

Ripristino dei file caricati:
```bash
docker compose exec -T api tar xzf - -C /var/lib/atti-pa/archivio < archivio-DATA.tar.gz
```

---

## 6. Enti (`enti.py`)

Gli enti non hanno un'interfaccia web: si gestiscono da riga di comando. Lo script è nell'immagine
dell'API: i comandi qui sotto vanno preceduti dal prefisso dell'ambiente (tabella in alto), es.

```bash
docker compose exec api python enti.py elenco                     # sviluppo e server Docker
kubectl -n attipa exec -it deploy/api -- python enti.py elenco    # cluster
```

| Comando | Cosa fa |
|---|---|
| `python enti.py elenco` | tutti gli enti, con domini e moduli |
| `python enti.py mostra CODICE` | dettaglio di un ente |
| `python enti.py crea CODICE "Nome" DOMINIO...` | nuovo ente con l'utente `admin` e la `PASSWORD_INIZIALE`, da cambiare al primo accesso |
| `python enti.py crea CODICE "Nome" DOMINIO... --moduli redazione,anticorruzione` | come sopra, solo con alcuni moduli |
| `python enti.py rinomina CODICE "Nome"` | cambia il nome |
| `python enti.py domini CODICE DOMINIO...` | **sostituisce** i domini dell'ente |
| `python enti.py moduli CODICE redazione,...` | **sostituisce** i moduli attivi (`""` = nessuno) |
| `python enti.py disattiva CODICE` | l'ente non si raggiunge più, i dati restano |
| `python enti.py attiva CODICE` | riattiva l'ente |
| `python enti.py reimposta CODICE` | `admin` torna alla password iniziale, riattivato, con l'accesso locale abilitato (password dimenticata) |

`CODICE`: lettere minuscole e cifre, es. `provincialucca`. Elenco dei moduli:
`python enti.py moduli --help`.

Esempio sul server Docker:
```bash
docker compose exec api python enti.py crea provincia "Provincia di Lucca" provincia.attipa.papuntozero.it
```

Nel cluster ogni nuovo dominio richiede anche il record DNS, l'host nell'Ingress
(`deploy/k8s/ingress.yaml`) e il certificato. Sul server Docker bastano il DNS (record wildcard)
e il comando: Caddy ottiene il certificato alla prima visita.

---

## 7. Pacchetti di modelli e checklist (`pacchetto.py`)

Di norma i pacchetti si importano dall'app (Amministrazione → Pacchetti), scegliendo oggetto per
oggetto. Da riga di comando, in sviluppo (usa il `DATABASE_URL` del `.env`):

| Comando | Cosa fa |
|---|---|
| `python deploy/pacchetto.py prova` | controlla il pacchetto in `pacchetto/` |
| `python deploy/pacchetto.py crea` | crea lo zip standard da distribuire (`atti-pa-modelli-<versione>.zip`) |
| `python deploy/pacchetto.py analizza ENTE FILE.zip` | cosa cambierebbe per l'ente, senza modificare nulla |
| `python deploy/pacchetto.py importa ENTE FILE.zip` | importa con le azioni proposte (nei conflitti resta la versione dell'ente) |
| `python deploy/pacchetto.py esporta ENTE FILE.zip` | esporta la configurazione dell'ente |

Al posto di `FILE.zip` si può indicare una cartella con la struttura del pacchetto (es.
`pacchetto/`).

---

## 8. Manutenzione delle norme (`riprocessa_norme.py`)

Dopo una correzione del parser di Normattiva (`common/normattiva/parser.py`): ricalcola
struttura, impronta e rinvii degli articoli già salvati, senza riscaricare nulla. In sviluppo:

Elencare le differenze, senza modificare:
```bash
python deploy/manutenzione/riprocessa_norme.py --prova
```

Aggiornare il database:
```bash
python deploy/manutenzione/riprocessa_norme.py
```

---

## 9. Utilità

Generare una password o una chiave casuale (per `.env` e segreti; solo lettere e cifre):
```bash
openssl rand -hex 32
```

Verificare la chiave Gemini e gli embedding:
```bash
source .env
curl -s "$EMBEDDING_BASE_URL/embeddings" -H "Authorization: Bearer $EMBEDDING_API_KEY" \
  -H 'Content-Type: application/json' -d "{\"model\":\"$EMBEDDING_MODEL\",\"input\":[\"prova\"]}" | head -c 200
```

Controllare che l'API risponda e raggiunga il database:
```bash
curl -s https://provincia.attipa.papuntozero.it/api/v1/health
curl -s https://provincia.attipa.papuntozero.it/api/v1/ready
```

Controllare quale ente risponde a un dominio:
```bash
curl -s https://provincia.attipa.papuntozero.it/api/v1/auth/ente
```
