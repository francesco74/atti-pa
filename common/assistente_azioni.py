"""Azioni dell'assistente sui documenti della conversazione: Riassumi, Confronta, Estrai
(progettazione/assistente_documenti.md). Le esegue il worker (worker/src/assistente.py).

Un documento intero non entra nel contesto dell'LLM e, anche quando ci entra, il modello usa
male la parte centrale. Per questo si lavora a blocchi (map-reduce):

1. le parti (sezioni) di ogni documento si leggono in ordine dalla sessione del RAG e si
   raggruppano in blocchi consecutivi di al massimo ASSISTENTE_CARATTERI_BLOCCO caratteri;
2. ogni blocco va all'LLM da solo: riassunto della parte, scheda della parte o elementi
   estratti, sempre con le parti citate;
3. i risultati parziali si uniscono a gruppi finché non stanno in una sola chiamata
   (ASSISTENTE_CARATTERI_PASSAGGI);
4. un'ultima chiamata scrive il risultato: riassunto di ogni documento, confronto tra le
   schede, tabella degli elementi senza duplicati.

Ogni chiamata ha quindi un contesto corto. Dopo ogni chiamata si segnala l'avanzamento: se
il lavoro non c'è più (annullato dall'utente) l'azione si interrompe.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from common.llm import testo_prompt

log = logging.getLogger("common.assistente_azioni")

RIASSUNTO = "RIASSUNTO"
CONFRONTO = "CONFRONTO"
ESTRAZIONE = "ESTRAZIONE"
TIPI = (RIASSUNTO, CONFRONTO, ESTRAZIONE)

SEZIONI_PER_RICHIESTA = 50  # massimo della lettura in ordine del RAG
NESSUNO = "NESSUNO"  # risposta di un blocco senza elementi da estrarre

UNIONI = {
    RIASSUNTO: "riassunti di parti consecutive dello stesso documento: uniscili in un unico "
    "riassunto più breve, nell'ordine del documento",
    CONFRONTO: "schede di parti dello stesso documento: uniscile in un'unica scheda del documento, "
    "con le stesse voci",
    ESTRAZIONE: "elenchi di elementi estratti da parti dei documenti: uniscili in un unico elenco, "
    "togliendo i duplicati",
}

# (fatti, totale) -> False se il lavoro non c'è più
Avanzamento = Callable[[int, int], Awaitable[bool]]


class AzioneNonEseguibile(ValueError):
    """Errore della richiesta (documento vuoto, troppo lungo): ritentare non serve."""


class AzioneInterrotta(Exception):
    """Il lavoro è stato annullato dall'utente."""


@dataclass
class Documento:
    id: str
    nome: str


@dataclass
class Blocco:
    documento: str
    prima: int  # parti numerate da 1
    ultima: int
    testo: str

    @property
    def parti(self) -> str:
        return f"parte {self.prima}" if self.prima == self.ultima else f"parti {self.prima}-{self.ultima}"


async def leggi_blocchi(rag, sessione: str, documento: Documento, max_caratteri: int) -> list[Blocco]:
    """Parti del documento in ordine, raggruppate in blocchi consecutivi. Ogni parte porta
    l'etichetta che l'LLM userà per citarla."""
    parti: list[tuple[int, str]] = []
    da = 0
    while True:
        r = await rag.sezioni(sessione, documento.id, da, SEZIONI_PER_RICHIESTA)
        sezioni = r.get("sections") or []
        for s in sezioni:
            numero = int(s["index"]) + 1
            parti.append((numero, f"[{documento.nome}, parte {numero}]\n{s['content'].strip()}"))
        if len(sezioni) < SEZIONI_PER_RICHIESTA:
            break
        da = int(sezioni[-1]["index"]) + 1
    if not parti:
        raise AzioneNonEseguibile(f"Il documento {documento.nome} non ha testo")
    blocchi: list[Blocco] = []
    for numero, testo in parti:
        if testo and len(testo) > max_caratteri:
            testo = testo[:max_caratteri] + " […]"
        ultimo = blocchi[-1] if blocchi else None
        if ultimo and len(ultimo.testo) + len(testo) + 2 <= max_caratteri:
            ultimo.testo += "\n\n" + testo
            ultimo.ultima = numero
        else:
            blocchi.append(Blocco(documento.nome, numero, numero, testo))
    return blocchi


class Esecuzione:
    """Una azione: conta le chiamate all'LLM e segnala l'avanzamento dopo ognuna."""

    def __init__(self, llm, avanza: Avanzamento, max_caratteri_unione: int):
        self.llm = llm
        self.avanza = avanza
        self.max_unione = max_caratteri_unione
        self.fatti = 0
        self.totale = 0
        self.sistema = testo_prompt("azioni_sistema")

    async def _chiama(self, nome: str, **valori: str) -> str:
        risposta = (await self.llm.elabora(self.sistema, testo_prompt(nome, **valori))).strip()
        self.fatti += 1
        if not await self.avanza(self.fatti, max(self.totale, self.fatti)):
            raise AzioneInterrotta()
        return risposta

    async def riduci(self, tipo: str, testi: list[str], istruzioni: str) -> list[str]:
        """Unisce i risultati parziali a gruppi consecutivi finché non stanno in una chiamata."""
        while len(testi) > 1 and sum(len(t) + 2 for t in testi) > self.max_unione:
            gruppi: list[list[str]] = [[]]
            for t in testi:
                if gruppi[-1] and sum(len(x) + 2 for x in gruppi[-1]) + len(t) > self.max_unione:
                    gruppi.append([])
                gruppi[-1].append(t)
            if len(gruppi) == len(testi):  # ogni testo da solo supera il limite: si accorciano
                testi = [t[: self.max_unione // 2] + " […]" for t in testi]
                continue
            self.totale += sum(1 for g in gruppi if len(g) > 1)
            nuovi = []
            for g in gruppi:
                if len(g) == 1:
                    nuovi.append(g[0])
                else:
                    nuovi.append(await self._chiama(
                        "azione_unisci", compito=UNIONI[tipo], parziali="\n\n---\n\n".join(g), istruzioni=istruzioni))  # fmt: skip
            testi = nuovi
        return testi

    async def riassumi(self, documenti: list[tuple[Documento, list[Blocco]]], istruzioni: str) -> str:
        sezioni = []
        for documento, blocchi in documenti:
            if len(blocchi) == 1:
                contenuto = blocchi[0].testo
            else:
                parziali = []
                for b in blocchi:
                    riassunto = await self._chiama(
                        "azione_riassunto_parte", documento=documento.nome, parti=b.parti, testo=b.testo,
                        istruzioni=istruzioni)  # fmt: skip
                    parziali.append(f"Riassunto delle {b.parti} di {documento.nome}:\n{riassunto}")
                contenuto = "\n\n".join(await self.riduci(RIASSUNTO, parziali, istruzioni))
            riassunto = await self._chiama("azione_riassunto", documento=documento.nome, contenuto=contenuto,
                                           istruzioni=istruzioni)  # fmt: skip
            sezioni.append(f"## {documento.nome}\n\n{riassunto}" if len(documenti) > 1 else riassunto)
        return "\n\n".join(sezioni)

    async def confronta(self, documenti: list[tuple[Documento, list[Blocco]]], istruzioni: str) -> str:
        schede = []
        for documento, blocchi in documenti:
            parziali = [
                await self._chiama("azione_scheda", documento=documento.nome, parti=b.parti, testo=b.testo,
                                   istruzioni=istruzioni)  # fmt: skip
                for b in blocchi
            ]
            if len(parziali) > 1:
                parziali = await self.riduci(CONFRONTO, parziali, istruzioni)
            schede.append(f"### Scheda di {documento.nome}\n\n" + "\n\n".join(parziali))
        testo = "\n\n".join(schede)
        if len(testo) > self.max_unione:  # molti documenti lunghi: ogni scheda si accorcia
            quota = self.max_unione // len(schede)
            testo = "\n\n".join(s[:quota] for s in schede)
        return await self._chiama("azione_confronto", schede=testo, istruzioni=istruzioni)

    async def estrai(self, documenti: list[tuple[Documento, list[Blocco]]], istruzioni: str) -> str:
        trovati = []
        for documento, blocchi in documenti:
            for b in blocchi:
                elementi = await self._chiama(
                    "azione_estrai_parte", documento=documento.nome, parti=b.parti, testo=b.testo, istruzioni=istruzioni)  # fmt: skip
                if elementi and elementi.strip().strip(".").upper() != NESSUNO:
                    trovati.append(elementi)
        if not trovati:
            return "Nei documenti selezionati non ho trovato elementi corrispondenti alla richiesta."
        trovati = await self.riduci(ESTRAZIONE, trovati, istruzioni)
        return await self._chiama("azione_estrai", elementi="\n\n---\n\n".join(trovati), istruzioni=istruzioni)


async def esegui(
    tipo: str,
    rag,
    sessione: str,
    documenti: list[Documento],
    istruzioni: str,
    llm,
    avanza: Avanzamento,
    *,
    caratteri_blocco: int,
    caratteri_unione: int,
    max_blocchi: int,
) -> str:
    """Esegue l'azione e restituisce il risultato in Markdown."""
    if tipo not in TIPI:
        raise AzioneNonEseguibile(f"Azione sconosciuta: {tipo}")
    letti = [(d, await leggi_blocchi(rag, sessione, d, caratteri_blocco)) for d in documenti]
    n_blocchi = sum(len(b) for _, b in letti)
    if n_blocchi > max_blocchi:
        raise AzioneNonEseguibile(
            f"I documenti selezionati sono troppo lunghi per questa azione ({n_blocchi} blocchi, al massimo "
            f"{max_blocchi}): selezionane meno"
        )
    e = Esecuzione(llm, avanza, caratteri_unione)
    if tipo == RIASSUNTO:
        e.totale = sum(len(b) if len(b) > 1 else 0 for _, b in letti) + len(letti)
    else:
        e.totale = n_blocchi + 1
    await avanza(0, e.totale)
    log.info("Azione %s su %d documenti: %d blocchi, %d chiamate previste", tipo, len(documenti), n_blocchi, e.totale)
    istruzioni = istruzioni.strip() or "nessuna"
    if tipo == RIASSUNTO:
        return await e.riassumi(letti, istruzioni)
    if tipo == CONFRONTO:
        return await e.confronta(letti, istruzioni)
    return await e.estrai(letti, istruzioni)
