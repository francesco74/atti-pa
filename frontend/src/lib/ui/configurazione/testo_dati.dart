import 'package:flutter/material.dart';

/// Dato inseribile in un testo: {{nome}} o, per gli elenchi, {{nome.sottocampo}}.
class DatoInseribile {
  const DatoInseribile(this.segnaposto, this.etichetta, this.gruppo);

  final String segnaposto; // es. importo_offerta, impegni.capitolo
  final String etichetta;
  final String gruppo; // Dati, Domande, Valori calcolati
}

/// Dati di una definizione di modello o di specificità (più quelli aggiuntivi, es. i dati
/// dei modelli a cui si applica una specificità).
List<DatoInseribile> datiDi(Map<String, dynamic> definizione,
    {List<DatoInseribile> altri = const []}) {
  final risultato = <DatoInseribile>[];
  final campi = Map<String, dynamic>.from(definizione['campi'] as Map? ?? const {});
  for (final c in campi.entries) {
    final campo = Map<String, dynamic>.from(c.value as Map);
    if (campo['tipo'] == 'elenco') {
      final sotto = Map<String, dynamic>.from(campo['sottocampi'] as Map? ?? const {});
      for (final s in sotto.entries) {
        risultato.add(DatoInseribile('${c.key}.${s.key}',
            '${campo['etichetta']}: ${(s.value as Map)['etichetta']}', 'Dati (elenchi)'));
      }
    } else {
      risultato.add(DatoInseribile(c.key, campo['etichetta']?.toString() ?? c.key, 'Dati'));
    }
  }
  for (final q in List<Map<String, dynamic>>.from(definizione['domande'] as List? ?? const [])) {
    if (q['tipo'] != 'scelta_multipla') {
      risultato.add(DatoInseribile(q['id'] as String, q['testo'] as String, 'Risposte alle domande'));
    }
  }
  for (final d in Map<String, dynamic>.from(definizione['derivati'] as Map? ?? const {}).keys) {
    risultato.add(DatoInseribile(d, d, 'Valori calcolati'));
  }
  final presenti = risultato.map((d) => d.segnaposto).toSet();
  return [...risultato, ...altri.where((d) => !presenti.contains(d.segnaposto))];
}

final segnapostoRe = RegExp(r'\{\{\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\}\}');

/// Testo con i dati evidenziati: quelli noti con lo sfondo dei dati, quelli inesistenti in
/// rosso.
class _ControllerDati extends TextEditingController {
  _ControllerDati(String testo, this.noti) : super(text: testo);

  Set<String> noti;

  @override
  TextSpan buildTextSpan({required BuildContext context, TextStyle? style, required bool withComposing}) {
    final colori = Theme.of(context).colorScheme;
    final parti = <TextSpan>[];
    var da = 0;
    for (final m in segnapostoRe.allMatches(text)) {
      if (m.start > da) parti.add(TextSpan(text: text.substring(da, m.start)));
      final noto = noti.contains(m.group(1));
      parti.add(TextSpan(
        text: m.group(0),
        style: TextStyle(
          backgroundColor: noto ? colori.secondaryContainer : colori.errorContainer,
          color: noto ? colori.onSecondaryContainer : colori.error,
          fontWeight: FontWeight.w600,
        ),
      ));
      da = m.end;
    }
    if (da < text.length) parti.add(TextSpan(text: text.substring(da)));
    return TextSpan(style: style, children: parti);
  }
}

/// Testo di un capoverso: i dati {{...}} sono evidenziati; si inseriscono con il pulsante o
/// digitando @. Sotto, i dati usati con il loro nome leggibile.
class TestoConDati extends StatefulWidget {
  const TestoConDati({
    super.key,
    required this.valore,
    required this.dati,
    required this.onChanged,
    this.etichetta = 'Testo',
    this.onDato,
    this.righe = 4,
  });

  final String valore;
  final List<DatoInseribile> dati;
  final ValueChanged<String> onChanged;
  final String etichetta;
  final ValueChanged<String>? onDato; // clic su un dato usato: lo apre nell'editor
  final int righe;

  @override
  State<TestoConDati> createState() => _TestoConDatiState();
}

class _TestoConDatiState extends State<TestoConDati> {
  late final _ControllerDati _controller;
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    _controller = _ControllerDati(widget.valore, _noti());
  }

  Set<String> _noti() => widget.dati.map((d) => d.segnaposto).toSet();

  @override
  void didUpdateWidget(covariant TestoConDati vecchio) {
    super.didUpdateWidget(vecchio);
    _controller.noti = _noti();
    if (widget.valore != _controller.text) _controller.text = widget.valore;
  }

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _inserisci({bool togliChiocciola = false}) async {
    final scelto = await showDialog<String>(
      context: context,
      builder: (_) => _SceltaDato(dati: widget.dati),
    );
    final sel = _controller.selection;
    var testo = _controller.text;
    var inizio = sel.isValid ? sel.start : testo.length;
    var fine = sel.isValid ? sel.end : testo.length;
    if (togliChiocciola && inizio > 0 && testo[inizio - 1] == '@') {
      inizio -= 1;
    }
    if (scelto == null) {
      _focus.requestFocus();
      return;
    }
    final inserito = '{{$scelto}}';
    testo = testo.replaceRange(inizio, fine, inserito);
    _controller.value = TextEditingValue(
      text: testo,
      selection: TextSelection.collapsed(offset: inizio + inserito.length),
    );
    widget.onChanged(testo);
    _focus.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    final usati = <String>{for (final m in segnapostoRe.allMatches(_controller.text)) m.group(1)!};
    final perNome = {for (final d in widget.dati) d.segnaposto: d};
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      TextField(
        controller: _controller,
        focusNode: _focus,
        minLines: widget.righe,
        maxLines: null,
        decoration: InputDecoration(
          labelText: widget.etichetta,
          border: const OutlineInputBorder(),
          alignLabelWithHint: true,
          helperText: 'Digita @ o usa "Inserisci un dato" per aggiungere un dato da compilare',
        ),
        onChanged: (t) {
          widget.onChanged(t);
          final sel = _controller.selection;
          if (sel.isValid && sel.start > 0 && t[sel.start - 1] == '@' &&
              (sel.start == 1 || t[sel.start - 2] == ' ' || t[sel.start - 2] == '\n')) {
            _inserisci(togliChiocciola: true);
          } else {
            setState(() {});
          }
        },
      ),
      const SizedBox(height: 4),
      Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
        TextButton.icon(
          onPressed: _inserisci,
          icon: const Icon(Icons.data_object, size: 18),
          label: const Text('Inserisci un dato'),
        ),
        for (final u in usati)
          ActionChip(
            avatar: Icon(perNome.containsKey(u) ? Icons.label_outline : Icons.error_outline,
                size: 16, color: perNome.containsKey(u) ? null : Theme.of(context).colorScheme.error),
            label: Text(perNome[u]?.etichetta ?? '$u (non definito)'),
            onPressed: widget.onDato == null ? null : () => widget.onDato!(u.split('.').first),
          ),
      ]),
    ]);
  }
}

class _SceltaDato extends StatefulWidget {
  const _SceltaDato({required this.dati});

  final List<DatoInseribile> dati;

  @override
  State<_SceltaDato> createState() => _SceltaDatoState();
}

class _SceltaDatoState extends State<_SceltaDato> {
  String _filtro = '';

  @override
  Widget build(BuildContext context) {
    final f = _filtro.toLowerCase();
    final visibili = widget.dati
        .where((d) => f.isEmpty || d.etichetta.toLowerCase().contains(f) || d.segnaposto.contains(f))
        .toList();
    final gruppi = <String, List<DatoInseribile>>{};
    for (final d in visibili) {
      gruppi.putIfAbsent(d.gruppo, () => []).add(d);
    }
    return AlertDialog(
      title: const Text('Inserisci un dato'),
      content: SizedBox(
        width: 520,
        height: 420,
        child: Column(children: [
          TextField(
            autofocus: true,
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Cerca'),
            onChanged: (v) => setState(() => _filtro = v),
            onSubmitted: (_) {
              if (visibili.length == 1) Navigator.pop(context, visibili.first.segnaposto);
            },
          ),
          Expanded(
            child: ListView(children: [
              for (final g in gruppi.entries) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 8, bottom: 4),
                  child: Text(g.key, style: Theme.of(context).textTheme.labelLarge),
                ),
                for (final d in g.value)
                  ListTile(
                    dense: true,
                    title: Text(d.etichetta),
                    subtitle: Text('{{${d.segnaposto}}}'),
                    onTap: () => Navigator.pop(context, d.segnaposto),
                  ),
              ],
            ]),
          ),
        ]),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla'))],
    );
  }
}
