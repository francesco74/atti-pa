import 'package:flutter/material.dart';

import '../comuni.dart';

/// Selezione di riferimenti dalla libreria (condivisi e personali) o inserimento manuale.
class SceltaRiferimentiDialog extends StatefulWidget {
  const SceltaRiferimentiDialog({super.key, this.tipologia});

  final String? tipologia;

  @override
  State<SceltaRiferimentiDialog> createState() => _SceltaRiferimentiDialogState();
}

class _SceltaRiferimentiDialogState extends State<SceltaRiferimentiDialog> {
  late Future<List<dynamic>> _riferimenti;
  final _cerca = TextEditingController();
  final Set<String> _scelti = {};
  bool _soloTipologia = true;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _cerca.dispose();
    super.dispose();
  }

  void _carica() {
    setState(() {
      _riferimenti = apiDi(context).get('/api/v1/riferimenti', query: {
        'q': _cerca.text.trim(),
        if (_soloTipologia && widget.tipologia != null) 'tipologia': widget.tipologia!,
      }).then((v) => v as List<dynamic>);
    });
  }

  Future<void> _manuale() async {
    final r = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => const RiferimentoManualeDialog(),
    );
    if (r != null && mounted) Navigator.pop(context, [r]);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Riferimenti normativi'),
      content: SizedBox(
        width: 700,
        height: 480,
        child: Column(children: [
          TextField(
            controller: _cerca,
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Cerca'),
            onSubmitted: (_) => _carica(),
          ),
          if (widget.tipologia != null)
            CheckboxListTile(
              value: _soloTipologia,
              contentPadding: EdgeInsets.zero,
              title: const Text('Solo i riferimenti indicati per questa tipologia'),
              onChanged: (v) {
                _soloTipologia = v ?? true;
                _carica();
              },
            ),
          Expanded(
            child: Caricamento<List<dynamic>>(
              future: _riferimenti,
              riprova: _carica,
              builder: (context, lista) => lista.isEmpty
                  ? const Center(child: Text('Nessun riferimento in libreria.'))
                  : ListView(children: [
                      for (final r in lista.cast<Map<String, dynamic>>())
                        CheckboxListTile(
                          value: _scelti.contains(r['id']),
                          title: Text(r['citazione'].toString()),
                          subtitle: r['note'] != null ? Text(r['note'].toString()) : null,
                          secondary: Icon(r['owner_id'] == null ? Icons.groups : Icons.person,
                              size: 20),
                          onChanged: (v) => setState(() {
                            v == true ? _scelti.add(r['id'] as String) : _scelti.remove(r['id']);
                          }),
                        ),
                    ]),
            ),
          ),
        ]),
      ),
      actions: [
        TextButton.icon(
            onPressed: _manuale, icon: const Icon(Icons.edit), label: const Text('Inserisci a mano')),
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FutureBuilder<List<dynamic>>(
          future: _riferimenti,
          builder: (context, snap) => FilledButton(
            onPressed: _scelti.isEmpty || !snap.hasData
                ? null
                : () => Navigator.pop(context, [
                      for (final r in snap.data!.cast<Map<String, dynamic>>())
                        if (_scelti.contains(r['id']))
                          {
                            'urn_atto': r['urn_atto'],
                            'articolo': r['articolo'],
                            'comma': r['comma'],
                            'lettera': r['lettera'],
                            'citazione': r['citazione'],
                          },
                    ]),
            child: Text('Aggiungi (${_scelti.length})'),
          ),
        ),
      ],
    );
  }
}

const tipiAtto = {
  'legge': 'Legge',
  'decreto legislativo': 'Decreto legislativo',
  'decreto-legge': 'Decreto-legge',
  'decreto del presidente della repubblica': 'D.P.R.',
  'decreto del presidente del consiglio dei ministri': 'D.P.C.M.',
  'regio decreto': 'Regio decreto',
};

/// Riferimento a una norma non presente in libreria: l'atto viene verificato su Normattiva.
class RiferimentoManualeDialog extends StatefulWidget {
  const RiferimentoManualeDialog({super.key});

  @override
  State<RiferimentoManualeDialog> createState() => _RiferimentoManualeDialogState();
}

class _RiferimentoManualeDialogState extends State<RiferimentoManualeDialog> {
  String _tipo = 'decreto legislativo';
  DateTime? _data;
  final _numero = TextEditingController();
  final _articolo = TextEditingController();
  final _comma = TextEditingController();
  final _lettera = TextEditingController();
  bool _inCorso = false;

  @override
  void dispose() {
    for (final c in [_numero, _articolo, _comma, _lettera]) {
      c.dispose();
    }
    super.dispose();
  }

  String? _vuoto(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();

  Future<void> _conferma() async {
    if (_data == null || _numero.text.trim().isEmpty || _articolo.text.trim().isEmpty) {
      mostraErrore(context, 'Indicare data, numero e articolo');
      return;
    }
    setState(() => _inCorso = true);
    try {
      final norma = await apiDi(context).post('/api/v1/norme', {
        'tipo': _tipo,
        'data': isoData(_data!),
        'numero': _numero.text.trim(),
      }) as Map<String, dynamic>;
      if (!mounted) return;
      Navigator.pop(context, {
        'urn_atto': norma['urn'],
        'articolo': _articolo.text.trim(),
        'comma': _vuoto(_comma),
        'lettera': _vuoto(_lettera),
      });
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _inCorso = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Riferimento manuale'),
      content: SizedBox(
        width: 480,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          DropdownButtonFormField<String>(
            initialValue: _tipo,
            decoration: const InputDecoration(labelText: 'Tipo di atto'),
            items: [
              for (final e in tipiAtto.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
            ],
            onChanged: (v) => setState(() => _tipo = v ?? _tipo),
          ),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: InputDecorator(
                decoration: const InputDecoration(labelText: 'Data'),
                child: InkWell(
                  onTap: () async {
                    final d = await scegliData(context, _data);
                    if (d != null) setState(() => _data = d);
                  },
                  child: Text(_data == null ? 'Scegli…' : formatData(isoData(_data!))),
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                  controller: _numero, decoration: const InputDecoration(labelText: 'Numero')),
            ),
          ]),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
                child: TextField(
                    controller: _articolo, decoration: const InputDecoration(labelText: 'Articolo'))),
            const SizedBox(width: 12),
            Expanded(
                child: TextField(
                    controller: _comma, decoration: const InputDecoration(labelText: 'Comma'))),
            const SizedBox(width: 12),
            Expanded(
                child: TextField(
                    controller: _lettera, decoration: const InputDecoration(labelText: 'Lettera'))),
          ]),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FilledButton(
          onPressed: _inCorso ? null : _conferma,
          child: _inCorso
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Verifica e aggiungi'),
        ),
      ],
    );
  }
}
