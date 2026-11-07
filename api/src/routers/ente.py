"""Amministrazione dell'ente: profilo (logo, caratteristiche), modi di accesso (utenti
locali, Active Directory), strutture organizzative e utenti.

Riservata all'amministratore dell'ente (ruolo ADMIN). I dati dell'ente e la carta intestata
sono in routers/modelli.py. Gli utenti locali creati qui, o con la password reimpostata,
devono sceglierne una propria al primo accesso.
"""

import asyncio
import csv
import io
import logging
from http import HTTPStatus

from flask import Blueprint
from ldap3.core.exceptions import LDAPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from auth import password as pw
from auth.ldap import GRUPPI_PREDEFINITI, ConfigLdap, ruoli_da_gruppi
from deps import amministratore_ente, audit, autenticato, db, ente, risorse, utente
from schemas import UtenteOut
from web import ErroreApi, allegato, corpo, file_caricato, nessun_contenuto
from common.models import Ente, OrigineUtente, Ruolo, Struttura, User
from common import posta
from common.cifratura import ErroreCifratura
from common.cifratura import cifra as cifra_segreto
from common.rag import RagClient, RagError, cifra

log = logging.getLogger("atti_api.ente")

bp = Blueprint("ente", __name__, url_prefix="/api/v1/ente")


# --- profilo -------------------------------------------------------------------------------

LOGO_MAX_BYTE = 2 * 1024 * 1024
# solo immagini raster: un SVG può contenere script
_FIRME_LOGO = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}


class ProfiloIn(BaseModel):
    """Si aggiornano solo i campi presenti nel corpo."""

    caratteristiche: str | None = Field(default=None, max_length=10_000)
    assistenza: str | None = Field(default=None, max_length=2_000)
    dichiarazione_accessibilita: str | None = Field(default=None, max_length=500, pattern=r"^(https?://\S+)?$")


def _profilo(e: Ente) -> dict:
    return {"nome": e.nome, "caratteristiche": e.caratteristiche, "assistenza": e.assistenza,
            "dichiarazione_accessibilita": e.dichiarazione_accessibilita, "logo": e.logo_mime is not None}  # fmt: skip


@bp.get("/profilo")
@autenticato(modulo=None)
async def profilo():
    """Nome, caratteristiche dell'amministrazione e presenza del logo (per tutti i moduli)."""
    return _profilo(await db().get(Ente, ente().id))


@bp.put("/profilo")
@amministratore_ente
async def aggiorna_profilo():
    dati = corpo(ProfiloIn)
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    for campo in dati.model_fields_set:
        setattr(e, campo, (getattr(dati, campo) or "").strip() or None)
    audit(sessione, utente(), "ente", e.id, "PROFILO", {"campi": sorted(dati.model_fields_set)})
    await sessione.commit()
    return _profilo(e)


@bp.get("/logo")
@autenticato(modulo=None)
async def logo():
    e = await db().scalar(select(Ente).where(Ente.id == ente().id).options(undefer(Ente.logo)))
    if e is None or not e.logo:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Logo non caricato")
    estensione = "png" if e.logo_mime == "image/png" else "jpg"
    return allegato(e.logo, e.logo_mime, f"logo.{estensione}", in_linea=True)


@bp.post("/logo")
@amministratore_ente
async def carica_logo():
    """Logo dell'ente (PNG o JPEG), usato nei documenti generati dai moduli."""
    contenuto = file_caricato().read(LOGO_MAX_BYTE + 1)
    if len(contenuto) > LOGO_MAX_BYTE:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Logo troppo grande (massimo 2 MB)")
    mime = next((m for firma, m in _FIRME_LOGO.items() if contenuto.startswith(firma)), None)
    if mime is None:
        raise ErroreApi(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Il logo deve essere un'immagine PNG o JPEG")
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    e.logo, e.logo_mime = contenuto, mime
    audit(sessione, utente(), "ente", e.id, "LOGO")
    await sessione.commit()
    return _profilo(e)


@bp.delete("/logo")
@amministratore_ente
async def elimina_logo():
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    e.logo = e.logo_mime = None
    audit(sessione, utente(), "ente", e.id, "LOGO_RIMOSSO")
    await sessione.commit()
    return nessun_contenuto()


# --- accesso -------------------------------------------------------------------------------


class AccessoIn(BaseModel):
    accesso_locale: bool = True
    ldap: ConfigLdap | None = None  # None: Active Directory non usato


def _accesso(e: Ente) -> dict:
    return {
        "accesso_locale": e.accesso_locale,
        "ldap": e.ldap_json,
        "gruppi_predefiniti": GRUPPI_PREDEFINITI,
        "ruoli": list(Ruolo.TUTTI),
    }


@bp.get("/accesso")
@amministratore_ente
async def accesso():
    return _accesso(await db().get(Ente, ente().id))


@bp.put("/accesso")
@amministratore_ente
async def aggiorna_accesso():
    dati = corpo(AccessoIn)
    if not dati.accesso_locale and dati.ldap is None:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Serve almeno un modo di accesso")
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    e.accesso_locale = dati.accesso_locale
    e.ldap_json = dati.ldap.model_dump() if dati.ldap else None
    audit(
        sessione, utente(), "ente", e.id, "ACCESSO",
        {"locale": e.accesso_locale, "ldap": dati.ldap.url if dati.ldap else None},
    )  # fmt: skip
    await sessione.commit()
    return _accesso(e)


class ProvaIn(BaseModel):
    ldap: ConfigLdap
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


@bp.post("/accesso/prova")
@amministratore_ente
async def prova_accesso():
    """Prova la configurazione di Active Directory (anche non ancora salvata) con un account:
    mostra i gruppi letti e i ruoli che ne derivano."""
    dati = corpo(ProvaIn)
    try:
        trovato = await asyncio.to_thread(
            risorse().authenticator(dati.ldap).autentica, dati.username, dati.password
        )
    except LDAPException as e:
        return {"esito": "ERRORE", "messaggio": f"Server non raggiungibile o certificato non valido: {e}"}
    if trovato is None:
        return {"esito": "CREDENZIALI", "messaggio": "Credenziali rifiutate dal server"}
    return {
        "esito": "OK",
        "utente": trovato.username,
        "nome": trovato.nome_completo,
        "gruppi": trovato.gruppi,
        "ruoli": ruoli_da_gruppi(trovato.gruppi, dati.ldap.gruppi),
    }


# --- collegamento al RAG -------------------------------------------------------------------


class RagIn(BaseModel):
    url: str = Field(min_length=1, max_length=500, pattern=r"^https?://\S+$")
    chiave: str | None = Field(default=None, max_length=500)  # None o vuota: resta quella salvata


def _rag(e: Ente) -> dict:
    """La chiave non esce mai: si sa solo se c'è."""
    r = e.rag_json or {}
    return {"url": r.get("url"), "chiave_impostata": bool(r.get("chiave_cifrata"))}


@bp.get("/rag")
@amministratore_ente
async def rag():
    return _rag(await db().get(Ente, ente().id))


@bp.put("/rag")
@amministratore_ente
async def aggiorna_rag():
    """Indirizzo dell'API del RAG e chiave dell'ente (cifrata con CHIAVE_CIFRATURA)."""
    dati = corpo(RagIn)
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    cifrata = (e.rag_json or {}).get("chiave_cifrata")
    if dati.chiave and dati.chiave.strip():
        try:
            cifrata = cifra(dati.chiave.strip(), risorse().settings.chiave_cifratura)
        except RagError as errore:
            raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, str(errore)) from errore
    if not cifrata:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Indica la chiave del RAG")
    e.rag_json = {"url": dati.url.rstrip("/"), "chiave_cifrata": cifrata}
    audit(sessione, utente(), "ente", e.id, "RAG", {"url": e.rag_json["url"], "chiave_cambiata": bool(dati.chiave)})
    await sessione.commit()
    return _rag(e)


@bp.delete("/rag")
@amministratore_ente
async def elimina_rag():
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    e.rag_json = None
    audit(sessione, utente(), "ente", e.id, "RAG", {"url": None})
    await sessione.commit()
    return nessun_contenuto()


@bp.post("/rag/prova")
@amministratore_ente
async def prova_rag():
    """Prova il collegamento salvato: elenca i topic che la chiave consente di consultare."""
    e = await db().get(Ente, ente().id)
    try:
        client = RagClient.dell_ente(risorse().rag_http, e.rag_json, risorse().settings.chiave_cifratura)
        if client is None:
            raise RagError("Collegamento al RAG non configurato")
        topics = await client.topics()
    except RagError as errore:
        return {"esito": "ERRORE", "messaggio": str(errore)}
    return {"esito": "OK", "topics": [{"id": t.get("id"), "descrizione": t.get("description")} for t in topics]}


# --- posta in uscita ------------------------------------------------------------------------


class PostaIn(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    porta: int = Field(default=587, ge=1, le=65535)
    sicurezza: str = Field(default="STARTTLS", pattern="^(STARTTLS|SSL|NESSUNA)$")
    utente: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)  # None o vuota: resta quella salvata
    mittente: str = Field(min_length=3, max_length=255)
    rispondi_a: str | None = Field(default=None, max_length=255)


def _posta(e: Ente) -> dict:
    """La password non esce mai: si sa solo se c'è."""
    p = dict(e.smtp_json or {})
    if not p:
        return {"configurata": False}
    return {
        "configurata": True, "host": p.get("host"), "porta": p.get("porta"), "sicurezza": p.get("sicurezza"),
        "utente": p.get("utente"), "password_impostata": bool(p.get("password_cifrata")),
        "mittente": p.get("mittente"), "rispondi_a": p.get("rispondi_a"),
    }  # fmt: skip


@bp.get("/posta")
@amministratore_ente
async def configurazione_posta():
    return _posta(await db().get(Ente, ente().id))


@bp.put("/posta")
@amministratore_ente
async def aggiorna_posta():
    """Server SMTP dell'ente per le notifiche; la password si salva cifrata con CHIAVE_CIFRATURA."""
    dati = corpo(PostaIn)
    for campo, valore in (("mittente", dati.mittente), ("rispondi_a", dati.rispondi_a)):
        if valore and not posta.indirizzo_valido(valore):
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Indirizzo non valido: {campo}")
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    utente_smtp = (dati.utente or "").strip() or None
    cifrata = (e.smtp_json or {}).get("password_cifrata") if utente_smtp else None
    if utente_smtp and dati.password and dati.password.strip():
        try:
            cifrata = cifra_segreto(dati.password, risorse().settings.chiave_cifratura)
        except ErroreCifratura as errore:
            raise ErroreApi(HTTPStatus.SERVICE_UNAVAILABLE, str(errore)) from errore
    e.smtp_json = {
        "host": dati.host.strip(), "porta": dati.porta, "sicurezza": dati.sicurezza, "utente": utente_smtp,
        "password_cifrata": cifrata, "mittente": dati.mittente.strip(),
        "rispondi_a": (dati.rispondi_a or "").strip() or None,
    }  # fmt: skip
    audit(sessione, utente(), "ente", e.id, "POSTA",
          {"host": e.smtp_json["host"], "password_cambiata": bool(dati.password)})  # fmt: skip
    await sessione.commit()
    return _posta(e)


@bp.delete("/posta")
@amministratore_ente
async def elimina_posta():
    """Senza posta configurata le notifiche non si inviano."""
    sessione = db()
    e = await sessione.get(Ente, ente().id)
    e.smtp_json = None
    audit(sessione, utente(), "ente", e.id, "POSTA", {"host": None})
    await sessione.commit()
    return nessun_contenuto()


class ProvaPostaIn(BaseModel):
    destinatario: str | None = Field(default=None, max_length=255)  # di solito l'amministratore


@bp.post("/posta/prova")
@amministratore_ente
async def prova_posta():
    """Invia subito un'email di prova con la configurazione salvata e dice com'è andata."""
    dati = corpo(ProvaPostaIn)
    e = await db().get(Ente, ente().id)
    config = posta.config_ente(e.smtp_json)
    destinatario = (dati.destinatario or utente().email or "").strip()
    if config is None:
        return {"esito": "ERRORE", "messaggio": "Posta in uscita non configurata"}
    if not posta.indirizzo_valido(destinatario):
        return {"esito": "ERRORE", "messaggio": "Indica l'indirizzo a cui inviare la prova"}
    impostazioni = risorse().settings
    try:
        await asyncio.to_thread(
            risorse().posta_invio, config, impostazioni.chiave_cifratura, destinatario,
            f"Prova della posta in uscita - {e.nome}",
            f"Questa è un'email di prova inviata da Atti PA per {e.nome}.\n"
            "Se la ricevi, le notifiche (ad esempio le proposte dell'anticorruzione) arriveranno correttamente.\n",
            impostazioni.posta_timeout,
        )  # fmt: skip
    except posta.ErrorePosta as errore:
        return {"esito": "ERRORE", "messaggio": str(errore)}
    return {"esito": "OK", "messaggio": f"Email di prova inviata a {destinatario}"}


# --- strutture organizzative ---------------------------------------------------------------

IMPORTAZIONE_MAX_BYTE = 2 * 1024 * 1024


class Orario(BaseModel):
    """Fascia oraria di apertura al pubblico (es. "Lunedì e giovedì", "09:00", "12:30")."""

    giorni: str = Field(min_length=1, max_length=100)
    ora_inizio: str = Field(pattern=r"^\d{1,2}[:.]\d{2}$")
    ora_fine: str = Field(pattern=r"^\d{1,2}[:.]\d{2}$")


class StrutturaIn(BaseModel):
    codice: str = Field(min_length=1, max_length=50)
    descrizione: str = Field(min_length=1, max_length=255)
    padre_id: str | None = None
    ordine: int = 0
    attiva: bool = True
    # recapiti istituzionali (procedimenti, art. 35): facoltativi
    telefono: str | None = Field(default=None, max_length=50)
    peo: str | None = Field(default=None, max_length=255)
    pec: str | None = Field(default=None, max_length=255)
    sede: str | None = Field(default=None, max_length=255)
    orari: list[Orario] = Field(default_factory=list, max_length=20)
    responsabile: str | None = Field(default=None, max_length=255)
    qualifica: str | None = Field(default=None, max_length=255)


_RECAPITI = ("telefono", "peo", "pec", "sede", "responsabile", "qualifica")


def _struttura_out(s: Struttura) -> dict:
    return {
        "id": s.id, "codice": s.codice, "descrizione": s.descrizione,
        "padre_id": s.padre_id, "ordine": s.ordine, "attiva": s.attiva,
        **{k: getattr(s, k) for k in _RECAPITI}, "orari": s.orari or [],
    }  # fmt: skip


def _imposta_recapiti(s: Struttura, dati: StrutturaIn) -> None:
    for campo, valore in (("peo", dati.peo), ("pec", dati.pec)):
        if valore and valore.strip() and not posta.indirizzo_valido(valore.strip()):
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"{campo.upper()}: indirizzo email non valido")
    for k in _RECAPITI:
        setattr(s, k, (getattr(dati, k) or "").strip() or None)
    s.orari = [o.model_dump() for o in dati.orari] or None


async def _strutture(sessione) -> list[Struttura]:
    return list(
        (await sessione.scalars(
            select(Struttura).where(Struttura.ente_id == ente().id).order_by(Struttura.ordine, Struttura.codice)
        )).all()
    )  # fmt: skip


async def _struttura_dell_ente(sessione, struttura_id: str) -> Struttura:
    s = await sessione.get(Struttura, struttura_id)
    if s is None or s.ente_id != ente().id:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Struttura non trovata")
    return s


async def _controlla_padre(sessione, s: Struttura, padre_id: str | None) -> None:
    """Il padre è dell'ente e non è la struttura stessa né una sua sottostante."""
    if padre_id is None:
        return
    padre = await _struttura_dell_ente(sessione, padre_id)
    padri = {x.id: x.padre_id for x in await _strutture(sessione)}
    corrente: str | None = padre.id
    while corrente is not None:
        if corrente == s.id:
            raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Una struttura non può stare sotto sé stessa")
        corrente = padri.get(corrente)


async def _codice_libero(sessione, codice: str, escluso: str | None = None) -> None:
    q = select(Struttura).where(Struttura.ente_id == ente().id, Struttura.codice == codice)
    trovata = await sessione.scalar(q)
    if trovata is not None and trovata.id != escluso:
        raise ErroreApi(HTTPStatus.CONFLICT, f"Codice già usato: {codice}")


@bp.get("/strutture")
@autenticato(modulo=None)
async def elenco_strutture():
    """Strutture dell'ente (anche disattivate), per ordine e codice: per tutti gli utenti, che
    le scelgono nei moduli."""
    return [_struttura_out(s) for s in await _strutture(db())]


@bp.post("/strutture")
@amministratore_ente
async def crea_struttura():
    dati = corpo(StrutturaIn)
    sessione = db()
    s = Struttura(ente_id=ente().id, codice=dati.codice.strip(), descrizione=dati.descrizione.strip(),
                  ordine=dati.ordine, attiva=dati.attiva)  # fmt: skip
    _imposta_recapiti(s, dati)
    await _codice_libero(sessione, s.codice)
    await _controlla_padre(sessione, s, dati.padre_id)
    s.padre_id = dati.padre_id
    sessione.add(s)
    await sessione.flush()
    audit(sessione, utente(), "struttura", s.id, "CREATA", {"codice": s.codice})
    await sessione.commit()
    return _struttura_out(s), HTTPStatus.CREATED


@bp.put("/strutture/<struttura_id>")
@amministratore_ente
async def aggiorna_struttura(struttura_id: str):
    dati = corpo(StrutturaIn)
    sessione = db()
    s = await _struttura_dell_ente(sessione, struttura_id)
    await _codice_libero(sessione, dati.codice.strip(), escluso=s.id)
    await _controlla_padre(sessione, s, dati.padre_id)
    s.codice, s.descrizione = dati.codice.strip(), dati.descrizione.strip()
    s.padre_id, s.ordine, s.attiva = dati.padre_id, dati.ordine, dati.attiva
    _imposta_recapiti(s, dati)
    audit(sessione, utente(), "struttura", s.id, "AGGIORNATA", {"codice": s.codice, "attiva": s.attiva})
    await sessione.commit()
    return _struttura_out(s)


@bp.delete("/strutture/<struttura_id>")
@amministratore_ente
async def elimina_struttura(struttura_id: str):
    """Solo se non ha strutture sottostanti né utenti; altrimenti si disattiva."""
    sessione = db()
    s = await _struttura_dell_ente(sessione, struttura_id)
    figlie = await sessione.scalar(select(func.count()).select_from(Struttura).where(Struttura.padre_id == s.id))
    utenti = await sessione.scalar(select(func.count()).select_from(User).where(User.struttura_id == s.id))
    if figlie or utenti:
        raise ErroreApi(
            HTTPStatus.CONFLICT,
            "La struttura ha strutture sottostanti o utenti assegnati: disattivala invece di eliminarla",
        )
    audit(sessione, utente(), "struttura", s.id, "ELIMINATA", {"codice": s.codice})
    await sessione.delete(s)
    await sessione.commit()
    return nessun_contenuto()


def _righe_importazione(contenuto: bytes, nome: str) -> list[dict[str, str]]:
    """Righe di un file Excel (.xlsx) o CSV con le colonne codice, descrizione e padre
    (codice della struttura superiore, facoltativo); la prima riga è l'intestazione."""
    if nome.lower().endswith(".xlsx"):
        import openpyxl

        foglio = openpyxl.load_workbook(io.BytesIO(contenuto), read_only=True, data_only=True).active
        tabella = [["" if v is None else str(v).strip() for v in r] for r in foglio.iter_rows(values_only=True)]
    elif nome.lower().endswith(".csv"):
        testo = contenuto.decode("utf-8-sig", errors="replace")
        dialetto = csv.Sniffer().sniff(testo.split("\n", 1)[0], delimiters=";,\t")
        tabella = [[v.strip() for v in r] for r in csv.reader(io.StringIO(testo), dialetto)]
    else:
        raise ErroreApi(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Formato non ammesso: usa un file .xlsx o .csv")
    if not tabella:
        return []
    intestazione = [c.lower() for c in tabella[0]]
    if "codice" not in intestazione or "descrizione" not in intestazione:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "Servono le colonne codice e descrizione (e facoltativa padre)")
    righe = []
    for r in tabella[1:]:
        valori = dict(zip(intestazione, r, strict=False))
        if valori.get("codice"):
            righe.append({k: valori.get(k, "") for k in ("codice", "descrizione", "padre")})
    return righe


@bp.post("/strutture/importa")
@amministratore_ente
async def importa_strutture():
    """Crea o aggiorna (per codice) le strutture di un file, nell'ordine del file; quelle che
    non compaiono restano come sono."""
    file = file_caricato()
    contenuto = file.read(IMPORTAZIONE_MAX_BYTE + 1)
    if len(contenuto) > IMPORTAZIONE_MAX_BYTE:
        raise ErroreApi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File troppo grande (massimo 2 MB)")
    try:
        righe = _righe_importazione(contenuto, file.filename or "")
    except (ValueError, csv.Error) as e:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"File non leggibile: {e}") from e
    sessione = db()
    esistenti = {s.codice: s for s in await _strutture(sessione)}
    nel_file = {r["codice"] for r in righe}
    errori = [
        f"{r['codice']}: struttura superiore {r['padre']} non trovata"
        for r in righe
        if r["padre"] and r["padre"] not in esistenti and r["padre"] not in nel_file
    ]
    errori += [f"{r['codice']}: descrizione mancante" for r in righe if not r["descrizione"]]
    errori += [f"{r['codice']}: codice o descrizione troppo lunghi" for r in righe
               if len(r["codice"]) > 50 or len(r["descrizione"]) > 255]  # fmt: skip
    if errori:
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, "; ".join(errori[:20]))
    create = aggiornate = 0
    for ordine, r in enumerate(righe, start=1):
        s = esistenti.get(r["codice"])
        if s is None:
            s = Struttura(ente_id=ente().id, codice=r["codice"], attiva=True)
            sessione.add(s)
            esistenti[s.codice] = s
            create += 1
        else:
            aggiornate += 1
        s.descrizione, s.ordine = r["descrizione"], ordine
    await sessione.flush()
    for r in righe:  # i padri dopo: possono comparire più avanti nel file
        esistenti[r["codice"]].padre_id = esistenti[r["padre"]].id if r["padre"] else None
    padri = {s.id: s.padre_id for s in esistenti.values()}
    for s in esistenti.values():
        visti, corrente = set(), s.id
        while corrente is not None:
            if corrente in visti:
                raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, f"Gerarchia circolare a partire da {s.codice}")
            visti.add(corrente)
            corrente = padri.get(corrente)
    audit(sessione, utente(), "struttura", ente().id, "IMPORTATE", {"create": create, "aggiornate": aggiornate})
    await sessione.commit()
    return {"create": create, "aggiornate": aggiornate}


# --- utenti --------------------------------------------------------------------------------


def _utente_out(u: User) -> dict:
    return {**UtenteOut.model_validate(u).model_dump(mode="json"), "attivo": u.attivo}


@bp.get("/utenti")
@amministratore_ente
async def elenco_utenti():
    utenti = (
        await db().scalars(select(User).where(User.ente_id == ente().id).order_by(User.username))
    ).all()
    return [_utente_out(u) for u in utenti]


def _ruoli(v: list[str]) -> list[str]:
    sconosciuti = set(v) - set(Ruolo.TUTTI)
    if sconosciuti:
        raise ValueError(f"Ruoli sconosciuti: {', '.join(sorted(sconosciuti))}")
    return [r for r in Ruolo.TUTTI if r in v]


class UtenteNuovoIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._@-]{2,100}$")
    nome_completo: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    ruoli: list[str] = Field(min_length=1)
    password: str
    struttura_id: str | None = None

    @field_validator("ruoli")
    @classmethod
    def _controlla_ruoli(cls, v: list[str]) -> list[str]:
        return _ruoli(v)


class UtenteIn(BaseModel):
    nome_completo: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    ruoli: list[str] | None = None  # solo utenti locali: quelli AD vengono dai gruppi
    attivo: bool = True
    struttura_id: str | None = None  # anche per gli utenti AD

    @field_validator("ruoli")
    @classmethod
    def _controlla_ruoli(cls, v: list[str] | None) -> list[str] | None:
        return v if v is None else _ruoli(v)


class NuovaPasswordIn(BaseModel):
    password: str


@bp.post("/utenti")
@amministratore_ente
async def crea_utente():
    """Utente locale dell'ente (per chi non è in Active Directory)."""
    dati = corpo(UtenteNuovoIn)
    e = ente()
    if not e.accesso_locale:
        raise ErroreApi(HTTPStatus.CONFLICT, "L'accesso con utenti locali non è abilitato per l'ente")
    if errore := pw.controlla_nuova(dati.password):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, errore)
    sessione = db()
    username = dati.username.lower()
    if await sessione.scalar(select(User).where(User.ente_id == e.id, User.username == username)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Nome utente già usato")
    if dati.struttura_id:
        await _struttura_dell_ente(sessione, dati.struttura_id)
    u = User(
        ente_id=e.id, username=username, origine=OrigineUtente.LOCALE,
        password_hash=pw.calcola(dati.password), cambio_password=True,
        nome_completo=dati.nome_completo, email=dati.email, ruoli=dati.ruoli,
        struttura_id=dati.struttura_id,
    )  # fmt: skip
    sessione.add(u)
    await sessione.flush()
    audit(sessione, utente(), "utente", u.id, "CREATO", {"username": username, "ruoli": dati.ruoli})
    await sessione.commit()
    return _utente_out(u), HTTPStatus.CREATED


async def _utente_dell_ente(sessione, utente_id: str) -> User:
    u = await sessione.get(User, utente_id)
    if u is None or u.ente_id != ente().id:
        raise ErroreApi(HTTPStatus.NOT_FOUND, "Utente non trovato")
    return u


@bp.put("/utenti/<utente_id>")
@amministratore_ente
async def aggiorna_utente(utente_id: str):
    dati = corpo(UtenteIn)
    sessione = db()
    u = await _utente_dell_ente(sessione, utente_id)
    if u.id == utente().id and (not dati.attivo or (dati.ruoli is not None and Ruolo.ADMIN not in dati.ruoli)):
        raise ErroreApi(HTTPStatus.CONFLICT, "Non puoi disattivarti né toglierti il ruolo di amministratore")
    if u.origine == OrigineUtente.LOCALE:
        u.nome_completo = dati.nome_completo
        u.email = dati.email
        if dati.ruoli is not None:
            u.ruoli = dati.ruoli
    if dati.struttura_id:
        await _struttura_dell_ente(sessione, dati.struttura_id)
    u.struttura_id = dati.struttura_id
    if u.attivo and not dati.attivo:
        u.token_version = (u.token_version or 0) + 1  # chiude le sessioni aperte
    u.attivo = dati.attivo
    audit(sessione, utente(), "utente", u.id, "AGGIORNATO",
          {"attivo": u.attivo, "ruoli": u.ruoli, "struttura_id": u.struttura_id})  # fmt: skip
    await sessione.commit()
    return _utente_out(u)


@bp.put("/utenti/<utente_id>/password")
@amministratore_ente
async def reimposta_password(utente_id: str):
    dati = corpo(NuovaPasswordIn)
    if errore := pw.controlla_nuova(dati.password):
        raise ErroreApi(HTTPStatus.UNPROCESSABLE_ENTITY, errore)
    sessione = db()
    u = await _utente_dell_ente(sessione, utente_id)
    if u.origine != OrigineUtente.LOCALE:
        raise ErroreApi(HTTPStatus.BAD_REQUEST, "La password di dominio si cambia in Active Directory")
    u.password_hash = pw.calcola(dati.password)
    u.cambio_password = u.id != utente().id
    u.token_version = (u.token_version or 0) + 1
    audit(sessione, utente(), "utente", u.id, "PASSWORD_REIMPOSTATA")
    await sessione.commit()
    return _utente_out(u)
