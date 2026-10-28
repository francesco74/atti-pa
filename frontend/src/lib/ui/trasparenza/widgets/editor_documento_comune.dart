/// Accesso al contenuto dell'editor dei documenti dall'esterno del widget.
class ControlloEditor {
  /// Impostato dal widget dell'editor quando è montato.
  Future<String> Function()? lettore;

  /// Contenuto attuale dell'editor; errore se l'editor non è pronto.
  Future<String> testo() {
    final leggi = lettore;
    if (leggi == null) return Future.error(StateError('Editor non pronto'));
    return leggi();
  }
}
