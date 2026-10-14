import 'dart:convert';

import 'package:http/http.dart' as http;

import 'log.dart';

/// Configurazione dell'app, letta all'avvio da `config.json`.
///
/// Il file è generato dal container nginx con le sue variabili d'ambiente (`API_URL`,
/// `LOG_LEVEL`), quindi la stessa immagine si configura per ogni ambiente senza
/// ricompilare. In sviluppo (`flutter run`) si usa `web/config.json`, oppure
/// `--dart-define=API_URL=...` / `--dart-define=LOG_LEVEL=...`.
class Config {
  Config._();

  static const _apiUrlCompilazione = String.fromEnvironment('API_URL');
  static const _logLevelCompilazione = String.fromEnvironment('LOG_LEVEL', defaultValue: 'INFO');

  /// Indirizzo dell'API; vuoto = stessa origine della pagina (Ingress con /api).
  static String apiUrl = '';
  static String logLevel = 'INFO';

  static Future<void> carica() async {
    var valori = <String, dynamic>{};
    try {
      final r = await http.get(Uri.base.resolve('config.json'));
      if (r.statusCode == 200) {
        valori = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
      }
    } catch (_) {
      // file assente o non valido: valori di compilazione
    }
    String valore(String chiave, String predefinito) {
      final v = (valori[chiave] as String?)?.trim() ?? '';
      return v.isNotEmpty ? v : predefinito;
    }

    apiUrl = valore('API_URL', _apiUrlCompilazione);
    if (apiUrl.isEmpty) apiUrl = Uri.base.origin;
    logLevel = valore('LOG_LEVEL', _logLevelCompilazione);
    Log.imposta(logLevel);
    Log.info('Configurazione: API $apiUrl, log ${Log.livello.name.toUpperCase()}');
  }
}
