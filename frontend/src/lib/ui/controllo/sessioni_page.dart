import 'package:flutter/material.dart';

import '../comuni.dart';
import 'sessione_page.dart';

class SessioniPage extends StatefulWidget {
  const SessioniPage({super.key});

  @override
  State<SessioniPage> createState() => _SessioniPageState();
}

class _SessioniPageState extends State<SessioniPage> {
  late Future<List<dynamic>> _sessioni;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _sessioni = apiDi(context).get('/api/v1/controllo/sessioni').then((v) => v as List);
      });

  Future<void> _nuova() async {
    final titolo = TextEditingController();
    DateTime? da;
    DateTime? a;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: const Text('Nuova sessione di controllo'),
          content: SizedBox(
            width: 420,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(
                controller: titolo,
                decoration: const InputDecoration(labelText: 'Titolo', hintText: 'Controllo 1° semestre 2026'),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(da == null ? 'Periodo dal' : 'Dal ${formatData(isoData(da!))}'),
                trailing: const Icon(Icons.calendar_month),
                onTap: () async {
                  final d = await scegliData(c, da);
                  if (d != null) aggiorna(() => da = d);
                },
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(a == null ? 'Periodo al' : 'Al ${formatData(isoData(a!))}'),
                trailing: const Icon(Icons.calendar_month),
                onTap: () async {
                  final d = await scegliData(c, a);
                  if (d != null) aggiorna(() => a = d);
                },
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Crea')),
          ],
        ),
      ),
    );
    if (ok != true || da == null || a == null || !mounted) return;
    try {
      await apiDi(context).post('/api/v1/controllo/sessioni', {
        'titolo': titolo.text.trim(),
        'periodo_da': isoData(da!),
        'periodo_a': isoData(a!),
      });
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      titolo.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _nuova,
        icon: const Icon(Icons.add),
        label: const Text('Nuova sessione'),
      ),
      body: Caricamento<List<dynamic>>(
        future: _sessioni,
        riprova: _carica,
        builder: (context, sessioni) => sessioni.isEmpty
            ? const Center(child: Text('Nessuna sessione di controllo.'))
            : ListView(padding: const EdgeInsets.all(16), children: [
                for (final s in sessioni.cast<Map<String, dynamic>>())
                  Card(
                    child: ListTile(
                      leading: Icon(s['stato'] == 'CHIUSA' ? Icons.lock : Icons.fact_check),
                      title: Text(s['titolo'].toString()),
                      subtitle: Text('Dal ${formatData(s['periodo_da'])} al ${formatData(s['periodo_a'])}'
                          ' · ${_riepilogo(s['conteggio_stati'] as Map<String, dynamic>? ?? {})}'),
                      trailing: Chip(label: Text(s['stato'].toString())),
                      onTap: () async {
                        await Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => SessionePage(sessioneId: s['id'] as String)));
                        _carica();
                      },
                    ),
                  ),
              ]),
      ),
    );
  }

  String _riepilogo(Map<String, dynamic> conteggi) {
    final totale = conteggi.values.fold<int>(0, (a, b) => a + (b as int));
    final chiusi = (conteggi['CHIUSO'] as int?) ?? 0;
    return '$totale atti, $chiusi chiusi';
  }
}
