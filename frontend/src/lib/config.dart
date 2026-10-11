import 'package:flutter/foundation.dart';

/// Indirizzo dell'API.
///
/// Sul web l'app è servita dallo stesso dominio dell'API (Ingress con /api), quindi
/// si usa l'origine della pagina. Per il client desktop l'indirizzo si imposta in
/// compilazione: `flutter build windows --dart-define=API_URL=https://atti.ente.local`.
class Config {
  static const String _apiUrl = String.fromEnvironment('API_URL');

  static String get apiUrl {
    if (_apiUrl.isNotEmpty) return _apiUrl;
    if (kIsWeb) return Uri.base.origin;
    return 'http://localhost:8000';
  }
}
