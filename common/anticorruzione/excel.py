"""File Excel del modulo anticorruzione (monitoraggio, allegati al PTPCT): fogli con
l'intestazione in grassetto, bloccata, e le colonne larghe quanto serve (al massimo 60)."""

from __future__ import annotations

import io
from collections.abc import Iterable

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Foglio = tuple[str, list[str], Iterable[list]]  # titolo, intestazioni, righe


def cartella(fogli: list[Foglio]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    libro = Workbook()
    libro.remove(libro.active)
    for titolo, intestazioni, righe in fogli:
        f = libro.create_sheet(titolo[:31])  # limite di Excel
        f.append(intestazioni)
        for cella in f[1]:
            cella.font = Font(bold=True)
        larghezze = [len(i) for i in intestazioni]
        for riga in righe:
            valori = ["" if v is None else v for v in riga]
            f.append(valori)
            larghezze = [max(lg, min(len(str(v)), 60)) for lg, v in zip(larghezze, valori, strict=False)]
        for indice, larghezza in enumerate(larghezze, start=1):
            f.column_dimensions[f.cell(row=1, column=indice).column_letter].width = larghezza + 2
        for riga in f.iter_rows(min_row=2):
            for cella in riga:
                cella.alignment = Alignment(wrap_text=True, vertical="top")
        f.freeze_panes = "A2"
    dati = io.BytesIO()
    libro.save(dati)
    return dati.getvalue()


def foglio(titolo: str, intestazioni: list[str], righe: Iterable[list]) -> bytes:
    return cartella([(titolo, intestazioni, righe)])
