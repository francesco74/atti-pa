import 'package:flutter/material.dart';

/// Variabile utilizzabile nelle condizioni: una domanda iniziale, un valore calcolato o una
/// caratteristica (specificità) scelta tra le caratteristiche dell'atto.
class Variabile {
  const Variabile(this.nome, this.etichetta, this.tipo, [this.opzioni = const {}]);

  final String nome;
  final String etichetta;
  final String tipo; // si_no, scelta, numero, testo
  final Map<String, String> opzioni;
}

/// Variabili di una definizione di modello (domande, opzioni delle scelte multiple, valori
/// calcolati), più quelle aggiuntive (es. le domande dei modelli a cui si applica una
/// specificità).
List<Variabile> variabiliDi(Map<String, dynamic> definizione, {List<Variabile> altre = const []}) {
  final risultato = <Variabile>[];
  for (final q in List<Map<String, dynamic>>.from(definizione['domande'] as List? ?? const [])) {
    final opzioni = Map<String, String>.from(
        (q['opzioni'] as Map? ?? const {}).map((k, v) => MapEntry(k.toString(), v.toString())));
    switch (q['tipo']) {
      case 'si_no':
        risultato.add(Variabile(q['id'] as String, q['testo'] as String, 'si_no'));
      case 'scelta':
        risultato.add(Variabile(q['id'] as String, q['testo'] as String, 'scelta', opzioni));
      case 'scelta_multipla':
        for (final o in opzioni.entries) {
          risultato.add(Variabile(o.key, 'Caratteristica: ${o.value}', 'si_no'));
        }
      case 'importo' || 'numero':
        risultato.add(Variabile(q['id'] as String, q['testo'] as String, 'numero'));
      default:
        risultato.add(Variabile(q['id'] as String, q['testo'] as String, 'testo'));
    }
  }
  final derivati = Map<String, dynamic>.from(definizione['derivati'] as Map? ?? const {});
  for (final d in derivati.entries) {
    if (d.value is String) {
      risultato.add(Variabile(d.key, 'Calcolato: ${d.key}', 'si_no'));
    } else {
      final valori = <String, String>{
        for (final c in List<Map<String, dynamic>>.from(d.value as List))
          if (c['valore'] != null) c['valore'].toString(): c['valore'].toString(),
      };
      risultato.add(Variabile(d.key, 'Calcolato: ${d.key}', 'scelta', valori));
    }
  }
  final nomi = risultato.map((v) => v.nome).toSet();
  return [...risultato, ...altre.where((v) => !nomi.contains(v.nome))];
}

/// Una riga della condizione: variabile, operatore, valore.
class Clausola {
  Clausola(this.nome, this.operatore, [this.valore]);

  String nome;
  String operatore; // vero, falso, ==, !=, <, <=, >, >=, in
  Object? valore; // String, num o List<String>
}

class CondizioneSemplice {
  CondizioneSemplice(this.clausole, this.connettivo);

  final List<Clausola> clausole;
  String connettivo; // and, or
}

final _nomeRe = RegExp(r'^[A-Za-z_]\w*$');
final _confrontoRe = RegExp(r'^([A-Za-z_]\w*)\s*(==|!=|<=|>=|<|>)\s*(.+)$');
final _inRe = RegExp(r'^([A-Za-z_]\w*)\s+in\s+\[(.*)\]$');
final _notRe = RegExp(r'^not\s+([A-Za-z_]\w*)$');

Object? _valore(String testo) {
  final t = testo.trim();
  if (t.startsWith('"') && t.endsWith('"') && t.length >= 2) return t.substring(1, t.length - 1);
  if (t == 'true') return true;
  if (t == 'false') return false;
  return num.tryParse(t);
}

/// Prova a leggere la condizione come elenco di clausole unite da "and" o da "or". Null se è
/// più complessa (parentesi, connettivi misti, "implica"): si modifica come testo.
CondizioneSemplice? analizzaCondizione(String? testo) {
  final t = (testo ?? '').trim();
  if (t.isEmpty) return CondizioneSemplice([], 'and');
  if (t.contains('(') || t.contains(' implica ')) return null;
  final haAnd = t.contains(' and ');
  final haOr = t.contains(' or ');
  if (haAnd && haOr) return null;
  final connettivo = haOr ? 'or' : 'and';
  final clausole = <Clausola>[];
  for (final parte in t.split(' $connettivo ')) {
    final p = parte.trim();
    Match? m;
    if ((m = _notRe.firstMatch(p)) != null) {
      clausole.add(Clausola(m!.group(1)!, 'falso'));
    } else if (_nomeRe.hasMatch(p)) {
      clausole.add(Clausola(p, 'vero'));
    } else if ((m = _inRe.firstMatch(p)) != null) {
      final valori = m!.group(2)!.split(',').map((v) => _valore(v)).toList();
      if (valori.any((v) => v is! String)) return null;
      clausole.add(Clausola(m.group(1)!, 'in', valori.cast<String>()));
    } else if ((m = _confrontoRe.firstMatch(p)) != null) {
      final v = _valore(m!.group(3)!);
      if (v == null) return null;
      if (v is bool) {
        final vero = (m.group(2) == '==') == v;
        clausole.add(Clausola(m.group(1)!, vero ? 'vero' : 'falso'));
      } else {
        clausole.add(Clausola(m.group(1)!, m.group(2)!, v));
      }
    } else {
      return null;
    }
  }
  return CondizioneSemplice(clausole, connettivo);
}

String _letterale(Object? v) => v is num ? v.toString() : '"${v ?? ''}"';

String scriviCondizione(CondizioneSemplice c) => c.clausole
    .map((k) => switch (k.operatore) {
          'vero' => k.nome,
          'falso' => 'not ${k.nome}',
          'in' => '${k.nome} in [${(k.valore as List? ?? const []).map(_letterale).join(', ')}]',
          _ => '${k.nome} ${k.operatore} ${_letterale(k.valore)}',
        })
    .join(' ${c.connettivo} ');

/// Descrizione leggibile di una condizione (per l'albero e l'anteprima).
String descriviCondizione(String? testo, List<Variabile> variabili) {
  final c = analizzaCondizione(testo);
  if ((testo ?? '').trim().isEmpty) return 'sempre';
  if (c == null) return testo!;
  String etichetta(String nome) =>
      variabili.where((v) => v.nome == nome).map((v) => v.etichetta).firstOrNull ?? nome;
  String valore(Clausola k, Object? v) {
    final variabile = variabili.where((x) => x.nome == k.nome).firstOrNull;
    return variabile?.opzioni[v?.toString()] ?? v.toString();
  }

  return c.clausole.map((k) {
    final e = etichetta(k.nome);
    return switch (k.operatore) {
      'vero' => e,
      'falso' => 'non: $e',
      'in' => '$e è uno tra ${(k.valore as List).map((v) => valore(k, v)).join(', ')}',
      '==' => '$e è ${valore(k, k.valore)}',
      '!=' => '$e non è ${valore(k, k.valore)}',
      _ => '$e ${k.operatore} ${k.valore}',
    };
  }).join(c.connettivo == 'and' ? ' e ' : ' oppure ');
}

/// "Quando compare": righe con variabile, operatore e valore scelti da menu; per le
/// condizioni complesse una casella di testo con la sintassi delle condizioni.
class CondizioneEditor extends StatefulWidget {
  const CondizioneEditor({
    super.key,
    required this.valore,
    required this.variabili,
    required this.onChanged,
    this.etichetta = 'Quando compare',
    this.vuota = 'Sempre',
  });

  final String? valore;
  final List<Variabile> variabili;
  final ValueChanged<String?> onChanged;
  final String etichetta;
  final String vuota;

  @override
  State<CondizioneEditor> createState() => _CondizioneEditorState();
}

class _CondizioneEditorState extends State<CondizioneEditor> {
  late bool _avanzata;
  final _testo = TextEditingController();

  @override
  void initState() {
    super.initState();
    _avanzata = analizzaCondizione(widget.valore) == null;
    _testo.text = widget.valore ?? '';
  }

  @override
  void didUpdateWidget(covariant CondizioneEditor vecchio) {
    super.didUpdateWidget(vecchio);
    if (widget.valore != vecchio.valore && widget.valore != _testo.text) {
      _testo.text = widget.valore ?? '';
      if (analizzaCondizione(widget.valore) == null) _avanzata = true;
    }
  }

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  void _emetti(CondizioneSemplice c) {
    final testo = scriviCondizione(c);
    _testo.text = testo;
    widget.onChanged(testo.isEmpty ? null : testo);
  }

  Variabile? _variabile(String nome) => widget.variabili.where((v) => v.nome == nome).firstOrNull;

  List<(String, String)> _operatori(Variabile? v) => switch (v?.tipo) {
        'si_no' => const [('vero', 'sì'), ('falso', 'no')],
        'scelta' => const [('==', 'è'), ('!=', 'non è'), ('in', 'è uno tra')],
        'numero' => const [('<', '<'), ('<=', '≤'), ('>', '>'), ('>=', '≥'), ('==', '='), ('!=', '≠')],
        _ => const [('==', 'è'), ('!=', 'non è'), ('vero', 'compilato'), ('falso', 'non compilato')],
      };

  Widget _riga(CondizioneSemplice c, int i) {
    final k = c.clausole[i];
    final v = _variabile(k.nome);
    final operatori = _operatori(v);
    if (!operatori.any((o) => o.$1 == k.operatore)) k.operatore = operatori.first.$1;
    Widget valore = const SizedBox.shrink();
    if (k.operatore == 'in' && v != null) {
      final scelti = List<String>.from(k.valore as List? ?? const []);
      valore = Wrap(spacing: 4, children: [
        for (final o in v.opzioni.entries)
          FilterChip(
            label: Text(o.value, overflow: TextOverflow.ellipsis),
            selected: scelti.contains(o.key),
            onSelected: (s) {
              s ? scelti.add(o.key) : scelti.remove(o.key);
              k.valore = scelti;
              _emetti(c);
            },
          ),
      ]);
    } else if (!['vero', 'falso'].contains(k.operatore)) {
      if (v?.tipo == 'scelta') {
        final attuale = v!.opzioni.containsKey(k.valore) ? k.valore as String : null;
        valore = DropdownButton<String>(
          isExpanded: true,
          value: attuale,
          hint: const Text('valore'),
          items: [
            for (final o in v.opzioni.entries)
              DropdownMenuItem(value: o.key, child: Text(o.value, overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (x) {
            k.valore = x;
            _emetti(c);
          },
        );
      } else {
        valore = TextFormField(
          key: ValueKey('${k.nome}-$i'),
          initialValue: k.valore?.toString() ?? '',
          decoration: const InputDecoration(isDense: true, hintText: 'valore'),
          onChanged: (x) {
            k.valore = v?.tipo == 'numero' ? (num.tryParse(x.replaceAll('.', '').replaceAll(',', '.')) ?? x) : x;
            _emetti(c);
          },
        );
      }
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        Expanded(
          flex: 5,
          child: DropdownButton<String>(
            isExpanded: true,
            value: v != null ? k.nome : null,
            hint: Text(k.nome),
            items: [
              for (final x in widget.variabili)
                DropdownMenuItem(value: x.nome, child: Text(x.etichetta, overflow: TextOverflow.ellipsis)),
            ],
            onChanged: (x) {
              k.nome = x!;
              k.valore = null;
              k.operatore = _operatori(_variabile(x)).first.$1;
              _emetti(c);
            },
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          width: 120,
          child: DropdownButton<String>(
            isExpanded: true,
            value: k.operatore,
            items: [for (final o in operatori) DropdownMenuItem(value: o.$1, child: Text(o.$2))],
            onChanged: (x) {
              k.operatore = x!;
              k.valore = x == 'in' ? <String>[] : null;
              _emetti(c);
            },
          ),
        ),
        const SizedBox(width: 8),
        Expanded(flex: 4, child: valore),
        IconButton(
          tooltip: 'Togli',
          icon: const Icon(Icons.close, size: 18),
          onPressed: () {
            c.clausole.removeAt(i);
            _emetti(c);
          },
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final c = _avanzata ? null : analizzaCondizione(widget.valore);
    return InputDecorator(
      decoration: InputDecoration(labelText: widget.etichetta, border: const OutlineInputBorder()),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (c == null)
          TextField(
            controller: _testo,
            maxLines: null,
            style: const TextStyle(fontFamily: 'monospace'),
            decoration: const InputDecoration(
              isDense: true,
              helperText: 'Condizione avanzata: and, or, not, ==, !=, <, >, in [..], implica, parentesi',
              helperMaxLines: 2,
            ),
            onChanged: (x) => widget.onChanged(x.trim().isEmpty ? null : x.trim()),
          )
        else ...[
          if (c.clausole.isEmpty) Text(widget.vuota, style: tema.textTheme.bodySmall),
          for (var i = 0; i < c.clausole.length; i++) _riga(c, i),
          Row(children: [
            TextButton.icon(
              onPressed: widget.variabili.isEmpty
                  ? null
                  : () {
                      final v = widget.variabili.first;
                      c.clausole.add(Clausola(v.nome, _operatori(v).first.$1));
                      _emetti(c);
                    },
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Condizione'),
            ),
            if (c.clausole.length > 1)
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'and', label: Text('tutte')),
                  ButtonSegment(value: 'or', label: Text('almeno una')),
                ],
                selected: {c.connettivo},
                onSelectionChanged: (s) {
                  c.connettivo = s.first;
                  _emetti(c);
                },
              ),
          ]),
        ],
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(
            onPressed: () => setState(() {
              if (_avanzata && analizzaCondizione(_testo.text) == null) return;
              _avanzata = !_avanzata;
            }),
            child: Text(_avanzata ? 'Modifica con i menu' : 'Scrivi la condizione'),
          ),
        ),
      ]),
    );
  }
}
