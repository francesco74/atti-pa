# Installazione su un server Docker

Installazione di produzione su un server con Docker, senza Kubernetes. I file sono in
`deploy/docker/`. Le immagini sono su Docker Hub (`francesco74/atti-pa-*`). Ogni ente si
raggiunge dal suo sottodominio, es. `provincia.attipa.papuntozero.it`.

| Servizio | Ruolo |
|---|---|
| caddy | unico esposto (porte 80 e 443): https con Let's Encrypt, `/api` all'API, il resto all'app |
| api, frontend | API Flask e app web |
| worker, converter, converter-consumatore | verifiche, trasparenza, conversione dei documenti |
| mysql, rabbitmq | database e code, solo all'interno |
| normattiva-sync | aggiornamento delle norme ogni notte alle 03:30 |
| phpmyadmin | solo su richiesta, solo dal server |

## Certificati

Caddy ottiene e rinnova da solo i certificati Let's Encrypt:

- per il dominio principale (`DOMINIO`) all'avvio;
- per il dominio di un ente alla prima visita ("on demand"). Prima di chiederlo, Caddy domanda
  all'API se il dominio è di un ente attivo (`/api/v1/tls/consenti`, bloccato dall'esterno):
  un nome inventato non genera richieste a Let's Encrypt.

Un nuovo ente funziona appena creato con `enti.py`, senza toccare Caddy. I certificati sono nel
volume `caddy_data`: non va cancellato (Let's Encrypt limita i certificati per settimana).

## Prima installazione

**1. DNS e rete.** Due record verso l'IP pubblico del server:

```
attipa.papuntozero.it      A  <IP>
*.attipa.papuntozero.it    A  <IP>
```

Porte 80 e 443 aperte da internet (la 80 serve a Let's Encrypt per la verifica e a
reindirizzare su https).

**2. File sul server.** Servono `deploy/docker/` e `deploy/k8s/sql/` (lo schema del database),
nella stessa disposizione, es. in `/opt/atti-pa`:

```bash
sudo mkdir -p /opt/atti-pa/deploy
# dal computer di sviluppo
rsync -a deploy/docker deploy/k8s utente@server:/opt/atti-pa/deploy/
```

**3. Configurazione.**

```bash
cd /opt/atti-pa/deploy/docker
cp .env.example .env && chmod 600 .env
openssl rand -hex 32     # una volta per ogni password e chiave
```

Compilare `.env`: `VERSIONE`, `ACME_EMAIL`, password e chiavi (solo lettere e cifre: finiscono
negli URL di connessione), `PASSWORD_INIZIALE`, `LLM_API_KEY` ed `EMBEDDING_API_KEY` (la chiave
di Google AI Studio, la stessa per entrambi).

**4. Verifica della chiave Gemini** (prima di avviare):

```bash
source .env
curl -s "$EMBEDDING_BASE_URL/embeddings" -H "Authorization: Bearer $EMBEDDING_API_KEY" \
  -H 'Content-Type: application/json' -d "{\"model\":\"$EMBEDDING_MODEL\",\"input\":[\"prova\"]}" | head -c 200
```

Deve rispondere con `"data":[{"embedding":[...`.

**5. Avvio.**

```bash
docker compose up -d
docker compose ps        # tutti "healthy" o "Up" dopo un minuto
```

Al primo avvio MySQL crea lo schema da `deploy/k8s/sql`.

**6. Enti.** Per ciascuno, con il suo dominio:

```bash
docker compose exec api python enti.py crea provincia "Provincia di …" provincia.attipa.papuntozero.it
docker compose exec api python enti.py elenco
```

Si accede su `https://provincia.attipa.papuntozero.it` come `admin` con la `PASSWORD_INIZIALE`,
da cambiare subito. La prima apertura impiega qualche secondo: Caddy ottiene il certificato.
Gli altri comandi di `enti.py` (domini, moduli, disattiva, reimposta) sono descritti in testa al
file `deploy/enti.py`.

**7. Backup.** Nel cron di root (`crontab -e`):

```
0 2 * * * /opt/atti-pa/deploy/docker/backup.sh >> /var/log/atti-pa-backup.log 2>&1
```

Ogni notte salva il dump del database e l'archivio dei file in `/var/backups/atti-pa`, tenendo
14 giorni. Le copie vanno portate anche fuori dal server. Il ripristino è descritto in testa a
`backup.sh`.

## Rilascio di una nuova versione

Dal computer di sviluppo, dopo `docker login`:

```bash
REGISTRY=francesco74 PREFISSO=atti-pa- deploy/immagini.sh 0.3.0
```

Sul server: `VERSIONE=0.3.0` nel `.env`, poi

```bash
docker compose pull && docker compose up -d
```

**Modifiche al database.** Lo schema in `deploy/k8s/sql` vale solo alla prima installazione.
Le modifiche di una nuova versione (indicate nelle note di rilascio) si applicano a mano, prima
di avviare la nuova versione:

```bash
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" atti_pa' < modifica.sql
```

Le immagini su Docker Hub sono pubbliche: contengono il codice, ma nessuna password o chiave
(stanno solo nel `.env` del server).

## Consultazione del database

phpMyAdmin non parte con gli altri servizi e ascolta solo sul server:

```bash
docker compose --profile strumenti up -d phpmyadmin
# dal proprio computer
ssh -L 8081:localhost:8081 utente@server     # poi http://localhost:8081, utente root
docker compose stop phpmyadmin               # finito
```

## Controllo e problemi

```bash
docker compose ps
docker compose logs -f api            # o worker, caddy, normattiva-sync...
docker compose logs caddy | grep -i error    # certificati
```

- **Il sito di un ente non apre (errore di certificato).** Il dominio è registrato?
  (`enti.py mostra CODICE`). Il DNS punta al server e la porta 80 è aperta? Nei log di Caddy
  c'è il motivo; nei log dell'API la richiesta a `/api/v1/tls/consenti` deve avere esito 200.
- **Un container è "unhealthy".** Docker non lo riavvia da solo: `docker compose restart NOME`
  e guardarne i log.
- **Gemini.** Con `LLM_PROVIDER=gemini` il testo degli atti (con gli eventuali dati personali)
  e, per la ricerca, i testi di processi, procedimenti e delle domande vengono inviati a
  Google: l'ente ne deve tenere conto nel registro dei trattamenti. Senza `EMBEDDING_*` la
  ricerca funziona solo per parole.
