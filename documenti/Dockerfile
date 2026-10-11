# Build dalla radice del repository:
#   docker build -f documenti/Dockerfile -t atti-pa/documenti:0.1.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

# LibreOffice Writer senza interfaccia grafica e font compatibili con i documenti Office
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui \
        fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY documenti/pyproject.toml documenti/pyproject.toml
COPY documenti/src documenti/src
RUN pip install ./documenti && rm -rf /build

RUN useradd --system --uid 10001 app
USER 10001
WORKDIR /app
EXPOSE 8000

CMD ["uvicorn", "documenti.main:app", "--host", "0.0.0.0", "--port", "8000"]
