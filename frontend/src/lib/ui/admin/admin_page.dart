import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../util/download.dart';
import '../comuni.dart';
import 'checklist_editor.dart';

class AdminPage extends StatelessWidget {
  const AdminPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const DefaultTabController(
      length: 3,
      child: Column(children: [
        TabBar(tabs: [
          Tab(icon: Icon(Icons.checklist), text: 'Checklist'),
          Tab(icon: Icon(Icons.article_outlined), text: 'Template'),
          Tab(icon: Icon(Icons.sync), text: 'Aggiornamenti Normattiva'),
        ]),
        Expanded(child: TabBarView(children: [_Checklist(), _Template(), _Aggiornamenti()])),
      ]),
    );
  }
}

// --- Checklist -----------------------------------------------------------------------

class _Checklist extends StatefulWidget {
  const _Checklist();

  @override
  State<_Checklist> createState() => _ChecklistState();
}

class _ChecklistState extends State<_Checklist> {
  late Future<List<dynamic>> _lista;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _lista = apiDi(context).get('/api/v1/checklists').then((v) => v as List);
      });

  Future<void> _apri([Map<String, dynamic>? esistente]) async {
    final salvata = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => ChecklistEditorPage(esistente: esistente)),
    );
    if (salvata == true) _carica();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _apri(),
        icon: const Icon(Icons.add),
        label: const Text('Nuova checklist'),
      ),
      body: Caricamento<List<dynamic>>(
        future: _lista,
        riprova: _carica,
        builder: (context, lista) => ListView(padding: const EdgeInsets.all(16), children: [
          if (lista.isEmpty) const Text('Nessuna checklist attiva.'),
          for (final c in lista.cast<Map<String, dynamic>>())
            Card(
              child: ListTile(
                title: Text('${c['titolo']} (v${c['versione']})'),
                subtitle: Text('${c['codice']} · ${c['tipologia_atto']} · '
                    '${(c['elementi'] as List).length} criteri'),
                trailing: IconButton(
                  tooltip: 'Disattiva',
                  icon: const Icon(Icons.archive_outlined),
                  onPressed: () async {
                    if (!await conferma(context, 'Disattivare la checklist?',
                        'Le verifiche già eseguite restano consultabili.')) {
                      return;
                    }
                    if (!context.mounted) return;
                    try {
                      await apiDi(context).delete('/api/v1/checklists/codice/${c['codice']}');
                      _carica();
                    } catch (e) {
                      if (context.mounted) mostraErrore(context, e);
                    }
                  },
                ),
                onTap: () => _apri(c),
              ),
            ),
        ]),
      ),
    );
  }
}

// --- Template ------------------------------------------------------------------------

class _Template extends StatefulWidget {
  const _Template();

  @override
  State<_Template> createState() => _TemplateState();
}

class _TemplateState extends State<_Template> {
  late Future<List<dynamic>> _lista;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _lista = apiDi(context).get('/api/v1/templates').then((v) => v as List);
      });

  Future<void> _caricaTemplate() async {
    final api = apiDi(context);
    final tipologie = List<Map<String, dynamic>>.from(await api.get('/api/v1/tipologie') as List);
    final file = await FilePicker.platform
        .pickFiles(type: FileType.custom, allowedExtensions: ['odt'], withData: true);
    final scelto = file?.files.single;
    if (scelto == null || scelto.bytes == null || !mounted) return;
    final nome = TextEditingController(text: scelto.name.replaceAll('.odt', ''));
    String? tipologia;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: const Text('Nuovo template'),
          content: SizedBox(
            width: 460,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Text('Nel documento usa segnaposto come {{ premesse }} o {{ cig }}. '
                  'Sono disponibili anche {{ oggetto }}, {{ data_adozione }} e '
                  '{{ riferimenti_normativi }}. Caricando un template con lo stesso nome '
                  'si crea una nuova versione.'),
              const SizedBox(height: 12),
              TextField(controller: nome, decoration: const InputDecoration(labelText: 'Nome')),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: tipologia,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Tipologia di atto'),
                items: [
                  for (final t in tipologie)
                    DropdownMenuItem(value: t['codice'] as String, child: Text(t['descrizione'] as String)),
                ],
                onChanged: (v) => aggiorna(() => tipologia = v),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Carica')),
          ],
        ),
      ),
    );
    if (ok != true || tipologia == null || !mounted) return;
    try {
      final t = await api.postMultipart(
        '/api/v1/templates',
        campi: {'nome': nome.text.trim(), 'tipologia_atto': tipologia!},
        campoFile: 'file',
        bytes: scelto.bytes!,
        nomeFile: scelto.name,
      );
      _carica();
      if (mounted) await _modificaCampi(t as Map<String, dynamic>);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      nome.dispose();
    }
  }

  Future<void> _modificaCampi(Map<String, dynamic> t) async {
    final campi = List<Map<String, dynamic>>.from(
        (t['campi_json'] as List).map((c) => Map<String, dynamic>.from(c as Map)));
    final etichette = [for (final c in campi) TextEditingController(text: c['etichetta'] as String)];
    final aiuti = [for (final c in campi) TextEditingController(text: (c['aiuto'] ?? '') as String)];
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: Text('Campi del wizard · ${t['nome']}'),
          content: SizedBox(
            width: 760,
            height: 480,
            child: ListView(children: [
              for (var i = 0; i < campi.length; i++)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Row(children: [
                    SizedBox(width: 140, child: Text('{{ ${campi[i]['nome']} }}')),
                    Expanded(
                      child: TextField(
                          controller: etichette[i],
                          decoration: const InputDecoration(labelText: 'Etichetta', isDense: true)),
                    ),
                    const SizedBox(width: 8),
                    SizedBox(
                      width: 140,
                      child: DropdownButtonFormField<String>(
                        value: campi[i]['tipo'] as String,
                        isDense: true,
                        decoration: const InputDecoration(labelText: 'Tipo', isDense: true),
                        items: const [
                          DropdownMenuItem(value: 'testo', child: Text('Testo')),
                          DropdownMenuItem(value: 'testo_lungo', child: Text('Testo lungo')),
                          DropdownMenuItem(value: 'data', child: Text('Data')),
                          DropdownMenuItem(value: 'importo', child: Text('Importo')),
                          DropdownMenuItem(value: 'numero', child: Text('Numero')),
                        ],
                        onChanged: (v) => aggiorna(() => campi[i]['tipo'] = v),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextField(
                          controller: aiuti[i],
                          decoration: const InputDecoration(labelText: 'Aiuto', isDense: true)),
                    ),
                    Checkbox(
                      value: campi[i]['obbligatorio'] as bool? ?? true,
                      onChanged: (v) => aggiorna(() => campi[i]['obbligatorio'] = v ?? true),
                    ),
                    const Text('obbl.'),
                  ]),
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
    if (ok == true && mounted) {
      try {
        await apiDi(context).put('/api/v1/templates/${t['id']}/campi', {
          'campi': [
            for (var i = 0; i < campi.length; i++)
              {
                'nome': campi[i]['nome'],
                'etichetta': etichette[i].text.trim(),
                'tipo': campi[i]['tipo'],
                'obbligatorio': campi[i]['obbligatorio'] ?? true,
                'aiuto': aiuti[i].text.trim().isEmpty ? null : aiuti[i].text.trim(),
              },
          ],
        });
        _carica();
      } catch (e) {
        if (mounted) mostraErrore(context, e);
      }
    }
    for (final c in [...etichette, ...aiuti]) {
      c.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _caricaTemplate,
        icon: const Icon(Icons.upload_file),
        label: const Text('Carica template .odt'),
      ),
      body: Caricamento<List<dynamic>>(
        future: _lista,
        riprova: _carica,
        builder: (context, lista) => ListView(padding: const EdgeInsets.all(16), children: [
          if (lista.isEmpty) const Text('Nessun template attivo.'),
          for (final t in lista.cast<Map<String, dynamic>>())
            Card(
              child: ListTile(
                title: Text('${t['nome']} (v${t['versione']})'),
                subtitle: Text('${t['tipologia_atto']} · ${(t['campi_json'] as List).length} campi'),
                onTap: () => _modificaCampi(t),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(
                    tooltip: 'Scarica',
                    icon: const Icon(Icons.download),
                    onPressed: () => salvaFile(
                        apiDi(context), '/api/v1/templates/${t['id']}/file', t['file_nome'].toString()),
                  ),
                  IconButton(
                    tooltip: 'Disattiva',
                    icon: const Icon(Icons.archive_outlined),
                    onPressed: () async {
                      try {
                        await apiDi(context).delete('/api/v1/templates/${t['id']}');
                        _carica();
                      } catch (e) {
                        if (context.mounted) mostraErrore(context, e);
                      }
                    },
                  ),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}

// --- Aggiornamenti Normattiva --------------------------------------------------------

class _Aggiornamenti extends StatelessWidget {
  const _Aggiornamenti();

  @override
  Widget build(BuildContext context) {
    return Caricamento<dynamic>(
      future: apiDi(context).get('/api/v1/norme/aggiornamenti'),
      builder: (context, dati) {
        final lista = (dati as List).cast<Map<String, dynamic>>();
        if (lista.isEmpty) {
          return const Center(child: Text('Il job di aggiornamento non è ancora stato eseguito.'));
        }
        return ListView(padding: const EdgeInsets.all(16), children: [
          for (final s in lista)
            ListTile(
              leading: Icon(
                s['esito'] == 'OK' ? Icons.check_circle : Icons.warning,
                color: s['esito'] == 'OK' ? Colors.green : Colors.orange,
              ),
              title: Text('${formatData(s['eseguito_il'])} · ${s['esito']}'),
              subtitle: Text('${s['atti_modificati']} atti modificati, '
                  '${s['articoli_aggiornati']} articoli aggiornati'
                  '${s['dettaglio'] != null ? '\n${s['dettaglio']}' : ''}'),
            ),
        ]);
      },
    );
  }
}
