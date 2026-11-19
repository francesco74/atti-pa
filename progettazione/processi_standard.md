# Processi standard del modulo anticorruzione

Pacchetto standard 2026.6 (19/11/2026), pensato per gli **enti locali**: la 2026.4 ha sostituito il
pacchetto precedente, ricavato dalla mappatura del Comune di Lucca. I sorgenti stanno in
`pacchetto/anticorruzione/` (aree, catalogo delle voci, procedimenti, processi per area);
lo zip si crea con `python deploy/pacchetto.py crea`.

## Fonti

- **PNA 2025** (delibera ANAC n. 19 del 28/01/2026): rinvia per la metodologia all'Allegato 1
  del PNA 2019 (valutazione qualitativa con indicatori: è la metodologia del pacchetto); la
  parte speciale sui contratti pubblici (PAD, FVOE, conflitto di interessi, programmazione,
  appalti su delega, esecuzione di servizi, forniture e lavori, subappalto, collegio
  consultivo tecnico, qualificazione) è la base dell'area B.
- **PNA 2019, Allegato 1, Tabella 3**: aree generali e aree specifiche degli enti locali
  (governo del territorio, pianificazione urbanistica, gestione dei rifiuti); **Box 9**: gli
  indicatori di stima del rischio, tutti presenti nella metodologia (il decimo indicatore di
  probabilità, la collaborazione del responsabile, è stato aggiunto nella 2026.5).
- Elenchi esemplificativi di rischi e misure del PNA 2013 (allegati 3, 4 e 7, in
  `docs/pna/`): solo come spunti; il metodo numerico P × I dell'allegato 5 è superato.
- Esempi di mappature di enti locali (`docs/pna/piano_anticorruzione_processi_rischi.xlsx`,
  allegati A, B e C del piano 2021-23 di una provincia, costruiti sullo schema dell'Allegato 1
  del PNA 2019) e il pacchetto precedente, riletti e resi generici. Dal piano provinciale
  vengono, nella 2026.5, l'area N e i processi su contrattazione integrativa, stipendi,
  trasporto privato e diritto allo studio delle superiori.
- Elenco dei procedimenti pubblicato da un comune capoluogo (art. 35, 2025), senza i dati
  dell'ente: spunto per descrizioni e per 43 procedimenti della 2026.6 (anagrafe, stato civile,
  elettorale, personale, casa, scuola e famiglia). Norme e termini vengono dalla normativa
  nazionale, non dalla scheda del comune; restano fuori le norme di una sola regione.

## Contenuto

- **12 aree**: A personale, B contratti pubblici, C provvedimenti ampliativi senza effetto
  economico (anche servizi demografici), D con effetto economico, E entrate, spese e
  patrimonio, F controlli e sanzioni, G incarichi e nomine, H affari legali, I governo del
  territorio, L pianificazione urbanistica, M rifiuti, N affari istituzionali e servizi
  generali (protocollo, atti e organi, reclami, cultura, sistemi informativi: processi
  trasversali che la Tabella 3 non colloca).
- **140 processi**: 46 dei soli comuni e 14 delle sole province e città metropolitane
  (`ambito`); all'importazione l'amministratore indica il tipo di ente e quelli dell'altro
  tipo non si importano.
- **102 procedimenti** (`procedimenti.yaml`, codici PRC-0001...): solo i dati che vengono
  dalla norma (breve descrizione, riferimenti normativi, termine, tipologia, istanza di parte, silenzio assenso,
  dichiarazione sostitutiva, tutele); uffici, recapiti e modulistica li mette l'ente. Le
  attività che sono un procedimento lo indicano (`procedimento: PRC-0012`).
- Ogni rischio ha il fattore abilitante, una **valutazione proposta** (l'ente la rivede) e
  almeno una misura con categoria, indicatore, target e tempi; le misure generali (conflitto
  di interessi, codice di comportamento, rotazione, trasparenza, inconferibilità,
  pantouflage, patti d'integrità, formazione...) sono le stesse voci del catalogo in tutti i
  processi.

## Codici stabili tra le versioni

I codici di aree, processi (A.1...), voci del catalogo (ATT-, RIS-, MIS-) e procedimenti
(PRC-) non cambiano da una versione all'altra: i processi e le attività nuove si aggiungono
in fondo, le voci e i procedimenti nuovi prendono il numero successivo; un'attività tolta
lascia libero il suo numero (`RIMOSSA` nel generatore), che non si riusa. Così un ente che ha
importato la 2026.4 importa la 2026.5 senza azzerare: i processi nuovi arrivano come nuovi,
quelli già presenti risultano invariati (la valutazione proposta non entra nell'impronta) e la
metodologia come aggiornata, per il decimo indicatore. Se l'ente non la aggiorna, i rischi
nuovi arrivano senza valutazione proposta e si valutano a mano.

## Passaggio dal pacchetto precedente

Importato sopra il pacchetto di prima, i processi vecchi e nuovi si mescolerebbero (codici e
contenuti diversi). Per ogni ente, dopo il backup e la migrazione `0014_procedimenti_standard.sql`:

    python deploy/manutenzione/azzera_mappatura.py --ente CODICE --dry-run
    python deploy/manutenzione/azzera_mappatura.py --ente CODICE

poi si importa lo zip 2026.6 da Amministrazione → Pacchetti, indicando il tipo di ente.
Restano metodologia, strutture e procedimenti dell'ente.

## Da rivedere prima del rilascio

Un foglio di revisione con una riga per misura (processi, rischi, valutazioni proposte,
misure, procedimenti) si ricava dai file del pacchetto; i testi sono generici e vanno letti
da chi conosce i processi degli enti locali, in particolare valutazioni proposte, termini e
riferimenti normativi dei procedimenti (alcuni dipendono dalla legge regionale).
