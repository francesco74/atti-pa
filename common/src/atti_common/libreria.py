"""Accesso alla libreria normativa con cache per data di vigenza.

Il testo di un articolo viene letto dalla cache se esiste una versione che copre la data
richiesta; altrimenti viene scaricato da Normattiva alla data e salvato.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atti_common.models import NormaArticoloVersione, NormaAtto
from atti_common.normattiva import (
    NormattivaClient,
    RisultatoAmbiguo,
    TestoArticolo,
    Urn,
    testo_principale,
)
from atti_common.normattiva.citazioni import citazione_atto


async def versione_alla_data(
    db: AsyncSession, urn_atto: str, articolo: str, giorno: date
) -> NormaArticoloVersione | None:
    return await db.scalar(
        select(NormaArticoloVersione)
        .where(
            NormaArticoloVersione.urn_atto == urn_atto,
            NormaArticoloVersione.articolo == articolo,
            or_(
                NormaArticoloVersione.vigenza_inizio.is_(None),
                NormaArticoloVersione.vigenza_inizio <= giorno,
            ),
            or_(
                NormaArticoloVersione.vigenza_fine.is_(None),
                NormaArticoloVersione.vigenza_fine >= giorno,
            ),
        )
        .order_by(NormaArticoloVersione.vigenza_inizio.desc())
        .limit(1)
    )


async def scarica_testo(client: NormattivaClient, urn: Urn, giorno: date) -> TestoArticolo:
    try:
        return await client.articolo(urn, vigenza=giorno)
    except RisultatoAmbiguo as e:
        testo = testo_principale(e)
        if testo is None:
            raise
        return testo


async def assicura_atto(db: AsyncSession, urn_atto: str, testo: TestoArticolo) -> NormaAtto:
    atto = await db.get(NormaAtto, urn_atto)
    if atto is None:
        u = Urn.parse(urn_atto)
        atto = NormaAtto(
            urn=urn_atto,
            denominazione=testo.denominazione or u.denominazione.upper(),
            data_provvedimento=testo.data_provvedimento or date.fromisoformat(u.data),
            numero=testo.numero or u.numero,
            titolo=testo.sottotitolo,
            citazione=citazione_atto(u),
            data_gu=testo.data_gu,
        )
        db.add(atto)
        await db.flush()
    return atto


async def salva_versione(
    db: AsyncSession, urn_atto: str, articolo: str, testo: TestoArticolo
) -> NormaArticoloVersione:
    await assicura_atto(db, urn_atto, testo)
    a = testo.articolo
    versione = await db.scalar(
        select(NormaArticoloVersione).where(
            NormaArticoloVersione.urn_atto == urn_atto,
            NormaArticoloVersione.articolo == articolo,
            NormaArticoloVersione.vigenza_inizio == testo.vigenza_inizio
            if testo.vigenza_inizio
            else NormaArticoloVersione.vigenza_inizio.is_(None),
        )
    )
    if versione is None:
        versione = NormaArticoloVersione(urn_atto=urn_atto, articolo=articolo)
        db.add(versione)
    versione.rubrica = a.rubrica
    versione.vigenza_inizio = testo.vigenza_inizio
    versione.vigenza_fine = testo.vigenza_fine
    versione.struttura_json = a.to_dict()
    versione.testo_html = testo.html
    versione.hash_testo = a.hash()
    versione.rinvii_json = a.rinvii
    await db.flush()
    return versione


async def articolo_alla_data(
    db: AsyncSession,
    client: NormattivaClient,
    urn_atto: str,
    articolo: str,
    giorno: date,
) -> NormaArticoloVersione:
    """Versione dell'articolo vigente alla data, dalla cache o da Normattiva."""
    versione = await versione_alla_data(db, urn_atto, articolo, giorno)
    if versione is not None:
        return versione
    urn = Urn.parse(urn_atto).con_articolo(articolo)
    testo = await scarica_testo(client, urn, giorno)
    versione = await salva_versione(db, urn_atto, articolo, testo)
    await db.commit()
    return versione


def trova_partizione(
    struttura: dict, comma: str | None, lettera: str | None
) -> tuple[bool, str | None]:
    """Cerca comma e lettera nella struttura di un articolo.

    Restituisce (trovato, testo della partizione più specifica).
    """
    commi = struttura.get("commi") or []
    if not comma:
        return True, "\n".join(f"{c['numero']}. {c['testo']}" for c in commi)
    c = next((c for c in commi if c["numero"] == comma), None)
    if c is None:
        return False, None
    if not lettera:
        return True, c["testo"]
    lett = next((x for x in c.get("lettere") or [] if x["lettera"] == lettera), None)
    if lett is None:
        return False, None
    return True, f"{c.get('alinea') or ''} {lettera}) {lett['testo']}".strip()
