"""Configurazione di gunicorn dalle variabili d'ambiente.

Uso: `gunicorn -c python:atti_api.gunicorn_conf "atti_api.main:create_app()"`.

I valori predefiniti sono pensati per un pod dietro l'Ingress Kubernetes:
- worker `gthread`: le richieste lunghe (conversioni, LLM) occupano un thread, non il
  processo, e il controllo di vita del worker non le interrompe;
- 2 processi × 8 thread reggono gli utenti di un ente con i limiti di memoria del pod;
- keep-alive di 65 s, oltre i 60 s con cui ingress-nginx riusa le connessioni verso i
  backend: così non è mai gunicorn a chiudere per primo una connessione che il proxy
  sta per riusare (errori 502 sporadici);
- arresto entro 25 s, prima dei 30 s dopo cui Kubernetes termina il pod.
"""

import os

bind = f"{os.environ.get('WEB_HOST', '0.0.0.0')}:{os.environ.get('WEB_PORT', '8000')}"
worker_class = "gthread"
workers = int(os.environ.get("WEB_WORKERS", "2"))
threads = int(os.environ.get("WEB_THREADS", "8"))
timeout = int(os.environ.get("WEB_TIMEOUT", "60"))
graceful_timeout = int(os.environ.get("WEB_GRACEFUL_TIMEOUT", "25"))
keepalive = int(os.environ.get("WEB_KEEPALIVE", "65"))

# Socket di controllo non usato (si gestisce con i segnali di Kubernetes): andrebbe scritto
# in $HOME, che nel pod è in sola lettura
control_socket_disable = True

# Log su stdout; formato e livello sono poi allineati da LOG_LEVEL. Il DEBUG interno di
# gunicorn (ogni connessione aperta e chiusa) duplicherebbe il log delle richieste.
accesslog = "-"
errorlog = "-"
loglevel = (
    "info"
    if os.environ.get("LOG_LEVEL", "INFO").upper() == "DEBUG"
    else os.environ.get("LOG_LEVEL", "INFO").lower()
)
