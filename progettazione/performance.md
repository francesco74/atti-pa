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
  rispetto alle altre dello stesso obiettivo, quella di **completamento** e la **data massima
  di completamento**.
- **Indicatori** di un'azione o misura (anche più d'uno): cosa si misura e il **valore da
  raggiungere** (target), es. "eventi a cui si partecipa: 3". Tipi: *numero* (con l'unità di
  misura), *percentuale*, *sì/no* (es. regolamento adottato), *data* (entro quando). Per numero e
  percentuale anche il valore di partenza (facoltativo) e il verso: *più alto è meglio* o *più
  basso è meglio* (es. giorni medi di attesa). Facoltativa la fonte del dato. Il target dice
  quanto fare, la scadenza dell'azione entro quando. Tabella `pf_indicatori`.

## 2. Regole e calcoli (`common/performance`)

- Gli impegni di un insieme (obiettivi di una struttura in un anno; azioni e misure di un
  obiettivo) **non possono superare 100**: l'API rifiuta il salvataggio indicando quanto è
  disponibile. Finché non arrivano a 100 l'insieme è segnato **incompleto**.
- **Completamento dell'obiettivo** = media dei completamenti delle azioni e misure pesata con
  il loro impegno; **completamento della struttura** nell'anno = media dei completamenti degli
  obiettivi pesata con il loro impegno (un obiettivo senza azioni conta 0). Con gli impegni
  sotto 100 il valore si calcola sui pesi presenti ed è provvisorio.
- **Ritardo**: scadenza passata con il completamento sotto 100.
- **Raggiungimento di un indicatore** (0-100): numero e percentuale, più alto è meglio
  (rilevato − partenza) / (target − partenza), con la partenza a 0 se manca; più basso è meglio
  (partenza − rilevato) / (partenza − target) o, senza partenza, target / rilevato; a target
  raggiunto 100, mai sopra 100 né sotto 0. Sì/no: 100 se rilevato "sì". Data: 100 se raggiunto
  entro la data. Senza rilevazione 0. Es. 2 eventi su 3: 66,7.
- **Completamento di un'azione o misura**: con almeno un indicatore è la **media del
  raggiungimento** degli indicatori (arrotondata), calcolata e non più inserita a mano; senza
  indicatori si inserisce a mano come prima.

## 2-bis. Controlli (07/11/2026)

Sull'obiettivo, senza modello (`controlli_obiettivo` in `common/performance`): impegno 0% (di
obiettivi, azioni o misure), scadenze fuori dall'anno dell'obiettivo, misure non più nella
mappatura o attribuite nella mappatura a un'altra struttura, obiettivo senza azioni o senza
misure della mappatura, azioni e misure **senza indicatori** (informazione: l'indicatore è
facoltativo, ma nel PIAO gli obiettivi devono essere misurabili). Nell'elenco il numero degli
avvisi, nel dettaglio l'elenco; nel riepilogo il numero delle azioni e misure senza indicatori
per struttura.

## 3. Ruoli

| Ruolo | Può |
|---|---|
| `PERFORMANCE_RESPONSABILE` (dirigente di un servizio, responsabile di un ufficio) | **proporre** la creazione, la modifica e l'eliminazione degli obiettivi della **propria struttura** (quella del suo utente); aggiornarne l'**avanzamento** (valori rilevati degli indicatori, o completamento di azioni e misure senza indicatori) senza approvazione; vedere in sola lettura quelli delle strutture sottostanti |
| `PERFORMANCE_APPROVATORE` (es. segretario o direttore generale) | vedere gli obiettivi di tutte le strutture; **approvare, restituire o respingere** le proposte; modificare gli obiettivi direttamente |
| `PERFORMANCE_AMMINISTRATORE` | creare, aprire, chiudere ed eliminare i PIAO; vedere tutti gli obiettivi e proporre, come i responsabili, per qualsiasi struttura; aggiornare l'avanzamento; consultare lo storico dell'intero PIAO |
| `ADMIN` | come l'amministratore della performance e l'approvatore (come in tutti i controlli dei ruoli); le email delle proposte vanno però solo a chi ha il ruolo di approvatore |

Gruppi di Active Directory predefiniti: `ATTI-PA-Performance-Responsabili`,
`ATTI-PA-Performance-Approvatori`, `ATTI-PA-Performance-Amministratori`.

## 3-bis. Iter di approvazione (09/11/2026)

Come le proposte dell'anticorruzione, ma la proposta riguarda l'**obiettivo intero**: porta la
versione completa dell'obiettivo con le sue azioni e misure, così l'approvatore valuta l'insieme
(compresi gli impegni che arrivano a 100%). Tabella `pf_proposte`.

- **Tipi**: creazione, modifica, eliminazione. Creazione e modifica nascono **in bozza** (la
  modifica con l'obiettivo com'è): la struttura la completa con le stesse finestre delle
  modifiche dirette, ogni cambiamento si salva subito, poi la **invia** con una nota.
  L'eliminazione va subito all'approvatore, con il motivo.
- **Stati**: bozza → inviata → approvata (la modifica si applica) | respinta | restituita (si
  corregge e si reinvia, o si scarta). L'inviata si **ritira** e torna in bozza (l'eliminazione
  si annulla); bozza e restituita si **scartano**. Restituire e respingere richiedono la
  motivazione. Le bozze le vede solo la struttura.
- **Una sola proposta aperta per obiettivo**; i nuovi obiettivi proposti compaiono nell'elenco
  della struttura, con lo stato.
- **Avanzamento escluso**: il completamento di azioni e misure e i valori rilevati degli
  indicatori sono monitoraggio, non programmazione; non fanno parte della proposta, il
  responsabile li aggiorna direttamente (restano nello storico). All'approvazione quelli
  esistenti restano, i nuovi partono da 0. La **definizione** degli indicatori (cosa si misura,
  tipo, partenza, target, verso) fa invece parte dell'obiettivo: cambiare il target (es. da 3 a
  5 eventi) passa dalla proposta. Se cambia il tipo di un indicatore il valore rilevato si
  azzera.
- **Differenze**: per la modifica, la proposta conserva l'obiettivo com'era quando è nata e
  mostra cosa cambia (campi dell'obiettivo; azioni e misure nuove, modificate, tolte; i loro
  indicatori prima e dopo). Se nel
  frattempo l'obiettivo è stato modificato (es. direttamente dall'approvatore) la proposta lo
  segnala e l'approvazione chiede conferma.
- **Controlli**: impegni e misure si verificano a ogni salvataggio, all'invio e
  all'approvazione (gli altri obiettivi della struttura possono essere cambiati); PIAO aperto.
- **Storico**: l'approvazione registra in `pf_modifiche` ogni cambiamento a nome
  dell'approvatore, con la nota "Proposta di ... approvata", la nota della proposta e la
  motivazione.
- **Email** (se l'ente ha la posta configurata): agli approvatori quando una proposta è inviata
  o reinviata; a chi l'ha inviata quando è approvata, respinta o restituita.

## 4. Storico delle modifiche

Ogni creazione, modifica ed eliminazione di PIAO, obiettivi, azioni, misure e indicatori (anche
ogni valore rilevato) va in
`pf_modifiche`: chi, quando, l'elemento (descrizione al momento della modifica) e i campi
cambiati con il valore **prima e dopo**, più una nota facoltativa (motivo). Un salvataggio
senza cambiamenti non registra nulla. Lo storico resta dopo l'eliminazione; si consulta
dall'obiettivo (sue azioni e misure comprese) e, per l'amministratore, per l'intero PIAO.

## 5. Organizzazione

```
common/performance/               regole e calcoli (media pesata, disponibile, ritardo, indicatori)
api/src/routers/performance.py    /api/v1/performance/...
frontend/src/lib/ui/performance/  schede: Obiettivi, Proposte, Riepilogo, PIAO (amministratore)
tabelle: pf_piao, pf_obiettivi, pf_elementi, pf_indicatori, pf_proposte, pf_modifiche
```

API: `contesto`, `piao` (+ `/<id>`, `/<id>/storico`), `obiettivi` (filtri PIAO, anno,
struttura; con il riepilogo della struttura), `obiettivi/<id>` (+ `/elementi`, `/storico`),
`elementi/<id>` (con gli indicatori; + `/avanzamento`: valori rilevati degli indicatori o, senza
indicatori, completamento), `misure` (della mappatura, quelle della struttura per prime, con
indicatore e target: una misura aggiunta all'obiettivo parte con quell'indicatore), `riepilogo`
(con le azioni e misure senza indicatori e le proposte da approvare), `proposte` (filtri PIAO,
stato, struttura; `/<id>` con `/invia`, `/ritira`, `/approva`, `/restituisci`, `/respingi`).
Creazione, modifica ed eliminazione dirette di obiettivi, azioni e misure: solo l'approvatore.

## 6. Decisioni (05/11/2026)

1. Obiettivi **annuali** dentro il PIAO triennale; impegni sommati per struttura e anno.
2. Impegni **obbligatoriamente** non oltre 100%; insieme completo solo a 100%.
3. Il completamento delle misure si **inserisce nella performance** (non dal monitoraggio
   anticorruzione).
4. ~~Nessuna validazione degli obiettivi~~: superata dall'iter di approvazione (sezione 3-bis,
   09/11/2026).
5. Dirigenti e responsabili hanno lo stesso ruolo: servizio o ufficio dipende dalla struttura
   assegnata all'utente (gerarchia delle strutture organizzative).

## 6-bis. Relazione sulla performance (07/11/2026)

Scheda "Relazione" dell'amministratore: per un PIAO e un anno, sintesi (obiettivi, strutture,
obiettivi completati, completamento medio, azioni e misure, ritardi a fine anno o a oggi,
strutture con impegni non al 100%) con la tabella per struttura, elenco degli obiettivi e
indicatori (target, valore rilevato, raggiungimento; quanti raggiunti, non rilevati, azioni e
misure senza indicatori). Testo
scritto dal modello dai soli dati, numeri da verificare, esportazione in DOCX/ODT: come le
relazioni dell'anticorruzione (`anticorruzione.md`, decisione 23).

## 6-ter. Indicatori (09/11/2026)

Prima il completamento era solo una percentuale inserita a mano e la scadenza l'unico
riferimento: non si poteva dire "partecipare a **3** eventi". Decisioni:

1. Più indicatori per azione o misura, in una tabella a sé (`pf_indicatori`, schema
   `0003_indicatori_performance.sql`): la definizione segue l'iter, il valore rilevato no, e
   all'approvazione di una modifica i valori già rilevati restano.
2. Con degli indicatori il completamento si **calcola** (sezione 2); senza, resta manuale:
   le azioni e misure esistenti non cambiano.
3. Indicatore **facoltativo ma segnalato** (controlli, riepilogo, relazione).
4. Una misura della mappatura aggiunta a un obiettivo parte con il suo indicatore e target
   (testo libero): il primo numero del target diventa il valore da raggiungere (percentuale se
   c'è "%"), senza numeri è un sì/no; si corregge prima di salvare.

## 7. Da fare

- importazione degli obiettivi da Excel del Piano (come in Si.Ge.Ri.Co.);
- notifiche email (es. scadenze vicine o passate);
- collegamento degli obiettivi a processi e attività della mappatura.
