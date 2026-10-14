# Prompt dell'LLM

Testi inviati al modello linguistico, caricati da `common/llm.py`. Si possono modificare
senza toccare il codice: le modifiche valgono al riavvio di API e worker.

| File | Uso | Segnaposto |
|---|---|---|
| `verifica_sistema.md` | prompt di sistema della verifica (un elemento di checklist alla volta) | — |
| `verifica_utente.md` | messaggio con criterio, data, norme e testo dell'atto | `titolo`, `regola`, `data_riferimento`, `norme`, `testo_atto` |
| `verifica_norme.md` | sezione delle norme, inserita in `${norme}` solo se ci sono norme | `norme` |
| `verifica_norma.md` | una singola norma della sezione | `citazione`, `testo` |
| `verifica_correzione.md` | secondo tentativo se la risposta non è JSON valido | — |
| `redazione_sistema.md` | prompt di sistema della riscrittura degli appunti | — |
| `redazione_utente.md` | messaggio con oggetto, sezione e appunti | `oggetto`, `sezione`, `appunti` |
| `coerenza_sistema.md` | prompt di sistema della coerenza tra riferimenti normativi e atto | — |
| `coerenza_utente.md` | messaggio con l'atto (citazioni marcate) e un gruppo di riferimenti | `data_riferimento`, `testo_atto`, `riferimenti`, `elenco_id` |
| `coerenza_riferimento.md` | un riferimento del gruppo: citazione e testo vigente della norma | `id`, `citazione`, `testo_citazione`, `testo_norma` |
| `riconoscimento_sistema.md` | prompt di sistema del riconoscimento delle citazioni di norme inserite manualmente | — |
| `riconoscimento_utente.md` | messaggio con le norme manuali, le citazioni già riconosciute e l'atto | `norme`, `riconosciute`, `testo_atto` |
| `riconoscimento_norma.md` | una norma manuale dell'elenco | `id`, `citazione`, `titolo`, `denominazioni` |
| `dati_personali_sistema.md` | prompt di sistema del rilevamento dei dati personali (omissis) | — |
| `dati_personali_utente.md` | messaggio con il testo (o una sua parte) in cui cercare i dati | `parte`, `testo_atto` |

I segnaposto si scrivono `${nome}`. Per un simbolo `$` letterale nel testo scrivere `$$`.
Un segnaposto sconosciuto o scritto male blocca l'avvio di API e worker con un errore che
indica il file.

Per usare prompt diversi senza modificare questi file (ad esempio da una ConfigMap in
Kubernetes) indicare una cartella in `LLM_PROMPT_DIR`: i file presenti lì sostituiscono
quelli con lo stesso nome, gli altri restano quelli di questa cartella.
