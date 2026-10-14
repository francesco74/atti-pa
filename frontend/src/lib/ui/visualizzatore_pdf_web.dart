import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

/// PDF mostrato dal visualizzatore integrato del browser (zoom, ricerca, stampa).
/// La richiesta porta il cookie di sessione come le altre chiamate all'API.
class VisualizzatorePdf extends StatefulWidget {
  const VisualizzatorePdf({super.key, required this.url});

  final Uri url;

  @override
  State<VisualizzatorePdf> createState() => _VisualizzatorePdfState();
}

class _VisualizzatorePdfState extends State<VisualizzatorePdf> {
  static int _contatore = 0;
  late final String _tipoVista = 'atti-pa-pdf-${_contatore++}';

  @override
  void initState() {
    super.initState();
    ui_web.platformViewRegistry.registerViewFactory(_tipoVista, (int _) {
      return web.HTMLIFrameElement()
        ..src = widget.url.toString()
        ..title = 'Atto originale'
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%';
    });
  }

  @override
  Widget build(BuildContext context) => HtmlElementView(viewType: _tipoVista);
}
