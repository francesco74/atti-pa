#!/bin/sh
# Eseguito dall'entrypoint di nginx all'avvio del container (/docker-entrypoint.d):
# scrive la configurazione dell'app web con le variabili d'ambiente. Il file va in /tmp
# perché in Kubernetes il filesystem del container è in sola lettura.
#   API_URL    indirizzo dell'API (vuoto = stessa origine della pagina)
#   LOG_LEVEL  log nella console del browser: DEBUG, INFO, WARNING, ERROR
#   SORGENTE_URL  repository del codice sorgente mostrato nell'app (licenza AGPL); vuoto =
#                 quello del progetto. Da impostare se si installa una versione modificata.
# Logo dell'installazione (facoltativo): se esiste /etc/atti-pa/marchio/logo.png (volume o
# ConfigMap montato), l'app lo usa al posto del martelletto e da lì si generano l'icona del
# browser (favicon.svg) e quelle dell'app installata (icons/), servite da nginx al posto delle
# predefinite. Senza il file restano quelle dell'immagine.
set -eu

ORIGINE_LOGO=/etc/atti-pa/marchio/logo.png
MARCHIO=/tmp/atti-pa/marchio
SFONDO_ICONE='#f5f6f8'  # background_color di manifest.json

# Ridimensiona il logo dentro un quadrato di lato $2 (trasparente), su un fondo di lato $3
# (colore $4, "none" = trasparente); risultato in $5. -limit: il container ha poca memoria.
quadrato() {
  magick -limit memory 32MiB -limit map 64MiB "$1" -strip -background none \
    -resize "$2x$2" -gravity center -extent "$2x$2" \
    -background "$4" -extent "$3x$3" -flatten "PNG32:$5"
}

# set -e non vale dentro un if: ogni passo controlla l'esito
genera_marchio() {
  mkdir -p "$MARCHIO/icons" || return 1
  magick -limit memory 32MiB -limit map 64MiB "$ORIGINE_LOGO" -strip -resize '512x512>' "PNG32:$MARCHIO/logo.png" || return 1
  quadrato "$ORIGINE_LOGO" 192 192 none "$MARCHIO/icons/Icon-192.png" || return 1
  quadrato "$ORIGINE_LOGO" 512 512 none "$MARCHIO/icons/Icon-512.png" || return 1
  # maskable: il sistema ritaglia l'icona (cerchio, goccia...); il logo sta nella zona sicura
  # (cerchio dell'80%), su fondo pieno
  quadrato "$ORIGINE_LOGO" 108 192 "$SFONDO_ICONE" "$MARCHIO/icons/Icon-maskable-192.png" || return 1
  quadrato "$ORIGINE_LOGO" 288 512 "$SFONDO_ICONE" "$MARCHIO/icons/Icon-maskable-512.png" || return 1
  # favicon: index.html punta a favicon.svg, che qui contiene il PNG a 64 px
  quadrato "$ORIGINE_LOGO" 64 64 none "$MARCHIO/favicon.png" || return 1
  {
    printf '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
    printf '<image width="64" height="64" href="data:image/png;base64,'
    base64 -w 0 "$MARCHIO/favicon.png" || return 1
    printf '"/></svg>\n'
  } > "$MARCHIO/favicon.svg" || return 1
  rm "$MARCHIO/favicon.png" || return 1
}

LOGO=false
rm -rf "$MARCHIO"
if [ -f "$ORIGINE_LOGO" ]; then
  if genera_marchio; then
    LOGO=true
    echo "atti-pa: logo dell'installazione, icone generate da $ORIGINE_LOGO"
  else
    rm -rf "$MARCHIO"
    echo "atti-pa: $ORIGINE_LOGO non leggibile, restano le icone predefinite" >&2
  fi
fi

json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

mkdir -p /tmp/atti-pa
cat > /tmp/atti-pa/config.json <<FINE
{
  "API_URL": "$(json "${API_URL:-}")",
  "LOG_LEVEL": "$(json "${LOG_LEVEL:-INFO}")",
  "SORGENTE_URL": "$(json "${SORGENTE_URL:-}")",
  "LOGO": $LOGO
}
FINE
echo "atti-pa: config.json generato (API_URL='${API_URL:-}', LOG_LEVEL='${LOG_LEVEL:-INFO}')"
