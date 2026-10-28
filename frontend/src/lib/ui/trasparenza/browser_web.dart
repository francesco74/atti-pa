import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

const _mime = {
  'pdf': 'application/pdf',
  'doc': 'application/msword',
  'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'odt': 'application/vnd.oasis.opendocument.text',
  'xls': 'application/vnd.ms-excel',
  'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'ods': 'application/vnd.oasis.opendocument.spreadsheet',
  'csv': 'text/csv',
};

web.Blob _blob(Uint8List bytes, String nome) => web.Blob(
      [bytes.toJS].toJS,
      web.BlobPropertyBag(type: _mime[nome.split('.').last.toLowerCase()] ?? 'application/octet-stream'),
    );

/// Apre il file in una nuova scheda del browser (anteprima prima dell'invio).
void apriAnteprima(Uint8List bytes, String nome) {
  web.window.open(web.URL.createObjectURL(_blob(bytes, nome)), '_blank');
}

/// Avvia il download del file.
void scaricaBytes(Uint8List bytes, String nome) {
  final url = web.URL.createObjectURL(_blob(bytes, nome));
  (web.HTMLAnchorElement()
        ..href = url
        ..download = nome)
      .click();
  web.URL.revokeObjectURL(url);
}

/// Chiede conferma all'uscita dalla pagina finché `nonSalvato` è vero; restituisce la
/// funzione che toglie l'avviso.
void Function() avvisoUscita(bool Function() nonSalvato) {
  final ascoltatore = ((web.Event evento) {
    if (nonSalvato()) {
      evento.preventDefault();
      (evento as web.BeforeUnloadEvent).returnValue = '';
    }
  }).toJS;
  web.window.addEventListener('beforeunload', ascoltatore);
  return () => web.window.removeEventListener('beforeunload', ascoltatore);
}
