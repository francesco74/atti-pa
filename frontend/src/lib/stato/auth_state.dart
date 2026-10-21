import 'package:flutter/foundation.dart';

import '../api/api_client.dart';

class Utente {
  Utente.daJson(Map<String, dynamic> j)
      : id = j['id'] as String,
        username = j['username'] as String,
        nomeCompleto = (j['nome_completo'] as String?) ?? j['username'] as String,
        ufficio = j['ufficio'] as String?,
        decretoIncarico = j['decreto_incarico'] as String?,
        ruoli = List<String>.from(j['ruoli'] as List);

  final String id;
  final String username;
  final String nomeCompleto;
  final String? ufficio;
  final String? decretoIncarico;
  final List<String> ruoli;

  bool get isAdmin => ruoli.contains('ADMIN');
  bool get isRedattore => isAdmin || ruoli.contains('REDATTORE');
  bool get isControllore => isAdmin || ruoli.contains('CONTROLLORE');
  bool get isGestoreModelli => isAdmin || ruoli.contains('GESTORE_MODELLI');
}

enum StatoAuth { verifica, anonimo, autenticato }

class AuthState extends ChangeNotifier {
  AuthState(this.api) {
    api.suNonAutenticato = _sessioneScaduta;
  }

  final ApiClient api;
  StatoAuth stato = StatoAuth.verifica;
  Utente? utente;

  /// All'avvio verifica se esiste già una sessione valida (cookie di sessione).
  Future<void> avvia() async {
    try {
      utente = Utente.daJson(await api.utenteCorrente());
      stato = StatoAuth.autenticato;
    } catch (_) {
      stato = StatoAuth.anonimo;
    }
    notifyListeners();
  }

  Future<void> login(String username, String password) async {
    utente = Utente.daJson(await api.login(username, password));
    stato = StatoAuth.autenticato;
    notifyListeners();
  }

  /// Profilo modificato dall'utente (settore usato per precompilare gli atti).
  Future<void> aggiornaProfilo({String? ufficio, String? decretoIncarico}) async {
    final r = await api.put('/api/v1/auth/profilo', {
      'ufficio': ufficio,
      'decreto_incarico': decretoIncarico,
    }) as Map<String, dynamic>;
    utente = Utente.daJson(r);
    notifyListeners();
  }

  Future<void> logout() async {
    await api.logout();
    utente = null;
    stato = StatoAuth.anonimo;
    notifyListeners();
  }

  void _sessioneScaduta() {
    if (stato == StatoAuth.autenticato) {
      utente = null;
      stato = StatoAuth.anonimo;
      notifyListeners();
    }
  }
}
