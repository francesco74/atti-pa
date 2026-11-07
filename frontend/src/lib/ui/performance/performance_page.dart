import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../comuni.dart';
import 'comune.dart';
import 'obiettivi.dart';
import '../relazioni/relazioni.dart';

/// Modulo performance: obiettivi annuali delle strutture nel PIAO triennale, con azioni e
/// misure; riepilogo per struttura; PIAO (solo l'amministratore della performance).
class PerformancePage extends StatefulWidget {
  const PerformancePage({super.key});

  @override
  State<PerformancePage> createState() => _PerformancePageState();
}

class _PerformancePageState extends State<PerformancePage> {
  late Future<DatiPerformance> _dati;
  int _versione = 0; // cambia quando si ricaricano i dati comuni: le schede si ricreano

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _dati = DatiPerformance.carica(apiDi(context));
        _versione++;
      });

  @override
  Widget build(BuildContext context) {
    return Caricamento<DatiPerformance>(
      future: _dati,
      riprova: _carica,
      builder: (context, dati) => Provider<DatiPerformance>.value(
        value: dati,
        child: DefaultTabController(
          length: dati.amministratore ? 4 : 2,
          child: Column(children: [
            TabBar(isScrollable: true, tabs: [
              const Scheda(Icon(Icons.flag_outlined), 'Obiettivi'),
              const Scheda(Icon(Icons.insights), 'Riepilogo'),
              if (dati.amministratore) const Scheda(Icon(Icons.calendar_month_outlined), 'PIAO'),
              if (dati.amministratore) const Scheda(Icon(Icons.summarize_outlined), 'Relazione'),
            ]),
            Expanded(
              child: TabBarView(key: ValueKey(_versione), children: [
                const ObiettiviTab(),
                const RiepilogoTab(),
                if (dati.amministratore) PiaoTab(onCambiato: _carica),
                if (dati.amministratore) const RelazioniTab(tipi: ['PERFORMANCE']),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Per ogni struttura visibile e anno: obiettivi, impegno totale, completamento, obiettivi
/// con gli impegni di azioni e misure non a 100, ritardi.
class RiepilogoTab extends StatefulWidget {
  const RiepilogoTab({super.key});

  @override
  State<RiepilogoTab> createState() => _RiepilogoTabState();
}

class _RiepilogoTabState extends State<RiepilogoTab> {
  String? _piaoId;
  int? _anno; // null: tutti gli anni
  Future<List<Map<String, dynamic>>>? _righe;

  @override
  void initState() {
    super.initState();
    final piao = context.read<DatiPerformance>().piaoPredefinito;
    _piaoId = piao?['id'] as String?;
    _anno = piao == null ? null : annoPredefinito(piao);
    _carica();
  }

  void _carica() {
    if (_piaoId == null) return;
    setState(() {
      _righe = apiDi(context).get('$apiPerformance/riepilogo', query: {
        'piao_id': _piaoId!,
        if (_anno != null) 'anno': '$_anno',
      }).then((v) => (v as List).cast<Map<String, dynamic>>());
    });
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiPerformance>();
    if (_piaoId == null) return const Center(child: Text('Nessun PIAO.'));
    final piao = dati.piaoDi(_piaoId)!;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(
          width: 240,
          child: DropdownButtonFormField<String>(
            initialValue: _piaoId,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'PIAO', isDense: true),
            items: [for (final p in dati.piao) DropdownMenuItem(value: p['id'] as String, child: Text('${p['titolo']}'))],
            onChanged: (v) {
              _piaoId = v;
              _anno = null;
              _carica();
            },
          ),
        ),
        SizedBox(
          width: 160,
          child: DropdownButtonFormField<int?>(
            initialValue: _anno,
            decoration: const InputDecoration(labelText: 'Anno', isDense: true),
            items: [
              const DropdownMenuItem(value: null, child: Text('Tutti')),
              for (final a in (piao['anni'] as List).cast<int>()) DropdownMenuItem(value: a, child: Text('$a')),
            ],
            onChanged: (v) {
              _anno = v;
              _carica();
            },
          ),
        ),
      ]),
      const SizedBox(height: 16),
      Caricamento<List<Map<String, dynamic>>>(
        future: _righe!,
        riprova: _carica,
        builder: (context, righe) => righe.isEmpty
            ? const Center(child: Text('Nessun obiettivo.'))
            : SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(columns: const [
                  DataColumn(label: Text('Anno')),
                  DataColumn(label: Text('Struttura')),
                  DataColumn(label: Text('Obiettivi'), numeric: true),
                  DataColumn(label: Text('Impegno')),
                  DataColumn(label: Text('Completamento')),
                  DataColumn(label: Text('Da completare'), numeric: true),
                  DataColumn(label: Text('In ritardo'), numeric: true),
                ], rows: [
                  for (final r in righe)
                    DataRow(cells: [
                      DataCell(Text('${r['anno']}')),
                      DataCell(Text('${r['struttura'] ?? '—'}')),
                      DataCell(Text('${r['obiettivi']}')),
                      DataCell(Text('${r['impegno_totale']}%',
                          style: TextStyle(color: r['completo'] == true ? null : Colors.red, fontWeight: FontWeight.w600))),
                      DataCell(BarraCompletamento(r['completamento'] as num?, larghezza: 120)),
                      DataCell(Text('${r['obiettivi_incompleti']}')),
                      DataCell(Text('${r['ritardi']}', style: TextStyle(color: (r['ritardi'] as int) > 0 ? Colors.orange.shade800 : null))),
                    ]),
                ]),
              ),
      ),
    ]);
  }
}

/// PIAO dell'ente: creazione, titolo e atto di approvazione, chiusura (sola lettura) e
/// riapertura, eliminazione di un PIAO senza obiettivi, storico.
class PiaoTab extends StatefulWidget {
  const PiaoTab({super.key, required this.onCambiato});

  final VoidCallback onCambiato; // ricarica i dati comuni

  @override
  State<PiaoTab> createState() => _PiaoTabState();
}

class _PiaoTabState extends State<PiaoTab> {
  Future<void> _esegui(Future<void> Function() azione) async {
    try {
      await azione();
      widget.onCambiato();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<Map<String, dynamic>?> _modulo({Map<String, dynamic>? p}) async {
    final anno = TextEditingController(text: '${p?['anno_inizio'] ?? DateTime.now().year}');
    final titolo = TextEditingController(text: p?['titolo'] as String? ?? '');
    final atto = TextEditingController(text: p?['atto'] as String? ?? '');
    final risultato = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(p == null ? 'Nuovo PIAO' : 'Modifica il PIAO'),
        content: SizedBox(
          width: 480,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (p == null)
              TextField(
                controller: anno,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Primo anno del triennio', helperText: 'es. 2026 per il PIAO 2026-2028'),
              ),
            TextField(controller: titolo, decoration: const InputDecoration(labelText: 'Titolo', hintText: 'PIAO 2026-2028')),
            TextField(controller: atto, decoration: const InputDecoration(labelText: 'Atto di approvazione', hintText: 'DGC n. ... del ...')),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Annulla')),
          FilledButton(
            onPressed: () {
              final a = int.tryParse(anno.text.trim());
              if (a == null || titolo.text.trim().isEmpty && p != null) return;
              Navigator.pop(c, {
                if (p == null) 'anno_inizio': a,
                'titolo': titolo.text.trim().isEmpty ? 'PIAO $a-${a + 2}' : titolo.text.trim(),
                'atto': atto.text.trim().isEmpty ? null : atto.text.trim(),
              });
            },
            child: const Text('Salva'),
          ),
        ],
      ),
    );
    for (final t in [anno, titolo, atto]) {
      t.dispose();
    }
    return risultato;
  }

  Future<void> _nuovo() => _esegui(() async {
        final v = await _modulo();
        if (v != null && mounted) await apiDi(context).post('$apiPerformance/piao', v);
      });

  Future<void> _modifica(Map<String, dynamic> p) => _esegui(() async {
        final v = await _modulo(p: p);
        if (v != null && mounted) await apiDi(context).put('$apiPerformance/piao/${p['id']}', {...v, 'stato': p['stato']});
      });

  Future<void> _cambiaStato(Map<String, dynamic> p) async {
    final chiudi = p['stato'] == 'APERTO';
    final nota = await confermaConNota(
      context,
      chiudi ? 'Chiudere il ${p['titolo']}?' : 'Riaprire il ${p['titolo']}?',
      chiudi
          ? 'Obiettivi, azioni e misure non si potranno più modificare (resta possibile riaprirlo).'
          : 'Dirigenti e responsabili potranno di nuovo modificare gli obiettivi.',
    );
    if (nota == null || !mounted) return;
    await _esegui(() => apiDi(context).put('$apiPerformance/piao/${p['id']}', {
          'titolo': p['titolo'],
          'atto': p['atto'],
          'stato': chiudi ? 'CHIUSO' : 'APERTO',
          if (nota.isNotEmpty) 'nota': nota,
        }));
  }

  Future<void> _elimina(Map<String, dynamic> p) async {
    if (!await conferma(context, 'Eliminare il ${p['titolo']}?', 'Si può eliminare solo un PIAO senza obiettivi.') || !mounted) return;
    await _esegui(() => apiDi(context).delete('$apiPerformance/piao/${p['id']}'));
  }

  Future<void> _storico(Map<String, dynamic> p) async {
    final voci = apiDi(context).get('$apiPerformance/piao/${p['id']}/storico').then((v) => (v as List).cast<Map<String, dynamic>>());
    await showDialog<void>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Storico del ${p['titolo']}'),
        content: SizedBox(
          width: 640,
          height: 480,
          child: Caricamento<List<Map<String, dynamic>>>(
            future: voci,
            builder: (context, v) => SingleChildScrollView(child: Storico(v)),
          ),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiPerformance>();
    return ListView(padding: const EdgeInsets.all(16), children: [
      Align(
        alignment: Alignment.centerLeft,
        child: FilledButton.icon(onPressed: _nuovo, icon: const Icon(Icons.add), label: const Text('Nuovo PIAO')),
      ),
      const SizedBox(height: 16),
      if (dati.piao.isEmpty) const Text('Nessun PIAO.'),
      for (final p in dati.piao)
        Card(
          child: ListTile(
            leading: Icon(p['stato'] == 'APERTO' ? Icons.lock_open : Icons.lock_outline),
            title: Text('${p['titolo']}'),
            subtitle: Text([
              'Triennio ${p['anno_inizio']}-${(p['anno_inizio'] as int) + 2}',
              ?p['atto'] as String?,
              p['stato'] == 'APERTO' ? 'aperto' : 'chiuso: sola lettura',
            ].join(' · ')),
            trailing: Wrap(spacing: 4, children: [
              TextButton(onPressed: () => _cambiaStato(p), child: Text(p['stato'] == 'APERTO' ? 'Chiudi' : 'Riapri')),
              IconButton(tooltip: 'Modifica', icon: const Icon(Icons.edit_outlined), onPressed: () => _modifica(p)),
              IconButton(tooltip: 'Storico', icon: const Icon(Icons.history), onPressed: () => _storico(p)),
              IconButton(tooltip: 'Elimina', icon: const IconaElimina(), onPressed: () => _elimina(p)),
            ]),
          ),
        ),
    ]);
  }
}
