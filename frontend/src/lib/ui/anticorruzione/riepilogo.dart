import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../../util/download.dart';
import '../comuni.dart';
import 'comune.dart';
import 'metodologia.dart';

/// Riepilogo della mappatura (totali, rischi per livello, per area e per struttura),
/// allegati al PTPCT in Excel e metodologia di valutazione.
class RiepilogoTab extends StatefulWidget {
  const RiepilogoTab({super.key, required this.onDatiCambiati});

  final VoidCallback onDatiCambiati; // metodologia modificata: si ricaricano i dati comuni

  @override
  State<RiepilogoTab> createState() => _RiepilogoTabState();
}

class _RiepilogoTabState extends State<RiepilogoTab> {
  late Future<Map<String, dynamic>> _riepilogo;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _riepilogo = apiDi(context).get('$apiAnticorruzione/riepilogo').then((v) => v as Map<String, dynamic>);
      });

  Future<void> _ripristina() async {
    if (!await conferma(context, 'Tornare alla metodologia standard?',
        'Le valutazioni esistenti restano come sono: si ricalcolano rivalutando i rischi.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('$apiAnticorruzione/metodologia');
      widget.onDatiCambiati();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _distribuzione(DatiAnticorruzione dati, Map<String, dynamic> perLivello, List<String> livelli) {
    final totale = perLivello.values.fold<int>(0, (a, b) => a + (b as int));
    return Column(children: [
      for (final l in livelli)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(children: [
            SizedBox(width: 150, child: Text(l == 'None' ? 'Non valutati' : l)),
            Expanded(
              child: LinearProgressIndicator(
                value: totale == 0 ? 0 : (perLivello[l] as int) / totale,
                minHeight: 14,
                color: dati.colore(l == 'None' ? null : l),
                backgroundColor: Colors.black12,
              ),
            ),
            SizedBox(width: 48, child: Text('  ${perLivello[l]}')),
          ]),
        ),
    ]);
  }

  Widget _tabella(DatiAnticorruzione dati, String titolo, List<Map<String, dynamic>> righe, List<String> livelli) => Sezione(
        titolo: titolo,
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(columns: [
            const DataColumn(label: Text('')),
            const DataColumn(label: Text('Rischi'), numeric: true),
            for (final l in livelli) DataColumn(label: Text(l == 'None' ? 'Non valutati' : l.replaceFirst('Rischio ', '')), numeric: true),
          ], rows: [
            for (final r in righe)
              DataRow(cells: [
                DataCell(SizedBox(width: 280, child: Text('${r['codice'] ?? ''} ${r['descrizione']}', overflow: TextOverflow.ellipsis))),
                DataCell(Text('${r['rischi']}')),
                for (final l in livelli) DataCell(Text('${(r['per_livello'] as Map)[l]}')),
              ]),
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    final m = dati.metodologia;
    return Caricamento<Map<String, dynamic>>(
      future: _riepilogo,
      riprova: _carica,
      builder: (context, r) {
        final t = r['totali'] as Map;
        final livelli = List<String>.from(r['livelli'] as List);
        return ListView(padding: const EdgeInsets.all(16), children: [
          Sezione(
            titolo: 'Mappatura',
            azioni: [
              FilledButton.icon(
                onPressed: () => salvaFile(apiDi(context), '$apiAnticorruzione/esporta/ptpct', 'allegato_ptpct.xlsx'),
                icon: const Icon(Icons.download),
                label: const Text('Allegati al PTPCT (Excel)'),
              ),
            ],
            child: Text('${t['processi']} processi, ${t['attivita']} attività, ${t['rischi']} rischi '
                '(${t['rischi_non_valutati']} non valutati), ${t['misure']} misure '
                '(${t['misure_generali']} generali, ${t['misure_trasparenza']} di trasparenza).'),
          ),
          Sezione(titolo: 'Rischi per livello', child: _distribuzione(dati, (r['per_livello'] as Map).cast<String, dynamic>(), livelli)),
          _tabella(dati, 'Per area di rischio', (r['per_area'] as List).cast<Map<String, dynamic>>(), livelli),
          _tabella(dati, 'Per struttura responsabile', (r['per_struttura'] as List).cast<Map<String, dynamic>>(), livelli),
          Sezione(
            titolo: 'Metodologia di valutazione del rischio${m['standard'] == true ? ' (standard)' : ' (dell\'ente)'}',
            azioni: [
              if (rpct)
                TextButton.icon(
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('Modifica'),
                  onPressed: () async {
                    final salvata = await Navigator.of(context).push<bool>(
                      MaterialPageRoute(builder: (_) => MetodologiaPage(metodologia: m)),
                    );
                    if (salvata == true) widget.onDatiCambiati();
                  },
                ),
              if (rpct && m['standard'] != true) TextButton(onPressed: _ripristina, child: const Text('Torna allo standard')),
            ],
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Probabilità e impatto sono la moda dei valori degli indicatori (a parità vale il più alto); il livello '
                  'viene dalla matrice. La metodologia standard arriva con il pacchetto (Amministrazione → Pacchetti); '
                  'il RPCT la adatta a quella adottata nel PIAO dell\'ente con "Modifica".'),
              const SizedBox(height: 8),
              Text('Indicatori di probabilità', style: Theme.of(context).textTheme.titleSmall),
              for (final i in dati.indicatoriProbabilita) Text('${i['id']}. ${i['nome']}'),
              const SizedBox(height: 8),
              Text('Indicatori di impatto', style: Theme.of(context).textTheme.titleSmall),
              for (final i in dati.indicatoriImpatto) Text('${i['id']}. ${i['nome']}'),
              const SizedBox(height: 8),
              Text('Matrice (probabilità × impatto)', style: Theme.of(context).textTheme.titleSmall),
              DataTable(columns: [
                const DataColumn(label: Text('P \\ I')),
                for (final i in dati.scala) DataColumn(label: Text(i)),
              ], rows: [
                for (final p in dati.scala.reversed)
                  DataRow(cells: [
                    DataCell(Text(p)),
                    for (final i in dati.scala) DataCell(LivelloChip(dati, dati.livelloDa(p, i))),
                  ]),
              ]),
            ]),
          ),
        ]);
      },
    );
  }
}
