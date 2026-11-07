"""Esegue un comando ogni giorno a un'ora fissa (ora italiana): sostituisce il CronJob del
cluster nell'installazione Docker (servizio normattiva-sync di docker-compose.yml).

    python pianifica.py 03:30 python /app
"""

import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("Europe/Rome")


def prossima(ora: int, minuto: int) -> datetime:
    adesso = datetime.now(FUSO)
    quando = adesso.replace(hour=ora, minute=minuto, second=0, microsecond=0)
    return quando if quando > adesso else quando + timedelta(days=1)


def main() -> None:
    ora, minuto = (int(x) for x in sys.argv[1].split(":"))
    comando = sys.argv[2:]
    while True:
        quando = prossima(ora, minuto)
        print(f"Prossima esecuzione: {quando:%d/%m/%Y %H:%M}", flush=True)
        while (attesa := (quando - datetime.now(FUSO)).total_seconds()) > 0:
            time.sleep(min(attesa, 300))  # a passi brevi: regge cambi d'ora e sospensioni
        esito = subprocess.run(comando).returncode
        print(f"Esecuzione terminata con codice {esito}", flush=True)


if __name__ == "__main__":
    main()
