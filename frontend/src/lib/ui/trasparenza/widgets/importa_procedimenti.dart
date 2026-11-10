import 'package:flutter/material.dart';

import '../../../api/api_client.dart';
import '../../comuni.dart' show Caricamento;

/// Scelta dei procedimenti del catalogo (mappatura dell'anticorruzione o procedimenti della
/// trasparenza) da importare nella scheda
/// art. 35 (GET /api/v1/trasparenza/procedimenti-mappatura): restituisce gli elementi nel
/// formato dello schema, già compilati con i recapiti degli uffici; si possono poi modificare.
Future<List<Map<String, dynamic>>?> scegliProcedimenti(BuildContext context, ApiClient api) {
  final elenco = api
      .get('/api/v1/trasparenza/procedimenti-mappatura')
      .then((v) => (v as List).cast<Map<String, dynamic>>());
  return showDialog<List<Map<String, dynamic>>>(context: context, builder: (_) => _Scelta(elenco));
}

class _Scelta extends StatefulWidget {
  const _Scelta(this.elenco);

  final Future<List<Map<String, dynamic>>> elenco;

  @override
  State<_Scelta> createState() => _SceltaState();
}

class _SceltaState extends State<_Scelta> {
  final _scelti = <String>{};
  final _testo = TextEditingController();

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<List<Map<String, dynamic>>>(
        future: widget.elenco,
        builder: (context, snap) {
          final tutti = snap.data ?? const <Map<String, dynamic>>[];
          final cerca = _testo.text.trim().toLowerCase();
          final visibili = tutti.where((p) => '${p['codice']} ${p['denominazione']} ${p['struttura'] ?? ''}'.toLowerCase().contains(cerca)).toList();
          return AlertDialog(
            title: const Text('Importa dai procedimenti dell\'ente'),
            content: SizedBox(
              width: 680,
              height: 480,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Text('I dati arrivano dai procedimenti dell\'ente (scheda Procedimenti o mappatura dell\'anticorruzione), '
                    'con i recapiti degli uffici '
                    'presi dalle strutture; dopo l\'importazione si possono modificare nella scheda.'),
                const SizedBox(height: 8),
                TextField(
                  controller: _testo,
                  decoration: const InputDecoration(labelText: 'Cerca', prefixIcon: Icon(Icons.search), isDense: true),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: Caricamento<List<Map<String, dynamic>>>(
                    future: widget.elenco,
                    builder: (context, _) => tutti.isEmpty
                        ? const Center(child: Text('Nessun procedimento: si inseriscono nella scheda Procedimenti.'))
                        : ListView(children: [
                            for (final p in visibili)
                              CheckboxListTile(
                                dense: true,
                                value: _scelti.contains(p['id']),
                                onChanged: (v) => setState(() => v == true ? _scelti.add(p['id'] as String) : _scelti.remove(p['id'])),
                                title: Text('${p['codice']} - ${p['denominazione']}'),
                                subtitle: Text([
                                  ?p['struttura'] as String?,
                                  (p['mancanti'] as List).isEmpty ? 'dati art. 35 completi' : 'mancano ${(p['mancanti'] as List).length} dati art. 35',
                                ].join(' · ')),
                              ),
                          ]),
                  ),
                ),
              ]),
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
              FilledButton(
                onPressed: _scelti.isEmpty
                    ? null
                    : () => Navigator.pop(context, [
                          for (final p in tutti)
                            if (_scelti.contains(p['id'])) (p['elemento'] as Map).cast<String, dynamic>(),
                        ]),
                child: Text(_scelti.isEmpty ? 'Importa' : 'Importa (${_scelti.length})'),
              ),
            ],
          );
        },
      );
}
