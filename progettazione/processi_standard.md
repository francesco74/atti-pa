# Processi standard del modulo anticorruzione — da rivedere

I file in `pacchetto/anticorruzione/` sono stati ricavati il 29/10/2026 dalla mappatura del
Comune di Lucca (Si.Ge.Ri.Co., PTPCT 2026-2028): 14 aree, 130 processi, 437 attività, 252
rischi, 258 misure. Arrivano agli enti con il pacchetto standard (Amministrazione → Pacchetti).

## Cosa è stato fatto in automatico

- **Tolto**: la struttura responsabile dei processi e le strutture coinvolte nelle attività
  (sono le U.O. di Lucca: ogni ente assegna le proprie).
- **Valutazione**: i valori degli indicatori di Lucca restano come **valutazione proposta**;
  entra solo nei rischi nuovi di un ente, che la rivede. Non conta nel confronto tra standard
  e versione dell'ente.
- **Fattore abilitante**: riportato com'era (tolto solo "valutazione media"); molti testi non
  coincidono con gli 8 fattori della metodologia.
- **Categoria delle misure**: proposta dal testo con parole chiave (pubblicazione →
  Trasparenza, verifica/controllo → Controllo, regolamento → Regolamentazione...), assegnata a
  175 misure su 258. **Tutte le misure sono "specifiche"**: le misure generali del PIAO (§ 3:
  codice di comportamento, rotazione, conflitto di interessi, pantouflage, whistleblowing...)
  non sono nella mappatura di Lucca e andrebbero aggiunte.
- **Aree**: quelle del PNA (A-M) più N "Programmazione e controlli", O "Supporto agli organi"
  ed EXL "Servizi demografici", usate da Lucca.

## Da rivedere a mano

1. I testi che citano Lucca, le sue U.O. o le sue società (elenco sotto).
2. I riferimenti normativi superati (es. d.lgs. 50/2016 al posto del d.lgs. 36/2023) e quelli
   regionali (Regione Toscana).
3. I fattori abilitanti fuori elenco e le categorie delle misure.
4. Le misure generali da aggiungere e i collegamenti delle misure di trasparenza agli obblighi
   di pubblicazione (`obbligo_trasparenza`, es. ART_23).

Dopo ogni revisione si aumenta la versione in `pacchetto/pacchetto.yaml`: gli enti vedranno i
processi cambiati come "aggiornabili" (o in conflitto, se li hanno modificati).

### Testi con riferimenti all'ente

- **A.1 attori_esterni**: E.r.p. Lucca S.r.l. - inquilini alloggi edilizia residenziale pubblica
- **A.1.1_R.1_M.1 misura**: Chiedere all'ente gestore E.r.p. Lucca S.r.l. un elenco aggiornato trimestralmente degli alloggi pronti e disponibili per l'assegnazione con il dettaglio, per ciascuno, dell'ubicazione, dei vani utili, della composizione…
- **A.5.2_R.1_M.1 misura**: Ogni SCIA, entro le 24 ore lavorative successive alla presentazione, viene assegnata ad un diverso istruttore, seguendo progressivamente un elenco di istruttori ordinato alfabeticamente. L'elenco prestabilito è pubbliciz…
- **A.16.2_R.1_M.1 misura**: Rotazione del personale effettuata nel corso del 2022 con assegnazione pratiche di autorizzazioni in deroga ai limiti di emissione acustica a ulteriore personale della U.O. 7.2
- **A.17.3_R.1 rischio**: Non corretta rilevazione di una causa di esclusione (limite Isee, residenza o occupazione lavorativa nel Comune di Lucca, permesso di soggiorno...)
- **B.5 attori_esterni**: RESIDENTI NEL COMUNE DI LUCCA, STRANIERI E APOLIDI SECONDO LE NORMATIVE VIGENTI, MINORI ITALIANI O STRANIERI NON RESIDENTI NEL COMUNE DI LUCCA CHE NECESSITANO DI INTERVENTI DI PRIMA NECESSITA'
- **B.5.1_R.1_M.1 misura**: Determinazione preventiva dei criteri per la definizione dei soggetti a cui destinare benefici economici, contributi, sussidi. Applicazione del Regolamento per gli interventi economici e socio-economici dei Servizi Socia…
- **B.5.1_R.2_M.1 misura**: Determinazione preventiva dei criteri per la definizione dei soggetti a cui destinare benefici economici, contributi, sussidi. Applicazione del Regolamento per gli interventi economici e socio-economici dei Servizi Socia…
- **B.5.1_R.3_M.1 misura**: Determinazione preventiva dei criteri per la definizione dei soggetti a cui destinare benefici economici, contributi, sussidi. Applicazione del Regolamento per gli interventi economici e socio-economici dei Servizi Socia…
- **B.5.2_R.1_M.1 misura**: Determinazione preventiva dei criteri per la definizione dei soggetti a cui destinare benefici economici, contributi, sussidi. Applicazione del Regolamento per gli interventi economici e socio-economici dei Servizi Socia…
- **B.5.2_R.2_M.1 misura**: Determinazione preventiva dei criteri per la definizione dei soggetti a cui destinare benefici economici, contributi, sussidi. Applicazione del Regolamento per gli interventi economici e socio-economici dei Servizi Socia…
- **B.5.2_R.3_M.1 misura**: Determinazione preventiva dei criteri per la definizione dei soggetti a cui destinare benefici economici, contributi, sussidi. Applicazione del Regolamento per gli interventi economici e socio-economici dei Servizi Socia…
- **B.11.2_R.1_M.2 misura**: Rafforzare l'analisi condotta di concerto tra U.O. 2.1. e 2.2 per la stesura di progettualità condivise sui bisogni dei cittadini
- **B.17.2_R.1_M.1 misura**: Assegnazioni secondo il regolamento comunale e coinvolgimento della commissione interna del Luna Park. Rispetto del codice di comportamento dei dipendenti del Comune di Lucca.
- **B.20 denominazione**: Concessione d'uso di aree o immobili di proprietà pubblica gestite direttamente dalla U.O.6.1 (cd. sistema congressuale- impianti sportivi)
- **B.28.1_R.1_M.1 misura**: Incremento qualitativo dei Tavoli della Marginalità, sede in cui A.C.ed ETS si confrontano sui bisogni individuati sul territorio e programmano congiuntamente gli interventi necessari in base alle risorse disponibili. Ri…
- **B.29 tempi**: Co-progettazione pluriennale con Fondazione Casa Lucca
- **B.29 attori_esterni**: Fondazione Casa Lucca
- **C.1.9_R.1 rischio**: Presieduto dal Responsabile della procedura di gara individuato in ambito della U.O. A.3 (che può o meno coincidere con il RUP se acquisto esperito dal Provveditorato)
- **C.7.1_R.1_M.1 misura**: Divisione, ove possibile, delle figure del RUP e del Direttore Lavori, anche per i lavori ove la norma non vieta la coincidenza, oppure qualora ciò non fosse possibile (per mancanza di soggetti all'interno delle U.O. Con…
- **C.8.1_R.1_M.1 misura**: Divisione, ove possibile, delle figure del RUP e del Direttore Lavori, anche per i lavori ove la norma non vieta la coincidenza, oppure qualora ciò non fosse possibile (per mancanza di soggetti all'interno delle U.O. Con…
- **D.4.8 attività**: Comunicazione dei soggetti individuati al Centro per l'Impiego della Provincia di Lucca (ARTI).
- **E.8.1_R.1_M.1 misura**: Utilizzo di software informatico per la elaborazione ed emissione dei provvedimenti che tiene traccia delle operazioni effettuate e pertanto con iter non riferibili a singolo operatore ma all'intera U.O.
- **E.8.2_R.1_M.1 misura**: Verifica a campione incrociata delle pratiche da parte del personale d'ufficio sotto la direzione del dirigente ed emissione del relativo ruolo da riscuotere in forma coattiva da parte di Lucca Riscossione e Servizi, com…
- **E.17.2_R.1_M.1 misura**: Elaborazione tramite la procedura informatica della contabilità di stampe/prospetti dimostrativi delle concordanze contabili. Comunicazioni formali all'agente contabile in caso di discordanze e/o richiesta informazioni. …
- **E.18.3_R.1_M.2 misura**: Redazione documento di sintesi della strategia antifrode del Comune di Lucca entro Giugno 2025 - in attuazione Reg. (Ue) 2021/241 e dal d.l. 77/2021
- **E.20 denominazione**: Bilancio consolidato del Comune di Lucca
- **E.20.2 attività**: Predisposizione della nota informativa sulla verifica dei crediti e debiti reciproci tra il Comune di Lucca e gli organismi partecipati ai sensi dell'art. 11, comma 6, lett. j), D.Lgs. 23.06.2011, n. 118
- **EXL.2.1 attività**: Ricevimento (da consolato o direttamente dagli interessati, se iscritti nell'anagrafe della popolazione residente) degli atti di eventi avvenuti all'estero, da trascrivere nei Registri di Stato Civile, verifica dei presu…
- **F.3 attori_esterni**: cittadini, altri comandi che ricevono la documentazione che deve essere presentata presso il Comando di Polizia Municipale di Lucca
- **F.3.1_R.1_M.1 misura**: Controllo dell'agente al front-office e dell'ufficio violazioni o della Forza di Polizia diversa dalla P.M. Lucca che riceve le copie per competenza;
- **G.2 denominazione**: Attività istruttoria relativa alle nomine dei rappresentanti del Comune di Lucca in enti, istituzioni e organismi partecipati
- **I.3 attori_esterni**: - Soprintendenza ai beni Culturali, Paesaggisti e Ambientali - Autorità di Bacino - Regione Toscana - Provincia di Lucca -Società Autostrade - Ferrovie dello Stato - Consorzio di Bonifica Toscana Nord - VV.FF.
- **I.3.2_R.1_M.1 misura**: Ogni domanda, entro le 24 ore lavorative successive alla presentazione, viene assegnata ad un diverso istruttore, seguendo progressivamente un elenco di istruttori ordinato alfabeticamente. L'elenco prestabilito è pubbli…
- **L.1 attori_esterni**: privati/ditte/Az. USL/ARPAT/Sistema Ambiente
- **N.1.2 attività**: Monitoraggio sul rispetto degli "indirizzi e obiettivi di contenimento delle spese di funzionamento delle società controllate dal Comune di Lucca" ai sensi dell'art. 19 del D.Lgs. n. 175/2016 e dell'art. 147 quater del D…
