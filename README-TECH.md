# Frontend Flutter

Client web di atti-pa (Flutter Web, Flutter 3.38 o successivo). Il progetto Flutter è in `src/`.

## Sviluppo

```bash
cd frontend/src
flutter pub get
flutter run -d chrome --web-hostname provincia.localhost \
    --dart-define=API_URL=http://provincia.localhost:8000 --dart-define=LOG_LEVEL=DEBUG
```

L'ente si riconosce dal dominio con cui si raggiunge l'API: in sviluppo si usa quello di un
ente creato con `deploy/enti.py` (es. `provincia.localhost`). L'API va avviata con
`COOKIE_SECURE=false` e con `CORS_ORIGINI` che ammette l'origine dell'app (`.env.example`).

## Configurazione

L'app legge all'avvio `config.json`, generato dal container nginx con le sue variabili
d'ambiente (script `config-app.sh`), quindi la stessa immagine vale per ogni ambiente:

| Variabile | Significato | Predefinito |
|---|---|---|
| `API_URL` | indirizzo dell'API | vuoto = stessa origine della pagina |
| `LOG_LEVEL` | messaggi nella console del browser: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

Con `LOG_LEVEL=DEBUG` la console mostra ogni chiamata all'API con il codice di risposta.
Se `API_URL` è su un'origine diversa, va aggiunta a `connect-src` nella CSP di `nginx.conf`.
La cartella `/editor/` (editor dei documenti della trasparenza, aperto dall'app in un iframe)
ha in `nginx.conf` una CSP propria: va mantenuta allineata nei due file `nginx*.conf`.

### Logo dell'installazione

Un'installazione può usare un proprio logo al posto del martelletto: basta montare nel
container la cartella `/etc/atti-pa/marchio` con il file `logo.png` (quadrato o quasi, almeno
512 px, fondo trasparente). All'avvio `config-app.sh` lo copia in `/tmp/atti-pa/marchio` e con
ImageMagick genera l'icona del browser (`favicon.svg`) e quelle dell'app installata
(`icons/Icon-*.png`, le *maskable* con il logo nella zona sicura su fondo `#f5f6f8`); nginx le
serve al posto delle predefinite e `config.json` riporta `"LOGO": true`. L'app mostra il logo
nella pagina di accesso, nella filigrana dello sfondo e come icona dell'app quando l'ente non ha
caricato un logo proprio, che resta prioritario. Senza il file, o con un file non leggibile
(segnalato nel log del container), restano le icone dell'immagine.

In Kubernetes il logo è il ConfigMap facoltativo `atti-pa-marchio` (`deploy/k8s/frontend.yaml`),
in Docker un volume (`deploy/docker/docker-compose.yml`). Dopo averlo cambiato va riavviato il
frontend; i browser che hanno l'app installata possono tenere la vecchia icona per un po'.

In sviluppo con `flutter run` si usa `src/web/config.json`, oppure i valori passati con
`--dart-define=API_URL=...` e `--dart-define=LOG_LEVEL=DEBUG` quando nel file sono vuoti.

## Web in produzione

L'immagine Docker compila l'app (`flutter build web`) e la serve con nginx sulla porta 8080.
L'Ingress pubblica frontend e API sullo stesso dominio (`/` e `/api`): così il cookie di
sessione httpOnly funziona senza CORS e il token non è mai accessibile a JavaScript.

## Note

L'app è solo web: non generare le piattaforme mobile/desktop. Se serve rigenerare i file
di `web/`, usare `flutter create --platforms=web .` e poi ripristinare `pubspec.yaml`,
`lib/main.dart`, `test/` e `web/index.html` con `git checkout`, perché vengono sovrascritti.

## Struttura

```
lib/
  api/          client REST (autenticazione con cookie di sessione)
  stato/        stato di autenticazione
  ui/
    bozze/      modulo Redazione: elenco, scelta del modello, percorso in 4 fasi
    libreria/   riferimenti, norme, consultazione articoli per data
    controllo/  controlli: atto, audit automatico, revisione
    admin/      checklist, modelli e dati dell'ente, aggiornamenti Normattiva
    verifica/   pannelli con gli esiti delle verifiche
  util/         download dei documenti
```
