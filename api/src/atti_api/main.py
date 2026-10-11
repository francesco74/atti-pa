from datetime import date
from typing import Annotated

from atti_common.normattiva import (
    ATTRIBUZIONE,
    AttoNonTrovato,
    NormattivaClient,
    NormattivaError,
    RisultatoAmbiguo,
    Urn,
)
from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="atti-pa", version="0.1.0")


@app.get("/api/v1/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/norme/articolo")
async def leggi_articolo(
    urn: Annotated[str, Query(examples=["urn:nir:stato:decreto.legislativo:2023-03-31;36~art50"])],
    vigenza: Annotated[date | None, Query(description="Data di vigenza (default: oggi)")] = None,
) -> dict:
    """Testo di un articolo da Normattiva, scomposto in commi e lettere."""
    try:
        u = Urn.parse(urn)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    async with NormattivaClient() as client:
        try:
            testo = await client.articolo(u, vigenza)
        except AttoNonTrovato as e:
            raise HTTPException(404, "Articolo non trovato su Normattiva") from e
        except RisultatoAmbiguo as e:
            raise HTTPException(
                409,
                {
                    "messaggio": "La URN corrisponde a più testi",
                    "candidati": [
                        {"titolo": c.titolo_atto, "sottotitolo": c.sottotitolo} for c in e.candidati
                    ],
                },
            ) from e
        except NormattivaError as e:
            raise HTTPException(502, str(e)) from e

    return {
        "urn": testo.urn,
        "atto": testo.titolo_atto,
        "vigenza_inizio": testo.vigenza_inizio,
        "vigenza_fine": testo.vigenza_fine,
        "articolo": testo.articolo.to_dict(),
        "fonte": ATTRIBUZIONE,
    }
