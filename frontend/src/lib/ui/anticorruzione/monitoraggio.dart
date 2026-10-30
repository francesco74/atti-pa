import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../../util/download.dart';
import '../comuni.dart';
import 'comune.dart';

const _attuazione = {'ATTUATA': 'Attuata', 'PARZIALE': 'Parzialmente attuata', 'NON_ATTUATA': 'Non attuata'};
const _coloriAttuazione = {'ATTUATA': Colors.green, 'PARZIALE': Colors.orange, 'NON_ATTUATA': Colors.red};
const _statiVerifica = {'DA_VERIFICARE': 'Da verificare', 'VERIFICATA': 'Verificata', 'CONTESTATA': 'Contestata'};

Widget _chip(String testo, Color colore) => Chip(
      visualDensity: VisualDensity.compact,
      side: BorderSide(color: colore),
      backgroundColor: colore.withValues(alpha: 0.1),
      label: Text(testo, style: TextStyle(color: colore)),
    );

/// Monitoraggio annuale delle misure: "Da dichiarare" (misure della propria struttura, con
/// la dichiarazione), "Dichiarazioni" (con la verifica del RPCT) e "Cruscotto".
class MonitoraggioTab extends StatefulWidget {
  const MonitoraggioTab({super.key});

  @override
  State<MonitoraggioTab> createState() => _MonitoraggioTabState();
}

class _MonitoraggioTabState extends State<MonitoraggioTab> {
  int _anno = DateTime.now().year;
  List<int> _anni = [DateTime.now().year];
  String? _struttura;
  int _vista = 0; // 0 da dichiarare, 1 dichiarazioni, 2 cruscotto
  late Future<Object?> _dati;
  String? _filtroVerifica;

  @override
  void initState() {
    super.initState();
    _struttura = context.read<AuthState>().utente?.strutturaId;
    apiDi(context).get('$apiAnticorruzione/monitoraggio/anni').then((v) {
      if (mounted) setState(() => _anni = List<int>.from(v as List));
    }, onError: (_) {});
    _carica();
  }

  String get _base => '$apiAnticorruzione/monitoraggio/$_anno';

  void _carica() => setState(() {
        final api = apiDi(context);
        _dati = switch (_vista) {
          0 => _struttura == null
              ? Future.value(null)
              : api.get('$_base/misure', query: {'struttura': _struttura!}),
          1 => api.get(_base, query: {'struttura': ?_struttura, 'stato_verifica': ?_filtroVerifica}),
          _ => api.get('$_base/cruscotto'),
        };
      });

  Future<void> _dichiara(Map<String, dynamic> voce) async {
    final d = (voce['dichiarazione'] as Map?)?.cast<String, dynamic>() ?? const {};
    final misura = (voce['contesto'] as Map)['misura'] as Map;
    var stato = d['stato_attuazione'] as String? ?? 'ATTUATA';
    final campi = {
      for (final k in const ['motivazione', 'indicatore_rilevato', 'target', 'evidenze'])
        k: TextEditingController(text: (d[k] ?? (k == 'target' ? misura['target'] : null)) as String? ?? ''),
    };
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: Text('Misura ${misura['codice']} - $_anno'),
          content: SizedBox(
            width: 560,
            child: SingleChildScrollView(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(misura['descrizione'] as String? ?? ''),
                if (misura['indicatore'] != null) Text('Indicatore previsto: ${misura['indicatore']}'),
                if (d['note_rpct'] != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text('Nota del RPCT: ${d['note_rpct']}', style: TextStyle(color: Theme.of(c).colorScheme.error)),
                  ),
                const SizedBox(height: 12),
                SegmentedButton<String>(
                  segments: [for (final e in _attuazione.entries) ButtonSegment(value: e.key, label: Text(e.value))],
                  selected: {stato},
                  onSelectionChanged: (s) => aggiorna(() => stato = s.first),
                ),
                TextField(
                  controller: campi['motivazione'],
                  maxLines: 3,
                  decoration: InputDecoration(labelText: 'Motivazione${stato == 'ATTUATA' ? '' : ' *'}'),
                ),
                TextField(controller: campi['indicatore_rilevato'], decoration: const InputDecoration(labelText: 'Indicatore rilevato')),
                TextField(controller: campi['target'], decoration: const InputDecoration(labelText: 'Target')),
                TextField(controller: campi['evidenze'], maxLines: 3, decoration: const InputDecoration(labelText: 'Evidenze')),
              ]),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Salva')),
          ],
        ),
      ),
    );
    final corpo = {
      'stato_attuazione': stato,
      'struttura_id': voce['struttura_id'],
      for (final e in campi.entries) e.key: testoOppureNull(e.value),
    };
    for (final c in campi.values) {
      c.dispose();
    }
    if (ok != true || !mounted) return;
    try {
      await apiDi(context).put('$_base/misure/${voce['misura_id']}', corpo);
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _verifica(Map<String, dynamic> d, bool verifica) async {
    final note = TextEditingController(text: d['note_rpct'] as String? ?? '');
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(verifica ? 'Verifica la dichiarazione' : 'Contesta la dichiarazione'),
        content: SizedBox(
          width: 480,
          child: TextField(controller: note, maxLines: 4, decoration: InputDecoration(labelText: verifica ? 'Note' : 'Nota per la struttura *')),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(verifica ? 'Verifica' : 'Contesta')),
        ],
      ),
    );
    final testo = note.text.trim();
    note.dispose();
    if (ok != true || !mounted) return;
    try {
      await apiDi(context).post('$apiAnticorruzione/monitoraggio/dichiarazioni/${d['id']}/${verifica ? 'verifica' : 'contesta'}',
          {'note': testo.isEmpty ? null : testo});
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _riga(Map<String, dynamic> contesto) => Text(
        '${(contesto['processo'] as Map)['codice']} ${(contesto['processo'] as Map)['denominazione']} › '
        '${(contesto['attivita'] as Map)['codice']} › ${(contesto['rischio'] as Map)['codice']}',
        style: Theme.of(context).textTheme.bodySmall,
      );

  Widget _daDichiarare(List<Map<String, dynamic>> voci) {
    if (voci.isEmpty) return const Center(child: Text('Nessuna misura da dichiarare per la struttura.'));
    final fatte = voci.where((v) => v['dichiarazione'] != null).length;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('$fatte dichiarate su ${voci.length}'),
      for (final v in voci)
        Card(
          child: ListTile(
            title: Text('${((v['contesto'] as Map)['misura'] as Map)['codice']} - ${((v['contesto'] as Map)['misura'] as Map)['descrizione']}'),
            subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _riga((v['contesto'] as Map).cast<String, dynamic>()),
              if (v['trasversale'] == true) const Text('Misura trasversale: la dichiara ogni struttura'),
              if ((v['obiettivi'] as List? ?? const []).isNotEmpty)
                Text('Obiettivi: ${(v['obiettivi'] as List).map((o) => o['codice']).join(', ')}'),
            ]),
            trailing: v['dichiarazione'] == null
                ? const Text('Da dichiarare')
                : Wrap(spacing: 4, children: [
                    _chip(_attuazione[(v['dichiarazione'] as Map)['stato_attuazione']]!,
                        _coloriAttuazione[(v['dichiarazione'] as Map)['stato_attuazione']]!),
                    _chip(_statiVerifica[(v['dichiarazione'] as Map)['stato_verifica']] ?? '', Colors.blueGrey),
                  ]),
            onTap: (v['dichiarazione'] as Map?)?['stato_verifica'] == 'VERIFICATA' ? null : () => _dichiara(v),
          ),
        ),
    ]);
  }

  Widget _dichiarazioni(List<Map<String, dynamic>> righe, bool rpct) {
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          for (final s in [null, ..._statiVerifica.keys])
            ChoiceChip(
              label: Text(s == null ? 'Tutte' : _statiVerifica[s]!),
              selected: _filtroVerifica == s,
              onSelected: (_) {
                _filtroVerifica = s;
                _carica();
              },
            ),
          TextButton.icon(
            icon: const Icon(Icons.download),
            label: const Text('Excel'),
            onPressed: () => salvaFile(apiDi(context), '$_base/esporta', 'monitoraggio_$_anno.xlsx',
                query: {'struttura': ?_struttura, 'stato_verifica': ?_filtroVerifica}),
          ),
        ]),
      ),
      Expanded(
        child: righe.isEmpty
            ? const Center(child: Text('Nessuna dichiarazione.'))
            : ListView(padding: const EdgeInsets.all(16), children: [
                for (final d in righe)
                  Card(
                    child: ListTile(
                      title: Text('${(d['contesto'] as Map)['struttura']['codice']} · '
                          '${(d['contesto'] as Map)['misura']['codice']} - ${(d['contesto'] as Map)['misura']['descrizione']}'),
                      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        _riga((d['contesto'] as Map).cast<String, dynamic>()),
                        if (d['motivazione'] != null) Text('Motivazione: ${d['motivazione']}'),
                        if (d['evidenze'] != null) Text('Evidenze: ${d['evidenze']}'),
                        if (d['note_rpct'] != null) Text('Note del RPCT: ${d['note_rpct']}'),
                        Text('Dichiarata il ${formatData(d['dichiarato_il'])}'),
                      ]),
                      isThreeLine: true,
                      trailing: Wrap(spacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                        _chip(_attuazione[d['stato_attuazione']]!, _coloriAttuazione[d['stato_attuazione']]!),
                        _chip(_statiVerifica[d['stato_verifica']] ?? '', Colors.blueGrey),
                        if (rpct && d['stato_verifica'] != 'VERIFICATA') ...[
                          IconButton(tooltip: 'Verifica', icon: const Icon(Icons.verified_outlined), onPressed: () => _verifica(d, true)),
                          IconButton(tooltip: 'Contesta', icon: const Icon(Icons.report_outlined), onPressed: () => _verifica(d, false)),
                        ],
                      ]),
                    ),
                  ),
              ]),
      ),
    ]);
  }

  Widget _cruscotto(Map<String, dynamic> c) {
    final t = c['totale'] as Map;
    DataRow riga(List<Object?> valori) => DataRow(cells: [for (final v in valori) DataCell(Text('${v ?? ''}'))]);
    return ListView(padding: const EdgeInsets.all(16), children: [
      Sezione(
        titolo: 'Anno $_anno',
        child: Text('${t['totale']} dichiarazioni: ${t['attuate']} attuate, ${t['parziali']} parziali, '
            '${t['non_attuate']} non attuate (${t['percentuale_attuate']}% attuate); '
            '${t['verificate']} verificate, ${t['contestate']} contestate.'),
      ),
      Sezione(
        titolo: 'Per struttura',
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(columns: const [
            DataColumn(label: Text('Struttura')),
            DataColumn(label: Text('Attese'), numeric: true),
            DataColumn(label: Text('Dichiarate'), numeric: true),
            DataColumn(label: Text('Attuate'), numeric: true),
            DataColumn(label: Text('Parziali'), numeric: true),
            DataColumn(label: Text('Non attuate'), numeric: true),
            DataColumn(label: Text('% attuate'), numeric: true),
            DataColumn(label: Text('Verificate'), numeric: true),
            DataColumn(label: Text('Contestate'), numeric: true),
          ], rows: [
            for (final s in (c['strutture'] as List).cast<Map<String, dynamic>>())
              riga(['${s['codice']} ${s['descrizione']}', s['attese'], s['totale'], s['attuate'], s['parziali'],
                    s['non_attuate'], s['percentuale_attuate'], s['verificate'], s['contestate']]),
          ]),
        ),
      ),
      Sezione(
        titolo: 'Confronto tra gli anni',
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(columns: const [
            DataColumn(label: Text('Anno')),
            DataColumn(label: Text('Dichiarazioni'), numeric: true),
            DataColumn(label: Text('% attuate'), numeric: true),
            DataColumn(label: Text('Verificate'), numeric: true),
            DataColumn(label: Text('Contestate'), numeric: true),
          ], rows: [
            for (final a in (c['anni'] as List).cast<Map<String, dynamic>>())
              riga([a['anno'], a['totale'], a['percentuale_attuate'], a['verificate'], a['contestate']]),
          ]),
        ),
      ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    final utente = context.read<AuthState>().utente;
    final rpct = utente?.isAnticorruzioneRpct ?? false;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          SizedBox(
            width: 120,
            child: DropdownButtonFormField<int>(
              initialValue: _anno,
              decoration: const InputDecoration(labelText: 'Anno', isDense: true),
              items: [for (final a in {..._anni, DateTime.now().year - 1, DateTime.now().year}.toList()..sort((a, b) => b - a))
                DropdownMenuItem(value: a, child: Text('$a'))],
              onChanged: (v) {
                _anno = v ?? _anno;
                _carica();
              },
            ),
          ),
          SizedBox(
            width: 320,
            child: DropdownButtonFormField<String?>(
              initialValue: _struttura,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Struttura', isDense: true),
              items: [
                if (rpct || _vista != 0) const DropdownMenuItem(value: null, child: Text('Tutte')),
                for (final s in dati.strutture.where((s) => s['attiva'] == true))
                  DropdownMenuItem(value: s['id'] as String, child: Text('${s['codice']} - ${s['descrizione']}', overflow: TextOverflow.ellipsis)),
              ],
              onChanged: (v) {
                _struttura = v;
                _carica();
              },
            ),
          ),
          SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 0, icon: Icon(Icons.edit_note), label: Text('Da dichiarare')),
              ButtonSegment(value: 1, icon: Icon(Icons.fact_check_outlined), label: Text('Dichiarazioni')),
              ButtonSegment(value: 2, icon: Icon(Icons.insights), label: Text('Cruscotto')),
            ],
            selected: {_vista},
            onSelectionChanged: (s) {
              _vista = s.first;
              _carica();
            },
          ),
        ]),
      ),
      Expanded(
        child: Caricamento<Object?>(
          future: _dati,
          riprova: _carica,
          builder: (context, v) => switch (_vista) {
            0 => v == null
                ? const Center(child: Text('Scegli la struttura (al tuo utente non ne è assegnata una: chiedi all\'amministratore).'))
                : _daDichiarare((v as List).cast<Map<String, dynamic>>()),
            1 => _dichiarazioni((v as List).cast<Map<String, dynamic>>(), rpct),
            _ => _cruscotto(v as Map<String, dynamic>),
          },
        ),
      ),
    ]);
  }
}
