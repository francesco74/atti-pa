#!/usr/bin/env bash
# Backup dell'installazione Docker: dump del database e archivio dei file caricati.
#
#   deploy/docker/backup.sh [CARTELLA]     # predefinita /var/backups/atti-pa
#
# Da pianificare con il cron del server, es. ogni notte alle 02:00 (prima di normattiva-sync):
#   0 2 * * * /opt/atti-pa/deploy/docker/backup.sh >> /var/log/atti-pa-backup.log 2>&1
# Tiene GIORNI giorni di copie (predefinito 14). Le copie vanno poi portate fuori dal server.
#
# Ripristino del database (sostituisce i dati):
#   gunzip -c atti_pa-DATA.sql.gz | docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" atti_pa'
# Ripristino dei file:
#   docker compose exec -T api tar xzf - -C /var/lib/atti-pa/archivio < archivio-DATA.tar.gz
set -euo pipefail

CARTELLA="${1:-/var/backups/atti-pa}"
GIORNI="${GIORNI:-14}"
data="$(date +%Y%m%d-%H%M)"

cd "$(dirname "$0")"
mkdir -p "$CARTELLA"
umask 077

echo "$(date -Is) backup in $CARTELLA"
docker compose exec -T mysql sh -c \
    'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers atti_pa' \
    | gzip > "$CARTELLA/atti_pa-$data.sql.gz.parziale"
mv "$CARTELLA/atti_pa-$data.sql.gz.parziale" "$CARTELLA/atti_pa-$data.sql.gz"

docker compose exec -T api tar czf - -C /var/lib/atti-pa/archivio . \
    > "$CARTELLA/archivio-$data.tar.gz.parziale"
mv "$CARTELLA/archivio-$data.tar.gz.parziale" "$CARTELLA/archivio-$data.tar.gz"

find "$CARTELLA" -maxdepth 1 \( -name 'atti_pa-*.sql.gz' -o -name 'archivio-*.tar.gz' -o -name '*.parziale' \) \
    -mtime +"$GIORNI" -delete
echo "$(date -Is) fatto: $(du -sh "$CARTELLA" | cut -f1) in totale"
