#!/usr/bin/env bash
# Costruisce le immagini di atti-pa e le pubblica nel registry interno.
#
#   deploy/immagini.sh 0.1.0              # costruisce e pubblica la versione 0.1.0
#   deploy/immagini.sh 0.1.0 --solo-build # costruisce soltanto
#   REGISTRY=altro.registry/progetto deploy/immagini.sh 0.1.0
#
# Da eseguire su una macchina della rete interna, dopo `docker login` sul registry; la
# macchina deve poter scaricare le immagini di base (Python, Flutter, nginx). Dopo la
# pubblicazione aggiornare newTag in deploy/k8s/kustomization.yaml e applicare i manifest.
set -euo pipefail

REGISTRY="${REGISTRY:-registry.intranet.provincia.lucca/atti.pa}"
COMPONENTI=(api converter verifica-worker normattiva-sync frontend)

versione="${1:-}"
if [[ -z "$versione" || "$versione" == -* ]]; then
    echo "Uso: $0 VERSIONE [--solo-build]" >&2
    exit 2
fi
pubblica=true
[[ "${2:-}" == "--solo-build" ]] && pubblica=false

# le immagini si costruiscono dalla radice del repository
cd "$(dirname "$0")/.."

for c in "${COMPONENTI[@]}"; do
    immagine="$REGISTRY/$c:$versione"
    echo "==> $immagine"
    docker build -f "$c/Dockerfile" -t "$immagine" .
done

if $pubblica; then
    for c in "${COMPONENTI[@]}"; do
        docker push "$REGISTRY/$c:$versione"
    done
    echo "Pubblicate in $REGISTRY con la versione $versione."
    echo "Aggiorna newTag in deploy/k8s/kustomization.yaml, poi: kubectl apply -k deploy/k8s"
fi
