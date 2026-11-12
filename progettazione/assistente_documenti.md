# Assistente — documenti della conversazione (proposta)

Stato: **fasi 1 e 2 realizzate** (rag: sessioni di documenti; atti-pa: sessione, pannello,
domande con citazioni). Da fare: azioni Riassumi, Confronta ed Estrai (fase 3) e batteria di
prova (fase 4). La parte del rag è descritta nel repository `rag`, in `misc/SESSIONI_DOCUMENTI.md`.
Le differenze rispetto alla proposta iniziale sono nel §10.

## 1. Obiettivo

L'assistente serve a porre rimedio alla **Shadow AI**: dare ai dipendenti un'alternativa
autorizzata, comoda quanto ChatGPT, così che non incollino i dati dell'ente in servizi esterni.
Uno dei motivi più frequenti per cui si va su ChatGPT o NotebookLM è lavorare su **più
documenti insieme**: "confronta queste due delibere", "cosa dice la legge sui termini?",
"elenca le scadenze del bando".

Si aggiunge quindi un **pannello dei documenti della conversazione**, sul modello di
NotebookLM ma molto più semplice, perché l'obiettivo di atti-pa è un altro.

**Fuori dal perimetro:** quaderni salvati o condivisi, sintesi audio, mappe concettuali, FAQ
generate, documenti conservati tra una sessione e l'altra.

## 2. Come funziona oggi

Un allegato si converte in testo con il rag (`POST /external/v1/convert`) e il testo entra
**nel messaggio** dell'utente. Da lì fa parte della conversazione: si rimanda all'LLM a ogni
domanda, non si toglie, consuma il limite di `ASSISTENTE_MAX_CARATTERI`. Con due o tre leggi o
delibere si arriva al limite, e anche prima del limite l'LLM usa male la parte centrale di un
contesto lungo ("lost in the middle").

## 3. Decisioni

1. **I documenti sono legati alla sessione della pagina.** Ricaricando la pagina o con "Nuova
   conversazione" si perdono. Sul rag la sessione si chiude esplicitamente ("Nuova
   conversazione", chiusura della pagina quando il browser lo permette) e comunque scade da
   sola dopo un periodo senza uso.
2. **Tutti i documenti vanno nel rag**, in una sessione temporanea in Qdrant, anche quelli
   piccoli. Non c'è una modalità "testo intero nel contesto": un solo percorso, prevedibile.
3. **La strategia dipende dal compito, non dalla dimensione dei documenti**, e il compito lo
   sceglie l'utente:
   - **domanda libera** → ricerca dei passaggi pertinenti nei documenti selezionati e risposta
     con le citazioni;
   - **azioni esplicite** (Riassumi, Confronta, Estrai) → lettura delle sezioni in ordine,
     un blocco alla volta, e sintesi finale (map-reduce).

   In entrambi i casi ogni chiamata all'LLM ha un contesto corto: il problema della parte
   centrale non si pone e le leggi intere si gestiscono.
4. **atti-pa fa da tramite verso il rag**, come per la conversione: la chiave del rag resta sul
   server e l'app non parla mai con il rag.

## 4. Esperienza d'uso

- **Pannello "Documenti"** accanto alla chat (sul telefono si apre dal basso). Sostituisce
  l'allegato al singolo messaggio: per incollare un testo breve resta il campo del messaggio.
- Ogni documento mostra nome, dimensione (pagine e token stimati) e stato: *in conversione*,
  *in indicizzazione*, *pronto*, *errore* con il motivo. Si può togliere.
- Una **casella** per selezionarlo: domande e azioni lavorano solo sui documenti selezionati.
  Selezionare e deselezionare vale dalla domanda successiva.
- **Pulsanti delle azioni**: *Riassumi*, *Confronta* (almeno due documenti selezionati),
  *Estrai…* (scadenze, importi, obblighi, soggetti; con un campo libero per altro). Durante
  un'azione lunga si vede l'avanzamento ("sezione 12 di 40").
- Nelle risposte le **citazioni** indicano documento e sezione, per esempio
  "[Delibera_45.pdf, §3]". In questa prima versione non sono link.
- Limiti visibili nel pannello: al massimo 10 documenti e il totale dei token della sessione
  (vedi il documento del rag).
- Con un LLM esterno resta l'avviso di oggi, esteso ai documenti.

## 5. API di atti-pa (modulo assistente)

```
POST   /api/v1/assistente/sessione                     crea la sessione nel rag → {sessione}
DELETE /api/v1/assistente/sessione                     la chiude (header con la sessione)
POST   /api/v1/assistente/sessione/documenti           carica un documento → 202 {doc_id}
GET    /api/v1/assistente/sessione/documenti/<did>     stato, token, sezioni
DELETE /api/v1/assistente/sessione/documenti/<did>     lo toglie
POST   /api/v1/assistente/messaggi                     + {sessione, documenti: [doc_id...]}
POST   /api/v1/assistente/azioni                       {sessione, tipo, documenti, istruzioni} → lavoro
GET    /api/v1/assistente/azioni/<id>                  stato, avanzamento, risultato
```

- **Sessione senza tabelle nuove.** `sessione` è un token firmato dall'API (HMAC con un
  segreto del server) che contiene l'id della sessione del rag, l'ente e l'utente. Un utente
  non può usare la sessione di un altro, e atti-pa non salva nulla. L'`owner` passato al rag è
  un'impronta di ente e utente.
- **Domanda libera** (`/messaggi`): l'API chiama `search` del rag con l'ultima domanda,
  riformulata con le domande precedenti se la conversazione lo richiede, sui documenti
  selezionati, e mette insieme il prompt (§6). Senza documenti selezionati la chat funziona
  come oggi.
- **Azioni** (`/azioni`): possono richiedere decine di chiamate all'LLM, quindi sono un
  **lavoro asincrono nel worker**, come le analisi della trasparenza. L'app segue lo stato. Il
  risultato è un messaggio dell'assistente nella conversazione, e la conversazione resta
  nell'app come oggi.
- Il limite di `ASSISTENTE_MAX_CARATTERI` resta, ma vale solo per la conversazione: i
  documenti non ci entrano più.

## 6. Prompt

- **Ordine:** prima i passaggi trovati, ciascuno tra delimitatori con documento e sezione; poi
  la conversazione; **in fondo** la domanda e le regole essenziali ripetute (rispondi solo dai
  passaggi, cita documento e sezione, di' se l'informazione non c'è).
- **Prima le citazioni, poi la risposta:** il modello individua i passaggi che usa e risponde
  solo su quelli.
- **Azioni:**
  - *Riassumi*: riassunto di ogni blocco di sezioni, poi riassunto dei riassunti, con la
    struttura del documento (premesse, dispositivo, allegati);
  - *Confronta*: scheda strutturata per ogni documento (oggetto, soggetti, importi, date,
    obblighi), poi confronto tra le schede;
  - *Estrai*: estrazione per blocco in formato tabellare, poi unione e rimozione dei
    duplicati.
- I prompt nuovi si aggiungono a `common/prompt/` come gli altri e si possono personalizzare
  per ente.

## 7. Batteria di prova

Prima di chiudere il lavoro, una batteria sul **modello di produzione**: una ventina di
domande con risposta nota su delibere e leggi vere (risposta all'inizio, al centro e alla fine
del documento), più alcuni riassunti e confronti valutati a mano. Serve a regolare il numero di
passaggi, le dimensioni di sezioni e pezzi nel rag e i blocchi delle azioni. Le domande e le
risposte attese si conservano, per ripetere la prova quando cambia il modello.

## 8. Fasi

1. **rag**: sessioni di documenti (vedi il documento del rag). È il prerequisito. **Fatto.**
2. **atti-pa**: token di sessione, pannello dei documenti, domande libere con ricerca e
   citazioni. Gli allegati al messaggio si tolgono. **Fatto.**
3. **atti-pa**: azioni Riassumi, Confronta ed Estrai nel worker.
4. **Batteria di prova** e regolazioni.
5. **Dopo**, se serve: aggiungere al pannello articoli dalla libreria delle norme (Normattiva)
   invece del PDF della legge intera.

## 9. Da decidere

- Testo dell'informativa: i documenti restano sul server del rag fino alla chiusura o alla
  scadenza della sessione, mentre la vecchia conversione non lasciava copie.
- `max_model_len` del modello in produzione: decide quanti passaggi e quanta conversazione
  entrano in una domanda. Per ora valori prudenti per un contesto di 32k, configurabili
  (`ASSISTENTE_PASSAGGI` 8, `ASSISTENTE_CARATTERI_PASSAGGI` 24.000).

Decisi: scadenza 2 ore dall'ultimo uso e 12 al massimo; 10 documenti e 500.000 token per
sessione (impostazioni `SESSION_*` del rag).

## 10. Come è stato realizzato (fase 2)

- **Rotte** in `api/src/routers/assistente.py`: `POST/GET/DELETE /sessione`,
  `POST /sessione/documenti`, `GET` e `DELETE /sessione/documenti/<id>`, `/messaggi` con
  `documenti`. Client in `common/rag.py`. Le vecchie rotte `/allegati` sono state tolte.
- **Token**: id della sessione del rag e firma HMAC (con `JWT_SECRET`) di sessione, ente e
  utente, nell'intestazione `X-Assistente-Sessione`. Un token di un altro utente risponde 404.
  L'`owner` passato al rag è un'impronta SHA-256 di ente e utente.
- **Ordine del prompt**: la conversazione resta com'è; l'ultimo messaggio dell'utente diventa
  `common/prompt/assistente_documenti.md` con, nell'ordine, i passaggi trovati (tra
  delimitatori con documento e parte), la domanda e le regole. Così i passaggi stanno vicino
  alla domanda e le regole in fondo; le risposte precedenti restano senza passaggi.
- **Citazioni** nel testo, dopo ogni informazione: "[Delibera 45.pdf, parte 3]". "Parte" e non
  "§", per non confonderla con commi e paragrafi del documento. Sotto la risposta l'app mostra
  i passaggi consultati, raggruppati per documento.
- **Domanda per la ricerca**: l'ultima domanda; se è breve (meno di 80 caratteri, es. "e a chi
  va?") insieme alla precedente dell'utente. Niente riformulazione con l'LLM in questa versione:
  costerebbe una chiamata in più a ogni domanda.
- **Budget**: i passaggi entrano in ordine di pertinenza fino ad
  `ASSISTENTE_CARATTERI_PASSAGGI`; l'ultimo che non ci sta si tronca con "[…]".
- **App**: pannello "Documenti" a lato da 1000 pixel di larghezza, dal basso sotto; casella di
  selezione, stato, parti e token, barra dello spazio usato. "Nuova conversazione" chiude la
  sessione nel rag. Se la sessione è scaduta i documenti risultano in errore e vanno ricaricati.
