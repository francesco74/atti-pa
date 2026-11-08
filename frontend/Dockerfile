# Build dalla radice del repository:
#   docker build -f frontend/Dockerfile -t atti-pa/frontend:0.1.0 .

# --- Compilazione Flutter Web --------------------------------------------------------
FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app
COPY frontend/src/pubspec.yaml ./
RUN flutter pub get

COPY frontend/src/ ./
RUN flutter analyze --no-fatal-infos --no-fatal-warnings \
    && flutter test \
    && flutter build web --release --no-web-resources-cdn

# --- Server statico ------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine

# Licenza (AGPL-3.0-or-later): etichette OCI e testo nell'immagine
LABEL org.opencontainers.image.title="atti-pa-frontend" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/francesco74/atti-pa"
COPY LICENSE NOTICE /usr/share/licenses/atti-pa/

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build/web /usr/share/nginx/html
# Genera config.json all'avvio da API_URL e LOG_LEVEL
COPY --chmod=755 frontend/config-app.sh /docker-entrypoint.d/40-config-app.sh
ENV API_URL="" \
    LOG_LEVEL=INFO

EXPOSE 8080
