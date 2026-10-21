import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LivelloLog = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# File .env per lo sviluppo locale, letti in quest'ordine (l'ultimo prevale):
# quello nella radice del repository, valido per tutti i componenti, e quello nella
# cartella da cui si avvia il programma. Le variabili d'ambiente prevalgono su entrambi.
# Nelle immagini Docker i .env sono esclusi (.dockerignore): lì vale solo l'ambiente.
# ENV_FILE indica un file diverso da quello della radice (es. ENV_FILE=.env.prova).
FILE_ENV = (
    Path(os.environ.get("ENV_FILE") or Path(__file__).resolve().parent.parent / ".env"),
    Path(".env"),
)


class Settings(BaseSettings):
    """Configurazione letta da variabili d'ambiente (ConfigMap/Secret in Kubernetes).

    I valori predefiniti sono pensati per l'uso reale e sono coerenti tra loro: i tempi
    massimi delle chiamate fatte durante una richiesta HTTP restano sotto il timeout
    dell'Ingress (180 s), così l'utente riceve l'errore vero e non un 504 del proxy.
    """

    model_config = SettingsConfigDict(env_file=FILE_ENV, env_file_encoding="utf-8", extra="ignore")

    fuso_orario: str = "Europe/Rome"

    # Log: DEBUG (diagnostica dettagliata), INFO (normale), WARNING (solo anomalie), ERROR
    log_level: LivelloLog = "INFO"
    log_sql: bool = False  # con LOG_LEVEL=DEBUG registra anche le query SQL

    # Normattiva: 3 tentativi da 30 s con pause di 1 e 2 s restano sotto i 180 s dell'Ingress
    normattiva_base_url: str = "https://api.normattiva.it/t/normattiva.api"
    normattiva_timeout: float = 30.0
    normattiva_tentativi: int = 3

    # Database (valore per lo sviluppo locale, come in .env.example)
    database_url: str = "mysql+aiomysql://atti_pa:password@localhost:3306/atti_pa"

    # LLM: provider scelto in configurazione (vedi common/llm.py).
    #   ollama (predefinito) | openai_compatibile (vLLM, llama.cpp...): on-premise
    #   openai (ChatGPT) | gemini (Google) | anthropic (Claude): servizi esterni, il testo
    #   degli atti (dati personali compresi) esce dall'ente
    llm_provider: Literal["ollama", "openai_compatibile", "openai", "gemini", "anthropic"] = (
        "ollama"
    )
    # Vuoti = valori predefiniti del provider (indirizzo dell'API e modello, in llm.py)
    llm_base_url: str | None = None
    # Indirizzo di Ollama quando LLM_BASE_URL è vuoto (in docker compose: il computer host)
    llm_ollama_url: str = "http://localhost:11434/v1"
    llm_model: str | None = None
    # Obbligatoria per openai e gemini; per anthropic, se vuota, vale ANTHROPIC_API_KEY
    llm_api_key: str = ""
    # Verifiche (nel worker, senza utente in attesa): prompt lunghi con l'intero atto
    llm_timeout: float = 180.0
    # Riscrittura degli appunti (richiesta interattiva): testo breve, sotto il timeout
    # dell'Ingress
    llm_timeout_redazione: float = 60.0
    # Temperatura (ollama, openai_compatibile, gemini; OpenAI e Claude usano la propria)
    llm_temperatura: float = 0.0  # valutazioni ripetibili
    llm_temperatura_redazione: float = 0.2  # un minimo di varietà nella scrittura
    # Solo anthropic: profondità del ragionamento (low | medium | high | xhigh | max).
    # medium = predefinito del modello, buon equilibrio tra qualità e costo
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Solo anthropic: token massimi della risposta (ragionamento compreso)
    llm_max_token: int = 16_000
    # Solo anthropic: se Claude rifiuta una richiesta, riprova su un altro modello Claude
    llm_fallback: bool = True
    # Coerenza tra i riferimenti normativi citati e il contenuto dell'atto (nelle verifiche):
    # una chiamata all'LLM ogni LLM_COERENZA_GRUPPO riferimenti, con l'atto intero.
    # Oltre 8-10 riferimenti per chiamata la precisione sugli ultimi tende a calare.
    llm_coerenza_riferimenti: bool = True
    llm_coerenza_gruppo: int = 8
    # Testo massimo di una norma nel prompt (articoli citati senza comma possono essere lunghi)
    llm_coerenza_max_caratteri_norma: int = 8_000
    # Norme inserite manualmente (regolamenti interni...) citate in forme non previste dalle
    # loro denominazioni: una chiamata all'LLM per verifica, solo se ci sono norme manuali
    llm_riconoscimento_norme_manuali: bool = True
    # Dati personali da valutare per la pubblicazione (omissis): li cerca il modello, una
    # chiamata per atto (più di una per gli atti oltre LLM_MAX_CARATTERI_ATTO)
    llm_dati_personali: bool = True

    # Modelli di atto e checklist: all'avvio dell'API si caricano dai file quelli cambiati
    # (common/configurazione.py). Le cartelle predefinite sono quelle del repository, copiate
    # anche nell'immagine dell'API; in Kubernetes si possono montare da una ConfigMap.
    # pacchetto standard importato al primo avvio, con il database vuoto (common/pacchetti.py)
    importa_pacchetto_iniziale: bool = True
    pacchetto_dir: str = str(Path(__file__).resolve().parents[1] / "deploy")
    # Cartella con prompt personalizzati: i file presenti sostituiscono quelli di
    # common/prompt/ con lo stesso nome (vuota = solo quelli predefiniti)
    llm_prompt_dir: str | None = None
    # ~60.000 caratteri ≈ 17.000 token: con le norme nel prompt resta in un contesto di 32k
    llm_max_caratteri_atto: int = 60_000

    # Autenticazione
    auth_enabled: bool = True
    ldap_url: str = "ldaps://dc.ente.local"
    ldap_dominio: str = "ente.local"  # per il bind con UPN: utente@dominio
    ldap_base_dn: str = "DC=ente,DC=local"
    ldap_ca_cert: str | None = None  # percorso del certificato CA per LDAPS
    # Verifica del certificato del server con ldaps://. Disattivarla solo per prove o con
    # certificati autofirmati in una rete fidata: le password viaggiano cifrate ma senza
    # garanzia di parlare con il vero domain controller (attacco man-in-the-middle).
    ldap_verifica_certificato: bool = True
    ldap_timeout: int = 10  # il login è interattivo: un controller che non risponde va scartato
    # Gruppi AD (CN o DN completo) che concedono i ruoli applicativi
    ldap_gruppo_redattori: str = "ATTI-PA-Redattori"
    ldap_gruppo_controllori: str = "ATTI-PA-Controllori"
    ldap_gruppo_gestori_modelli: str = "ATTI-PA-Gestori-Modelli"
    ldap_gruppo_admin: str = "ATTI-PA-Admin"

    # Nessun segreto predefinito: con AUTH_ENABLED=true l'API non parte senza JWT_SECRET
    jwt_secret: str = ""
    jwt_scadenza_minuti: int = 480  # una giornata lavorativa
    cookie_secure: bool = True
    # Solo in sviluppo (in produzione app e API hanno lo stesso host). Le voci possono essere
    # espressioni regolari, da ancorare con ^ e $ (es. "^http://localhost:[0-9]+$"):
    # senza, "http://localhost:5000.altro.dominio" verrebbe accettata.
    cors_origini: list[str] = []
    # Proxy davanti all'API di cui fidarsi per X-Forwarded-*: 1 = il solo Ingress.
    # 0 se l'API è raggiungibile direttamente (le intestazioni sarebbero falsificabili).
    proxy_hops: int = 1

    # RabbitMQ: code tra API, converter e worker (vedi common/coda.py). Le credenziali sono
    # nell'URL: in Kubernetes va nel Secret.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_prefisso: str = "atti-pa"  # nomi delle code: <prefisso>.conversione, ...

    # Archivio dei file originali degli atti (cartella condivisa tra API e converter);
    # nel database restano percorso, impronta SHA-256 e il testo in Markdown
    archivio_dir: str = "/var/lib/atti-pa/archivio"

    # Servizio documenti: oltre i 120 s di conversione di LibreOffice, sotto i 180 s
    # dell'Ingress
    documenti_url: str = "http://converter:8000"
    documenti_timeout: float = 150.0
    upload_max_mb: int = 20  # l'Ingress accetta 25 MB per richiesta

    # Job notturno di aggiornamento normative
    sync_giorni_iniziali: int = 7  # prima esecuzione: modifiche dell'ultima settimana
    sync_finestra_giorni: int = 7  # ampiezza di ogni interrogazione a Normattiva
    sync_pausa_secondi: float = 0.5  # pausa tra le chiamate, per non sovraccaricare il servizio

    # Worker di verifica
    worker_intervallo_secondi: float = 5.0  # attesa tra due controlli della coda vuota
    worker_max_tentativi: int = 3
    # Verifiche "IN_CORSO" oltre questo tempo tornano in coda: deve superare la durata
    # della verifica più lunga (circa 30 s per elemento di checklist con un LLM su GPU)
    worker_timeout_minuti: int = 60
    worker_heartbeat: str = "/tmp/heartbeat"  # file controllato dalla liveness probe
    # Lavori fermi da più di questo tempo (messaggio perso o RabbitMQ non raggiungibile
    # all'invio) vengono reinviati sulle code
    worker_reinvio_minuti: int = 10

    @field_validator("log_level", mode="before")
    @classmethod
    def _livello_maiuscolo(cls, valore: object) -> object:
        return valore.strip().upper() if isinstance(valore, str) else valore

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.fuso_orario)


@lru_cache
def get_settings() -> Settings:
    return Settings()
