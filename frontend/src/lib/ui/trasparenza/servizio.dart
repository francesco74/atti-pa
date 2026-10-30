import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import '../../api/api_client.dart';

/// Chiamate all'API del modulo trasparenza (/api/v1/trasparenza). Analisi ed estrazioni
/// sono lavori in coda eseguiti dal worker: si avviano e si attende il risultato.
class ServizioTrasparenza {
  ServizioTrasparenza(this.api);

  final ApiClient api;

  static const _base = '/api/v1/trasparenza';

  // Gli schemi ANAC sono uguali per tutti e cambiano solo con un nuovo rilascio: si
  // scaricano una volta e le schede li condividono.
  static Future<List<Map<String, dynamic>>>? _schemi;

  Future<List<Map<String, dynamic>>> schemi({bool ricarica = false}) {
    if (ricarica || _schemi == null) {
      _schemi = api.get('$_base/schemi').then((v) => (v as List).cast<Map<String, dynamic>>());
      // un errore non resta in memoria: il prossimo tentativo riprova
      _schemi!.catchError((Object _) {
        _schemi = null;
        return <Map<String, dynamic>>[];
      });
    }
    return _schemi!;
  }

  /// Documento HTML generato dai dati del form di uno schema (con 'pdf_type').
  Future<String> generaScheda(Map<String, dynamic> dati) async =>
      ((await api.post('$_base/schede', dati)) as Map)['html'] as String;

  // --- analisi ed estrazioni ------------------------------------------------------------

  Future<Map<String, dynamic>> _avvia(String percorso, Map<String, dynamic> dati, List<(String, Uint8List)> files) async {
    final risposta = files.isEmpty
        ? await api.post(percorso, dati)
        : await api.postMultipartFiles(percorso, campi: {'dati': jsonEncode(dati)}, campoFile: 'file', files: files);
    return risposta as Map<String, dynamic>;
  }

  /// Avvia l'analisi di una pagina (dati['url']) o dei file; restituisce il lavoro.
  Future<Map<String, dynamic>> avviaAnalisi(Map<String, dynamic> dati, List<(String, Uint8List)> files) =>
      _avvia('$_base/analisi', dati, files);

  /// Avvia l'estrazione dei dati per il form di uno schema; restituisce il lavoro.
  Future<Map<String, dynamic>> avviaEstrazione(Map<String, dynamic> dati, List<(String, Uint8List)> files) =>
      _avvia('$_base/estrazioni', dati, files);

  /// Attende la fine del lavoro e ne restituisce il risultato; un lavoro in errore
  /// diventa un'eccezione con il messaggio del worker.
  Future<Map<String, dynamic>> attendi(
    String lavoroId, {
    Duration intervallo = const Duration(seconds: 3),
    Duration massimo = const Duration(minutes: 30),
  }) async {
    final fine = DateTime.now().add(massimo);
    while (DateTime.now().isBefore(fine)) {
      final lavoro = await api.get('$_base/lavori/$lavoroId') as Map<String, dynamic>;
      switch (lavoro['stato']) {
        case 'COMPLETATA':
          return lavoro['risultato'] as Map<String, dynamic>;
        case 'ERRORE':
          throw LavoroNonRiuscito((lavoro['errore'] as String?) ?? 'Lavoro non riuscito');
      }
      await Future<void>.delayed(intervallo);
    }
    throw LavoroNonRiuscito('Il lavoro non si è concluso in tempo: riprova più tardi');
  }

  /// Analisi dell'utente degli ultimi 30 giorni, dalla più recente, senza il report.
  Future<List<Map<String, dynamic>>> lavori() async =>
      ((await api.get('$_base/lavori')) as List).cast<Map<String, dynamic>>();

  /// Lavoro con il risultato, se completato.
  Future<Map<String, dynamic>> lavoro(String id) async =>
      await api.get('$_base/lavori/$id') as Map<String, dynamic>;

  /// Rimette in coda un lavoro non riuscito, con la stessa richiesta.
  Future<Map<String, dynamic>> riprovaLavoro(String id) async =>
      await api.post('$_base/lavori/$id/riprova', {}) as Map<String, dynamic>;

  /// Toglie il lavoro dall'elenco (se è ancora in coda lo annulla).
  Future<void> eliminaLavoro(String id) => api.delete('$_base/lavori/$id');

  // --- documenti salvati ---------------------------------------------------------------

  Future<List<Map<String, dynamic>>> documenti() async =>
      ((await api.get('$_base/documenti')) as List).cast<Map<String, dynamic>>();

  Future<Map<String, dynamic>> documento(String id) async =>
      await api.get('$_base/documenti/$id') as Map<String, dynamic>;

  /// Nuovo documento (id nullo) o aggiornamento; `datiSchema` nullo nell'aggiornamento
  /// lascia quelli già salvati.
  Future<Map<String, dynamic>> salva({
    String? id,
    required String descrizione,
    required String html,
    Map<String, dynamic>? datiSchema,
  }) async {
    final corpo = {'descrizione': descrizione, 'html': html, 'dati_schema': ?datiSchema};
    final risposta = id == null ? await api.post('$_base/documenti', corpo) : await api.put('$_base/documenti/$id', corpo);
    return risposta as Map<String, dynamic>;
  }

  Future<void> elimina(String id) => api.delete('$_base/documenti/$id');

  /// Verbale di validazione seguito dai documenti scelti.
  Future<String> verbale(List<String> documenti) async =>
      ((await api.post('$_base/verbale', {'documenti': documenti})) as Map)['html'] as String;

  /// Documento in PDF o DOCX (formato: "pdf" o "docx").
  Future<Uint8List> esporta(String html, String nome, String formato) =>
      api.postBytes('$_base/esporta', {'html': html, 'nome': nome, 'formato': formato});
}

class LavoroNonRiuscito implements Exception {
  LavoroNonRiuscito(this.messaggio);

  final String messaggio;

  @override
  String toString() => messaggio;
}

/// Formati dei documenti che si possono analizzare o da cui estrarre i dati.
const estensioniAmmesse = ['pdf', 'doc', 'docx', 'odt', 'xls', 'xlsx', 'ods', 'csv'];
