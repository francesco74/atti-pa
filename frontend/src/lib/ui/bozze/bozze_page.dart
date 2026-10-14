import 'package:flutter/material.dart';

import '../comuni.dart';
import 'bozza_editor_page.dart';

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

  Future<void> _apri([String? id]) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => BozzaEditorPage(bozzaId: id)));
    _carica();
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
        onPressed: () => _apri(),
        icon: const Icon(Icons.add),
        label: const Text('Nuova determina'),
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
                  ? const Center(child: Text('Nessuna bozza. Crea la prima determina.'))
                  : ListView.separated(
                      itemCount: bozze.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, i) {
                        final b = bozze[i] as Map<String, dynamic>;
                        return ListTile(
                          leading: const Icon(Icons.description_outlined),
                          title: Text(b['oggetto'].toString(),
                              maxLines: 2, overflow: TextOverflow.ellipsis),
                          subtitle: Text('${b['tipologia_atto']} · '
                              'adozione prevista ${formatData(b['data_adozione_prevista'])} · '
                              'modificata ${formatData(b['updated_at'])}'),
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
