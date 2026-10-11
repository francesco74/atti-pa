import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../util/download.dart';
import '../comuni.dart';
import 'atto_page.dart';

const statiAtto = {
  'DA_ANALIZZARE': 'Da analizzare',
  'IN_ANALISI': 'In analisi',
  'ANALIZZATO': 'Da revisionare',
  'IN_REVISIONE': 'In revisione',
  'CHIUSO': 'Chiuso',
};

class SessionePage extends StatefulWidget {
  const SessionePage({super.key, required this.sessioneId});

  final String sessioneId;

  @override
  State<SessionePage> createState() => _SessionePageState();
}

class _SessionePageState extends State<SessionePage> {
  late Future<List<dynamic>> _dati;
  bool _soloMiei = false;
  List<Map<String, dynamic>> _tipologie = [];

  String get _base => '/api/v1/controllo/sessioni/${widget.sessioneId}';

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        final api = apiDi(context);
        _dati = Future.wait([
          api.get(_base),
          api.get('$_base/atti', query: {'solo_miei': _soloMiei.toString()}),
          api.get('/api/v1/tipologie'),
        ]);
      });

  Future<void> _sorteggio(Map<String, dynamic> sessione) async {
    final elenco = TextEditingController();
    final percentuale = TextEditingController(text: '10');
    final seme = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Sorteggio degli atti'),
        content: SizedBox(
          width: 520,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
              controller: elenco,
              maxLines: 8,
              decoration: const InputDecoration(
                labelText: 'Numeri di registro degli atti del periodo',
                hintText: 'Uno per riga (anche incollati da un foglio di calcolo)',
              ),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(
                  child: TextField(
                      controller: percentuale,
                      decoration: const InputDecoration(labelText: 'Percentuale', suffixText: '%'))),
              const SizedBox(width: 12),
              Expanded(
                  child: TextField(
                      controller: seme,
                      decoration: const InputDecoration(
                          labelText: 'Seme (facoltativo)', helperText: 'Per rendere ripetibile l\'estrazione'))),
            ]),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Estrai')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final numeri = elenco.text
          .split(RegExp(r'[\n;,\t]'))
          .map((s) => s.trim())
          .where((s) => s.isNotEmpty)
          .toList();
      final r = await apiDi(context).post('$_base/sorteggio', {
        'elenco': numeri,
        'percentuale': double.tryParse(percentuale.text.replaceAll(',', '.')) ?? 10,
        if (int.tryParse(seme.text) != null) 'seme': int.parse(seme.text),
      }) as Map<String, dynamic>;
      _carica();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text('Estratti ${(r['estratti'] as List).length} atti su ${r['atti_nel_periodo']}'),
          content: SelectableText('${(r['estratti'] as List).join('\n')}\n\nSeme: ${r['seme']}'),
          actions: [FilledButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
        ),
      );
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      elenco.dispose();
      percentuale.dispose();
      seme.dispose();
    }
  }

  Future<void> _caricaAtto() async {
    final file = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf', 'odt', 'docx', 'doc'],
      withData: true,
    );
    final scelto = file?.files.single;
    if (scelto == null || scelto.bytes == null || !mounted) return;

    final numero = TextEditingController();
    final settore = TextEditingController();
    final oggetto = TextEditingController();
    DateTime? data;
    String? tipologia;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: Text('Carica ${scelto.name}'),
          content: SizedBox(
            width: 480,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: numero, decoration: const InputDecoration(labelText: 'Numero di registro')),
              const SizedBox(height: 12),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(data == null
                    ? 'Data di adozione (obbligatoria)'
                    : 'Adottato il ${formatData(isoData(data!))}'),
                subtitle: const Text('Le norme sono verificate al testo vigente in questa data'),
                trailing: const Icon(Icons.calendar_month),
                onTap: () async {
                  final d = await scegliData(c, data);
                  if (d != null) aggiorna(() => data = d);
                },
              ),
              DropdownButtonFormField<String?>(
                value: tipologia,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Tipologia (sceglie la checklist)'),
                items: [
                  const DropdownMenuItem<String?>(value: null, child: Text('Non indicata')),
                  for (final t in _tipologie)
                    DropdownMenuItem<String?>(
                        value: t['codice'] as String, child: Text(t['descrizione'] as String)),
                ],
                onChanged: (v) => aggiorna(() => tipologia = v),
              ),
              const SizedBox(height: 12),
              TextField(controller: settore, decoration: const InputDecoration(labelText: 'Settore')),
              const SizedBox(height: 12),
              TextField(controller: oggetto, decoration: const InputDecoration(labelText: 'Oggetto')),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Carica e analizza')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    if (data == null) {
      mostraErrore(context, 'Indicare la data di adozione');
      return;
    }
    try {
      await apiDi(context).postMultipart(
        '$_base/atti',
        campi: {
          'data_adozione': isoData(data!),
          if (numero.text.trim().isNotEmpty) 'numero_registro': numero.text.trim(),
          if (settore.text.trim().isNotEmpty) 'settore': settore.text.trim(),
          if (oggetto.text.trim().isNotEmpty) 'oggetto': oggetto.text.trim(),
          if (tipologia != null) 'tipologia_atto': tipologia!,
        },
        campoFile: 'file',
        bytes: scelto.bytes!,
        nomeFile: scelto.name,
      );
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      numero.dispose();
      settore.dispose();
      oggetto.dispose();
    }
  }

  Future<void> _report(Map<String, dynamic> sessione) async {
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => _ReportPage(base: _base, titolo: sessione['titolo'].toString()),
    ));
  }

  Future<void> _chiudi() async {
    if (!await conferma(context, 'Chiudere la sessione?',
        'Dopo la chiusura non si possono caricare altri atti.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).post('$_base/chiudi');
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<dynamic>>(
      future: _dati,
      builder: (context, snap) {
        if (!snap.hasData) {
          return Scaffold(
            appBar: AppBar(),
            body: Center(
                child: snap.hasError ? Text(snap.error.toString()) : const CircularProgressIndicator()),
          );
        }
        final sessione = snap.data![0] as Map<String, dynamic>;
        final atti = (snap.data![1] as List).cast<Map<String, dynamic>>();
        _tipologie = List<Map<String, dynamic>>.from(snap.data![2] as List);
        final aperta = sessione['stato'] == 'APERTA';
        final criteri = sessione['criteri_sorteggio'] as Map<String, dynamic>?;

        return Scaffold(
          appBar: AppBar(
            title: Text(sessione['titolo'].toString()),
            actions: [
              IconButton(tooltip: 'Aggiorna', onPressed: _carica, icon: const Icon(Icons.refresh)),
              IconButton(
                  tooltip: 'Report', onPressed: () => _report(sessione), icon: const Icon(Icons.summarize)),
              if (aperta)
                IconButton(tooltip: 'Chiudi sessione', onPressed: _chiudi, icon: const Icon(Icons.lock)),
            ],
          ),
          floatingActionButton: aperta
              ? FloatingActionButton.extended(
                  onPressed: _caricaAtto, icon: const Icon(Icons.upload_file), label: const Text('Carica atto'))
              : null,
          body: ListView(padding: const EdgeInsets.all(16), children: [
            Sezione(
              titolo: 'Sorteggio',
              azioni: [
                if (aperta && criteri == null)
                  FilledButton.tonal(onPressed: () => _sorteggio(sessione), child: const Text('Esegui')),
              ],
              child: criteri == null
                  ? const Text('Sorteggio non ancora eseguito.')
                  : Text('Estratti ${(criteri['estratti'] as List).length} atti su '
                      '${criteri['atti_nel_periodo']} (${criteri['percentuale']}%), seme ${criteri['seme']}, '
                      'il ${formatData(criteri['eseguito_il'])} da ${criteri['eseguito_da']}.\n'
                      'Numeri: ${(criteri['estratti'] as List).join(', ')}'),
            ),
            Row(children: [
              Text('Atti (${atti.length})', style: Theme.of(context).textTheme.titleMedium),
              const Spacer(),
              FilterChip(
                label: const Text('Solo assegnati a me'),
                selected: _soloMiei,
                onSelected: (v) {
                  _soloMiei = v;
                  _carica();
                },
              ),
            ]),
            const SizedBox(height: 8),
            if (atti.isEmpty) const Text('Nessun atto caricato.'),
            for (final a in atti)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.description),
                  title: Text('${a['numero_registro'] ?? 's.n.'} · ${a['oggetto'] ?? a['file_nome']}'),
                  subtitle: Text('Adottato il ${formatData(a['data_adozione'])}'
                      '${a['settore'] != null ? ' · ${a['settore']}' : ''}'),
                  trailing: Chip(label: Text(statiAtto[a['stato']] ?? a['stato'].toString())),
                  onTap: () async {
                    await Navigator.of(context)
                        .push(MaterialPageRoute(builder: (_) => AttoPage(attoId: a['id'] as String)));
                    _carica();
                  },
                ),
              ),
            const SizedBox(height: 80),
          ]),
        );
      },
    );
  }
}

class _ReportPage extends StatelessWidget {
  const _ReportPage({required this.base, required this.titolo});

  final String base;
  final String titolo;

  @override
  Widget build(BuildContext context) {
    final api = apiDi(context);
    return Scaffold(
      appBar: AppBar(
        title: Text('Report · $titolo'),
        actions: [
          TextButton.icon(
            onPressed: () async {
              try {
                await salvaFile(api, '$base/report.csv', 'report-controllo.csv');
              } catch (e) {
                if (context.mounted) mostraErrore(context, e);
              }
            },
            icon: const Icon(Icons.download),
            label: const Text('CSV'),
          ),
        ],
      ),
      body: Caricamento<dynamic>(
        future: api.get('$base/report'),
        builder: (context, dati) {
          final r = dati as Map<String, dynamic>;
          final perSettore = r['per_settore'] as Map<String, dynamic>;
          final perCriterio = r['per_criterio'] as Map<String, dynamic>;
          return ListView(padding: const EdgeInsets.all(16), children: [
            Sezione(
              titolo: 'Sintesi',
              child: Text('${r['atti_totali']} atti controllati, ${r['atti_revisionati']} revisionati.'),
            ),
            Sezione(
              titolo: 'Per settore',
              child: DataTable(columns: const [
                DataColumn(label: Text('Settore')),
                DataColumn(label: Text('Atti'), numeric: true),
                DataColumn(label: Text('Con rilievi'), numeric: true),
              ], rows: [
                for (final e in perSettore.entries)
                  DataRow(cells: [
                    DataCell(Text(e.key)),
                    DataCell(Text('${e.value['atti']}')),
                    DataCell(Text('${e.value['con_rilievi']}')),
                  ]),
              ]),
            ),
            Sezione(
              titolo: 'Per criterio',
              child: Column(children: [
                for (final e in perCriterio.entries)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(e.key),
                    subtitle: Wrap(spacing: 6, children: [
                      for (final esito in (e.value as Map<String, dynamic>).entries)
                        Chip(label: Text('${etichettaEsito(esito.key)}: ${esito.value}')),
                    ]),
                  ),
              ]),
            ),
          ]);
        },
      ),
    );
  }
}
