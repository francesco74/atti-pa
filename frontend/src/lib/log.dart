import 'package:flutter/foundation.dart';

enum LivelloLog { debug, info, warning, error }

/// Log nella console del browser, filtrati con LOG_LEVEL (debug, info, warning, error).
class Log {
  Log._();

  static LivelloLog livello = LivelloLog.info;

  static void imposta(String valore) {
    livello = LivelloLog.values.firstWhere(
      (l) => l.name == valore.trim().toLowerCase(),
      orElse: () => LivelloLog.info,
    );
  }

  static bool abilitato(LivelloLog l) => l.index >= livello.index;

  static void debug(String messaggio) => _scrivi(LivelloLog.debug, messaggio);
  static void info(String messaggio) => _scrivi(LivelloLog.info, messaggio);
  static void warning(String messaggio) => _scrivi(LivelloLog.warning, messaggio);
  static void error(String messaggio) => _scrivi(LivelloLog.error, messaggio);

  static void _scrivi(LivelloLog l, String messaggio) {
    if (!abilitato(l)) return;
    debugPrint('${DateTime.now().toIso8601String()} ${l.name.toUpperCase()} $messaggio');
  }
}
