/// Codici proposti nelle finestre di creazione: il successivo di una serie, che l'utente può
/// cambiare. Il server controlla comunque che il codice non sia già usato.
library;

/// [prefisso] seguito dal numero successivo al più alto tra i [codici] della forma
/// `prefisso<n>` (maiuscole e minuscole non contano), partendo da [primo]. Es. STR.1, STR.2...
String prossimoCodice(String prefisso, Iterable<Object?> codici, {int primo = 1}) {
  final forma = RegExp('^${RegExp.escape(prefisso)}(\\d+)\$', caseSensitive: false);
  var massimo = primo - 1;
  for (final c in codici) {
    final m = forma.firstMatch('${c ?? ''}'.trim());
    final n = m == null ? null : int.tryParse(m.group(1)!);
    if (n != null && n > massimo) massimo = n;
  }
  return '$prefisso${massimo + 1}';
}
