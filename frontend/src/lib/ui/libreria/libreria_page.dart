import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../bozze/scelta_riferimenti.dart' show tipiAtto;
import '../comuni.dart';

class LibreriaPage extends StatelessWidget {
  const LibreriaPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const DefaultTabController(
      length: 3,
      child: Column(children: [
        TabBar(tabs: [
          Tab(icon: Icon(Icons.bookmarks_outlined), text: 'Riferimenti'),
          Tab(icon: Icon(Icons.library_books_outlined), text: 'Norme'),
          Tab(icon: Icon(Icons.search), text: 'Consulta articolo'),
        ]),
        Expanded(
          child: TabBarView(children: [_Riferimenti(), _Norme(), ConsultaArticolo()]),
        ),
      ]),
    );
  }
}

class _Riferimenti extends StatefulWidget {
  const _Riferimenti();

  @override
  State<_Riferimenti> createState() => _RiferimentiState();
}

class _RiferimentiState extends State<_Riferimenti> {
  late Future<List<dynamic>> _lista;
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

  void _carica() => setState(() {
        _lista = apiDi(context)
            .get('/api/v1/riferimenti', query: {'q': _cerca.text.trim()}).then((v) => v as List);
      });

  @override
  Widget build(BuildContext context) {
    final utente = context.watch<AuthState>().utente!;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(children: [
        TextField(
          controller: _cerca,
          decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Cerca'),
          onSubmitted: (_) => _carica(),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: Caricamento<List<dynamic>>(
            future: _lista,
            riprova: _carica,
            builder: (context, lista) => lista.isEmpty
                ? const Center(
                    child: Text('Nessun riferimento. Aggiungili dalla scheda "Consulta articolo".'))
                : ListView(children: [
                    for (final r in lista.cast<Map<String, dynamic>>())
                      ListTile(
                        leading: Icon(r['owner_id'] == null ? Icons.groups : Icons.person),
                        title: Text(r['citazione'].toString()),
                        subtitle: Text([
                          if ((r['tipologie_atto'] as List?)?.isNotEmpty ?? false)
                            (r['tipologie_atto'] as List).join(', '),
                          if (r['note'] != null) r['note'],
                        ].join(' · ')),
                        trailing: (r['owner_id'] == utente.id || utente.isAdmin)
                            ? IconButton(
                                icon: const Icon(Icons.delete_outline),
                                onPressed: () async {
                                  if (!await conferma(context, 'Eliminare il riferimento?',
                                      r['citazione'].toString())) {
                                    return;
                                  }
                                  if (!context.mounted) return;
                                  try {
                                    await apiDi(context).delete('/api/v1/riferimenti/${r['id']}');
                                    _carica();
                                  } catch (e) {
                                    if (context.mounted) mostraErrore(context, e);
                                  }
                                },
                              )
                            : null,
                      ),
                  ]),
          ),
        ),
      ]),
    );
  }
}

class _Norme extends StatefulWidget {
  const _Norme();

  @override
  State<_Norme> createState() => _NormeState();
}

class _NormeState extends State<_Norme> {
  late Future<List<dynamic>> _lista;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _lista = apiDi(context).get('/api/v1/norme').then((v) => v as List);
      });

  Future<void> _aggiungi() async {
    String tipo = 'decreto legislativo';
    DateTime? data;
    final numero = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: const Text('Aggiungi norma'),
          content: SizedBox(
            width: 420,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<String>(
                value: tipo,
                decoration: const InputDecoration(labelText: 'Tipo'),
                items: [
                  for (final e in tipiAtto.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
                ],
                onChanged: (v) => aggiorna(() => tipo = v ?? tipo),
              ),
              const SizedBox(height: 12),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(data == null ? 'Data del provvedimento' : formatData(isoData(data!))),
                trailing: const Icon(Icons.calendar_month),
                onTap: () async {
                  final d = await scegliData(c, data);
                  if (d != null) aggiorna(() => data = d);
                },
              ),
              TextField(controller: numero, decoration: const InputDecoration(labelText: 'Numero')),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Verifica e aggiungi')),
          ],
        ),
      ),
    );
    if (ok != true || data == null || !mounted) return;
    try {
      await apiDi(context).post('/api/v1/norme', {
        'tipo': tipo,
        'data': isoData(data!),
        'numero': numero.text.trim(),
      });
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      numero.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _aggiungi,
        icon: const Icon(Icons.add),
        label: const Text('Aggiungi norma'),
      ),
      body: Caricamento<List<dynamic>>(
        future: _lista,
        riprova: _carica,
        builder: (context, lista) => ListView(padding: const EdgeInsets.all(16), children: [
          for (final n in lista.cast<Map<String, dynamic>>())
            ListTile(
              leading: const Icon(Icons.gavel),
              title: Text(n['citazione'].toString()),
              subtitle: n['titolo'] != null ? Text(n['titolo'].toString()) : null,
              trailing: IconButton(
                tooltip: 'Consulta',
                icon: const Icon(Icons.open_in_new),
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => Scaffold(
                    appBar: AppBar(title: Text(n['citazione'].toString())),
                    body: ConsultaArticolo(urnAtto: n['urn'] as String),
                  ),
                )),
              ),
            ),
        ]),
      ),
    );
  }
}

/// Testo di un articolo alla data, con salvataggio di commi e lettere come riferimenti.
class ConsultaArticolo extends StatefulWidget {
  const ConsultaArticolo({super.key, this.urnAtto});

  final String? urnAtto;

  @override
  State<ConsultaArticolo> createState() => _ConsultaArticoloState();
}

class _ConsultaArticoloState extends State<ConsultaArticolo> {
  final _urn = TextEditingController();
  final _articolo = TextEditingController();
  DateTime _data = DateTime.now();
  Future<Map<String, dynamic>>? _risultato;

  @override
  void initState() {
    super.initState();
    _urn.text = widget.urnAtto ?? '';
  }

  @override
  void dispose() {
    _urn.dispose();
    _articolo.dispose();
    super.dispose();
  }

  void _cerca() {
    if (_urn.text.trim().isEmpty || _articolo.text.trim().isEmpty) return;
    setState(() {
      _risultato = apiDi(context).get('/api/v1/norme/articolo', query: {
        'urn': '${_urn.text.trim()}~art${_articolo.text.trim()}',
        'data': isoData(_data),
      }).then((v) => v as Map<String, dynamic>);
    });
  }

  Future<void> _salvaRiferimento(Map<String, dynamic> art, String? comma, String? lettera) async {
    final utente = context.read<AuthState>().utente!;
    final note = TextEditingController();
    var condiviso = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: const Text('Salva come riferimento'),
          content: SizedBox(
            width: 420,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('art. ${art['articolo']}${comma != null ? ', comma $comma' : ''}'
                  '${lettera != null ? ', lett. $lettera)' : ''}, del ${art['citazione_atto']}'),
              const SizedBox(height: 12),
              TextField(controller: note, decoration: const InputDecoration(labelText: 'Nota (facoltativa)')),
              if (utente.isAdmin)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: condiviso,
                  title: const Text('Condividi con tutti gli utenti'),
                  onChanged: (v) => aggiorna(() => condiviso = v ?? false),
                ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Salva')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await apiDi(context).post('/api/v1/riferimenti', {
        'urn_atto': art['urn_atto'],
        'articolo': art['articolo'],
        'comma': comma,
        'lettera': lettera,
        'note': note.text.trim().isEmpty ? null : note.text.trim(),
        'condiviso': condiviso,
      });
      if (mounted) mostraMessaggio(context, 'Riferimento salvato in libreria');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      note.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.all(16), children: [
      Wrap(spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(
          width: 420,
          child: TextField(
            controller: _urn,
            decoration: const InputDecoration(
              labelText: 'URN dell\'atto',
              hintText: 'urn:nir:stato:decreto.legislativo:2023-03-31;36',
            ),
          ),
        ),
        SizedBox(
          width: 120,
          child: TextField(
            controller: _articolo,
            decoration: const InputDecoration(labelText: 'Articolo'),
            onSubmitted: (_) => _cerca(),
          ),
        ),
        OutlinedButton.icon(
          onPressed: () async {
            final d = await scegliData(context, _data);
            if (d != null) setState(() => _data = d);
          },
          icon: const Icon(Icons.calendar_month),
          label: Text('Vigente al ${formatData(isoData(_data))}'),
        ),
        FilledButton.icon(onPressed: _cerca, icon: const Icon(Icons.search), label: const Text('Mostra')),
      ]),
      const SizedBox(height: 16),
      if (_risultato != null)
        Caricamento<Map<String, dynamic>>(
          future: _risultato!,
          riprova: _cerca,
          builder: (context, art) {
            final commi = List<Map<String, dynamic>>.from(
                (art['struttura'] as Map<String, dynamic>)['commi'] as List);
            return Sezione(
              titolo: 'Art. ${art['articolo']} — ${art['citazione_atto']}',
              azioni: [
                IconButton(
                  tooltip: 'Salva l\'intero articolo',
                  icon: const Icon(Icons.bookmark_add_outlined),
                  onPressed: () => _salvaRiferimento(art, null, null),
                ),
              ],
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (art['rubrica'] != null)
                  Text(art['rubrica'].toString(), style: const TextStyle(fontStyle: FontStyle.italic)),
                Text('Testo vigente dal ${formatData(art['vigenza_inizio'])}'
                    '${art['vigenza_fine'] != null ? ' al ${formatData(art['vigenza_fine'])}' : ''}'),
                const Divider(),
                for (final c in commi) ...[
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Expanded(
                      child: SelectableText('${c['numero']}. ${c['alinea'] ?? c['testo']}'),
                    ),
                    IconButton(
                      tooltip: 'Salva comma ${c['numero']}',
                      icon: const Icon(Icons.bookmark_add_outlined, size: 20),
                      onPressed: () => _salvaRiferimento(art, c['numero'] as String, null),
                    ),
                  ]),
                  for (final l in List<Map<String, dynamic>>.from(c['lettere'] as List? ?? []))
                    Padding(
                      padding: const EdgeInsets.only(left: 24),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Expanded(child: SelectableText('${l['lettera']}) ${l['testo']}')),
                        IconButton(
                          tooltip: 'Salva lettera ${l['lettera']})',
                          icon: const Icon(Icons.bookmark_add_outlined, size: 18),
                          onPressed: () =>
                              _salvaRiferimento(art, c['numero'] as String, l['lettera'] as String),
                        ),
                      ]),
                    ),
                  const SizedBox(height: 8),
                ],
                const Divider(),
                Text(art['fonte'].toString(), style: Theme.of(context).textTheme.bodySmall),
              ]),
            );
          },
        ),
    ]);
  }
}
