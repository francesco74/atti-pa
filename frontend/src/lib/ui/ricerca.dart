import 'dart:async';

import 'package:flutter/material.dart';

/// Registro delle ricerche concluse e dei feedback (api/src/routers/ricerche.py): [base] è
/// `/api/v1/ricerche` per gli utenti, `/api/v1/pubblico/ricerche` per i cittadini. Gli errori
/// si ignorano: registro e feedback non devono mai disturbare chi cerca.
class RegistroRicerche {
  const RegistroRicerche(this._post, this.base, this.ambito);

  final Future<Object?> Function(String percorso, Object corpo) _post;
  final String base;
  final String ambito; // es. MAPPATURA, PROCEDIMENTI

  Future<String?> ricerca(Map<String, Object?> dati) async {
    try {
      final r = await _post('$base/registro', {...dati, 'ambito': ambito}) as Map<String, dynamic>;
      return r['id'] as String?;
    } catch (_) {
      return null;
    }
  }

  Future<bool> feedback(Map<String, Object?> dati) async {
    try {
      await _post('$base/feedback', {...dati, 'ambito': ambito});
      return true;
    } catch (_) {
      return false;
    }
  }
}

/// Ricerca in linguaggio naturale sul server (es. GET /anticorruzione/ricerca?testo=...): il
/// server risponde con gli id in ordine di pertinenza, trovati per parole (radici e sinonimi) e,
/// se c'è il modello di embedding, per significato. La ricerca parte dopo una breve pausa nella
/// scrittura; finché la risposta non arriva, o se non arriva, vale il filtro locale su codice e
/// denominazione.
///
/// Con [registro] la ricerca *conclusa* si registra: quando si apre un risultato ([aperto]:
/// TROVATA) oppure, senza aprirne, quando si cambia il testo dopo aver visto i risultati per
/// almeno [attesaLettura], si chiude la pagina ([dispose]) o non si fa nulla per
/// [attesaAbbandono]. I frammenti scritti mentre si digita non si registrano.
class RicercaTesto {
  RicercaTesto(this._chiama, this._aggiorna, {this.registro});

  /// Chiamata al server con il testo cercato.
  final Future<Object?> Function(String testo) _chiama;

  /// setState del widget che mostra i risultati.
  final void Function(VoidCallback) _aggiorna;

  final RegistroRicerche? registro;

  static const attesa = Duration(milliseconds: 400);
  static const attesaLettura = Duration(seconds: 2);
  static const attesaAbbandono = Duration(seconds: 30);

  Timer? _timer, _abbandono, _lettura;
  bool _risposta = false; // risultati del server arrivati per il testo attuale
  bool _letta = false; // e visti per almeno attesaLettura
  bool _semanticaRisposta = false;
  Future<String?>? _registrata; // la ricerca attuale è conclusa (id della registrazione)
  bool feedbackInviato = false;
  String _testo = '';
  List<String>? _ordine; // id in ordine di pertinenza (null: risposta non ancora arrivata)
  Map<String, bool> _soloSignificato = const {};
  bool semantica = false; // la risposta ha usato anche il modello
  bool inCorso = false;

  String get testo => _testo;

  void cambia(String testo) {
    final t = testo.trim();
    if (t == _testo) return;
    _timer?.cancel();
    _abbandono?.cancel();
    _lettura?.cancel();
    if (_letta) _concludi(); // risultati visti e non aperti: la persona riformula
    _imposta(() {
      _testo = t;
      _ordine = null;
      _risposta = _letta = false;
      _registrata = null;
      feedbackInviato = false;
      semantica = false;
      inCorso = t.isNotEmpty;
    });
    if (t.isEmpty) return;
    _timer = Timer(attesa, () async {
      try {
        final r = await _chiama(t) as Map<String, dynamic>;
        if (t != _testo) return; // nel frattempo il testo è cambiato
        final risultati = (r['risultati'] as List).cast<Map<String, dynamic>>();
        _imposta(() {
          _ordine = [for (final x in risultati) x['id'] as String];
          _soloSignificato = {for (final x in risultati) x['id'] as String: x['semantica'] == true};
          semantica = r['semantica'] == true;
          _semanticaRisposta = semantica;
          _risposta = true;
          inCorso = false;
        });
        if (registro != null) {
          _lettura = Timer(attesaLettura, () => _letta = true);
          _abbandono = Timer(attesaAbbandono, _concludi);
        }
      } catch (_) {
        if (t == _testo) _imposta(() => inCorso = false); // resta il filtro locale
      }
    });
  }

  /// Esito della ricerca attuale senza risultati aperti.
  String get _esitoSenzaApertura {
    final ordine = _ordine ?? const [];
    if (ordine.isEmpty) return 'NESSUN_RISULTATO';
    if (ordine.every(soloSignificato)) return 'RISULTATI_DEBOLI'; // nessuna parola in comune
    return 'NON_APERTI';
  }

  /// Registra la ricerca attuale (una volta sola) e ne restituisce l'id.
  Future<String?> _concludi({String? apertoId}) {
    final r = registro;
    if (r == null || _ordine == null || _testo.isEmpty) return Future.value();
    _abbandono?.cancel();
    return _registrata ??= () {
      final posizione = apertoId == null ? -1 : _ordine!.indexOf(apertoId);
      return r.ricerca({
        'testo': _testo,
        'risultati': _ordine!.length,
        'esito': posizione >= 0 ? 'TROVATA' : _esitoSenzaApertura,
        if (posizione >= 0) 'posizione': posizione + 1,
        'semantica': _semanticaRisposta,
      });
    }();
  }

  /// La persona ha aperto un risultato: ricerca riuscita.
  void aperto(String id) {
    if (_testo.isNotEmpty) _concludi(apertoId: id);
  }

  /// Feedback sui risultati (conclude la ricerca, se serve); false se non è stato registrato.
  Future<bool> inviaFeedback({required bool utile, String? commento}) async {
    final r = registro;
    if (r == null) return false;
    final id = await _concludi();
    if (id == null) return false;
    final fatto = await r.feedback({
      'tipo': 'RICERCA',
      'ricerca_id': id,
      'utile': utile,
      if (commento != null && commento.trim().isNotEmpty) 'commento': commento.trim(),
    });
    if (fatto) _imposta(() => feedbackInviato = true);
    return fatto;
  }

  /// Ci sono risultati del server per il testo attuale (si può chiedere il feedback).
  bool get conRisposta => _testo.isNotEmpty && _ordine != null;

  /// L'elemento è stato trovato solo per significato (nessuna parola in comune).
  bool soloSignificato(String id) => _soloSignificato[id] ?? false;

  /// Rifà la ricerca con lo stesso testo, quando cambia l'insieme in cui si cerca (es. il
  /// livello dell'elenco della mappatura).
  void rilancia() {
    final t = _testo;
    if (t.isEmpty) return;
    _testo = '';
    cambia(t);
  }

  /// Gli elementi di [elenco] trovati, in ordine di pertinenza. Finché il server non risponde
  /// vale il filtro locale su [testoLocale] (predefinito: codice e denominazione).
  List<Map<String, dynamic>> filtra(List<Map<String, dynamic>> elenco, {String Function(Map<String, dynamic>)? testoLocale}) {
    final ordine = _ordine;
    if (ordine == null) {
      final cerca = _testo.toLowerCase();
      final testo = testoLocale ?? (p) => '${p['codice']} ${p['denominazione']}';
      return elenco.where((p) => testo(p).toLowerCase().contains(cerca)).toList();
    }
    final perId = {for (final p in elenco) p['id']: p};
    return [for (final id in ordine) ?perId[id]];
  }

  bool _chiusa = false;

  /// setState solo finché il widget esiste (le risposte possono arrivare dopo).
  void _imposta(VoidCallback f) {
    if (!_chiusa) _aggiorna(f);
  }

  void dispose() {
    _chiusa = true;
    _timer?.cancel();
    _abbandono?.cancel();
    _lettura?.cancel();
    if (_risposta) _concludi(); // si lascia la pagina senza aprire risultati
  }
}

/// "Hai trovato quello che cercavi? Sì · No": facoltativo, sotto i risultati di una ricerca con
/// registro. Con "No" si può scrivere cosa si cercava.
class FeedbackRicerca extends StatelessWidget {
  const FeedbackRicerca(this.ricerca, {super.key});

  final RicercaTesto ricerca;

  @override
  Widget build(BuildContext context) {
    if (ricerca.registro == null || !ricerca.conRisposta) return const SizedBox.shrink();
    return _Feedback(
      key: ValueKey(ricerca.testo),
      domanda: 'Hai trovato quello che cercavi?',
      richiestaCommento: 'Cosa cercavi? (facoltativo)',
      inviato: ricerca.feedbackInviato,
      invia: (utile, commento) => ricerca.inviaFeedback(utile: utile, commento: commento),
    );
  }
}

/// "Questa pagina ti è stata utile? Sì · No" in fondo a una scheda (es. un procedimento).
class FeedbackScheda extends StatelessWidget {
  const FeedbackScheda({super.key, required this.registro, required this.id, required this.titolo});

  final RegistroRicerche registro;
  final String id;
  final String titolo;

  @override
  Widget build(BuildContext context) => _Feedback(
        key: ValueKey(id),
        domanda: 'Questa pagina ti è stata utile?',
        richiestaCommento: 'Cosa mancava? (facoltativo)',
        invia: (utile, commento) => registro.feedback({
          'tipo': 'SCHEDA',
          'riferimento_id': id,
          'riferimento': titolo,
          'utile': utile,
          if (commento != null && commento.trim().isNotEmpty) 'commento': commento.trim(),
        }),
      );
}

class _Feedback extends StatefulWidget {
  const _Feedback({super.key, required this.domanda, required this.richiestaCommento, required this.invia, this.inviato = false});

  final String domanda;
  final String richiestaCommento;
  final Future<bool> Function(bool utile, String? commento) invia;
  final bool inviato;

  @override
  State<_Feedback> createState() => _FeedbackState();
}

class _FeedbackState extends State<_Feedback> {
  final _commento = TextEditingController();
  bool _no = false, _inviato = false, _invio = false;

  @override
  void dispose() {
    _commento.dispose();
    super.dispose();
  }

  Future<void> _invia(bool utile, [String? commento]) async {
    setState(() => _invio = true);
    final fatto = await widget.invia(utile, commento);
    if (mounted) {
      setState(() {
        _invio = false;
        _inviato = fatto || _inviato;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final stile = Theme.of(context).textTheme.bodySmall;
    if (_inviato || widget.inviato) {
      return Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Semantics(liveRegion: true, child: Text('Grazie per la segnalazione.', style: stile)),
      );
    }
    // bersagli di almeno 48 px anche se il testo è corto (Sì, No)
    final piccolo = TextButton.styleFrom(minimumSize: const Size(48, 48), padding: const EdgeInsets.symmetric(horizontal: 12));
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 4, children: [
          Text(widget.domanda, style: stile),
          TextButton(style: piccolo, onPressed: _invio || _no ? null : () => _invia(true), child: const Text('Sì')),
          TextButton(style: piccolo, onPressed: _invio || _no ? null : () => setState(() => _no = true), child: const Text('No')),
        ]),
        if (_no)
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              TextField(
                controller: _commento,
                maxLength: 500,
                maxLines: 3,
                minLines: 1,
                decoration: InputDecoration(
                  labelText: widget.richiestaCommento,
                  helperText: 'Non scrivere dati personali (nome, telefono, email...)',
                  isDense: true,
                ),
              ),
              Wrap(spacing: 8, children: [
                FilledButton.tonal(onPressed: _invio ? null : () => _invia(false, _commento.text), child: const Text('Invia')),
                TextButton(onPressed: _invio ? null : () => _invia(false), child: const Text('Invia senza commento')),
              ]),
            ]),
          ),
      ]),
    );
  }
}

/// Riga sotto la casella di ricerca: ricerca in corso o come sono ordinati i risultati.
class NotaRicerca extends StatelessWidget {
  const NotaRicerca(this.ricerca, {super.key, this.risultati});

  final RicercaTesto ricerca;
  final int? risultati; // quanti ne mostra la pagina (annunciati ai lettori di schermo)

  @override
  Widget build(BuildContext context) {
    if (ricerca.testo.isEmpty) return const SizedBox.shrink();
    final stile = Theme.of(context).textTheme.bodySmall;
    final quanti = switch (risultati) {
      null => '',
      0 => 'Nessun risultato. ',
      1 => '1 risultato. ',
      final n => '$n risultati. ',
    };
    // regione "live": il lettore di schermo legge il messaggio quando cambia (WCAG 4.1.3)
    return Semantics(
      liveRegion: true,
      child: Padding(
        padding: const EdgeInsets.only(top: 8),
        child: ricerca.inCorso
            ? Row(children: [
                const ExcludeSemantics(child: SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 2))),
                const SizedBox(width: 8),
                Text('Ricerca in corso…', style: stile),
              ])
            : Text(
                quanti +
                    (ricerca.semantica
                        ? 'In ordine di pertinenza: per parole, sinonimi e significato.'
                        : 'In ordine di pertinenza: per parole e sinonimi.'),
                style: stile,
              ),
      ),
    );
  }
}
