# Build dalla radice del repository:
#   docker build -f converter/Dockerfile -t atti-pa/converter:0.1.0 .
# Stessa immagine per due processi:
#   - servizio HTTP di conversione (ODT -> PDF/PDF-A dei documenti delle bozze): comando predefinito
#   - consumatore della coda di conversione degli atti in Markdown: python consumatore.py
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    LOG_LEVEL=INFO

# LibreOffice Writer senza interfaccia grafica e font compatibili con i documenti Office
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui \
        fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /deps
COPY converter/requirements.txt converter/requirements.txt
RUN pip install -r converter/requirements.txt && rm -rf /deps

# Non usa la libreria comune: solo il contenuto di src
WORKDIR /app
COPY converter/src/ /app/
ENV PYTHONPATH=/app

RUN useradd --system --uid 10001 app
USER 10001
EXPOSE 8000

# Server WSGI gunicorn con l'app Flask; opzioni da WEB_* (vedi src/gunicorn_conf.py)
CMD ["gunicorn", "-c", "python:gunicorn_conf", "main:create_app()"]
