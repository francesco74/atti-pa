import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../log.dart';
import 'http_client.dart';

class ApiException implements Exception {
  ApiException(this.status, this.messaggio);

  final int status;
  final String messaggio;

  @override
  String toString() => messaggio;
}

/// Client REST dell'API atti-pa.
///
/// L'autenticazione usa il cookie di sessione httpOnly impostato dall'API: il token non
/// è mai accessibile all'app. `withCredentials` serve in sviluppo, quando l'app e l'API
/// sono su origini diverse; in produzione sono sullo stesso dominio.
class ApiClient {
  ApiClient(this.baseUrl, {http.Client? client})
      : _http = client ?? creaClient();

  final String baseUrl;
  final http.Client _http;

  /// Chiamata quando l'API risponde 401 (sessione scaduta).
  VoidCallback? suNonAutenticato;

  Uri uri(String percorso, [Map<String, String>? query]) {
    final q = query == null
        ? null
        : Map<String, String>.fromEntries(query.entries.where((e) => e.value.isNotEmpty));
    return Uri.parse('$baseUrl$percorso').replace(queryParameters: (q == null || q.isEmpty) ? null : q);
  }

  Map<String, String> _intestazioni({bool json = true}) => {
        if (json) 'Content-Type': 'application/json',
        'Accept': 'application/json',
      };

  void _registra(http.Response r) {
    final richiesta = '${r.request?.method} ${r.request?.url.path} -> ${r.statusCode}';
    if (r.statusCode >= 500) {
      Log.warning('$richiesta: ${_messaggioErrore(r)}');
    } else if (r.statusCode >= 400 && r.statusCode != 401) {
      Log.info('$richiesta: ${_messaggioErrore(r)}');
    } else {
      Log.debug('$richiesta (${r.bodyBytes.length} byte)');
    }
  }

  dynamic _decodifica(http.Response r) {
    _registra(r);
    if (r.statusCode == 401) {
      suNonAutenticato?.call();
    }
    if (r.statusCode >= 400) {
      throw ApiException(r.statusCode, _messaggioErrore(r));
    }
    if (r.statusCode == 204 || r.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(r.bodyBytes));
  }

  String _messaggioErrore(http.Response r) {
    try {
      final corpo = jsonDecode(utf8.decode(r.bodyBytes));
      final dettaglio = corpo is Map ? corpo['detail'] : null;
      if (dettaglio is String) return dettaglio;
      if (dettaglio is Map && dettaglio['messaggio'] != null) {
        return dettaglio['messaggio'].toString();
      }
      if (dettaglio is List && dettaglio.isNotEmpty) {
        return dettaglio
            .map((e) => e is Map ? (e['msg'] ?? e.toString()) : e.toString())
            .join('\n');
      }
    } catch (_) {
      // risposta non JSON
    }
    return 'Errore ${r.statusCode}';
  }

  Future<dynamic> get(String percorso, {Map<String, String>? query}) async {
    final r = await _http.get(uri(percorso, query), headers: _intestazioni(json: false));
    return _decodifica(r);
  }

  Future<dynamic> post(String percorso, [Object? corpo]) async {
    final r = await _http.post(uri(percorso),
        headers: _intestazioni(), body: corpo == null ? null : jsonEncode(corpo));
    return _decodifica(r);
  }

  Future<dynamic> put(String percorso, Object corpo) async {
    final r = await _http.put(uri(percorso), headers: _intestazioni(), body: jsonEncode(corpo));
    return _decodifica(r);
  }

  Future<void> delete(String percorso) async {
    final r = await _http.delete(uri(percorso), headers: _intestazioni(json: false));
    _decodifica(r);
  }

  Future<dynamic> postMultipart(
    String percorso, {
    required Map<String, String> campi,
    required String campoFile,
    required Uint8List bytes,
    required String nomeFile,
  }) async {
    final richiesta = http.MultipartRequest('POST', uri(percorso))
      ..headers.addAll(_intestazioni(json: false))
      ..fields.addAll(campi)
      ..files.add(http.MultipartFile.fromBytes(campoFile, bytes, filename: nomeFile));
    final risposta = await http.Response.fromStream(await _http.send(richiesta));
    return _decodifica(risposta);
  }

  Future<Uint8List> getBytes(String percorso, {Map<String, String>? query}) async {
    final r = await _http.get(uri(percorso, query), headers: _intestazioni(json: false));
    _registra(r);
    if (r.statusCode >= 400) {
      if (r.statusCode == 401) suNonAutenticato?.call();
      throw ApiException(r.statusCode, _messaggioErrore(r));
    }
    return r.bodyBytes;
  }

  // --- Autenticazione ---------------------------------------------------------------

  Future<Map<String, dynamic>> login(String username, String password) async {
    final risposta = await post('/api/v1/auth/login', {
      'username': username,
      'password': password,
    }) as Map<String, dynamic>;
    return risposta['utente'] as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> utenteCorrente() async =>
      await get('/api/v1/auth/me') as Map<String, dynamic>;

  Future<void> logout() async {
    try {
      await post('/api/v1/auth/logout');
    } catch (_) {
      // il logout locale avviene comunque
    }
  }
}
