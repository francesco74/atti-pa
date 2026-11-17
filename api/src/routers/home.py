"""Pagina iniziale (Home) dopo l'accesso: il messaggio dell'amministratore dell'ente e le cose
"da fare" per l'utente, secondo i suoi moduli e ruoli, ognuna con la voce del menu dove si
fanno. Solo conteggi di dati che i moduli hanno già; quelle a zero non compaiono.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint
from sqlalchemy import func, select

from deps import autenticato, db, ente, ente_id, utente
from common.models import (
    AcProposta, Bozza, Modulo, PfElemento, PfObiettivo, PfPiao, PfProposta, Ruolo, SessioneControllo, Struttura,
)  # fmt: skip
from common.performance import in_ritardo

bp = Blueprint("home", __name__, url_prefix="/api/v1/home")


def _voce(voce: str, dove: str | None, n: int, uno: str, molti: str) -> dict | None:
    """Una cosa da fare (None se non ce n'è): voce del menu, scheda, testo con il numero."""
    if not n:
        return None
    return {"voce": voce, "dove": dove, "numero": n, "testo": uno if n == 1 else molti.format(n=n)}


async def _conta(q) -> int:
    return (await db().scalar(q)) or 0


async def _anticorruzione() -> list[dict | None]:
    u, sessione = utente(), db()
    da_fare = []
    if u.ha_ruolo(Ruolo.ADMIN, Ruolo.ANTICORRUZIONE_RPCT):
        n = await _conta(select(func.count()).select_from(AcProposta).where(AcProposta.ente_id == ente_id(), AcProposta.stato == "INVIATA"))
        da_fare.append(_voce("Anticorruzione", "Proposte", n, "1 proposta da decidere", "{n} proposte da decidere"))
    if u.ha_ruolo(Ruolo.ANTICORRUZIONE_REFERENTE):
        n = await _conta(select(func.count()).select_from(AcProposta).where(
            AcProposta.ente_id == ente_id(), AcProposta.utente_id == u.id, AcProposta.stato == "RESTITUITA"))  # fmt: skip
        da_fare.append(_voce("Anticorruzione", "Proposte", n, "1 tua proposta restituita da correggere",
                             "{n} tue proposte restituite da correggere"))  # fmt: skip
    if u.struttura_id and u.ha_ruolo(Ruolo.ADMIN, Ruolo.ANTICORRUZIONE_RPCT, Ruolo.ANTICORRUZIONE_REFERENTE):
        from routers.anticorruzione import misure_della_struttura

        strutture = {s.id: s for s in await sessione.scalars(select(Struttura).where(Struttura.ente_id == ente_id()))}
        if u.struttura_id in strutture:
            anno = date.today().year
            misure = await misure_della_struttura(sessione, strutture, u.struttura_id, anno)
            n = sum(1 for m in misure if m["dichiarazione"] is None)
            da_fare.append(_voce("Anticorruzione", "Monitoraggio", n, f"1 misura da dichiarare per il {anno}",
                                 f"{{n}} misure da dichiarare per il {anno}"))  # fmt: skip
    return da_fare


async def _performance() -> list[dict | None]:
    u, sessione = utente(), db()
    da_fare = []
    approvatore = u.ha_ruolo(Ruolo.ADMIN, Ruolo.PERFORMANCE_APPROVATORE)
    if approvatore:
        n = await _conta(select(func.count()).select_from(PfProposta).where(PfProposta.ente_id == ente_id(), PfProposta.stato == "INVIATA"))
        da_fare.append(_voce("Performance", "Proposte", n, "1 proposta da approvare", "{n} proposte da approvare"))
    if u.struttura_id and u.ha_ruolo(Ruolo.PERFORMANCE_RESPONSABILE):
        n = await _conta(select(func.count()).select_from(PfProposta).where(
            PfProposta.ente_id == ente_id(), PfProposta.struttura_id == u.struttura_id, PfProposta.stato == "RESTITUITA"))  # fmt: skip
        da_fare.append(_voce("Performance", "Proposte", n, "1 proposta restituita da correggere",
                             "{n} proposte restituite da correggere"))  # fmt: skip
    if u.struttura_id and (approvatore or u.ha_ruolo(Ruolo.PERFORMANCE_RESPONSABILE)):
        oggi = date.today()
        righe = await sessione.execute(
            select(PfElemento.scadenza, PfElemento.completamento).join(PfObiettivo, PfObiettivo.id == PfElemento.obiettivo_id)
            .join(PfPiao, PfPiao.id == PfObiettivo.piao_id)
            .where(PfObiettivo.ente_id == ente_id(), PfObiettivo.struttura_id == u.struttura_id, PfPiao.stato == "APERTO"))  # fmt: skip
        n = sum(1 for scadenza, completamento in righe if in_ritardo(scadenza, completamento, oggi))
        da_fare.append(_voce("Performance", "Obiettivi", n, "1 azione o misura in ritardo nella tua struttura",
                             "{n} azioni e misure in ritardo nella tua struttura"))  # fmt: skip
    return da_fare


async def _redazione() -> list[dict | None]:
    u = utente()
    da_fare = []
    if u.ha_ruolo(Ruolo.ADMIN, Ruolo.REDATTORE):
        n = await _conta(select(func.count()).select_from(Bozza).where(Bozza.ente_id == ente_id(), Bozza.owner_id == u.id))
        da_fare.append(_voce("Le mie bozze", None, n, "1 bozza in lavorazione", "{n} bozze in lavorazione"))
    if u.ha_ruolo(Ruolo.ADMIN, Ruolo.CONTROLLORE):
        n = await _conta(select(func.count()).select_from(SessioneControllo).where(
            SessioneControllo.ente_id == ente_id(), SessioneControllo.stato == "APERTA"))  # fmt: skip
        da_fare.append(_voce("Controllo atti", None, n, "1 sessione di controllo aperta", "{n} sessioni di controllo aperte"))
    return da_fare


@bp.get("")
@autenticato(modulo=None)
async def home():
    """Il messaggio dell'ente e le cose da fare dell'utente."""
    e = ente()
    da_fare: list[dict | None] = []
    if e.modulo_attivo(Modulo.REDAZIONE):
        da_fare += await _redazione()
    if e.modulo_attivo(Modulo.ANTICORRUZIONE):
        da_fare += await _anticorruzione()
    if e.modulo_attivo(Modulo.PERFORMANCE):
        da_fare += await _performance()
    return {"benvenuto": e.benvenuto, "da_fare": [v for v in da_fare if v]}
