# Build dalla radice del repository:
#   docker build -f db-migrate/Dockerfile -t atti-pa/db-migrate:0.1.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY common/pyproject.toml common/pyproject.toml
COPY common/src common/src
RUN pip install ./common && rm -rf /build

# Le migrazioni restano su file accanto al codice
WORKDIR /app
COPY db-migrate/src/ /app/
ENV PYTHONPATH=/app

RUN useradd --system --uid 10001 app
USER 10001

CMD ["python", "-m", "db_migrate"]
