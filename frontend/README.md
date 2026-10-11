# Frontend Flutter

Client web (e desktop) di atti-pa. Il progetto Flutter è in `src/`.

## Sviluppo

```bash
cd frontend/src
flutter pub get
flutter run -d chrome --dart-define=API_URL=http://localhost:8000
```

In sviluppo l'API va avviata con `CORS_ORIGINI='["http://localhost:PORTA"]'` e
`COOKIE_SECURE=false`, oppure con `AUTH_ENABLED=false` per l'uso personale senza login.

## Web in produzione

L'immagine Docker compila l'app (`flutter build web`) e la serve con nginx sulla porta 8080.
L'Ingress pubblica frontend e API sullo stesso dominio (`/` e `/api`): così il cookie di
sessione httpOnly funziona senza CORS e il token non è mai accessibile a JavaScript.

## Client desktop (Windows/Linux/macOS)

Le cartelle delle piattaforme desktop non sono versionate: si generano una volta con

```bash
cd frontend/src
flutter create --platforms=windows,linux,macos .
flutter build windows --dart-define=API_URL=https://atti.ente.local
```

Sul desktop il token JWT è conservato nel portachiavi del sistema (flutter_secure_storage).

## Struttura

```
lib/
  api/          client REST e conservazione del token
  stato/        stato di autenticazione
  ui/
    bozze/      modulo Redazione: elenco e wizard
    libreria/   riferimenti, norme, consultazione articoli per data
    controllo/  sessioni, sorteggio, caricamento atti, revisione, report
    admin/      checklist, template, aggiornamenti Normattiva
    verifica/   pannelli con gli esiti delle verifiche
```
