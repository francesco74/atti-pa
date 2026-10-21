# Manuale dell'editor di modelli, specificità e checklist

Questo manuale spiega, passo per passo, come si modificano nell'app **Atti PA** i modelli di
atto, le specificità e le checklist di controllo. Non serve conoscere linguaggi di
programmazione né il formato dei file: tutto si fa con caselle di testo, menu a tendina e
pulsanti.

Il manuale è lungo perché copre ogni casella dell'editor. Non serve leggerlo tutto prima di
cominciare: leggi i capitoli 1–4 e poi la guida pratica del capitolo 5, e consulta il resto
quando ti serve.

## Indice

1. [Concetti di base](#1-concetti-di-base)
2. [Chi può fare cosa](#2-chi-può-fare-cosa)
3. [Il ciclo di lavoro: bozza, controllo, pubblicazione](#3-il-ciclo-di-lavoro-bozza-controllo-pubblicazione)
4. [La pagina «Modelli e checklist»](#4-la-pagina-modelli-e-checklist)
5. [Guida pratica: le operazioni più comuni](#5-guida-pratica-le-operazioni-più-comuni)
6. [L'editor dei modelli di atto](#6-leditor-dei-modelli-di-atto)
7. [Le condizioni: «Quando compare»](#7-le-condizioni-quando-compare)
8. [I dati nel testo](#8-i-dati-nel-testo)
9. [L'anteprima e gli scenari di prova](#9-lanteprima-e-gli-scenari-di-prova)
10. [L'editor delle specificità](#10-leditor-delle-specificità)
11. [L'editor delle checklist](#11-leditor-delle-checklist)
12. [Errori e avvisi](#12-errori-e-avvisi)
13. [Confronti, versioni, ripristino dello standard](#13-confronti-versioni-ripristino-dello-standard)
14. [Le proposte dei redattori](#14-le-proposte-dei-redattori)
15. [Il sorgente (modalità avanzata)](#15-il-sorgente-modalità-avanzata)
16. [Domande frequenti e problemi](#16-domande-frequenti-e-problemi)
17. [Glossario](#17-glossario)

---

## 1. Concetti di base

Prima di aprire l'editor conviene avere chiari i quattro oggetti con cui si lavora e come si
collegano tra loro.

### 1.1 Il modello di atto

Il **modello di atto** è lo schema da cui nasce ogni atto. Per esempio il modello
*Determina di conferimento di incarico di patrocinio legale* contiene:

- le **domande iniziali** che l'app pone a chi scrive l'atto («L'ente promuove il giudizio o
  vi resiste?», «Come è stato scelto l'avvocato?»);
- il **testo dell'atto**, diviso in **fasi** (le quattro fasi dell'atto amministrativo:
  intestazione, preambolo e motivazione, dispositivo, chiusura), ogni fase in **sezioni**
  (es. «Visti», «Considerato che»), ogni sezione in **capoversi**;
- i **dati da compilare** (importo, nome dell'avvocato, CIG...), che compaiono nel testo dove
  servono;
- i **valori calcolati** dalle risposte (es. «promuovere il giudizio» oppure «resistere nel
  giudizio» a seconda della risposta);
- le **risposte consigliate** (suggerimenti mostrati a chi compila).

Un capoverso può comparire **sempre** oppure **solo in certi casi**: per esempio il
capoverso sul contributo ANAC compare solo se l'importo è almeno 40.000 euro. Questa regola
si chiama **condizione** (capitolo 7).

### 1.2 La specificità

La **specificità** (nei file si chiama anche *modulo di regole*) è un pacchetto di testi che
si **aggiunge** a uno o più modelli quando l'atto ha una certa caratteristica. Esempi:
*Servizi / Forniture Cloud ICT*, *Criteri ambientali minimi (CAM)*, *Manodopera*.

Chi scrive un affidamento trova la domanda «Caratteristiche dell'affidamento» con l'elenco
delle specificità; se spunta *Servizi / Forniture Cloud ICT*, nell'atto compaiono
automaticamente i richiami al Codice dell'amministrazione digitale, l'attestazione della
qualificazione ACN, la clausola di risoluzione e così via, ognuno nel punto giusto.

Il vantaggio: un testo che riguarda il cloud si scrive **una volta sola** nella specificità e
vale per tutti i modelli a cui la specificità si applica.

### 1.3 Il punto di innesto

Una specificità non sa da sola *dove* mettere i suoi testi. Il modello quindi segna alcune
sezioni come **punti di innesto**, con un nome: `oggetto`, `visti_normativi`, `dato_atto`,
`elementi_essenziali_192`, `garanzia`, `dispositivo`. La specificità dice «metti questo
capoverso nel punto `visti_normativi`» e l'app lo inserisce nella sezione del modello che
porta quel nome.

```
 MODELLO                                   SPECIFICITÀ «Cloud ICT»
 ─────────────────────────────            ─────────────────────────────
 Fase 2 · Preambolo                        Inserto → visti_normativi
   Sezione «Visti»                            «Visto il D.Lgs. 82/2005 (CAD)...»
     [innesto: visti_normativi] ◄──────────   «Visto il Regolamento ACN...»
     Visto il D.Lgs. 36/2023...
     Visto il D.Lgs. 267/2000...           Inserto → dispositivo
 Fase 3 · Dispositivo                         «di stabilire che la perdita della
   Sezione «Determina»                          qualificazione ACN comporta...»
     [innesto: dispositivo] ◄──────────────
```

### 1.4 La checklist

La **checklist** (scheda di controllo) è l'elenco dei **controlli** che la verifica applica a
un atto. Ogni controllo ha un titolo e una **regola** scritta in italiano, che il modello
linguistico (l'intelligenza artificiale) valuta leggendo l'atto insieme al testo vigente delle
norme indicate.

Le checklist sono di tre livelli:

| Livello | Si applica a | Esempio |
|---|---|---|
| **Generica** | ogni atto della tipologia | *Scheda delle determinazioni* (firma, oggetto, visto contabile...) |
| **Di modello** | gli atti nati da quel modello | *Scheda dell'incarico di patrocinio legale* |
| **Di specificità** | gli atti in cui è scelta quella specificità | *Scheda Cloud ICT* |

Quando si verifica un atto, l'app applica **insieme** la generica, quella del suo modello e
quelle delle specificità scelte. Il risultato della verifica è raggruppato per scheda.

### 1.5 Coerenza tra modelli e checklist

Modello e checklist devono «parlarsi»: se il modello inserisce un capoverso sulla
qualificazione ACN, la checklist della specificità deve contenere un controllo che verifica
proprio quel capoverso. Per questo ogni controllo può essere **collegato** ai capoversi che
lo soddisfano (capitolo 11.6). L'editor segnala quando questi collegamenti si rompono, per
esempio se si elimina un capoverso a cui un controllo rimandava.

### 1.6 Lo standard e la versione dell'ente

I modelli, le specificità e le checklist che forniamo arrivano con un **pacchetto standard**
(es. *Modelli standard Atti PA 2026.1*). Una volta importati, appartengono all'ente: l'ente
li modifica liberamente con l'editor. L'app ricorda comunque lo standard da cui sono nati, e
questo permette di:

- vedere cosa l'ente ha cambiato rispetto allo standard (capitolo 13);
- tornare al testo standard di un singolo capoverso;
- ricevere un nuovo pacchetto senza perdere le modifiche dell'ente (Amministrazione →
  Pacchetti).

---

## 2. Chi può fare cosa

I ruoli si ricevono dai gruppi di Active Directory.

| Ruolo | Gruppo AD (nome predefinito) | Nell'editor |
|---|---|---|
| **Gestore dei modelli** | `ATTI-PA-Gestori-Modelli` | apre l'editor, modifica e salva le bozze, crea oggetti nuovi, gestisce le proposte dei redattori. **Non pubblica.** |
| **Amministratore** | gruppo amministratori | tutto quello che fa il gestore, più la **pubblicazione** e l'importazione dei pacchetti |
| **Redattore** | gruppo redattori | non vede l'editor; dalla bozza di un atto può **proporre** il nuovo testo di un capoverso |

La voce di menu **Modelli e checklist** compare solo a gestori e amministratori. Se dopo
l'inserimento nel gruppo AD la voce non compare, esci dall'app e rientra: i ruoli si leggono
all'accesso.

---

## 3. Il ciclo di lavoro: bozza, controllo, pubblicazione

Questo è il punto più importante del manuale.

```
  Versione pubblicata (v3)  ──── usata dagli atti nuovi
          │
          │ apri l'editor e modifica
          ▼
  Modifiche in memoria      ──── «modifiche non salvate» (si perdono se chiudi il browser)
          │
          │ Salva bozza
          ▼
  Bozza                      ──── salvata sul server, INVISIBILE agli atti
          │                       errori e avvisi controllati
          │ Pubblica (solo amministratore, solo senza errori)
          ▼
  Versione pubblicata (v4)  ──── usata dagli atti nuovi da questo momento
```

### 3.1 Le modifiche in memoria

Quando scrivi nell'editor, le modifiche restano **nel browser**. In alto, sotto il titolo,
compare «bozza in corso, modifiche non salvate» e il pulsante **Salva bozza** è attivo.
L'app non salva da sola: premi **Salva bozza** regolarmente, come faresti con un documento
di Word.

Se provi a uscire dall'editor con modifiche non salvate, l'app chiede:

- **Salva bozza** – salva e esce;
- **Esci senza salvare** – le modifiche si perdono;
- **Annulla** – resti nell'editor.

> Attenzione: se chiudi la scheda del browser o lo ricarichi (F5), la domanda non compare e
> le modifiche non salvate si perdono.

### 3.2 La bozza

La bozza è salvata sul server. Caratteristiche:

- **gli atti non la vedono**: chi scrive un atto continua a usare la versione pubblicata;
  puoi quindi lavorare con calma, anche per giorni;
- è **una sola per oggetto**: se due gestori modificano lo stesso modello, lavorano sulla
  stessa bozza e l'ultimo che salva sovrascrive le modifiche dell'altro. Accordatevi su chi
  modifica cosa;
- quando riapri l'editor, ritrovi la bozza dove l'avevi lasciata;
- puoi salvarla **anche se contiene errori**: gli errori impediscono solo la pubblicazione;
- si butta via con **⋮ → Scarta la bozza**: si torna alla versione pubblicata. Per un oggetto
  nuovo mai pubblicato, scartare la bozza lo elimina del tutto.

### 3.3 Il controllo continuo

Mentre scrivi, dopo circa un secondo di pausa, l'app controlla la definizione e mostra in
basso a sinistra:

- «Nessun problema» con un segno verde, oppure
- «N errori, M avvisi»: clicca per aprire l'elenco.

Gli **errori** (rossi) impediscono la pubblicazione: per esempio un dato usato nel testo che
non esiste. Gli **avvisi** (arancioni) segnalano qualcosa da guardare, ma non bloccano: per
esempio un dato definito e mai usato. Il capitolo 12 elenca tutti i messaggi con il rimedio.

### 3.4 La pubblicazione

Il pulsante **Pubblica** (in alto a destra) è attivo solo per gli amministratori e solo se
c'è una bozza o ci sono modifiche. Premendolo:

1. se ci sono modifiche non salvate, l'app salva prima la bozza;
2. se la bozza contiene errori, la pubblicazione si ferma con il messaggio «La bozza contiene
   errori: correggili prima di pubblicare»;
3. l'app chiede conferma;
4. nasce una nuova versione (es. da v3 a v4) e la bozza sparisce.

Cosa succede dopo la pubblicazione:

- gli **atti nuovi** usano la nuova versione;
- le **bozze di atto già iniziate** e le **verifiche già fatte** restano sulla versione con
  cui sono nate: la pubblicazione non cambia nulla di ciò che esiste già;
- se pubblichi una **specificità**, tutti i modelli a cui si applica ricevono
  automaticamente una nuova versione (perché il modello pubblicato contiene già i testi
  delle sue specificità).

Se, mentre lavoravi alla bozza, qualcuno ha pubblicato un'altra versione dello stesso
oggetto (per esempio importando un pacchetto), la pubblicazione viene rifiutata per non
cancellare quel lavoro: in questo caso confronta la bozza con la versione pubblicata
(capitolo 13), riporta le modifiche e riprova.

### 3.5 Come lavora un gestore senza diritti di pubblicazione

Il gestore prepara la bozza, la porta a «Nessun problema» (o almeno a zero errori) e avvisa
un amministratore. L'amministratore apre lo stesso oggetto, controlla con **⋮ → Confronta
con la versione pubblicata** cosa è cambiato e preme **Pubblica**.

---

## 4. La pagina «Modelli e checklist»

Si apre dal menu laterale. Ha tre schede:

- **Modelli di atto** – un elemento per ogni modello attivo;
- **Specificità** – un elemento per ogni specificità attiva;
- **Checklist** – un elemento per ogni checklist attiva, con il livello (generica, del
  modello X, della specificità Y).

Accanto al numero tra parentesi (quanti oggetti ci sono), ogni elemento mostra titolo,
versione pubblicata (es. *v3*), codice e alcuni **bollini**:

| Bollino | Significato |
|---|---|
| **standard** | è identico allo standard del pacchetto |
| **standard modificato** | nasce dallo standard ma l'ente l'ha cambiato |
| **creato dall'ente** | non viene da un pacchetto |
| **nuovo, mai pubblicato** | esiste solo come bozza |
| **bozza in corso** | qualcuno ha salvato una bozza non ancora pubblicata |
| **N proposte** | (solo modelli) ci sono proposte aperte dei redattori |

Clicca un elemento per aprirne l'editor.

### 4.1 Creare un oggetto nuovo

1. Vai nella scheda giusta (Modelli, Specificità o Checklist).
2. Premi il pulsante in basso a destra (**Nuovo modello**, **Nuova specificità**, **Nuova
   checklist**).
3. Scrivi il **codice**: è l'identificativo interno, non si potrà cambiare. Solo lettere
   maiuscole, cifre, trattino basso e trattino; almeno due caratteri. Esempi:
   `DD_ACQUISTO_ARREDI`, `SCHEDA_ARREDI`. Le minuscole vengono convertite in maiuscole.
4. In **Parti da** scegli:
   - **Vuoto**: l'oggetto nasce con lo scheletro minimo (un modello vuoto ha già le quattro
     fasi, senza sezioni);
   - **Copia di: ...**: l'oggetto nasce identico a quello scelto. È quasi sempre la scelta
     migliore: partire da un modello simile e cambiarlo è molto più semplice che partire da
     zero.
5. Premi **Crea la bozza**: si apre subito l'editor.

L'oggetto nuovo è solo una bozza (bollino *nuovo, mai pubblicato*) finché un amministratore
non lo pubblica.

> Una copia è **indipendente** dall'originale: le modifiche future all'originale non si
> riflettono sulla copia. La copia di un oggetto standard risulta *creata dall'ente*.

---

## 5. Guida pratica: le operazioni più comuni

Questi percorsi coprono la maggior parte del lavoro quotidiano. I dettagli di ogni casella
sono nei capitoli successivi.

### 5.1 Correggere il testo di un capoverso

1. **Modelli e checklist** → scheda **Modelli di atto** → clicca il modello.
2. A sinistra, nella **Struttura**, apri la fase e trova il capoverso (l'elenco mostra
   l'inizio del testo). In alternativa, trovalo nell'**anteprima** a destra e cliccaci
   sopra: viene selezionato.
3. Al centro modifica la casella **Testo**. Attenzione a non rompere i dati scritti come
   `{{nome}}` (evidenziati in colore): se ne cancelli un pezzo, il dato diventa rosso.
4. Guarda l'anteprima a destra: si aggiorna da sola dopo un istante.
5. Premi **Salva bozza**.
6. Chiedi a un amministratore di pubblicare (o pubblica, se lo sei).

### 5.2 Aggiungere un capoverso che compare solo in certi casi

Esempio: nel modello di patrocinio vuoi aggiungere, solo quando l'ente **resiste** in
giudizio, il capoverso «Dato atto che il ricorso è stato notificato all'ente in data
{{data_notifica}};».

1. Apri il modello. Nella struttura seleziona la **sezione** in cui va il capoverso
   (es. «Dato atto che»).
2. Al centro premi **Aggiungi un capoverso**: compare in fondo alla sezione con il testo
   «Nuovo testo» ed è già selezionato.
3. Nella casella **Testo** scrivi «Dato atto che il ricorso è stato notificato all'ente in
   data » e poi digita `@`: si apre l'elenco dei dati. Il dato `data_notifica` non esiste
   ancora: chiudi con **Annulla** e vai al punto 4. (Se il dato esistesse, lo sceglieresti
   dall'elenco.)
4. Crea il dato: nella struttura, gruppo **Dati da compilare**, premi **+**. Compare
   *nuovo_dato_1*. Nel campo **Nome nel testo** scrivi `data_notifica` e premi **Invio**;
   in **Etichetta** scrivi «Data di notifica del ricorso»; in **Tipo** scegli **Data**.
5. Torna al capoverso (cliccalo nella struttura), metti il cursore dove va il dato, premi
   **Inserisci un dato** e scegli «Data di notifica del ricorso». Finisci il testo con «;».
6. Nella riquadro **Quando compare** premi **+ Condizione**. Nella prima tendina scegli la
   domanda «L'ente promuove il giudizio o vi resiste?», nella seconda **è**, nella terza
   **Resiste in giudizio**.
7. Sposta il capoverso con le frecce ↑ ↓ se deve stare in un'altra posizione nella sezione.
8. Nell'anteprima, apri **Risposte di prova** e alla domanda sulla posizione scegli
   *Resiste in giudizio*: il capoverso compare. Scegli *Promuove*: sparisce.
9. **Salva bozza**.
10. Vai alla checklist del modello e collega il controllo pertinente al nuovo capoverso
    (capitolo 11.6), oppure aggiungi un controllo nuovo.

### 5.3 Aggiungere una nuova domanda iniziale

1. Nella struttura, gruppo **Domande iniziali**, premi **+**.
2. Imposta **Identificativo** (minuscole e trattino basso, es. `urgenza`): è il nome con cui
   la domanda si usa nelle condizioni.
3. Scrivi il testo della domanda e scegli il **Tipo di risposta** (capitolo 6.3).
4. Usa la domanda nelle condizioni dei capoversi che devono dipendere dalla risposta.

### 5.4 Rendere un capoverso facoltativo

Seleziona il capoverso e attiva **Facoltativo**. Chi scrive l'atto potrà toglierlo o
aggiungerlo. Con **Incluso all'inizio** decidi se parte presente (sì) o assente (no, il
redattore lo aggiunge se serve).

### 5.5 Creare un modello nuovo partendo da uno esistente

1. **Modelli di atto** → **Nuovo modello** → codice (es. `DD_ACQUISTO_ARREDI`) → **Parti
   da: Copia di** *Determina di affidamento diretto di servizi e forniture*.
2. In **Dati generali** cambia titolo e descrizione.
3. Modifica o elimina i capoversi che non servono, aggiungi quelli nuovi.
4. Crea la checklist del modello: **Checklist** → **Nuova checklist** → codice
   `SCHEDA_ACQUISTO_ARREDI`, parti dalla copia della scheda del modello originale, e in
   **Si applica a** scegli il nuovo modello.
5. Se alcune specificità devono valere anche per il nuovo modello, apri ciascuna specificità
   e spunta il nuovo modello in **Si applica ai modelli** (capitolo 10.2).
6. Chiedi la pubblicazione di tutti gli oggetti.

### 5.6 Aggiungere un controllo a una checklist

1. **Checklist** → clicca la scheda.
2. A sinistra premi **Aggiungi un controllo**.
3. Compila **Titolo**, **Cosa verificare** e gli esiti (capitolo 11.3).
4. Aggiungi le norme con **Aggiungi** nel riquadro **Norme citate**.
5. In **Collegato a** premi **Scegli i capoversi** e spunta i capoversi che soddisfano il
   controllo.
6. **Salva bozza**.

### 5.7 Annullare tutto e ripartire

- Per un solo capoverso standard: seleziona il capoverso e premi **Ripristina lo standard**
  (compare solo se il capoverso è diverso dallo standard).
- Per tutta la bozza: **⋮ → Scarta la bozza**.

---

## 6. L'editor dei modelli di atto

### 6.1 Com'è fatta la pagina

Su uno schermo largo la pagina ha tre colonne. Su uno schermo stretto le tre colonne
diventano tre schede: **Struttura**, **Elemento**, **Anteprima**.

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ Modello: Determina di ...                  [Salva bozza] [⋮] [Pubblica]                 │
│ Pubblicata: v3 · standard modificato · bozza in corso                                   │
├──────────────────────┬───────────────────────────────────┬──────────────────────────────┤
│ STRUTTURA            │ ELEMENTO SELEZIONATO              │ ANTEPRIMA   [modello] [⚗]    │
│                      │                                   │ ▸ Risposte di prova (2)      │
│ ⓘ Dati generali      │  Capoverso          ↑ ↓ ⧉ 🗑      │ ──────────────────────────── │
│ ▾ Domande iniziali + │  Fase 2 › Visti                   │ Fase 1 · Intestazione        │
│ ▾ Fase 1 · ...     + │                                   │   COMUNE DI ...              │
│ ▾ Fase 2 · ...     + │  Identificativo [visto_tuel   ]   │ Fase 2 · Preambolo           │
│     Visti            │  Testo [ Visto il D.Lgs. ...  ]   │   Visto il D.Lgs. ...        │
│       Visto il ...   │  Quando compare [ Sempre ]        │   ▓Visto il capoverso scelto▓│
│ ▾ Dati da compilare +│  ☐ Facoltativo                    │   ...                        │
│ ▾ Valori calcolati  +│  ☑ Modificabile in bozza          │                              │
│ ▾ Risposte consigl. +│  Aiuto ...  Norme citate ...      │                              │
│ ▾ Scenari di prova   │                                   │                              │
├──────────────────────┤                                   │                              │
│ ✓ Nessun problema    │                                   │                              │
└──────────────────────┴───────────────────────────────────┴──────────────────────────────┘
```

- **In alto**: titolo, stato della versione, pulsanti **Salva bozza**, **⋮** (altre azioni)
  e **Pubblica**.
- **A sinistra**: la **struttura** del modello, con in fondo il riquadro di **errori e
  avvisi**.
- **Al centro**: l'editor dell'elemento selezionato nella struttura.
- **A destra**: l'**anteprima** dell'atto.

### 6.2 La struttura (colonna sinistra)

Clicca una voce per modificarla al centro. Le voci:

| Voce | Cosa contiene |
|---|---|
| **Dati generali** | titolo del modello, tipologia, provvedimento, organo, formula |
| **Domande iniziali** | le domande che l'app pone a chi scrive l'atto |
| **Fase N · titolo** | una voce **Impostazioni della fase** e, sotto, le sezioni con i loro capoversi |
| **Dati da compilare** | i dati usati nei testi (`{{importo}}`, `{{cig}}`...) |
| **Valori calcolati** | valori ricavati dalle risposte |
| **Risposte consigliate** | suggerimenti sulle risposte |
| **Scenari di prova** | insiemi di risposte salvati per l'anteprima |

Il pulsante **+** a destra di un gruppo aggiunge un elemento: una domanda, una sezione (nel
gruppo di una fase), un dato, un valore calcolato, una risposta consigliata.

Sotto ogni capoverso l'elenco mostra l'identificativo e delle note: *condizionato* (ha una
condizione), *facoltativo*, *proposta di modifica*. Un capoverso con il colore diverso è
**cambiato rispetto allo standard** oppure ha una **proposta** aperta di un redattore.

Una sezione che è un punto di innesto mostra *punto di innesto: nome*.

### 6.3 Le domande iniziali

Selezionando una domanda, al centro trovi:

| Casella | Spiegazione |
|---|---|
| **Identificativo** | nome della domanda nelle condizioni. Minuscole, cifre, trattino basso; unico nel modello. Esempio: `posizione`. **Se lo cambi, le condizioni che lo usano non si aggiornano da sole**: l'editor segnalerà un errore per ognuna, da correggere. |
| **Domanda** | il testo mostrato a chi scrive l'atto |
| **Tipo di risposta** | vedi tabella sotto |
| **Opzioni** | (solo per le scelte) le risposte possibili |
| **Spiegazione** | aiuto mostrato sotto la domanda: perché la si chiede, base normativa |
| **Quando si chiede** | condizione: la domanda compare solo se vale (es. la domanda sul modello di servizio cloud compare solo se il servizio è cloud). Vuota = sempre |
| **Risposte che bloccano l'atto** | condizione che, se vera, impedisce di procedere: per esempio un importo oltre la soglia dell'affidamento diretto |
| **Messaggio di blocco** | cosa leggere quando l'atto è bloccato, con il motivo e cosa fare |

Tipi di risposta:

| Tipo | Chi scrive l'atto vede | Nelle condizioni |
|---|---|---|
| **Sì / No** | due pulsanti | `sì` / `no` |
| **Scelta tra opzioni** | un elenco, una sola risposta | *è*, *non è*, *è uno tra* |
| **Più scelte tra opzioni** | caselle da spuntare | ogni opzione diventa una variabile sì/no |
| **Importo** | un importo in euro | confronti numerici (<, ≥, =...) |
| **Numero** | un numero | confronti numerici |
| **Testo** | una casella di testo | *è*, *non è*, *compilato*, *non compilato* |

**Le opzioni** hanno due parti:

- **Codice** (a sinistra): il valore interno usato nelle condizioni, es. `resistere`. Usa
  minuscole e trattino basso. **Cambiare il codice non aggiorna le condizioni** che lo
  usano: dopo averlo cambiato, ricontrolla le condizioni.
- **Testo dell'opzione** (a destra): quello che legge chi compila, es. «Resiste in giudizio
  (resistente o convenuto)». Questo si può cambiare liberamente.

La domanda **Caratteristiche dell'affidamento** (presente negli affidamenti) è speciale: le
sue opzioni sono le specificità che si applicano al modello e si gestiscono dalle
specificità. Non si elimina e non ha l'elenco delle opzioni.

Le frecce ↑ ↓ cambiano l'ordine in cui le domande vengono poste.

### 6.4 Le impostazioni della fase

| Casella | Spiegazione |
|---|---|
| **Titolo** | es. «Preambolo e motivazione» |
| **Descrizione** | aiuto mostrato a chi compila all'inizio della fase |
| **Formula iniziale** | testo centrato in grassetto che apre la fase nell'atto, es. «DETERMINA» |
| **Premessa** | testo introduttivo prima delle sezioni |
| **Punti numerati automaticamente** | i capoversi della fase vengono numerati (1., 2., 3...). Si usa di norma per il dispositivo |

Le quattro fasi sono fisse: non si aggiungono né si eliminano.

### 6.5 La sezione

| Casella | Spiegazione |
|---|---|
| **Titolo** | nome della sezione (es. «Visti»), usato nell'editor e nel percorso guidato |
| **Formula che introduce i capoversi** | es. «Visti» o «Premesso che»: i capoversi diventano un elenco introdotto da questa formula |
| **Quando compare la sezione** | condizione per l'intera sezione: se è falsa, scompaiono tutti i suoi capoversi |
| **Aiuto per chi compila** | spiegazione mostrata nel percorso guidato |
| **È l'oggetto dell'atto** | segna la sezione che contiene l'oggetto (usato per titolo del documento e registri) |
| **Qui si aggiungono i riferimenti scelti dalla libreria normativa** | quando chi scrive l'atto aggiunge norme dalla libreria, i relativi «Visto...» finiscono in questa sezione. Va attivato su una sola sezione, di norma i «Visti» |
| **Punto di innesto per le specificità** | nome con cui le specificità inseriscono i loro testi in questa sezione (capitolo 1.3). Lascialo vuoto se la sezione non deve ricevere testi dalle specificità. **Non cambiare il nome** di un punto di innesto esistente senza aggiornare le specificità che lo usano |

Pulsanti: ↑ ↓ spostano la sezione nella fase; 🗑 la elimina con tutti i suoi capoversi;
**Aggiungi un capoverso** ne crea uno nuovo in fondo.

### 6.6 Il capoverso

Il capoverso è l'unità di testo dell'atto. Al centro trovi:

**Barra in alto**

- ↑ ↓ spostano il capoverso nella sezione;
- ⧉ **Duplica** crea una copia subito sotto (con un identificativo nuovo);
- 🗑 **Elimina** (con conferma; l'eliminazione vale per gli atti solo dopo la
  pubblicazione);
- **Ripristina lo standard** compare solo se il capoverso esiste nello standard ed è stato
  modificato: riporta **tutte** le sue impostazioni (testo, condizione, aiuto...) a quelle
  dello standard.

Sotto la barra, in piccolo, la posizione: *Fase 2 › Visti*.

**Proposte**: se un redattore ha proposto un nuovo testo per questo capoverso, compare un
riquadro colorato con la proposta (capitolo 14).

**Caselle**

| Casella | Spiegazione |
|---|---|
| **Identificativo** | nome univoco del capoverso nel modello, es. `visto_tuel`. Le checklist lo usano per collegare i controlli e le bozze di atto per ricordare i testi riscritti. **Evita di cambiarlo** su un capoverso già pubblicato: le checklist collegate perderebbero il collegamento (l'editor lo segnala) e i testi riscritti dai redattori nelle bozze in corso non sarebbero più riconosciuti |
| **Testo** | il testo, con i dati come `{{nome}}` (capitolo 8) |
| **Quando compare** | la condizione (capitolo 7). Vuota = sempre |
| **Facoltativo** | chi scrive l'atto può togliere o aggiungere il capoverso |
| **Incluso all'inizio** | (solo per i facoltativi) se il capoverso parte presente |
| **Modificabile in bozza** | chi scrive l'atto può riscrivere il testo fisso direttamente nel documento (i dati restano legati alle caselle). Disattivalo per formule che non devono essere toccate |
| **Ripeti per ogni riga di** | (compare solo se esiste un dato di tipo *Elenco*) il capoverso viene ripetuto per ogni riga dell'elenco, es. un capoverso per ogni impegno di spesa. Nel testo si usano i dati della riga, es. `{{impegni.capitolo}}` |
| **Aiuto per chi compila** | spiegazione mostrata accanto al capoverso: perché c'è, base normativa, quando toglierlo |
| **Norme citate** | gli articoli citati nel capoverso, scelti dalla libreria normativa. Servono a verificare su Normattiva che la norma sia vigente alla data dell'atto |
| **Fonte del testo** | da dove viene il testo (es. «ANCI-1», «aggiunto», «delibera G.C. n. 12/2026»). Solo informativo |

**Aggiungere una norma**: nel riquadro **Norme citate** premi **Aggiungi**, cerca l'atto
nella libreria normativa, scegli gli articoli e conferma. Ogni norma compare come etichetta
(es. «art. 50 D.Lgs. 36/2023»); la × la toglie. Se una norma non c'è nella libreria, prima
va aggiunta alla libreria (menu **Libreria normativa**).

### 6.7 Dati generali del modello

| Casella | Spiegazione |
|---|---|
| **Titolo** | come il modello compare a chi sceglie con cosa scrivere un atto |
| **Descrizione** | quando usare il modello |
| **Tipologia di atto** | es. Determina |
| **Provvedimento** | es. «Determinazione dirigenziale» |
| **Organo** | es. «Dirigente» |
| **Formula del dispositivo** | es. «DETERMINA» |

### 6.8 I dati da compilare

Ogni dato è definito una volta e può essere usato in quanti testi si vuole. Chi scrive
l'atto lo compila **una volta sola**, nella fase in cui compare per la prima volta.

| Casella | Spiegazione |
|---|---|
| **Nome nel testo** | il nome tra le graffe, es. `importo_offerta` → `{{importo_offerta}}`. Minuscole, cifre, trattino basso. Per rinominarlo scrivi il nuovo nome e premi **Invio**: tutti i testi che lo usano vengono aggiornati automaticamente |
| **Etichetta** | come chi compila vede la casella, es. «Importo dell'offerta (IVA esclusa)» |
| **Tipo** | vedi tabella sotto |
| **Chi lo fornisce** | vedi tabella sotto |
| **Obbligatorio** | se l'atto può essere completato senza questo dato |
| **Valore proposto** | valore iniziale; può contenere altri dati, es. «Affidamento a {{operatore}}» |
| **Aiuto per chi compila** | spiegazione sotto la casella |
| **Colonne dell'elenco** | (solo tipo *Elenco*) le colonne di ogni riga, es. capitolo, importo, esercizio |

In fondo trovi **Usato nei capoversi**: cliccando un identificativo vai a quel capoverso. Se
il dato non è usato da nessuna parte, compare «Non usato in nessun capoverso» (e un avviso).

Tipi di dato:

| Tipo | Uso |
|---|---|
| Testo breve | nomi, numeri di protocollo |
| Testo lungo | motivazioni, descrizioni |
| Data | date (il calendario aiuta a sceglierle) |
| Importo | somme in euro, scritte nell'atto nel formato italiano |
| Numero | quantità |
| CIG / CUP | codici con controllo del formato |
| Codice fiscale o partita IVA | con controllo del formato |
| Elenco di righe | tabelle, es. gli impegni di spesa (capitolo, importo, esercizio) |

Chi fornisce il dato:

| Valore | Significato |
|---|---|
| Chi scrive l'atto | il redattore lo compila |
| Dati dell'ente | preso da Amministrazione → Dati dell'ente (es. nome del Comune) |
| Profilo dell'utente | preso dal profilo di chi scrive (es. settore, decreto di incarico) |
| Assegnato alla registrazione | numero e data dell'atto, assegnati dopo; non si compila |

### 6.9 I valori calcolati

Un valore calcolato è ricavato automaticamente dalle risposte, senza chiedere nulla a chi
compila. Serve per scrivere testi che cambiano a seconda dei casi, o per semplificare
condizioni usate spesso. Due forme:

**Sì / No secondo una condizione.** Il valore è vero quando la condizione è vera. Esempio:
`contributo_anac` è vero quando *Importo ≥ 40000*. Poi nei capoversi si usa la condizione
«contributo_anac: sì» invece di ripetere ogni volta il confronto con l'importo.

**Valore secondo i casi.** Un elenco di casi, ognuno con una condizione e un valore. Vale il
primo caso la cui condizione è vera; l'ultimo caso, **senza condizione**, vale in tutti gli
altri casi. Esempio `posizione_testo`:

| Caso | Quando | Valore |
|---|---|---|
| 1 | posizione è *Promuove il giudizio* | promuovere il giudizio |
| 2 | posizione è *Resiste in giudizio* | resistere nel giudizio |
| 3 | in tutti gli altri casi | proporre impugnazione |

Nel testo: «di conferire l'incarico per {{posizione_testo}}...».

**Aggiungi un caso** inserisce un caso prima dell'ultimo: imposta sempre la sua condizione
(un caso intermedio senza condizione renderebbe inutili quelli successivi).

Per rinominare un valore calcolato usa il sorgente (capitolo 15) oppure eliminalo e
ricrealo.

### 6.10 Le risposte consigliate

Una risposta consigliata mostra a chi compila un suggerimento motivato, senza imporlo.
Esempio: se il servizio è cloud, consigliare di rispondere *Sì* alla domanda sul
trattamento dei dati personali, perché il fornitore tratterà dati per conto dell'ente.

| Casella | Spiegazione |
|---|---|
| **Domanda** | la domanda a cui si riferisce il consiglio |
| **Risposta consigliata** | *Sì* oppure l'opzione consigliata |
| **Quando consigliarla** | condizione; vuota = sempre |
| **Perché** | la motivazione mostrata a chi compila |

---

## 7. Le condizioni: «Quando compare»

Le condizioni decidono quando un capoverso, una sezione o una domanda compaiono, quando
un atto è bloccato, quale valore assume un valore calcolato. Si costruiscono **con i menu**,
senza scrivere nulla.

### 7.1 Costruire una condizione con i menu

Il riquadro mostra «Sempre» (nessuna condizione) e il pulsante **+ Condizione**. Ogni
condizione è una riga con tre parti:

```
[ variabile                    ▾] [ operatore ▾] [ valore              ▾]  ×
  L'ente promuove il giudizio...     è             Resiste in giudizio
```

1. **Variabile**: la domanda, il valore calcolato o la caratteristica da guardare.
2. **Operatore**: dipende dal tipo di variabile.
3. **Valore**: un'opzione, un numero o un testo.

La × toglie la riga.

Operatori disponibili:

| Tipo di variabile | Operatori |
|---|---|
| Sì / No | **sì**, **no** (nessun valore da scegliere) |
| Scelta tra opzioni | **è**, **non è**, **è uno tra** (con più opzioni da spuntare) |
| Importo / numero | **<**, **≤**, **>**, **≥**, **=**, **≠** (scrivi il numero senza punti delle migliaia, es. 40000) |
| Testo | **è**, **non è**, **compilato**, **non compilato** |

### 7.2 Più condizioni insieme

Con due o più righe compare la scelta:

- **tutte** – il capoverso compare solo se **tutte** le righe sono vere;
- **almeno una** – il capoverso compare se **almeno una** riga è vera.

Esempi:

| Vuoi che compaia quando... | Righe | Scelta |
|---|---|---|
| il servizio è cloud **e** l'importo è almeno 40.000 | cloud: sì · importo ≥ 40000 | tutte |
| la fascia è micro **oppure** piccola | fascia: è uno tra micro, piccolo | (una riga sola) |
| c'è il PNRR **oppure** il servizio è cloud | pnrr: sì · cloud: sì | almeno una |
| l'importo è **sotto** 5.000 | importo < 5000 | — |

### 7.3 Condizioni avanzate

Alcune condizioni non si possono costruire con i menu, per esempio quelle che mescolano
«tutte» e «almeno una» («cloud **e** (pnrr **oppure** importo ≥ 140000)»). In questi casi
l'editor mostra una casella di testo con la condizione scritta, e il pulsante **Modifica
con i menu** non ha effetto. Puoi anche passare volontariamente alla scrittura con
**Scrivi la condizione**.

La sintassi:

| Scrittura | Significato |
|---|---|
| `cloud` | la domanda sì/no *cloud* ha risposta sì |
| `not cloud` | ha risposta no |
| `posizione == "resistere"` | l'opzione scelta è *resistere* (il codice, tra virgolette) |
| `posizione != "resistere"` | l'opzione scelta non è *resistere* |
| `fascia in ["micro", "piccolo"]` | l'opzione è una di quelle elencate |
| `importo >= 40000` | confronto numerico (anche `<`, `<=`, `>`, `==`, `!=`) |
| `a and b` | entrambe vere |
| `a or b` | almeno una vera |
| `cloud and (pnrr or importo >= 140000)` | le parentesi raggruppano |
| `a implica b` | se *a* è vera, allora anche *b* deve esserlo (usato nei blocchi) |

Nelle condizioni si usano **gli identificativi** (non i testi delle domande) e **i codici
delle opzioni** (non i testi delle opzioni).

### 7.4 Quali variabili sono disponibili

Nel menu delle variabili trovi:

- le **domande** del modello (con il loro testo);
- i **valori calcolati** («Calcolato: nome»);
- le **caratteristiche** (le specificità che si applicano al modello, «Caratteristica:
  nome»), vere quando chi scrive spunta quella caratteristica;
- nell'editor di una **specificità**, anche le domande e i valori calcolati dei modelli a
  cui si applica, e la voce «Questa specificità è scelta».

Se una condizione usa una variabile che non esiste più, la tendina mostra il vecchio nome e
l'editor segnala un errore.

---

## 8. I dati nel testo

### 8.1 Come appaiono

Nel testo di un capoverso i dati sono scritti tra doppie graffe: `{{importo}}`. L'editor li
evidenzia:

- **colore normale (evidenziato)** – dato esistente;
- **rosso** – dato inesistente (errore): nome sbagliato o dato eliminato.

Sotto la casella compaiono delle etichette con i nomi leggibili dei dati usati; un clic su
un'etichetta apre la definizione di quel dato.

### 8.2 Inserire un dato

Due modi:

1. premi **Inserisci un dato** sotto la casella; oppure
2. digita **@** all'inizio di una parola (dopo uno spazio o a inizio riga).

Si apre una finestra con tutti i dati disponibili, raggruppati (Dati, Dati degli elenchi,
Risposte alle domande, Valori calcolati, e per le specificità i dati dei modelli). Scrivi
qualche lettera nella casella **Cerca** per filtrare; clicca il dato. Il dato viene inserito
dove si trovava il cursore (la @ viene sostituita).

Si possono inserire nel testo:

- i **dati da compilare** – `{{cig}}`;
- le **colonne di un elenco** – `{{impegni.capitolo}}` (solo nei capoversi ripetuti per
  quell'elenco);
- le **risposte alle domande** – `{{importo}}` (per le scelte viene scritto il testo
  dell'opzione);
- i **valori calcolati** – `{{posizione_testo}}`.

### 8.3 Scrivere un dato a mano

Si può anche scrivere direttamente `{{nome}}`, senza spazi strani e con le doppie graffe. Se
il nome non esiste, diventa rosso. Per evitare errori di battitura è meglio usare il pulsante.

### 8.4 Cosa vede chi scrive l'atto

Chi scrive l'atto vede il testo con il valore al posto del dato. Se il capoverso è
modificabile, può riscrivere il testo fisso intorno ai dati; cliccando un dato, il cursore
va nella casella da compilare.

---

## 9. L'anteprima e gli scenari di prova

### 9.1 L'anteprima

La colonna di destra mostra l'atto come sarebbe composto con la definizione attuale
**compresa la bozza e le modifiche non salvate** e con le specificità attive. Si aggiorna da
sola un istante dopo ogni modifica.

- I **dati non compilati** compaiono come «Etichetta del dato» su sfondo colorato.
- Il **capoverso selezionato** nell'editor è evidenziato in giallo.
- **Clic su un capoverso** dell'anteprima: viene selezionato nella struttura e aperto al
  centro. È il modo più rapido per trovare un testo.
- Se le risposte di prova fanno scattare un **blocco**, il messaggio di blocco compare in
  rosso in cima.
- I capoversi **facoltativi non inclusi** all'inizio non compaiono.

### 9.2 Le risposte di prova

Apri **Risposte di prova** sopra l'anteprima: compaiono le domande, come le vedrebbe chi
scrive l'atto. Rispondi e l'anteprima mostra l'atto con quelle risposte. È il modo per
verificare che le condizioni funzionino: prova le diverse risposte e guarda quali capoversi
compaiono e spariscono.

- Per le risposte di testo, importo o numero premi **Invio** dopo aver scritto.
- **Azzera le risposte** riporta tutto senza risposta.

Le risposte di prova **non** sono salvate nel modello (servono solo a te), a meno che tu non
le salvi come scenario.

### 9.3 Gli scenari di prova

Uno scenario è un insieme di risposte di prova salvato con un nome, per ritrovare
rapidamente un caso tipico (es. «Cloud SaaS sopra i 40.000 euro», «Patrocinio, ente
resistente»).

- **Salvare**: imposta le risposte di prova, premi **Salva scenario** sopra l'anteprima,
  scrivi un nome. Lo scenario è parte del modello: va salvato con **Salva bozza** e diventa
  disponibile a tutti con la pubblicazione.
- **Usare**: premi l'icona ⚗ sopra l'anteprima e scegli lo scenario; oppure selezionalo nella
  struttura (gruppo **Scenari di prova**) e premi **Usa nell'anteprima**.
- **Rinominare o eliminare**: selezionalo nella struttura.

Consiglio: dopo aver aggiunto condizioni, prova sempre almeno uno scenario in cui il
capoverso deve comparire e uno in cui non deve.

---

## 10. L'editor delle specificità

L'editor delle specificità ha la stessa forma di quello dei modelli, con alcune differenze.

### 10.1 La struttura

- **Specificità** (dati generali);
- **Domande iniziali**: domande aggiuntive poste solo quando la specificità è scelta (es.
  «I servizi sono erogati in cloud?»);
- **Testi inseriti nei modelli**: i **punti di inserimento**, ognuno con i suoi capoversi;
- **Dati da compilare**, **Valori calcolati**, **Risposte consigliate**: come nei modelli,
  e valgono solo quando la specificità è scelta.

Non ci sono fasi né scenari.

### 10.2 Dati generali della specificità

| Casella | Spiegazione |
|---|---|
| **Nome** | come compare tra le caratteristiche dell'atto, es. «Servizi / Forniture Cloud ICT» |
| **Variabile (fattore)** | nome con cui la specificità si usa nelle condizioni, es. `ict_cloud`. Minuscole e trattino basso. Non cambiarlo su una specificità pubblicata senza aggiornare le condizioni che lo usano |
| **Descrizione** | cosa attiva (mostrato a chi sceglie le caratteristiche) |
| **Si applica ai modelli** | spunta i modelli in cui la specificità è disponibile. Togliendo la spunta, la specificità sparisce dalle caratteristiche di quel modello dopo la pubblicazione |

### 10.3 I punti di inserimento

Ogni punto di inserimento dice **dove** vanno i capoversi che contiene.

1. Nella struttura, gruppo **Testi inseriti nei modelli**, premi **+**: nasce un punto di
   inserimento con un capoverso.
2. Selezionalo: al centro scegli **Dove inserire i testi** – l'elenco mostra i punti di
   innesto dei modelli selezionati, con il titolo della sezione (es. «visti_normativi
   (Visti)»). Se l'elenco è vuoto, prima spunta i modelli in **Dati generali**.
3. In **Posizione nella sezione** scegli **In fondo alla sezione** oppure **Prima del
   capoverso ...** per inserire i testi prima di un capoverso preciso del modello.
4. Premi **Aggiungi un capoverso** per aggiungere altri capoversi allo stesso punto.

I capoversi di una specificità si modificano esattamente come quelli di un modello
(capitolo 6.6). Tutti compaiono **solo se la specificità è scelta**; la loro condizione
**Quando compare** si aggiunge a questo (il riquadro vuoto dice «Sempre, quando la
specificità è scelta»).

Se più punti di inserimento servono la stessa sezione con posizioni diverse (es. alcuni
capoversi in fondo e altri prima di un capoverso preciso), crea due punti di inserimento con
lo stesso innesto.

### 10.4 L'anteprima della specificità

Sopra l'anteprima scegli **in quale modello** vederla (tra quelli a cui si applica).
L'anteprima mostra l'intero atto di quel modello con la specificità scelta; i capoversi
portati dalla specificità sono **evidenziati**, così si vede subito dove finiscono.

### 10.5 Cosa succede alla pubblicazione

Pubblicare una specificità crea automaticamente una nuova versione di **tutti i modelli a
cui si applica**, perché i testi vengono composti nei modelli. Gli atti già iniziati restano
sulla versione precedente.

---

## 11. L'editor delle checklist

### 11.1 Com'è fatta la pagina

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Checklist: Scheda di controllo ...          [Salva bozza] [⋮] [Pubblica]         │
├──────────────────────────────┬───────────────────────────────────────────────────┤
│ ⓘ Dati generali              │ Controllo 3                         ↑ ↓ ⧉ 🗑      │
│   Si applica a: modello ...  │                                                   │
│ ─────────────────────────    │ Titolo del controllo [                        ]   │
│ ① Codice dell'amm. digitale  │ ☑ Obbligatorio                                    │
│ ② Qualificazione ACN         │ Cosa verificare     [                         ]   │
│ ③ Clausola di risoluzione    │ È conforme se       [                         ]   │
│   collegato a 2 capoversi    │ Non è conforme se   [                         ]   │
│ [+ Aggiungi un controllo]    │ È dubbio se         [                         ]   │
│                              │ Non si applica se   [                         ]   │
│                              │ Note per chi valuta [                         ]   │
├──────────────────────────────┤ Norme citate  [art. 68 D.Lgs. 82/2005 ×] [+]     │
│ ⚠ 0 errori, 1 avvisi         │ Collegato a   [🔗 cloud_risoluzione ×]            │
└──────────────────────────────┴───────────────────────────────────────────────────┘
```

A sinistra i **controlli** in ordine, con il riquadro di errori e avvisi; a destra il
controllo selezionato. Su uno schermo stretto le due parti diventano schede.

### 11.2 Dati generali della checklist

| Casella | Spiegazione |
|---|---|
| **Titolo** | nome della scheda, compare nei risultati della verifica |
| **Descrizione** | a cosa serve |
| **Tipologia di atto** | es. Determina |
| **Si applica a** | **Ogni atto della tipologia (generica)**, oppure **Modello: ...**, oppure **Specificità: ...** (capitolo 1.4) |

Ogni modello dovrebbe avere la sua checklist e ogni specificità la sua: l'editor del modello
e quello della specificità avvisano se manca.

### 11.3 Il controllo e la sua regola

| Casella | Spiegazione |
|---|---|
| **Titolo del controllo** | breve, compare nei risultati (es. «Qualificazione ACN del servizio cloud») |
| **Obbligatorio** | se attivo, un esito non conforme rende non conforme l'atto; se disattivo il controllo è una buona pratica |
| **Cosa verificare** | la descrizione di cosa controllare, di solito «Verifica che l'atto...» |
| **È conforme se** | quando l'esito è positivo |
| **Non è conforme se** | quando l'esito è negativo |
| **È dubbio se** | quando non si può decidere dal solo testo e serve il controllore |
| **Non si applica se** | quando il controllo non riguarda l'atto |
| **Note per chi valuta** | precisazioni (eccezioni, esempi, cosa non considerare) |

Le caselle degli esiti sono facoltative: compila quelle che servono. Ogni esito va scritto
su **una riga** (gli a capo vengono tolti).

**Come scrivere una buona regola.** Il modello linguistico valuta un controllo alla volta,
leggendo solo l'atto e le norme indicate. Quindi:

- descrivi **cosa deve esserci nel testo dell'atto**, non cosa deve aver fatto l'ufficio
  (il modello non vede i documenti di gara, vede l'atto);
- un controllo, **una cosa sola**: se servono due verifiche, fai due controlli;
- negli esiti sii **concreto**: «l'atto indica il CIG» è meglio di «il CIG è corretto»;
- usa **Non si applica se** per i casi in cui il controllo non ha senso, così non viene
  segnato come non conforme;
- cita la norma nel testo («art. 50, comma 1, lett. b), D.Lgs. 36/2023») **e** aggiungila in
  **Norme citate**: il testo vigente viene passato al modello.

Esempio completo:

> **Titolo**: Qualificazione ACN del servizio cloud
>
> **Cosa verificare**: Verifica che l'atto attesti che il servizio cloud acquistato è
> qualificato nel Catalogo dei servizi cloud dell'Agenzia per la Cybersicurezza Nazionale
> per un livello adeguato alla classificazione dei dati.
>
> **È conforme se**: l'atto attesta la qualificazione e ne indica il livello o gli estremi
> nel Catalogo.
>
> **Non è conforme se**: l'atto acquista un servizio cloud senza alcun riferimento alla
> qualificazione ACN.
>
> **È dubbio se**: la qualificazione è citata senza indicare il livello o gli estremi.
>
> **Non si applica se**: il servizio non è erogato in cloud.

### 11.4 Testo libero

Le regole che non seguono lo schema dei campi (per esempio scritte in un'unica frase, o con
un esito ripetuto due volte) si aprono come **Regola (testo libero)**, una casella unica.
Per passare ai campi guidati premi **Usa i campi guidati**: tutto il testo finisce in
**Cosa verificare** e completi gli esiti. Puoi anche fare il contrario con **Modifica come
testo libero**.

Nel testo libero, gli esiti si scrivono su righe separate con esattamente queste parole:
`È CONFORME se ...`, `È NON_CONFORME se ...`, `È DUBBIO se ...`,
`È NON_APPLICABILE se ...`.

### 11.5 Norme citate

Come nei capoversi: **Aggiungi** apre la libreria normativa; scegli gli articoli. Il testo
vigente degli articoli alla data dell'atto viene passato a chi valuta, quindi indica solo gli
articoli davvero pertinenti (troppi articoli rendono la valutazione meno precisa).

### 11.6 Collegato a: i capoversi del modello

Il riquadro **Collegato a** dice quali capoversi del modello (o della specificità) servono a
soddisfare il controllo. Esempio: il controllo «Qualificazione ACN» è collegato al capoverso
`cloud_qualificazione_acn` della specificità Cloud.

Per collegare: **Scegli i capoversi** → cerca nel testo → spunta → **Conferma**. Ogni
capoverso collegato compare con il suo testo; la × lo scollega.

A cosa serve:

- a chi modifica il modello: se tocca o elimina un capoverso collegato, sa che c'è un
  controllo che dipende da lui (l'editor avvisa se il collegamento si rompe);
- a chi modifica la checklist: vede subito quale testo il modello propone per soddisfare il
  controllo;
- a mantenere coerenti bozze e controlli: un controllo senza capoversi collegati
  probabilmente verifica qualcosa che il modello non scrive.

Note:

- i collegamenti valgono solo per le checklist **di modello** o **di specificità**; una
  checklist generica vale per tutti i modelli e non si collega;
- un collegamento a un capoverso che non esiste più compare con l'icona di collegamento
  spezzato e il testo «capoverso inesistente»: togli il collegamento o scegli il capoverso
  nuovo.

### 11.7 Ordine dei controlli

Le frecce ↑ ↓ spostano il controllo; l'ordine è quello dei risultati della verifica. ⧉
duplica il controllo (utile per creare controlli simili), 🗑 lo elimina.

---

## 12. Errori e avvisi

Il riquadro in basso a sinistra elenca i problemi. Gli **errori** bloccano la
pubblicazione, gli **avvisi** no.

### 12.1 Errori frequenti

| Messaggio (o simile) | Causa | Rimedio |
|---|---|---|
| Dato inesistente / campo `xxx` non definito | nel testo c'è `{{xxx}}` ma il dato non esiste (in rosso nel testo) | correggi il nome o crea il dato |
| Condizione non valida / variabile `xxx` sconosciuta | una condizione usa una domanda, un'opzione o un valore calcolato che non esiste (spesso dopo aver cambiato un identificativo) | apri l'elemento e correggi la condizione |
| Identificativo duplicato | due capoversi o due domande hanno lo stesso identificativo | rinominane uno |
| Tipologia di atto inesistente | la tipologia scelta non esiste | scegli una tipologia dall'elenco |
| Il codice della definizione deve essere ... | nel sorgente è stato cambiato il codice | non cambiare il codice nel sorgente |
| Nel modello X: ... | (specificità) i testi della specificità, composti nel modello X, producono un errore: per esempio usano un dato che X non ha o un punto di innesto che X non ha | correggi la specificità, oppure aggiungi il dato o il punto di innesto al modello |

### 12.2 Avvisi

| Messaggio | Significato | Cosa fare |
|---|---|---|
| Il dato «...» non è usato in nessun testo | dato definito ma mai usato: chi compila non lo vedrà mai | usalo in un testo o eliminalo |
| La sezione «...» non ha capoversi | sezione vuota | aggiungi capoversi o elimina la sezione |
| Manca la checklist del modello / della specificità | non esiste una checklist collegata | crea la checklist (capitolo 5.5) |
| Il controllo «...» della checklist X è collegato al capoverso Y, che non esiste più | hai eliminato o rinominato un capoverso collegato | aggiorna la checklist X |
| Il controllo «...» rimanda al capoverso Y, che non esiste | (checklist) collegamento rotto | scegli il capoverso giusto |
| N controlli non sono collegati a nessun capoverso | (checklist) controlli senza collegamenti | collega i capoversi, se esistono |
| Il controllo «...» è collegato a capoversi, ma la checklist è generica | i collegamenti in una checklist generica non servono | togli i collegamenti o cambia il livello della checklist |
| Il modello X non esiste o non è attivo | la specificità o la checklist rimanda a un modello disattivato | aggiorna l'elenco dei modelli |

Il controllo considera i testi **del modello e delle specificità che gli si applicano**: un
dato che sembra non usato nel modello può essere usato da una specificità, e in quel caso
non viene segnalato.

---

## 13. Confronti, versioni, ripristino dello standard

Dal menu **⋮** in alto:

- **Confronta con la versione pubblicata** – elenca le differenze tra ciò che stai
  modificando (bozza e modifiche non salvate) e la versione usata oggi dagli atti. Ogni
  differenza indica l'elemento (capoverso, domanda, dato, controllo), dove si trova e lo
  stato: **aggiunto**, **modificato**, **tolto**, con il testo prima (a sinistra, in rosso)
  e dopo (a destra, in verde). Usalo **prima di pubblicare**.
- **Confronta con lo standard** – le differenze rispetto allo standard del pacchetto: tutto
  ciò che l'ente ha personalizzato.
- **Versioni** – l'elenco delle versioni pubblicate, con data, autore e pacchetto di
  provenienza.
- **Sorgente (modalità avanzata)** – capitolo 15.
- **Scarta la bozza** – capitolo 3.2.

**Ripristina lo standard** (sul singolo capoverso) riporta quel capoverso com'è nello
standard. Gli altri capoversi non cambiano. Il ripristino, come ogni modifica, va salvato e
pubblicato.

Per tornare a una **versione precedente** dell'ente non c'è un pulsante: confronta e
riporta a mano le modifiche, oppure chiedi all'amministratore di usare l'esportazione dei
pacchetti come copia di sicurezza prima delle modifiche importanti (Amministrazione →
Pacchetti → esporta).

---

## 14. Le proposte dei redattori

### 14.1 Come nasce una proposta

Chi scrive un atto può riscrivere il testo di un capoverso modificabile direttamente nel
documento. Sotto il capoverso riscritto compaiono due collegamenti:

- **Ripristina testo standard** – torna al testo del modello;
- **Proponi come testo del modello** – apre una finestra con il testo riscritto (i dati
  compaiono come `{{nome}}`), modificabile, e una casella **Perché**. **Invia la
  proposta** la manda ai gestori dei modelli.

### 14.2 Come la gestisce il gestore

- Nella pagina **Modelli e checklist** il modello mostra il bollino **N proposte**.
- Nell'editor del modello il capoverso interessato è colorato, con la nota *proposta di
  modifica* e l'icona del fumetto.
- Selezionando il capoverso, in cima compare il riquadro della proposta: chi l'ha fatta,
  quando, la motivazione e il testo proposto.

Due azioni:

- **Applica alla bozza** – il testo proposto sostituisce quello del capoverso **nella
  bozza** e la proposta risulta accolta. Controlla il testo (i dati devono essere validi),
  salva la bozza e fai pubblicare: solo allora gli atti useranno il nuovo testo.
- **Respingi** – chiede un motivo facoltativo e chiude la proposta.

La proposta si riferisce alla versione del modello in uso quando è stata fatta: se nel
frattempo il capoverso è cambiato, valuta se la proposta ha ancora senso.

---

## 15. Il sorgente (modalità avanzata)

**⋮ → Sorgente (modalità avanzata)** mostra la definizione completa in formato testo: YAML
per modelli e specificità, JSON per le checklist. È lo stesso formato dei file del
pacchetto.

Serve per:

- operazioni rapide su molti elementi (es. sostituire una parola in tutti i testi);
- copiare parti da un altro modello;
- le poche impostazioni non presenti nei menu (es. rinominare un valore calcolato).

Modifica il testo e premi **Applica all'editor**: l'app controlla il formato; se è
sbagliato mostra l'errore in rosso e non applica nulla. Se è corretto, la definizione
dell'editor viene sostituita (e va salvata con **Salva bozza** come ogni modifica).
**Annulla** chiude senza cambiare nulla.

Attenzione: nel YAML i rientri (gli spazi a inizio riga) hanno significato e i testi che
contengono «:» o iniziano con caratteri speciali vanno tra virgolette. Se non sei sicuro,
usa i menu.

---

## 16. Domande frequenti e problemi

**Ho modificato un modello ma gli atti non cambiano.**
Le modifiche sono in bozza: gli atti usano solo la versione pubblicata. Chiedi a un
amministratore di pubblicare. Ricorda anche che le bozze di atto già iniziate restano sulla
versione con cui sono nate: per vedere le modifiche serve un atto nuovo.

**Il pulsante Pubblica è grigio.**
Non sei amministratore (passa il mouse sul pulsante: compare il motivo), oppure non ci sono
modifiche né bozze da pubblicare.

**La pubblicazione dice che ci sono errori.**
Apri il riquadro in basso a sinistra e correggi ogni errore (capitolo 12.1).

**Ho cambiato l'identificativo di una domanda e ora ci sono molti errori.**
Le condizioni usano l'identificativo. Ripristina il vecchio identificativo oppure correggi
ogni condizione segnalata. In generale, non cambiare gli identificativi di elementi già
pubblicati.

**Un capoverso non compare nell'anteprima.**
Controlla, in ordine: la condizione del capoverso; la condizione della sezione; le
risposte di prova (la condizione può essere vera solo con certe risposte); se è facoltativo
non incluso all'inizio. Per una specificità: che sia scelta, che il modello dell'anteprima
sia tra quelli a cui si applica, che il punto di innesto esista nel modello.

**Nell'anteprima vedo «Etichetta» colorata invece del valore.**
È normale: l'anteprima non ha dati compilati e mostra il nome del dato al suo posto.

**Il dato nel testo è rosso.**
Il nome non corrisponde a nessun dato. Correggi il nome o crea il dato. Attenzione agli
spazi e alle maiuscole: `{{Importo}}` e `{{importo}}` sono diversi.

**La condizione è mostrata come testo e non con i menu.**
È una condizione avanzata (capitolo 7.3). Si modifica come testo, oppure si semplifica.

**Due colleghi lavorano sullo stesso modello.**
La bozza è una sola: vince l'ultimo salvataggio. Lavorate uno alla volta, oppure su oggetti
diversi.

**Ho chiuso il browser senza salvare.**
Le modifiche non salvate sono perse; la bozza salvata in precedenza è ancora lì.

**Voglio eliminare un modello, una specificità o una checklist.**
Un oggetto mai pubblicato si elimina con **⋮ → Scarta la bozza**. Per gli oggetti pubblicati
l'editor non ha ancora un comando di disattivazione: oggi si può farlo con un pacchetto
(Amministrazione → Pacchetti, azione *disattiva*).

**Arriva un nuovo pacchetto standard: perdo le mie modifiche?**
No. L'amministratore, in Amministrazione → Pacchetti, vede per ogni oggetto se l'ente l'ha
modificato e sceglie se mantenere la versione dell'ente o prendere quella nuova. Il
bollino *standard modificato* indica gli oggetti personalizzati.

---

## 17. Glossario

| Termine | Significato |
|---|---|
| **Bozza** (della configurazione) | modifiche salvate ma non pubblicate, invisibili agli atti. Da non confondere con la bozza di un atto |
| **Capoverso** | unità di testo dell'atto, con il suo identificativo, la condizione e le impostazioni |
| **Caratteristica** | una specificità scelta da chi scrive l'atto |
| **Checklist** (scheda di controllo) | elenco di controlli applicati dalla verifica |
| **Codice** | identificativo di un modello, specificità o checklist (maiuscole), non modificabile |
| **Condizione** | regola che decide quando compare un elemento |
| **Controllo** | voce di una checklist, con la sua regola |
| **Dato** | informazione da compilare, scritta nel testo come `{{nome}}` |
| **Fase** | una delle quattro parti dell'atto (intestazione, preambolo, dispositivo, chiusura) |
| **Fattore** | nome della variabile di una specificità nelle condizioni |
| **Identificativo** | nome interno di domande e capoversi (minuscole) |
| **Innesto / punto di innesto** | sezione di un modello in cui le specificità inseriscono testi |
| **Modello di atto** | schema da cui nasce un atto |
| **Pacchetto** | insieme di modelli, specificità e checklist standard distribuito come file |
| **Proposta** | testo di un capoverso proposto da un redattore |
| **Pubblicazione** | passaggio della bozza a nuova versione usata dagli atti |
| **Scenario** | insieme di risposte di prova salvato |
| **Sezione** | gruppo di capoversi in una fase |
| **Specificità** (modulo di regole) | insieme di testi e domande aggiunti ai modelli quando l'atto ha una caratteristica |
| **Standard** | versione fornita con il pacchetto, da cui l'ente parte |
| **Valore calcolato** | valore ricavato dalle risposte, senza chiederlo |
| **Versione** | ogni pubblicazione crea una versione numerata (v1, v2...) |
