import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../comuni.dart';
import 'atto_page.dart';

/// Elenco dei controlli: ogni controllo è un atto con il suo audit.
class ControlliPage extends StatefulWidget {
  const ControlliPage({super.key});

  @override
  State<ControlliPage> createState() => _ControlliPageState();
}

class _ControlliPageState extends State<ControlliPage> {
  late Future<List<dynamic>> _controlli;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _controlli = apiDi(context).get('/api/v1/controllo/controlli').then((v) => v as List);
      });

  Future<void> _nuovo() async {
    final api = apiDi(context);
    final List<Map<String, dynamic>> tipologie;
    try {
      tipologie = List<Map<String, dynamic>>.from(await api.get('/api/v1/tipologie') as List);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
      return;
    }
    if (!mounted) return;
    final titolo = TextEditingController();
    PlatformFile? file;
    DateTime? data;
    String? tipologia;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: const Text('Nuovo controllo'),
          content: SizedBox(
            width: 480,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(
                controller: titolo,
                autofocus: true,
                onChanged: (_) => aggiorna(() {}),
                decoration: const InputDecoration(labelText: 'Titolo', hintText: 'DD n. 123/2026 - Settore Lavori pubblici'),
              ),
              const SizedBox(height: 8),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.attach_file),
                title: Text(file?.name ?? 'Atto da controllare (PDF, ODT, DOCX o DOC)'),
                trailing: TextButton(
                  onPressed: () async {
                    final scelto = await FilePicker.pickFile(
                      type: FileType.custom,
                      allowedExtensions: ['pdf', 'odt', 'docx', 'doc'],
                    );
                    if (scelto != null) aggiorna(() => file = scelto);
                  },
                  child: Text(file == null ? 'Scegli' : 'Cambia'),
                ),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.calendar_month),
                title: Text(data == null
                    ? 'Data di adozione dell\'atto'
                    : 'Adottato il ${formatData(isoData(data!))}'),
                subtitle: const Text('Le norme sono verificate al testo vigente in questa data'),
                onTap: () async {
                  final d = await scegliData(c, data);
                  if (d != null) aggiorna(() => data = d);
                },
              ),
              DropdownButtonFormField<String?>(
                initialValue: tipologia,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Tipologia (sceglie la checklist)'),
                items: [
                  const DropdownMenuItem<String?>(value: null, child: Text('Non indicata')),
                  for (final t in tipologie)
                    DropdownMenuItem<String?>(
                        value: t['codice'] as String, child: Text(t['descrizione'] as String)),
                ],
                onChanged: (v) => aggiorna(() => tipologia = v),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(
              onPressed: titolo.text.trim().length >= 3 && file != null && data != null
                  ? () => Navigator.pop(c, true)
                  : null,
              child: const Text('Crea e analizza'),
            ),
          ],
        ),
      ),
    );
    try {
      if (ok != true || file == null || data == null || !mounted) return;
      final bytes = await file!.readAsBytes();
      if (!mounted) return;
      final controllo = await api.postMultipart(
        '/api/v1/controllo/controlli',
        campi: {
          'titolo': titolo.text.trim(),
          'data_adozione': isoData(data!),
          if (tipologia != null) 'tipologia_atto': tipologia!,
        },
        campoFile: 'file',
        bytes: bytes,
        nomeFile: file!.name,
      ) as Map<String, dynamic>;
      if (!mounted) return;
      await _apri(controllo);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      titolo.dispose();
      _carica();
    }
  }

  Future<void> _apri(Map<String, dynamic> controllo) async {
    final atto = controllo['atto'] as Map<String, dynamic>?;
    if (atto == null) return;
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => AttoPage(attoId: atto['id'] as String, titolo: controllo['titolo'] as String),
    ));
    _carica();
  }

  Future<void> _elimina(Map<String, dynamic> controllo) async {
    if (!await conferma(context, 'Eliminare il controllo?',
        'Saranno eliminati l\'atto "${controllo['titolo']}" e le sue verifiche.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('/api/v1/controllo/controlli/${controllo['id']}');
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _nuovo,
        icon: const Icon(Icons.add),
        label: const Text('Nuovo controllo'),
      ),
      body: Caricamento<List<dynamic>>(
        future: _controlli,
        riprova: _carica,
        builder: (context, controlli) => controlli.isEmpty
            ? const Center(child: Text('Nessun controllo. Crea il primo con "Nuovo controllo".'))
            : ListView(padding: const EdgeInsets.all(16), children: [
                for (final c in controlli.cast<Map<String, dynamic>>()) _riga(c),
              ]),
      ),
    );
  }

  Widget _riga(Map<String, dynamic> c) {
    final atto = c['atto'] as Map<String, dynamic>?;
    final stato = atto?['stato']?.toString();
    return Card(
      child: ListTile(
        leading: Icon(stato == 'CHIUSO' ? Icons.verified : Icons.fact_check),
        title: Text(c['titolo'].toString()),
        subtitle: Text(atto == null
            ? 'Nessun atto'
            : '${atto['file_nome']} · adottato il ${formatData(atto['data_adozione'])}'),
        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
          if (stato != null) Chip(label: Text(statiAtto[stato] ?? stato)),
          if (stato != 'CHIUSO')
            IconButton(
              tooltip: 'Elimina',
              icon: const Icon(Icons.delete_outline),
              onPressed: () => _elimina(c),
            ),
        ]),
        onTap: () => _apri(c),
      ),
    );
  }
}
