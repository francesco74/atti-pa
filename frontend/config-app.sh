#!/bin/sh
# Eseguito dall'entrypoint di nginx all'avvio del container (/docker-entrypoint.d):
# scrive la configurazione dell'app web con le variabili d'ambiente. Il file va in /tmp
# perché in Kubernetes il filesystem del container è in sola lettura.
#   API_URL    indirizzo dell'API (vuoto = stessa origine della pagina)
#   LOG_LEVEL  log nella console del browser: DEBUG, INFO, WARNING, ERROR
set -eu

json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

mkdir -p /tmp/atti-pa
cat > /tmp/atti-pa/config.json <<FINE
{
  "API_URL": "$(json "${API_URL:-}")",
  "LOG_LEVEL": "$(json "${LOG_LEVEL:-INFO}")"
}
FINE
echo "atti-pa: config.json generato (API_URL='${API_URL:-}', LOG_LEVEL='${LOG_LEVEL:-INFO}')"
