import 'dart:typed_data';

void apriAnteprima(Uint8List bytes, String nome) {}

void scaricaBytes(Uint8List bytes, String nome) {}

/// Chiede conferma all'uscita dalla pagina finché `nonSalvato` è vero; restituisce la
/// funzione che toglie l'avviso.
void Function() avvisoUscita(bool Function() nonSalvato) => () {};
