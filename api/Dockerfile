# Build dalla radice del repository:
#   docker build -f api/Dockerfile -t atti-pa/api:0.1.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOG_LEVEL=INFO

# Dipendenze dal requirements.txt del componente (include quelle di common)
WORKDIR /deps
COPY common/requirements.txt common/requirements.txt
COPY api/requirements.txt api/requirements.txt
RUN pip install -r api/requirements.txt && rm -rf /deps

# Codice: la libreria comune come pacchetto "common", il componente direttamente in /app
WORKDIR /app
COPY common/ /app/common/
COPY api/src/ /app/
ENV PYTHONPATH=/app

RUN useradd --system --uid 10001 app \
    && mkdir -p /var/lib/atti-pa/archivio && chown 10001 /var/lib/atti-pa/archivio
USER 10001
EXPOSE 8000
# archivio dei file originali (volume condiviso con il converter)
VOLUME /var/lib/atti-pa/archivio

# Server WSGI gunicorn con l'app Flask; opzioni da WEB_* (vedi src/gunicorn_conf.py)
CMD ["gunicorn", "-c", "python:gunicorn_conf", "main:create_app()"]
