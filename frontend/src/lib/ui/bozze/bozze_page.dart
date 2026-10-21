import 'package:flutter/material.dart';

import '../comuni.dart';
import 'bozza_editor_page.dart';

/// Testo breve dell'avanzamento di una bozza (0 = domande iniziali, 1-4 = fasi, 5 = verifica).
/// Avanzamento dai dati inseriti: fasi senza dati mancanti (null = domande da completare).
String avanzamentoBozza(Map<String, dynamic> b) {
  final complete = b['fasi_complete'] as int?;
  final totali = (b['fasi_totali'] as int?) ?? 0;
  if (complete == null) return 'domande iniziali da completare';
  if (complete >= totali) return 'dati completi';
  return '$complete fasi su $totali complete';
}

class BozzePage extends StatefulWidget {
  const BozzePage({super.key});

  @override
  State<BozzePage> createState() => _BozzePageState();
}

class _BozzePageState extends State<BozzePage> {
  late Future<List<dynamic>> _bozze;
  final _cerca = TextEditingController();

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
      _bozze = apiDi(context)
          .get('/api/v1/bozze', query: {'q': _cerca.text.trim()}).then((v) => v as List<dynamic>);
    });
  }

  Future<void> _apri(String id) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => BozzaEditorPage(bozzaId: id)));
    _carica();
  }

  /// "Che atto vuoi redigere?": si sceglie il modello, poi si apre il percorso.
  Future<void> _nuova() async {
    final modello = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => const _SceltaModello(),
    );
    if (modello == null || !mounted) return;
    try {
      final b = await apiDi(context).post('/api/v1/bozze', {'modello_id': modello['id']})
          as Map<String, dynamic>;
      if (mounted) await _apri(b['id'] as String);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _elimina(Map<String, dynamic> b) async {
    if (!await conferma(context, 'Eliminare la bozza?', b['oggetto'].toString())) return;
    if (!mounted) return;
    try {
      await apiDi(context).delete('/api/v1/bozze/${b['id']}');
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _nuova,
        icon: const Icon(Icons.add),
        label: const Text('Nuova bozza'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          Row(children: [
            Expanded(
              child: TextField(
                controller: _cerca,
                decoration: const InputDecoration(
                    prefixIcon: Icon(Icons.search), hintText: 'Cerca per oggetto'),
                onSubmitted: (_) => _carica(),
              ),
            ),
            IconButton(onPressed: _carica, icon: const Icon(Icons.refresh)),
          ]),
          const SizedBox(height: 12),
          Expanded(
            child: Caricamento<List<dynamic>>(
              future: _bozze,
              riprova: _carica,
              builder: (context, bozze) => bozze.isEmpty
                  ? const Center(child: Text('Nessuna bozza. Crea la prima con "Nuova bozza".'))
                  : ListView.separated(
                      padding: const EdgeInsets.only(bottom: 80),
                      itemCount: bozze.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, i) {
                        final b = bozze[i] as Map<String, dynamic>;
                        return ListTile(
                          leading: const Icon(Icons.description_outlined),
                          title: Text(b['oggetto'].toString(),
                              maxLines: 2, overflow: TextOverflow.ellipsis),
                          subtitle: Text([
                            b['modello'],
                            avanzamentoBozza(b),
                            if (b['data_adozione_prevista'] != null)
                              'adozione ${formatData(b['data_adozione_prevista'])}',
                            'modificata ${formatData(b['updated_at'])}',
                          ].join(' · ')),
                          trailing: IconButton(
                            tooltip: 'Elimina',
                            icon: const Icon(Icons.delete_outline),
                            onPressed: () => _elimina(b),
                          ),
                          onTap: () => _apri(b['id'] as String),
                        );
                      },
                    ),
            ),
          ),
        ]),
      ),
    );
  }
}

/// Elenco dei modelli attivi, raggruppati per tipo di provvedimento.
class _SceltaModello extends StatefulWidget {
  const _SceltaModello();

  @override
  State<_SceltaModello> createState() => _SceltaModelloState();
}

class _SceltaModelloState extends State<_SceltaModello> {
  late final Future<List<dynamic>> _modelli =
      apiDi(context).get('/api/v1/modelli').then((v) => v as List);

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Che atto vuoi redigere?'),
      content: SizedBox(
        width: 560,
        child: FutureBuilder<List<dynamic>>(
          future: _modelli,
          builder: (context, s) {
            if (s.hasError) return Text(s.error.toString());
            if (!s.hasData) return const LinearProgressIndicator();
            final modelli = s.data!.cast<Map<String, dynamic>>();
            if (modelli.isEmpty) {
              return const Text('Nessun modello di atto disponibile: chiedi all\'amministratore '
                  'di caricarne uno.');
            }
            final gruppi = <String, List<Map<String, dynamic>>>{};
            for (final m in modelli) {
              gruppi.putIfAbsent(m['provvedimento'] as String, () => []).add(m);
            }
            return ListView(shrinkWrap: true, children: [
              for (final g in gruppi.entries) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 8, bottom: 4),
                  child: Text(g.key, style: Theme.of(context).textTheme.titleSmall),
                ),
                for (final m in g.value)
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.description_outlined),
                      title: Text(m['titolo'] as String),
                      subtitle: Text([
                        if (m['tipologia_descrizione'] != null) m['tipologia_descrizione'],
                        if (m['descrizione'] != null) m['descrizione'],
                      ].join(' · ')),
                      onTap: () => Navigator.pop(context, m),
                    ),
                  ),
              ],
            ]);
          },
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
      ],
    );
  }
}
