import 'dart:async';

import 'package:flutter/foundation.dart';

import 'servizio.dart';

/// Analisi avviate dall'utente (lavori in coda eseguiti dal worker): l'elenco si rilegge
/// dal server finché ce ne sono in coda o in corso, così si possono avviarne altre senza
/// aspettare. Vive finché è aperta la pagina della trasparenza: le analisi continuano sul
/// server e al rientro si ritrovano.
class CodaAnalisi extends ChangeNotifier {
  CodaAnalisi(this.servizio, {this.intervallo = const Duration(seconds: 5)});

  final ServizioTrasparenza servizio;
  final Duration intervallo;

  List<Map<String, dynamic>> lavori = const [];
  bool caricata = false;
  Object? errore;

  /// Chiamata quando un'analisi seguita dall'app si conclude (completata o in errore).
  void Function(Map<String, dynamic> lavoro)? suConclusa;

  Timer? _timer;
  bool _chiusa = false;

  static bool attivo(Map<String, dynamic> lavoro) =>
      lavoro['stato'] == 'IN_CODA' || lavoro['stato'] == 'IN_CORSO';

  /// Analisi in coda o in corso.
  int get inCorso => lavori.where(attivo).length;

  Future<void> aggiorna() async {
    _timer?.cancel();
    try {
      final nuovi = await servizio.lavori();
      if (_chiusa) return;
      final seguiti = {for (final l in lavori.where(attivo)) l['id']};
      for (final l in nuovi) {
        if (seguiti.contains(l['id']) && !attivo(l)) suConclusa?.call(l);
      }
      lavori = nuovi;
      errore = null;
    } catch (e) {
      if (_chiusa) return;
      errore = e;
    }
    caricata = true;
    notifyListeners();
    _programma();
  }

  void _programma() {
    _timer?.cancel();
    if (!_chiusa && (inCorso > 0 || errore != null)) _timer = Timer(intervallo, aggiorna);
  }

  /// Analisi appena avviata: compare subito, poi la aggiorna il server.
  void aggiungi(Map<String, dynamic> lavoro) {
    lavori = [lavoro, ...lavori.where((l) => l['id'] != lavoro['id'])];
    notifyListeners();
    _programma();
  }

  /// Toglie l'analisi dall'elenco (se è in coda la annulla).
  Future<void> togli(String id) async {
    await servizio.eliminaLavoro(id);
    lavori = lavori.where((l) => l['id'] != id).toList();
    notifyListeners();
  }

  /// Analisi non riuscita rimessa in coda: torna seguita fino alla fine.
  Future<void> riprova(String id) async {
    final lavoro = await servizio.riprovaLavoro(id);
    lavori = [for (final l in lavori) l['id'] == id ? {...l, ...lavoro} : l];
    notifyListeners();
    _programma();
  }

  /// Report HTML di un'analisi completata.
  Future<String> report(String id) async {
    final lavoro = await servizio.lavoro(id);
    return (lavoro['risultato'] as Map<String, dynamic>)['html'] as String;
  }

  @override
  void dispose() {
    _chiusa = true;
    _timer?.cancel();
    super.dispose();
  }
}
