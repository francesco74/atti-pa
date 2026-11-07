# Modulo Performance — programmazione e monitoraggio degli obiettivi

Modulo `performance` del Sistema integrato di supporto al RPCT, attivabile per ente con
`enti.py moduli CODICE ...,performance`. Serve a dichiarare e monitorare gli obiettivi di
performance delle strutture rispetto al PIAO. In Si.Ge.Ri.Co. gli obiettivi erano solo un
catalogo importato da Excel dal Piano della Performance (codice, titolo, tipo, annualità,
centro di responsabilità) e agganciato agli elementi della mappatura; qui sono dichiarati da
dirigenti e responsabili e si compongono di azioni e misure con pesi e avanzamento.

## 1. Concetti

- **PIAO**: triennale (es. 2026-2028), creato dall'amministratore della performance con titolo
  e atto di approvazione. **Aperto**: gli obiettivi si dichiarano e si aggiornano. **Chiuso**:
  tutto in sola lettura (l'amministratore può riaprirlo). Si elimina solo se non ha obiettivi.
- **Obiettivo**: di una struttura (servizio o ufficio) per **un anno** del triennio. Ha il
  codice nel PIAO (facoltativo, es. `P2_OS3_OO1_OG1_26_2`), titolo, descrizione, tipo
  (Operativo, Funzionamento, Miglioramento, come in Si.Ge.Ri.Co.) e la **percentuale di
  impegno** rispetto agli altri obiettivi della struttura nello stesso anno.
- **Azioni e misure** dell'obiettivo: l'azione è descrittiva; la misura si sceglie tra quelle
  della mappatura dei rischi (modulo anticorruzione, con una copia di codice e descrizione: il
  riferimento resta se la mappatura cambia). Ciascuna ha la percentuale di **impegno**
  rispetto alle altre dello stesso obiettivo, quella di **completamento** (inserita qui, anche
  per le misure) e la **data massima di completamento**.

## 2. Regole e calcoli (`common/performance`)

- Gli impegni di un insieme (obiettivi di una struttura in un anno; azioni e misure di un
  obiettivo) **non possono superare 100**: l'API rifiuta il salvataggio indicando quanto è
  disponibile. Finché non arrivano a 100 l'insieme è segnato **incompleto**.
- **Completamento dell'obiettivo** = media dei completamenti delle azioni e misure pesata con
  il loro impegno; **completamento della struttura** nell'anno = media dei completamenti degli
  obiettivi pesata con il loro impegno (un obiettivo senza azioni conta 0). Con gli impegni
  sotto 100 il valore si calcola sui pesi presenti ed è provvisorio.
- **Ritardo**: scadenza passata con il completamento sotto 100.

## 2-bis. Controlli (07/11/2026)

Sull'obiettivo, senza modello (`controlli_obiettivo` in `common/performance`): impegno 0% (di
obiettivi, azioni o misure), scadenze fuori dall'anno dell'obiettivo, misure non più nella
mappatura o attribuite nella mappatura a un'altra struttura, obiettivo senza azioni o senza
misure della mappatura. Nell'elenco il numero degli avvisi, nel dettaglio l'elenco.

## 3. Ruoli

| Ruolo | Può |
|---|---|
| `PERFORMANCE_RESPONSABILE` (dirigente di un servizio, responsabile di un ufficio) | dichiarare e aggiornare gli obiettivi della **propria struttura** (quella del suo utente); vedere in sola lettura quelli delle strutture sottostanti |
| `PERFORMANCE_AMMINISTRATORE` | creare, aprire, chiudere ed eliminare i PIAO; vedere e correggere gli obiettivi di tutte le strutture; consultare lo storico dell'intero PIAO |
| `ADMIN` | come l'amministratore della performance |

Gruppi di Active Directory predefiniti: `ATTI-PA-Performance-Responsabili`,
`ATTI-PA-Performance-Amministratori`.

## 4. Storico delle modifiche

Ogni creazione, modifica ed eliminazione di PIAO, obiettivi, azioni e misure va in
`pf_modifiche`: chi, quando, l'elemento (descrizione al momento della modifica) e i campi
cambiati con il valore **prima e dopo**, più una nota facoltativa (motivo). Un salvataggio
senza cambiamenti non registra nulla. Lo storico resta dopo l'eliminazione; si consulta
dall'obiettivo (sue azioni e misure comprese) e, per l'amministratore, per l'intero PIAO.

## 5. Organizzazione

```
common/performance/               regole e calcoli (media pesata, disponibile, ritardo)
api/src/routers/performance.py    /api/v1/performance/...
frontend/src/lib/ui/performance/  schede: Obiettivi, Riepilogo, PIAO (amministratore)
tabelle: pf_piao, pf_obiettivi, pf_elementi, pf_modifiche
```

API: `contesto`, `piao` (+ `/<id>`, `/<id>/storico`), `obiettivi` (filtri PIAO, anno,
struttura; con il riepilogo della struttura), `obiettivi/<id>` (+ `/elementi`, `/storico`),
`elementi/<id>`, `misure` (della mappatura, quelle della struttura per prime), `riepilogo`.

## 6. Decisioni (05/11/2026)

1. Obiettivi **annuali** dentro il PIAO triennale; impegni sommati per struttura e anno.
2. Impegni **obbligatoriamente** non oltre 100%; insieme completo solo a 100%.
3. Il completamento delle misure si **inserisce nella performance** (non dal monitoraggio
   anticorruzione).
4. **Nessuna validazione** degli obiettivi: li dichiara e modifica il responsabile, ogni
   modifica è tracciata; il controllo è nella chiusura del PIAO.
5. Dirigenti e responsabili hanno lo stesso ruolo: servizio o ufficio dipende dalla struttura
   assegnata all'utente (gerarchia delle strutture organizzative).

## 6-bis. Relazione sulla performance (07/11/2026)

Scheda "Relazione" dell'amministratore: per un PIAO e un anno, sintesi (obiettivi, strutture,
obiettivi completati, completamento medio, azioni e misure, ritardi a fine anno o a oggi,
strutture con impegni non al 100%) con la tabella per struttura, ed elenco degli obiettivi. Testo
scritto dal modello dai soli dati, numeri da verificare, esportazione in DOCX/ODT: come le
relazioni dell'anticorruzione (`anticorruzione.md`, decisione 23).

## 7. Da fare

- importazione degli obiettivi da Excel del Piano (come in Si.Ge.Ri.Co.);
- notifiche email (es. scadenze vicine o passate);
- collegamento degli obiettivi a processi e attività della mappatura.
