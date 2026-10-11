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

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build/web /usr/share/nginx/html

EXPOSE 8080
