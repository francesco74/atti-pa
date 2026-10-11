# atti-pa

Strumenti di supporto alla redazione e al controllo delle **determinazioni dirigenziali** degli enti locali.

Il progetto è composto da due moduli distinti che condividono la stessa base normativa e le stesse checklist:

| Modulo | Utenti | Scopo |
|---|---|---|
| **Redazione** | uso personale | Schema guidato per stendere l'atto con riferimenti normativi corretti e vigenti |
| **Controllo** | gruppo controllo atti | Verifica della qualità degli atti sorteggiati (controllo successivo, art. 147-bis TUEL) |

Principi chiave:

- **Normattiva è la fonte di verità** per i riferimenti normativi: il testo viene estratto dalle API OpenData e versionato per data di vigenza.
- **LLM on-premise**: nessun dato esce dall'ente. Il modello lavora solo sul testo normativo che gli viene passato.
- **L'IA propone, l'umano decide**: ogni esito automatico è modificabile e motivato dal controllore.

## Struttura

```
backend/          API FastAPI (Python 3.11+)
  app/normattiva/ Client API Normattiva, costruzione URN, parser commi/lettere
  db/schema.sql   Schema MySQL 8
  tests/
docs/
  SPECIFICA.md    Specifica tecnica
frontend/         Client Flutter (da sviluppare)
```

## Avvio rapido (backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
uvicorn app.main:app --reload
```

## Fonte dei dati normativi

Dati: Normattiva (https://www.normattiva.it), Istituto Poligrafico e Zecca dello Stato, licenza CC BY 4.0.
