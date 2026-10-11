# Build dalla radice del repository:
#   docker build -f api/Dockerfile -t atti-pa/api:0.1.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY common/pyproject.toml common/pyproject.toml
COPY common/src common/src
COPY api/pyproject.toml api/pyproject.toml
COPY api/src api/src
RUN pip install ./common ./api && rm -rf /build

RUN useradd --system --uid 10001 app
USER 10001
WORKDIR /app
EXPOSE 8000

CMD ["uvicorn", "atti_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
