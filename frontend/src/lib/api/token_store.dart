import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Conservazione del token JWT.
///
/// Sul web il token NON viene salvato: l'autenticazione usa il cookie httpOnly impostato
/// dall'API, inaccessibile a JavaScript. Sul desktop il token è salvato nel portachiavi
/// del sistema operativo tramite flutter_secure_storage.
class TokenStore {
  static const _chiave = 'atti_pa_token';
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  Future<String?> leggi() async {
    if (kIsWeb) return null;
    return _storage.read(key: _chiave);
  }

  Future<void> salva(String token) async {
    if (kIsWeb) return;
    await _storage.write(key: _chiave, value: token);
  }

  Future<void> cancella() async {
    if (kIsWeb) return;
    await _storage.delete(key: _chiave);
  }
}
