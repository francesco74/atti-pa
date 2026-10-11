import 'package:flutter/material.dart';

import '../comuni.dart';

class _Elemento {
  _Elemento({String titolo = '', String regola = '', String riferimenti = '', this.obbligatorio = true})
      : titolo = TextEditingController(text: titolo),
        regola = TextEditingController(text: regola),
        riferimenti = TextEditingController(text: riferimenti);

  final TextEditingController titolo;
  final TextEditingController regola;
  final TextEditingController riferimenti;
  bool obbligatorio;

  void dispose() {
    titolo.dispose();
    regola.dispose();
    riferimenti.dispose();
  }

  Map<String, dynamic> toJson() => {
        'titolo': titolo.text.trim(),
        'regola': regola.text.trim(),
        'riferimenti': riferimenti.text
            .split(RegExp(r'[\s,;]+'))
            .map((s) => s.trim())
            .where((s) => s.startsWith('urn:nir:'))
            .toList(),
        'obbligatorio': obbligatorio,
      };
}

/// Creazione di una checklist o di una sua nuova versione.
class ChecklistEditorPage extends StatefulWidget {
  const ChecklistEditorPage({super.key, this.esistente});

  final Map<String, dynamic>? esistente;

  @override
  State<ChecklistEditorPage> createState() => _ChecklistEditorPageState();
}

class _ChecklistEditorPageState extends State<ChecklistEditorPage> {
  final _codice = TextEditingController();
  final _titolo = TextEditingController();
  final _descrizione = TextEditingController();
  String? _tipologia;
  final List<_Elemento> _elementi = [];
  late Future<List<dynamic>> _tipologie;
  bool _inCorso = false;

  bool get _nuova => widget.esistente == null;

  @override
  void initState() {
    super.initState();
    _tipologie = apiDi(context).get('/api/v1/tipologie').then((v) => v as List);
    final e = widget.esistente;
    if (e != null) {
      _codice.text = e['codice'] as String;
      _titolo.text = e['titolo'] as String;
      _descrizione.text = (e['descrizione'] ?? '') as String;
      _tipologia = e['tipologia_atto'] as String;
      for (final el in (e['elementi'] as List).cast<Map<String, dynamic>>()) {
        _elementi.add(_Elemento(
          titolo: el['titolo'] as String,
          regola: el['regola'] as String,
          riferimenti: ((el['riferimenti_json'] as List?) ?? []).join('\n'),
          obbligatorio: el['obbligatorio'] as bool? ?? true,
        ));
      }
    } else {
      _elementi.add(_Elemento());
    }
  }

  @override
  void dispose() {
    _codice.dispose();
    _titolo.dispose();
    _descrizione.dispose();
    for (final e in _elementi) {
      e.dispose();
    }
    super.dispose();
  }

  Future<void> _salva() async {
    final elementi = _elementi.map((e) => e.toJson()).where((e) => (e['titolo'] as String).isNotEmpty).toList();
    if (_titolo.text.trim().isEmpty || _tipologia == null || elementi.isEmpty) {
      mostraErrore(context, 'Indicare titolo, tipologia e almeno un criterio');
      return;
    }
    final corpo = {
      'titolo': _titolo.text.trim(),
      'tipologia_atto': _tipologia,
      'descrizione': _descrizione.text.trim().isEmpty ? null : _descrizione.text.trim(),
      'elementi': elementi,
    };
    setState(() => _inCorso = true);
    try {
      final api = apiDi(context);
      if (_nuova) {
        await api.post('/api/v1/checklists', {...corpo, 'codice': _codice.text.trim()});
      } else {
        await api.put('/api/v1/checklists/codice/${_codice.text}', corpo);
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _inCorso = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_nuova ? 'Nuova checklist' : 'Nuova versione di ${_codice.text}'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: FilledButton.icon(
              onPressed: _inCorso ? null : _salva,
              icon: const Icon(Icons.save),
              label: Text(_nuova ? 'Crea' : 'Salva nuova versione'),
            ),
          ),
        ],
      ),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Wrap(spacing: 12, runSpacing: 12, children: [
          SizedBox(
            width: 220,
            child: TextField(
              controller: _codice,
              enabled: _nuova,
              decoration: const InputDecoration(labelText: 'Codice', hintText: 'AFFIDAMENTO-BASE'),
            ),
          ),
          SizedBox(
            width: 420,
            child: TextField(controller: _titolo, decoration: const InputDecoration(labelText: 'Titolo')),
          ),
          SizedBox(
            width: 320,
            child: FutureBuilder<List<dynamic>>(
              future: _tipologie,
              builder: (context, snap) => DropdownButtonFormField<String>(
                value: _tipologia,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Tipologia di atto'),
                items: [
                  for (final t in (snap.data ?? const []).cast<Map<String, dynamic>>())
                    DropdownMenuItem(value: t['codice'] as String, child: Text(t['descrizione'] as String)),
                ],
                onChanged: (v) => setState(() => _tipologia = v),
              ),
            ),
          ),
        ]),
        const SizedBox(height: 12),
        TextField(
          controller: _descrizione,
          maxLines: 2,
          decoration: const InputDecoration(labelText: 'Descrizione'),
        ),
        const SizedBox(height: 16),
        Text('Criteri', style: Theme.of(context).textTheme.titleMedium),
        const Text('Ogni criterio è valutato separatamente dal modello. Nelle norme pertinenti '
            'indica le URN degli articoli (es. urn:nir:stato:decreto.legislativo:2023-03-31;36~art50): '
            'il loro testo vigente sarà incluso nella valutazione.'),
        const SizedBox(height: 8),
        for (var i = 0; i < _elementi.length; i++)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(children: [
                Row(children: [
                  Text('${i + 1}.'),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                        controller: _elementi[i].titolo,
                        decoration: const InputDecoration(labelText: 'Titolo del criterio')),
                  ),
                  Checkbox(
                    value: _elementi[i].obbligatorio,
                    onChanged: (v) => setState(() => _elementi[i].obbligatorio = v ?? true),
                  ),
                  const Text('Obbligatorio'),
                  IconButton(
                    tooltip: 'Rimuovi',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () => setState(() => _elementi.removeAt(i).dispose()),
                  ),
                ]),
                const SizedBox(height: 8),
                TextField(
                  controller: _elementi[i].regola,
                  maxLines: 4,
                  decoration: const InputDecoration(
                    labelText: 'Regola da verificare',
                    hintText: 'Es. L\'atto motiva la scelta dell\'operatore economico e dà conto '
                        'del rispetto del principio di rotazione.',
                    alignLabelWithHint: true,
                  ),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _elementi[i].riferimenti,
                  maxLines: 2,
                  decoration: const InputDecoration(labelText: 'Norme pertinenti (URN, una per riga)'),
                ),
              ]),
            ),
          ),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: () => setState(() => _elementi.add(_Elemento())),
            icon: const Icon(Icons.add),
            label: const Text('Aggiungi criterio'),
          ),
        ),
      ]),
    );
  }
}
