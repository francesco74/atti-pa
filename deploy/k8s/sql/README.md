# Schema del database

File SQL da eseguire **in ordine**, una sola volta ciascuno, sul database MySQL 8.

| File | Contenuto |
|---|---|
| `0001_schema.sql` | tutte le tabelle, la tipologia di atto "Determinazione dirigenziale" e la riga dei dati dell'ente |

Nuova installazione: MySQL li esegue da solo, in ordine, al primo avvio con il volume vuoto
(in Kubernetes: ConfigMap `mysql-schema` generata in `kustomization.yaml` e montata in
`mysql.yaml`; in docker compose: la cartella montata). Ogni nuovo file va aggiunto anche a
`configMapGenerator` in `kustomization.yaml`. Aggiornamento: eseguire solo quelli non ancora applicati. Le modifiche
allo schema vanno in nuovi file (`0002_...sql`), riportate nei modelli ORM
(`common/models.py`); i file già distribuiti non vanno modificati né cancellati.

Il database nasce senza modelli di atto, specificità e checklist: si caricano con il
pacchetto standard (vedi il README principale, "Modelli di atto").
