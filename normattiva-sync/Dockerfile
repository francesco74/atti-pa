# Build dalla radice del repository:
#   docker build -f normattiva-sync/Dockerfile -t atti-pa/normattiva-sync:0.1.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOG_LEVEL=INFO

# Dipendenze dal requirements.txt del componente (include quelle di common)
WORKDIR /deps
COPY common/requirements.txt common/requirements.txt
COPY normattiva-sync/requirements.txt normattiva-sync/requirements.txt
RUN pip install -r normattiva-sync/requirements.txt && rm -rf /deps

# Codice: la libreria comune come pacchetto "common", il componente direttamente in /app
WORKDIR /app
COPY common/ /app/common/
COPY normattiva-sync/src/ /app/
ENV PYTHONPATH=/app

RUN useradd --system --uid 10001 app
USER 10001

# src è piatto: si esegue src/__main__.py
CMD ["python", "/app"]
