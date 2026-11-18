# Processi standard del modulo anticorruzione

Pacchetto standard 2026.4 (18/11/2026), pensato per gli **enti locali**: sostituisce il
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
  (governo del territorio, pianificazione urbanistica, gestione dei rifiuti).
- Elenchi esemplificativi di rischi e misure del PNA 2013 (allegati 3, 4 e 7, in
  `docs/pna/`): solo come spunti; il metodo numerico P × I dell'allegato 5 è superato.
- Esempi di mappature di enti locali (`docs/pna/piano_anticorruzione_processi_rischi.xlsx`,
  allegati A, B e C di un piano 2021-23) e il pacchetto precedente, riletti e resi generici.

## Contenuto

- **11 aree**: A personale, B contratti pubblici, C provvedimenti ampliativi senza effetto
  economico (anche servizi demografici), D con effetto economico, E entrate, spese e
  patrimonio, F controlli e sanzioni, G incarichi e nomine, H affari legali, I governo del
  territorio, L pianificazione urbanistica, M rifiuti.
- **131 processi**: 46 dei soli comuni e 12 delle sole province e città metropolitane
  (`ambito`); all'importazione l'amministratore indica il tipo di ente e quelli dell'altro
  tipo non si importano.
- **53 procedimenti** (`procedimenti.yaml`, codici PRC-0001...): solo i dati che vengono
  dalla norma (riferimenti normativi, termine, tipologia, istanza di parte, silenzio assenso,
  dichiarazione sostitutiva, tutele); uffici, recapiti e modulistica li mette l'ente. Le
  attività che sono un procedimento lo indicano (`procedimento: PRC-0012`).
- Ogni rischio ha il fattore abilitante, una **valutazione proposta** (l'ente la rivede) e
  almeno una misura con categoria, indicatore, target e tempi; le misure generali (conflitto
  di interessi, codice di comportamento, rotazione, trasparenza, inconferibilità,
  pantouflage, patti d'integrità, formazione...) sono le stesse voci del catalogo in tutti i
  processi.

## Passaggio dal pacchetto precedente

Importato sopra il pacchetto di prima, i processi vecchi e nuovi si mescolerebbero (codici e
contenuti diversi). Per ogni ente, dopo il backup e la migrazione `0014_procedimenti_standard.sql`:

    python deploy/manutenzione/azzera_mappatura.py --ente CODICE --dry-run
    python deploy/manutenzione/azzera_mappatura.py --ente CODICE

poi si importa lo zip 2026.4 da Amministrazione → Pacchetti, indicando il tipo di ente.
Restano metodologia, strutture e procedimenti dell'ente.

## Da rivedere prima del rilascio

Un foglio di revisione con una riga per misura (processi, rischi, valutazioni proposte,
misure, procedimenti) si ricava dai file del pacchetto; i testi sono generici e vanno letti
da chi conosce i processi degli enti locali, in particolare valutazioni proposte, termini e
riferimenti normativi dei procedimenti (alcuni dipendono dalla legge regionale).
