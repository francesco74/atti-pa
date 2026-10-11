# Build dalla radice del repository:
#   docker build -f normattiva-sync/Dockerfile -t atti-pa/normattiva-sync:0.1.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY common/pyproject.toml common/pyproject.toml
COPY common/src common/src
COPY normattiva-sync/pyproject.toml normattiva-sync/pyproject.toml
COPY normattiva-sync/src normattiva-sync/src
RUN pip install ./common ./normattiva-sync && rm -rf /build

RUN useradd --system --uid 10001 app
USER 10001
WORKDIR /app

CMD ["python", "-m", "normattiva_sync"]
