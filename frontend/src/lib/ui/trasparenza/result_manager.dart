import 'package:flutter/foundation.dart';

/// Nuovo risultato da mostrare nella scheda dei risultati.
class NuovoRisultato {
  final String html;
  // Dati del form da cui è stata generata la scheda (con 'pdf_type'):
  // permettono di ricaricarla nel form per modificarla. Null per i risultati
  // delle analisi IA.
  final Map<String, dynamic>? datiSchema;
  // Nome proposto al salvataggio (es. nuova versione di un documento).
  final String? nomeProposto;

  const NuovoRisultato(this.html, {this.datiSchema, this.nomeProposto});
}

/// Dati di una scheda salvata da ricaricare nel form di generazione.
class DatiDaModificare {
  final Map<String, dynamic> dati;
  // Nome del documento da cui provengono i dati.
  final String origine;
  // Dati estratti con l'IA dal testo del documento (non salvati con la
  // scheda): vanno verificati prima di generare.
  final bool estratti;
  // Valori che l'estrazione non ha potuto caricare.
  final List<String> avvisi;

  const DatiDaModificare(
    this.dati,
    this.origine, {
    this.estratti = false,
    this.avvisi = const [],
  });
}

/// Collegamento tra le schede di analisi, generazione e risultati.
class ResultManager {
  /// Impostata dalla schermata principale: apre la scheda dei risultati.
  static void Function(NuovoRisultato risultato)? navigateToResults;

  /// Impostata dalla schermata principale: porta a una scheda
  /// (0 = analisi IA, 1 = generazione, 2 = risultati).
  static void Function(int scheda)? apriScheda;

  /// Impostata dalla scheda dei risultati: dice se l'editor contiene
  /// modifiche non salvate (usata per chiedere conferma prima del logout).
  static bool Function()? modificheNonSalvate;

  /// Vero quando nella scheda dei risultati c'è un documento da salvare:
  /// la navigazione lo segnala con un punto sulla voce Risultati.
  static final ValueNotifier<bool> daSalvare = ValueNotifier(false);

  /// Impostata dalla scheda dei risultati: salva subito le modifiche in
  /// attesa del documento aperto (se già salvato). True se non resta nulla.
  static Future<bool> Function()? salvaModifiche;

  // Dati in attesa di essere caricati nel form di generazione e funzione con
  // cui la scheda di generazione li riceve (registrata quando la scheda
  // esiste: se non è ancora stata aperta li prende alla creazione).
  static DatiDaModificare? _datiInAttesa;
  static VoidCallback? _riceviDati;

  /// Call this method from the API success handlers in other tabs.
  static void showResultInNewTab(
    String html, {
    Map<String, dynamic>? datiSchema,
    String? nomeProposto,
  }) {
    if (navigateToResults != null) {
      navigateToResults!(
        NuovoRisultato(html, datiSchema: datiSchema, nomeProposto: nomeProposto),
      );
    } else {
      debugPrint('Error: Navigation context not set in ResultManager.');
    }
  }

  /// Riapre i dati di una scheda nel form di generazione.
  static void modificaDati(
    Map<String, dynamic> dati,
    String origine, {
    bool estratti = false,
    List<String> avvisi = const [],
  }) {
    _datiInAttesa = DatiDaModificare(
      dati,
      origine,
      estratti: estratti,
      avvisi: avvisi,
    );
    apriScheda?.call(1);
    _riceviDati?.call();
  }

  static void registraGeneratore(VoidCallback? riceviDati) =>
      _riceviDati = riceviDati;

  static DatiDaModificare? prendiDatiInAttesa() {
    final dati = _datiInAttesa;
    _datiInAttesa = null;
    return dati;
  }
}
