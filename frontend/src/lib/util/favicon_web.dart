import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

const _predefinita = 'favicon.svg';
String? _url;

/// Sostituisce la favicon con [immagine] (PNG o JPEG); con null torna al martelletto.
void impostaFavicon(Uint8List? immagine) {
  final link = web.document.querySelector('link[rel="icon"]') as web.HTMLLinkElement?;
  if (link == null) return;
  if (_url != null) web.URL.revokeObjectURL(_url!);
  _url = immagine == null ? null : web.URL.createObjectURL(web.Blob([immagine.toJS].toJS));
  // il tipo dichiarato è quello della favicon predefinita (SVG): con il logo lo si toglie
  link.type = immagine == null ? 'image/svg+xml' : '';
  link.href = _url ?? _predefinita;
}
