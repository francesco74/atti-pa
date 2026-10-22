import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../util/download.dart';
import '../comuni.dart';

/// Pacchetti di modelli, specificità e checklist: il database comanda. Si carica un
/// pacchetto (zip), si guarda cosa cambia rispetto all'ente oggetto per oggetto, si decide
/// e si importa. L'esportazione scarica tutto ciò che è attivo come pacchetto.
class PacchettiPage extends StatefulWidget {
  const PacchettiPage({super.key});

  @override
  State<PacchettiPage> createState() => _PacchettiPageState();
}

const _stati = {
  'NUOVO': ('Nuovo', Icons.add_circle_outline),
  'AGGIORNABILE': ('Aggiornabile', Icons.system_update_alt),
  'CONFLITTO': ('Conflitto', Icons.call_split),
  'INVARIATO': ('Invariato', Icons.check),
  'ALLINEATO': ('Già allineato', Icons.check),
  'DISATTIVATO': ('Disattivato dall\'ente', Icons.block),
  'RIMOSSO': ('Tolto dallo standard', Icons.remove_circle_outline),
};

const _azioni = {
  'applica': 'Applica lo standard',
  'mantieni': 'Mantieni la versione dell\'ente',
  'disattiva': 'Disattiva',
};

const _tipi = {'modello': 'Modello', 'modulo': 'Specificità', 'checklist': 'Checklist'};

class _PacchettiPageState extends State<PacchettiPage> {
  late Future<List<dynamic>> _pacchetti;
  bool _vuoto = false; // nessun modello, specificità o checklist: sistema appena installato
  Map<String, dynamic>? _analisi; // pacchetto caricato e analizzato, in attesa di decisione
  final Map<String, String> _decisioni = {};
  bool _mostraInvariati = false;
  bool _inCorso = false;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() {
    final api = apiDi(context);
    setState(() {
      _pacchetti = api.get('/api/v1/pacchetti').then((v) => v as List);
    });
    api.get('/api/v1/configurazione').then((v) {
      final e = v as Map<String, dynamic>;
      final vuoto = ['modelli', 'moduli', 'checklist'].every((k) => (e[k] as List).isEmpty);
      if (mounted) setState(() => _vuoto = vuoto);
    }).catchError((_) {});
  }

  Future<void> _caricaPacchetto() async {
    final file = await FilePicker.pickFile(type: FileType.custom, allowedExtensions: ['zip']);
    if (file == null || !mounted) return;
    setState(() => _inCorso = true);
    try {
      final analisi = await apiDi(context).postMultipart(
        '/api/v1/pacchetti',
        campi: {},
        campoFile: 'file',
        bytes: await file.readAsBytes(),
        nomeFile: file.name,
      ) as Map<String, dynamic>;
      setState(() {
        _analisi = analisi;
        _decisioni.clear();
      });
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _inCorso = false);
    }
  }

  Future<void> _importa() async {
    final analisi = _analisi!;
    if (!await conferma(context, 'Importare il pacchetto?',
        'Gli oggetti da applicare ricevono una nuova versione; bozze e verifiche già fatte '
            'restano legate alla versione usata.')) {
      return;
    }
    if (!mounted) return;
    setState(() => _inCorso = true);
    try {
      final r = await apiDi(context).post(
        '/api/v1/pacchetti/${analisi['id']}/importa',
        {'decisioni': _decisioni},
      ) as Map<String, dynamic>;
      if (!mounted) return;
      final resoconto = Map<String, dynamic>.from(r['resoconto_json'] as Map);
      setState(() => _analisi = null);
      _carica();
      await _mostraResoconto(resoconto);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _inCorso = false);
    }
  }

  Future<void> _annulla() async {
    final id = _analisi!['id'];
    try {
      await apiDi(context).delete('/api/v1/pacchetti/$id');
    } catch (_) {}
    if (!mounted) return;
    setState(() => _analisi = null);
    _carica();
  }

  Future<void> _mostraResoconto(Map<String, dynamic> r) {
    List<String> lista(String k) => List<String>.from(r[k] as List? ?? const []);
    return showDialog<void>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Importato: ${r['pacchetto']}'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text('${lista('applicati').length} applicati, ${lista('mantenuti').length} mantenuti, '
                  '${lista('disattivati').length} disattivati.'),
              for (final (titolo, chiave) in [('Errori', 'errori'), ('Incoerenze tra modelli e checklist', 'avvisi')])
                if (lista(chiave).isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(titolo, style: Theme.of(c).textTheme.titleSmall),
                  for (final riga in lista(chiave)) Text('• $riga'),
                ],
            ]),
          ),
        ),
        actions: [FilledButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
      ),
    );
  }

  Widget _tabellaAnalisi() {
    final analisi = _analisi!;
    final voci = List<Map<String, dynamic>>.from(analisi['analisi_json'] as List);
    final daDecidere = voci.where((v) => (v['azioni'] as List).length > 1 || v['stato'] != 'INVARIATO');
    final mostrate = _mostraInvariati
        ? voci
        : voci.where((v) => !['INVARIATO', 'ALLINEATO'].contains(v['stato'])).toList();
    final tema = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('${analisi['nome']} ${analisi['versione']}', style: tema.textTheme.titleMedium),
          if (analisi['descrizione'] != null) Text(analisi['descrizione'] as String),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 4, children: [
            for (final s in _stati.keys)
              if (voci.any((v) => v['stato'] == s))
                Chip(
                  avatar: Icon(_stati[s]!.$2, size: 16),
                  label: Text('${_stati[s]!.$1}: ${voci.where((v) => v['stato'] == s).length}'),
                ),
          ]),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Mostra anche gli oggetti invariati'),
            value: _mostraInvariati,
            onChanged: (v) => setState(() => _mostraInvariati = v),
          ),
          if (mostrate.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text('Nessuna differenza rispetto all\'ente: il pacchetto non cambia nulla.'),
            ),
          for (final v in mostrate)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(_stati[v['stato']]?.$2 ?? Icons.help_outline,
                  color: v['stato'] == 'CONFLITTO' ? tema.colorScheme.error : null),
              title: Text('${_tipi[v['tipo']] ?? v['tipo']}: ${v['titolo']}'),
              subtitle: Text('${v['codice']} · ${_stati[v['stato']]?.$1 ?? v['stato']}'
                  '${v['versione_ente'] != null ? ' · versione dell\'ente v${v['versione_ente']}' : ''}\n'
                  '${v['nota']}'),
              isThreeLine: true,
              trailing: (v['azioni'] as List).length < 2
                  ? null
                  : DropdownButton<String>(
                      value: _decisioni[v['chiave']] ?? v['azione'] as String,
                      items: [
                        for (final a in List<String>.from(v['azioni'] as List))
                          DropdownMenuItem(value: a, child: Text(_azioni[a] ?? a)),
                      ],
                      onChanged: (a) => setState(() => _decisioni[v['chiave'] as String] = a!),
                    ),
            ),
          const SizedBox(height: 12),
          Wrap(spacing: 8, children: [
            FilledButton.icon(
              onPressed: _inCorso || daDecidere.isEmpty ? null : _importa,
              icon: const Icon(Icons.download_done),
              label: const Text('Importa'),
            ),
            OutlinedButton(onPressed: _inCorso ? null : _annulla, child: const Text('Annulla')),
          ]),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text(
        'Modelli di atto, specificità e checklist si modificano nell\'app: comanda il database. '
        'I pacchetti portano i contenuti standard: caricandone uno si vede, oggetto per oggetto, '
        'cosa cambia rispetto all\'ente e si sceglie cosa aggiornare. Le versioni modificate '
        'dall\'ente non vengono mai sostituite senza una scelta esplicita.',
        style: tema.textTheme.bodyMedium,
      ),
      if (_vuoto && _analisi == null) ...[
        const SizedBox(height: 12),
        Card(
          color: tema.colorScheme.primaryContainer,
          child: const ListTile(
            leading: Icon(Icons.rocket_launch_outlined),
            title: Text('Nessun modello installato'),
            subtitle: Text('Per cominciare carica il pacchetto standard fornito con l\'installazione '
                '(atti-pa-modelli-<versione>.zip): tutti gli oggetti risultano nuovi e si importano '
                'con "Importa". Dopo potrai modificarli in "Modelli e checklist".'),
          ),
        ),
      ],
      const SizedBox(height: 12),
      Wrap(spacing: 8, runSpacing: 8, children: [
        FilledButton.icon(
          onPressed: _inCorso || _analisi != null ? null : _caricaPacchetto,
          icon: _inCorso
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.upload_file),
          label: const Text('Carica un pacchetto (.zip)'),
        ),
        OutlinedButton.icon(
          onPressed: () => salvaFile(apiDi(context), '/api/v1/pacchetti/esporta', 'configurazione.zip'),
          icon: const Icon(Icons.archive_outlined),
          label: const Text('Esporta la configurazione dell\'ente'),
        ),
      ]),
      const SizedBox(height: 16),
      if (_analisi != null) _tabellaAnalisi(),
      const SizedBox(height: 16),
      Text('Pacchetti caricati', style: tema.textTheme.titleMedium),
      Caricamento<List<dynamic>>(
        future: _pacchetti,
        riprova: _carica,
        builder: (context, lista) => Column(children: [
          if (lista.isEmpty) const ListTile(title: Text('Nessun pacchetto.')),
          for (final p in lista.cast<Map<String, dynamic>>())
            ListTile(
              leading: Icon(p['stato'] == 'IMPORTATO' ? Icons.inventory_2_outlined : Icons.hourglass_empty),
              title: Text('${p['nome']} ${p['versione']}'),
              subtitle: Text([
                switch (p['stato']) {
                  'IMPORTATO' => 'importato il ${formatData(p['importato_il'])}',
                  'ANNULLATO' => 'annullato',
                  _ => 'analizzato, non importato',
                },
                if (p['resoconto_json'] != null)
                  '${(p['resoconto_json']['applicati'] as List).length} oggetti applicati',
              ].join(' · ')),
              trailing: p['resoconto_json'] == null
                  ? null
                  : IconButton(
                      tooltip: 'Resoconto',
                      icon: const Icon(Icons.info_outline),
                      onPressed: () => _mostraResoconto(Map<String, dynamic>.from(p['resoconto_json'] as Map)),
                    ),
            ),
        ]),
      ),
    ]);
  }
}
