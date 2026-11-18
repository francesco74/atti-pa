# Schema del database

File SQL da eseguire **in ordine**, una sola volta ciascuno, sul database MySQL 8.

| File | Contenuto |
|---|---|
| `0001_schema.sql` | tutte le tabelle, la tipologia di atto "Determinazione dirigenziale" e la riga dei dati dell'ente |
| `0002_proposte_performance.sql` | proposte sugli obiettivi della performance (iter di approvazione) |
| `0003_indicatori_performance.sql` | indicatori delle azioni e misure degli obiettivi della performance |
| `0004_password_amministratori.sql` | gli amministratori locali cambiano la password al prossimo accesso (minimo 16 caratteri) |
| `0005_assistente_lavori.sql` | azioni dell'assistente sui documenti (Riassumi, Confronta, Estrai) eseguite dal worker |
| `0006_azioni_da_mappatura.sql` | azioni degli obiettivi della performance copiate dalle attività della mappatura dei rischi; rieseguibile |
| `0007_strutture_coinvolte.sql` | strutture coinvolte nei processi e nelle attività della mappatura (oltre alla responsabile); rieseguibile |
| `0008_catalogo_mappatura.sql` | catalogo della mappatura (voci di attività, rischi e misure) e collegamento degli elementi; rieseguibile |
| `0009_radici_negli_obiettivi.sql` | azioni e misure degli obiettivi collegate alla loro voce del catalogo (radice); rieseguibile |
| `0010_messaggio_benvenuto.sql` | messaggio dell'amministratore nella pagina iniziale (Home); rieseguibile |
| `0011_motivazione_valutazione.sql` | motivazione della valutazione del rischio (anche proposta dall'IA); rieseguibile |
| `0012_catalogo_procedimenti.sql` | catalogo dei procedimenti (P.n) separato dai processi; l'attività può essere un procedimento; converte i procedimenti esistenti e toglie dai processi tipo, termine, norma e dati art. 35; rieseguibile |

Nuova installazione: MySQL li esegue da solo, in ordine, al primo avvio con il volume vuoto
(in Kubernetes: ConfigMap `mysql-schema` generata in `kustomization.yaml` e montata in
`mysql.yaml`; in docker compose: la cartella montata). Ogni nuovo file va aggiunto anche a
`configMapGenerator` in `kustomization.yaml`. Aggiornamento: eseguire solo quelli non ancora applicati. Le modifiche
allo schema vanno in nuovi file (`0002_...sql`), riportate nei modelli ORM
(`common/models.py`); i file già distribuiti non vanno modificati né cancellati.

Il database nasce senza modelli di atto, specificità e checklist: si caricano con il
pacchetto standard (vedi il README principale, "Modelli di atto").
