"""Archivio dei file originali degli atti su filesystem (ARCHIVIO_DIR).

I file sono salvati come `atti/AAAA/MM/<uuid><estensione>`; nel database restano il
percorso relativo, l'impronta SHA-256 e la dimensione. La cartella va condivisa tra API
(scrittura) e converter (lettura): in Kubernetes un volume ReadWriteMany.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath


class FileNonInArchivio(FileNotFoundError):
    pass


@dataclass
class FileArchiviato:
    percorso: str  # relativo alla cartella dell'archivio
    sha256: str
    dimensione: int


def _assoluto(cartella: str, percorso: str) -> Path:
    base = Path(cartella).resolve()
    pieno = (base / PurePosixPath(percorso)).resolve()
    if base not in pieno.parents:
        raise FileNonInArchivio(f"Percorso fuori dall'archivio: {percorso}")
    return pieno


def salva(cartella: str, contenuto: bytes, nome_file: str) -> FileArchiviato:
    """Scrive il file in modo atomico (file temporaneo e rinomina)."""
    oggi = date.today()
    estensione = Path(nome_file).suffix.lower()[:10]
    percorso = f"atti/{oggi:%Y}/{oggi:%m}/{uuid.uuid4()}{estensione}"
    destinazione = _assoluto(cartella, percorso)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = destinazione.with_suffix(destinazione.suffix + ".tmp")
    with open(temporaneo, "wb") as f:
        f.write(contenuto)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporaneo, destinazione)
    return FileArchiviato(percorso, hashlib.sha256(contenuto).hexdigest(), len(contenuto))


def scrivi(cartella: str, percorso: str, contenuto: bytes) -> None:
    """Scrive un file derivato (es. l'anteprima PDF) in un percorso stabilito, in modo atomico."""
    destinazione = _assoluto(cartella, percorso)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = destinazione.with_suffix(destinazione.suffix + ".tmp")
    temporaneo.write_bytes(contenuto)
    os.replace(temporaneo, destinazione)


def percorso_anteprima(atto_id: str) -> str:
    """PDF da mostrare nel browser per gli atti caricati in ODT, DOC o DOCX."""
    return f"anteprime/{atto_id}.pdf"


def leggi(cartella: str, percorso: str) -> bytes:
    try:
        return _assoluto(cartella, percorso).read_bytes()
    except FileNotFoundError as e:
        raise FileNonInArchivio(f"File non presente nell'archivio: {percorso}") from e


def elimina(cartella: str, percorso: str) -> None:
    try:
        _assoluto(cartella, percorso).unlink()
    except FileNotFoundError:
        pass
