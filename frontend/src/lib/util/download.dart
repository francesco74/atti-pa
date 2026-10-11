// Salvataggio dei file scaricati dall'API: implementazione diversa per web e desktop.
export 'download_io.dart' if (dart.library.js_interop) 'download_web.dart';
