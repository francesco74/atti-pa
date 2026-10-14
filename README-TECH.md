# Frontend Flutter

Client web di atti-pa (Flutter Web, Flutter 3.38 o successivo). Il progetto Flutter è in `src/`.

## Sviluppo

```bash
cd frontend/src
flutter pub get
flutter run -d chrome --dart-define=API_URL=http://localhost:8000 --dart-define=LOG_LEVEL=DEBUG
```

In sviluppo l'API va avviata con `CORS_ORIGINI='["http://localhost:PORTA"]'` e
`COOKIE_SECURE=false`, oppure con `AUTH_ENABLED=false` per l'uso personale senza login.

## Configurazione

L'app legge all'avvio `config.json`, generato dal container nginx con le sue variabili
d'ambiente (script `config-app.sh`), quindi la stessa immagine vale per ogni ambiente:

| Variabile | Significato | Predefinito |
|---|---|---|
| `API_URL` | indirizzo dell'API | vuoto = stessa origine della pagina |
| `LOG_LEVEL` | messaggi nella console del browser: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

Con `LOG_LEVEL=DEBUG` la console mostra ogni chiamata all'API con il codice di risposta.
Se `API_URL` è su un'origine diversa, va aggiunta a `connect-src` nella CSP di `nginx.conf`.

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
    bozze/      modulo Redazione: elenco e wizard
    libreria/   riferimenti, norme, consultazione articoli per data
    controllo/  controlli: atto, audit automatico, revisione
    admin/      checklist, template, aggiornamenti Normattiva
    verifica/   pannelli con gli esiti delle verifiche
  util/         download dei documenti
```
