import 'package:flutter/material.dart';

import '../comuni.dart';
import '../trasparenza/browser.dart' show scaricaBytes;

const apiRicerche = '/api/v1/ricerche';

const etichetteEsito = {
  'NESSUN_RISULTATO': 'nessun risultato',
  'RISULTATI_DEBOLI': 'solo risultati deboli',
  'NON_APERTI': 'risultati non aperti',
  'TROVATA': 'trovata',
};

/// Ricerche senza risposta e feedback di cittadini e utenti (ruolo "Analisi delle ricerche" o
/// amministratore): le domande che non trovano nulla, raggruppate per parole, e i giudizi sulle
/// ricerche e sulle schede, da segnare gestiti con una nota; riepilogo per mese ed esportazione
/// CSV. Non ci sono nomi né indirizzi di chi ha cercato.
class RicerchePage extends StatefulWidget {
  const RicerchePage({super.key});

  @override
  State<RicerchePage> createState() => _RicerchePageState();
}

enum _Periodo {
  mese('Ultimi 30 giorni', 30),
  trimestre('Ultimi 90 giorni', 90),
  anno('Ultimi 12 mesi', 365),
  tutto('Tutto', null);

  const _Periodo(this.etichetta, this.giorni);
  final String etichetta;
  final int? giorni;
}

class _RicerchePageState extends State<RicerchePage> {
  late final Future<List<Map<String, dynamic>>> _ambiti;
  _Periodo _periodo = _Periodo.trimestre;
  String? _ambito;
  bool? _pubblica; // null: tutte
  bool _gestite = false;
  bool? _utile = false; // feedback: null tutti
  int _versione = 0; // ricarica gli elenchi dopo una gestione

  @override
  void initState() {
    super.initState();
    _ambiti = apiDi(context).get('$apiRicerche/ambiti').then((v) => (v as List).cast<Map<String, dynamic>>());
  }

  Map<String, String> get _filtri {
    final giorni = _periodo.giorni;
    String data(DateTime d) => d.toIso8601String().substring(0, 10);
    return {
      if (giorni != null) 'da': data(DateTime.now().subtract(Duration(days: giorni))),
      'ambito': ?_ambito,
      if (_pubblica != null) 'pubblica': '$_pubblica',
      if (_gestite) 'gestite': 'true',
    };
  }

  Map<String, String> get _filtriFeedback => {..._filtri, if (_utile != null) 'utile': '$_utile'};

  void _aggiorna(VoidCallback f) => setState(() {
        f();
        _versione++;
      });

  Future<void> _esporta(String tipo, Map<String, String> filtri) async {
    try {
      final bytes = await apiDi(context).getBytes('$apiRicerche/esporta/$tipo', query: filtri);
      scaricaBytes(bytes, tipo == 'feedback' ? 'feedback.csv' : 'ricerche-senza-risposta.csv');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _barraFiltri(List<Map<String, dynamic>> ambiti) => Wrap(
        spacing: 12,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SizedBox(
            width: 180,
            child: DropdownButtonFormField<_Periodo>(
              initialValue: _periodo,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Periodo', isDense: true),
              items: [for (final p in _Periodo.values) DropdownMenuItem(value: p, child: Text(p.etichetta))],
              onChanged: (v) => _aggiorna(() => _periodo = v ?? _periodo),
            ),
          ),
          SizedBox(
            width: 240,
            child: DropdownButtonFormField<String?>(
              initialValue: _ambito,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Ambito', isDense: true),
              items: [
                const DropdownMenuItem(value: null, child: Text('Tutti')),
                for (final a in ambiti) DropdownMenuItem(value: a['id'] as String, child: Text('${a['descrizione']}')),
              ],
              onChanged: (v) => _aggiorna(() => _ambito = v),
            ),
          ),
          SizedBox(
            width: 180,
            child: DropdownButtonFormField<bool?>(
              initialValue: _pubblica,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Da', isDense: true),
              items: const [
                DropdownMenuItem(value: null, child: Text('Tutti')),
                DropdownMenuItem(value: true, child: Text('Cittadini')),
                DropdownMenuItem(value: false, child: Text('Utenti interni')),
              ],
              onChanged: (v) => _aggiorna(() => _pubblica = v),
            ),
          ),
          FilterChip(
            label: const Text('Anche le gestite'),
            selected: _gestite,
            onSelected: (v) => _aggiorna(() => _gestite = v),
          ),
        ],
      );

  @override
  Widget build(BuildContext context) => Caricamento<List<Map<String, dynamic>>>(
        future: _ambiti,
        builder: (context, ambiti) {
          final descrizioni = {for (final a in ambiti) a['id'] as String: a['descrizione'] as String};
          return DefaultTabController(
            length: 3,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Ricerche e feedback', style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 4),
                  const Text('Domande che non hanno trovato risposta e giudizi di cittadini e utenti. '
                      'Non si registrano nomi né indirizzi; i dati personali scritti nel testo sono oscurati.'),
                  const SizedBox(height: 12),
                  _barraFiltri(ambiti),
                ]),
              ),
              const TabBar(isScrollable: true, tabs: [Tab(text: 'Senza risposta'), Tab(text: 'Feedback'), Tab(text: 'Riepilogo')]),
              Expanded(
                child: TabBarView(children: [
                  _SenzaRisposta(
                    key: ValueKey('s$_versione'),
                    filtri: _filtri,
                    ambiti: descrizioni,
                    esporta: () => _esporta('senza-risposta', _filtri),
                    gestita: () => _aggiorna(() {}),
                  ),
                  _Feedback(
                    key: ValueKey('f$_versione'),
                    filtri: _filtriFeedback,
                    ambiti: descrizioni,
                    utile: _utile,
                    cambiaUtile: (v) => _aggiorna(() => _utile = v),
                    esporta: () => _esporta('feedback', _filtriFeedback),
                    gestito: () => _aggiorna(() {}),
                  ),
                  _Riepilogo(key: ValueKey('r$_versione'), filtri: _filtri),
                ]),
              ),
            ]),
          );
        },
      );
}

/// Dialogo per la nota di gestione; null se annullato.
Future<String?> _chiediNota(BuildContext context, String titolo, String descrizione) {
  final nota = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(titolo),
      content: SizedBox(
        width: 480,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(descrizione),
          const SizedBox(height: 12),
          TextField(
            controller: nota,
            maxLines: 4,
            minLines: 2,
            maxLength: 2000,
            decoration: const InputDecoration(labelText: 'Nota (es. cosa è stato fatto)'),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FilledButton(onPressed: () => Navigator.pop(context, nota.text), child: const Text('Segna gestita')),
      ],
    ),
  );
}

String _data(Object? iso) {
  final d = DateTime.tryParse('${iso ?? ''}');
  if (d == null) return '';
  String due(int n) => n.toString().padLeft(2, '0');
  return '${due(d.day)}/${due(d.month)}/${d.year}';
}

class _SenzaRisposta extends StatefulWidget {
  const _SenzaRisposta({super.key, required this.filtri, required this.ambiti, required this.esporta, required this.gestita});

  final Map<String, String> filtri;
  final Map<String, String> ambiti;
  final VoidCallback esporta;
  final VoidCallback gestita;

  @override
  State<_SenzaRisposta> createState() => _SenzaRispostaState();
}

class _SenzaRispostaState extends State<_SenzaRisposta> {
  late final _gruppi = apiDi(context).get('$apiRicerche/senza-risposta', query: widget.filtri).then((v) => (v as List).cast<Map<String, dynamic>>());

  Future<void> _gestisci(Map<String, dynamic> g) async {
    final nota = await _chiediNota(context, 'Domanda gestita',
        '«${g['testo']}»: le ${g['da_gestire']} ricerche da gestire si segnano gestite. Se la domanda torna, ricompare.');
    if (nota == null || !mounted) return;
    try {
      await apiDi(context).put('$apiRicerche/senza-risposta/gestione', {'ambito': g['ambito'], 'chiave': g['chiave'], 'nota': nota});
      widget.gestita();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) => Caricamento<List<Map<String, dynamic>>>(
        future: _gruppi,
        builder: (context, gruppi) => ListView(padding: const EdgeInsets.all(16), children: [
          Row(children: [
            Expanded(child: Text('${gruppi.length} domande, le più frequenti da gestire prima.')),
            OutlinedButton.icon(icon: const Icon(Icons.download), label: const Text('CSV'), onPressed: widget.esporta),
          ]),
          const SizedBox(height: 8),
          if (gruppi.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Nessuna domanda senza risposta.'))),
          for (final g in gruppi)
            Card(
              child: ListTile(
                title: Text('${g['testo']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if ((g['varianti'] as List).length > 1) Text('Anche: ${(g['varianti'] as List).skip(1).join(' · ')}'),
                  Text([
                    widget.ambiti[g['ambito']] ?? '${g['ambito']}',
                    '${g['volte']} volte (${g['da_gestire']} da gestire)',
                    if ((g['pubbliche'] as int) > 0) '${g['pubbliche']} dai cittadini',
                    'ultima il ${_data(g['ultima'])}',
                  ].join(' · ')),
                  Text([
                    for (final e in (g['esiti'] as Map).entries) '${etichetteEsito[e.key] ?? e.key}: ${e.value}',
                  ].join(', ')),
                  if (g['gestita_il'] != null)
                    Text('Gestita il ${_data(g['gestita_il'])} da ${g['gestita_da']}${g['nota'] == null ? '' : ': ${g['nota']}'}',
                        style: const TextStyle(fontStyle: FontStyle.italic)),
                ]),
                trailing: (g['da_gestire'] as int) > 0
                    ? TextButton(onPressed: () => _gestisci(g), child: const Text('Segna gestita'))
                    : const Icon(Icons.check),
              ),
            ),
        ]),
      );
}

class _Feedback extends StatefulWidget {
  const _Feedback({
    super.key,
    required this.filtri,
    required this.ambiti,
    required this.utile,
    required this.cambiaUtile,
    required this.esporta,
    required this.gestito,
  });

  final Map<String, String> filtri;
  final Map<String, String> ambiti;
  final bool? utile;
  final ValueChanged<bool?> cambiaUtile;
  final VoidCallback esporta;
  final VoidCallback gestito;

  @override
  State<_Feedback> createState() => _FeedbackState();
}

class _FeedbackState extends State<_Feedback> {
  late final _elenco = apiDi(context).get('$apiRicerche/feedback', query: widget.filtri).then((v) => (v as List).cast<Map<String, dynamic>>());

  Future<void> _gestisci(Map<String, dynamic> f) async {
    final nota = await _chiediNota(context, 'Feedback gestito', 'Il feedback si segna gestito con una nota facoltativa.');
    if (nota == null || !mounted) return;
    try {
      await apiDi(context).put('$apiRicerche/feedback/${f['id']}/gestione', {'nota': nota});
      widget.gestito();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) => Caricamento<List<Map<String, dynamic>>>(
        future: _elenco,
        builder: (context, elenco) => ListView(padding: const EdgeInsets.all(16), children: [
          Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SegmentedButton<bool?>(
              segments: const [
                ButtonSegment(value: false, label: Text('Non utili')),
                ButtonSegment(value: true, label: Text('Utili')),
                ButtonSegment(value: null, label: Text('Tutti')),
              ],
              selected: {widget.utile},
              onSelectionChanged: (s) => widget.cambiaUtile(s.first),
            ),
            Text('${elenco.length} feedback'),
            OutlinedButton.icon(icon: const Icon(Icons.download), label: const Text('CSV'), onPressed: widget.esporta),
          ]),
          const SizedBox(height: 8),
          if (elenco.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Nessun feedback.'))),
          for (final f in elenco)
            Card(
              child: ListTile(
                leading: f['tipo'] == 'ACCESSIBILITA'
                    ? Icon(Icons.accessibility_new, color: Colors.orange.shade900)
                    : Icon(f['utile'] == true ? Icons.thumb_up_outlined : Icons.thumb_down_outlined,
                        color: f['utile'] == true ? Colors.green.shade700 : Colors.orange.shade800),
                title: Text(switch (f['tipo']) {
                  'RICERCA' => 'Ricerca: «${f['testo']}»',
                  'ACCESSIBILITA' => 'Problema di accessibilità: ${f['riferimento'] ?? ''}',
                  _ => 'Pagina: ${f['riferimento'] ?? f['riferimento_id']}',
                }),
                subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if (f['commento'] != null) Text('«${f['commento']}»'),
                  if (f['contatto'] != null) Text('Rispondere a: ${f['contatto']}'),
                  Text([
                    widget.ambiti[f['ambito']] ?? '${f['ambito']}',
                    f['pubblica'] == true ? 'cittadino' : 'utente interno',
                    _data(f['quando']),
                  ].join(' · ')),
                  if (f['gestito_il'] != null)
                    Text('Gestito il ${_data(f['gestito_il'])} da ${f['gestito_da']}${f['nota'] == null ? '' : ': ${f['nota']}'}',
                        style: const TextStyle(fontStyle: FontStyle.italic)),
                ]),
                trailing: f['gestito_il'] == null
                    ? TextButton(onPressed: () => _gestisci(f), child: const Text('Segna gestito'))
                    : const Icon(Icons.check),
              ),
            ),
        ]),
      );
}

class _Riepilogo extends StatefulWidget {
  const _Riepilogo({super.key, required this.filtri});

  final Map<String, String> filtri;

  @override
  State<_Riepilogo> createState() => _RiepilogoState();
}

class _RiepilogoState extends State<_Riepilogo> {
  late final _dati = apiDi(context).get('$apiRicerche/riepilogo', query: widget.filtri).then((v) => v as Map<String, dynamic>);

  @override
  Widget build(BuildContext context) => Caricamento<Map<String, dynamic>>(
        future: _dati,
        builder: (context, d) {
          final mesi = (d['mesi'] as List).cast<Map<String, dynamic>>();
          final schede = (d['schede_non_utili'] as List).cast<Map<String, dynamic>>();
          String perc(int a, int b) => b == 0 ? '—' : '${(100 * a / b).round()}%';
          return ListView(padding: const EdgeInsets.all(16), children: [
            if (mesi.isEmpty)
              const Center(child: Text('Nessuna ricerca nel periodo.'))
            else
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(columns: const [
                  DataColumn(label: Text('Mese')),
                  DataColumn(label: Text('Ricerche'), numeric: true),
                  DataColumn(label: Text('Trovate'), numeric: true),
                  DataColumn(label: Text('Senza risposta'), numeric: true),
                  DataColumn(label: Text('% trovate'), numeric: true),
                  DataColumn(label: Text('Feedback utili'), numeric: true),
                  DataColumn(label: Text('Non utili'), numeric: true),
                ], rows: [
                  for (final m in mesi)
                    DataRow(cells: [
                      DataCell(Text('${m['mese']}')),
                      DataCell(Text('${m['ricerche']}')),
                      DataCell(Text('${m['trovate']}')),
                      DataCell(Text('${m['senza_risposta']}')),
                      DataCell(Text(perc(m['trovate'] as int, m['ricerche'] as int))),
                      DataCell(Text('${m['utili']}')),
                      DataCell(Text('${m['non_utili']}')),
                    ]),
                ]),
              ),
            if (schede.isNotEmpty) ...[
              const SizedBox(height: 24),
              Text('Pagine giudicate non utili', style: Theme.of(context).textTheme.titleMedium),
              for (final s in schede) ListTile(dense: true, title: Text('${s['riferimento']}'), trailing: Text('${s['volte']}')),
            ],
          ]);
        },
      );
}
