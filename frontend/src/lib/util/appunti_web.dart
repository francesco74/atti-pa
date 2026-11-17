import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:flutter/services.dart';
import 'package:web/web.dart' as web;

/// Nel browser HTML e testo semplice insieme; se il browser non lo consente (es. pagina non
/// sicura o API mancante), solo il testo semplice.
Future<void> copiaFormattato({required String html, required String testo}) async {
  try {
    final voci = JSObject()
      ..setProperty('text/html'.toJS, web.Blob([html.toJS].toJS, web.BlobPropertyBag(type: 'text/html')))
      ..setProperty('text/plain'.toJS, web.Blob([testo.toJS].toJS, web.BlobPropertyBag(type: 'text/plain')));
    await web.window.navigator.clipboard.write([web.ClipboardItem(voci)].toJS).toDart;
  } catch (_) {
    await Clipboard.setData(ClipboardData(text: testo));
  }
}
