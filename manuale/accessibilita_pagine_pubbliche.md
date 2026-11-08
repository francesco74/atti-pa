# Accessibilità delle pagine pubbliche

Le pagine per i cittadini (`/pubblico/mappatura` e `/pubblico/procedimenti`) seguono le WCAG 2.1
livello AA, richiamate dalle linee guida AgID sull'accessibilità degli strumenti informatici
(norma EN 301 549). Questa pagina dice cosa fa il sistema, cosa deve fare l'ente e come
verificare a mano ciò che i test automatici non coprono.

## Cosa fa il sistema

| Criterio WCAG | Come |
|---|---|
| 1.1.1 Contenuti non testuali | icone decorative escluse dai lettori di schermo; pulsanti con etichetta |
| 1.3.1 Informazioni e correlazioni | titolo della pagina come intestazione di livello 1, sezioni di livello 2, parti della scheda di livello 3; percorso di navigazione come gruppo con link |
| 1.4.1 Uso del colore | il livello di rischio è sempre scritto, il colore è solo un aiuto |
| 1.4.3 / 1.4.11 Contrasto | testo scuro sui livelli di rischio; contrasto verificato dai test automatici |
| 1.4.4 / 1.4.10 Ridimensionamento e reflow | a 320 px e con il testo al 200% nulla esce dalla pagina: intestazione che scorre, righe che vanno a capo, campi che si restringono, piè di pagina compatto |
| 2.1.1 Tastiera | tutto si usa con Tab, Invio e Spazio |
| 2.4.1 Salto di blocchi | "Vai al contenuto", primo elemento con il tasto Tab |
| 2.4.2 Titolo della pagina | la scheda del browser dice dove si è, es. "Contributo affitto – Tipologie di procedimento – Comune di …" |
| 2.4.3 Ordine del focus | cambiando vista il focus va all'inizio del nuovo contenuto, e il titolo viene annunciato |
| 2.4.7 Focus visibile | evidenziazione marcata e bordo sui pulsanti |
| 3.3.1 / 3.3.2 Moduli | campi con etichetta e aiuto; errori scritti e annunciati |
| 4.1.2 Nome, ruolo, valore | albero di accessibilità sempre attivo (senza il pulsante "Enable accessibility" di Flutter) |
| 4.1.3 Messaggi di stato | numero di risultati, "nessun risultato", errori e conferme annunciati senza spostare il focus |

Meccanismo di feedback (obbligatorio per le PA): in fondo a ogni pagina ci sono
**"Dichiarazione di accessibilità"** e **"Segnala un problema di accessibilità"**. La
segnalazione chiede la descrizione del problema e un'email facoltativa per la risposta, e
arriva in **Ricerche e feedback** (filtro *Non utili*, voce "Problema di accessibilità") a chi ha
il ruolo *Analisi delle ricerche e dei feedback* o è amministratore.

I test automatici (`frontend/src/test/accessibilita_pubblica_test.dart`) controllano a ogni
modifica: contrasto del testo, pulsanti con etichetta, bersagli di almeno 48 px, intestazioni,
titolo della scheda, pagina a 320 px con il testo al 200% e il modulo di segnalazione.

## Cosa deve fare l'ente

1. Compilare la **dichiarazione di accessibilità** su <https://form.agid.gov.it> e inserirne
   l'indirizzo in *Amministrazione → Profilo dell'ente → Dichiarazione di accessibilità*.
   Senza indirizzo il link non compare.
2. Assegnare a qualcuno il ruolo *Analisi delle ricerche e dei feedback* e rispondere alle
   segnalazioni entro 30 giorni (linee guida AgID), poi segnarle gestite con una nota.
3. Fare la verifica manuale qui sotto a ogni rilascio importante e riportarne l'esito nella
   dichiarazione.

## Limiti noti (da indicare nella dichiarazione)

- **1.4.12 Spaziatura del testo:** l'app è disegnata dal motore di Flutter su un canvas, quindi
  gli stili personali dell'utente (estensioni o fogli di stile per l'interlinea e la spaziatura)
  non si applicano. Zoom del browser e ingrandimento del testo funzionano.
- Il testo non si seleziona con il mouse come in una pagina HTML. Si può copiare dai campi e il
  lettore di schermo lo legge.

## Verifica manuale

Da fare su Chrome o Firefox, con la pagina aperta dal link pubblico dell'ente.

**Solo tastiera** (senza mouse)
- [ ] Il primo Tab mostra "Vai al contenuto"; con Invio il focus passa al contenuto.
- [ ] Con Tab e Maiusc+Tab si raggiungono, in ordine logico, ricerca, filtri, righe degli elenchi, percorso, feedback e piè di pagina.
- [ ] L'elemento con il focus è sempre ben visibile.
- [ ] Invio o Spazio aprono le righe; nella scheda di un procedimento si torna indietro dal percorso.
- [ ] La finestra "Segnala un problema di accessibilità" si compila e si invia da tastiera; Esc la chiude.

**Lettore di schermo** (NVDA su Windows con Firefox o Chrome; VoiceOver su Mac o iPhone)
- [ ] All'apertura il lettore legge la pagina: nessun pulsante "Enable accessibility".
- [ ] Con la navigazione per intestazioni (tasto H in NVDA) si trovano titolo, "Strutture responsabili" o "Aree di rischio" e le parti della scheda.
- [ ] La ricerca annuncia "Ricerca in corso…" e poi il numero di risultati.
- [ ] Le righe si leggono come un'unica voce (es. "Contributo affitto, Servizi sociali").
- [ ] Il livello di rischio si legge come "Livello di rischio: Rischio Medio".
- [ ] Il percorso si legge come link, con l'ultima voce indicata come pagina corrente.
- [ ] Aprendo una struttura o un procedimento il lettore annuncia il nuovo titolo.
- [ ] "Grazie per la segnalazione" e gli errori del modulo vengono letti.

**Zoom e schermi piccoli**
- [ ] Zoom del browser al 200%: tutto leggibile, nessuno scorrimento orizzontale.
- [ ] Larghezza 320 px (strumenti per sviluppatori del browser, o un telefono): nessuno scorrimento orizzontale, il piè di pagina mostra il pulsante "Informazioni".
- [ ] Telefono con il testo di sistema ingrandito: le righe vanno a capo e il livello di rischio finisce sotto il testo.

**Colori**
- [ ] Con un simulatore di daltonismo (es. Chrome → Rendering → Emulate vision deficiencies) il livello di rischio resta comprensibile dal testo.
