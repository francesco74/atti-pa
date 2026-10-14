"""Configurazione di gunicorn dalle variabili d'ambiente.

Uso: `gunicorn -c python:gunicorn_conf "main:create_app()"`.

Un solo processo: il limite di conversioni parallele (CONVERSIONI_PARALLELE) vale per
processo, quindi più processi moltiplicherebbero la memoria usata da LibreOffice.
I thread coprono le conversioni in corso, quelle in coda e le probe di Kubernetes.
"""

import os

bind = f"{os.environ.get('WEB_HOST', '0.0.0.0')}:{os.environ.get('WEB_PORT', '8000')}"
worker_class = "gthread"
workers = int(os.environ.get("WEB_WORKERS", "1"))
threads = int(os.environ.get("WEB_THREADS", "6"))
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
