import 'dart:async';
import 'dart:js_interop';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

import 'editor_documento_comune.dart';

/// Editor HTML del documento: la pagina statica editor/index.html (Summernote) in un
/// iframe della stessa origine, con una policy di sicurezza propria. Si parla con
/// postMessage (protocollo descritto in web/editor/editor.js).
///
/// Il contenuto iniziale si legge solo all'avvio: per aprire un altro documento si
/// ricrea il widget con una nuova chiave.
class EditorDocumento extends StatefulWidget {
  const EditorDocumento({
    super.key,
    required this.controllo,
    required this.contenuto,
    this.barraVisibile = true,
    required this.onCaricato,
    required this.onModifica,
  });

  final ControlloEditor controllo;
  final String contenuto;
  final bool barraVisibile;
  // Contenuto appena caricato, già normalizzato dall'editor: riferimento per
  // riconoscere le modifiche.
  final ValueChanged<String> onCaricato;
  final ValueChanged<String> onModifica;

  @override
  State<EditorDocumento> createState() => _EditorDocumentoState();
}

class _EditorDocumentoState extends State<EditorDocumento> {
  static int _contatore = 0;
  late final String _tipoVista = 'trasparenza-editor-${_contatore++}';
  late final JSFunction _ascolto = _messaggio.toJS;

  web.HTMLIFrameElement? _iframe;
  bool _caricato = false;
  int _prossimaRichiesta = 0;
  final _richieste = <int, Completer<String>>{};

  @override
  void initState() {
    super.initState();
    ui_web.platformViewRegistry.registerViewFactory(_tipoVista, (int _) {
      return _iframe = web.HTMLIFrameElement()
        ..src = 'editor/index.html'
        ..title = 'Editor del documento'
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%';
    });
    web.window.addEventListener('message', _ascolto);
    widget.controllo.lettore = _leggi;
  }

  @override
  void didUpdateWidget(EditorDocumento vecchio) {
    super.didUpdateWidget(vecchio);
    if (vecchio.controllo != widget.controllo) {
      if (vecchio.controllo.lettore == _leggi) vecchio.controllo.lettore = null;
      widget.controllo.lettore = _leggi;
    }
    if (vecchio.barraVisibile != widget.barraVisibile) {
      _invia({'tipo': 'barra', 'visibile': widget.barraVisibile});
    }
  }

  @override
  void dispose() {
    web.window.removeEventListener('message', _ascolto);
    if (widget.controllo.lettore == _leggi) widget.controllo.lettore = null;
    for (final richiesta in _richieste.values) {
      richiesta.completeError(StateError('Editor chiuso'));
    }
    _richieste.clear();
    super.dispose();
  }

  void _invia(Map<String, Object?> messaggio) =>
      _iframe?.contentWindow?.postMessage(messaggio.jsify(), web.window.location.origin.toJS);

  void _messaggio(web.MessageEvent evento) {
    // Solo i messaggi della pagina dell'editor di questo widget
    final finestra = _iframe?.contentWindow;
    if (finestra == null || evento.origin != web.window.location.origin) return;
    if (!evento.source.strictEquals(finestra).toDart) return;
    final dati = evento.data.dartify();
    if (dati is! Map) return;
    switch (dati['tipo']) {
      case 'pronto':
        _invia({'tipo': 'imposta', 'html': widget.contenuto, 'barra': widget.barraVisibile});
      case 'caricato':
        _caricato = true;
        widget.onCaricato(dati['html'] as String);
      case 'modifica':
        if (_caricato) widget.onModifica(dati['html'] as String);
      case 'testo':
        final richiesta = _richieste.remove((dati['id'] as num).toInt());
        final html = dati['html'];
        if (html is String) {
          richiesta?.complete(html);
        } else {
          richiesta?.completeError(StateError('Editor non pronto'));
        }
    }
  }

  Future<String> _leggi() {
    if (!_caricato) return Future.error(StateError('Editor non pronto'));
    final id = _prossimaRichiesta++;
    final richiesta = _richieste[id] = Completer<String>();
    _invia({'tipo': 'leggi', 'id': id});
    return richiesta.future.timeout(const Duration(seconds: 5), onTimeout: () {
      _richieste.remove(id);
      throw TimeoutException('L\'editor non risponde');
    });
  }

  @override
  Widget build(BuildContext context) => HtmlElementView(viewType: _tipoVista);
}
