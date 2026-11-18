Dal testo seguente (una parte del PIAO o del Piano della performance di un ente) estrai gli OBIETTIVI DI PERFORMANCE annuali assegnati alle strutture, con:
- codice: il codice dell'obiettivo nel documento (es. P1_OS1_OO1_OG1_26_1), null se non c'è;
- titolo: il titolo dell'obiettivo;
- descrizione: la descrizione delle attività e delle finalità (testo del documento, anche lungo), null se non c'è;
- struttura: il settore, servizio o ufficio responsabile, come scritto (es. "Settore Dipartimentale 5 Lavori Pubblici e Traffico");
- responsabile: il dirigente o responsabile, se indicato;
- azioni: le fasi o azioni dell'obiettivo, ognuna con descrizione e data di fine prevista (GG/MM/AAAA, null se manca);
- indicatori: gli indicatori dell'obiettivo, ognuno con descrizione, tipo come scritto nel documento (es. EFFICIENZA) e valore atteso come scritto (es. "31/12/2026", "100%", "3").

Lo stesso obiettivo può comparire su più pagine (la scheda continua con lo stesso codice): riportalo una volta sola con tutte le sue azioni e indicatori.
Ignora gli obiettivi strategici e operativi pluriennali (DUP/NADUP), le tabelle del valore pubblico e le risorse finanziarie.
Se il testo non contiene obiettivi di performance, restituisci un elenco vuoto.

TESTO:
${testo}
