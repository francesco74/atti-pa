import 'package:flutter/material.dart';

import '../comuni.dart';
import '../trasparenza/browser.dart' show scaricaBytes;

const apiRelazioni = '/api/v1/relazioni';

/// Relazioni di sintesi costruite sui dati del sistema: per ogni sezione dati e tabelle
/// calcolati; il testo lo scrive il modello dai soli dati della sezione (i numeri che nei dati
/// non ci sono si segnalano da verificare), poi si rivede e si esporta in DOCX o ODT.
/// [tipi]: le relazioni di questo modulo (es. RPCT e PIAO nell'anticorruzione).
class RelazioniTab extends StatefulWidget {
  const RelazioniTab({super.key, required this.tipi});

  final List<String> tipi;

  @override
  State<RelazioniTab> createState() => _RelazioniTabState();
}

class _SezioneBozza {
  _SezioneBozza(this.dati) : testo = TextEditingController();

  final Map<String, dynamic> dati;
  final TextEditingController testo;
  List<String> daVerificare = const [];
  bool inCorso = false;
}

class _RelazioniTabState extends State<RelazioniTab> with AutomaticKeepAliveClientMixin {
  late Future<List<Map<String, dynamic>>> _tipi;
  String? _tipo;
  int _anno = DateTime.now().year;
  String? _piaoId;
  List<Map<String, dynamic>> _piao = const [];
  Map<String, dynamic>? _relazione;
  List<_SezioneBozza> _sezioni = [];
  bool _caricamento = false;
  String? _errore;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _tipi = apiDi(context).get(apiRelazioni).then((v) => [
          for (final t in (v as List).cast<Map<String, dynamic>>())
            if (widget.tipi.contains(t['id'])) t,
        ]);
    _tipi.then((t) {
      if (mounted && t.isNotEmpty) _scegliTipo(t.first);
    }, onError: (_) {});
  }

  @override
  void dispose() {
    for (final s in _sezioni) {
      s.testo.dispose();
    }
    super.dispose();
  }

  Future<void> _scegliTipo(Map<String, dynamic> tipo) async {
    setState(() {
      _tipo = tipo['id'] as String;
      _azzera();
    });
    if (tipo['piao'] == true && _piao.isEmpty) {
      try {
        final p = (await apiDi(context).get('/api/v1/performance/piao') as List).cast<Map<String, dynamic>>();
        if (!mounted) return;
        setState(() {
          _piao = p;
          _piaoId = p.where((x) => x['stato'] == 'APERTO').firstOrNull?['id'] as String? ?? p.firstOrNull?['id'] as String?;
        });
      } catch (e) {
        if (mounted) mostraErrore(context, e);
      }
    }
  }

  void _azzera() {
    for (final s in _sezioni) {
      s.testo.dispose();
    }
    _sezioni = [];
    _relazione = null;
    _errore = null;
  }

  Map<String, String> get _parametri => {'anno': '$_anno', 'piao_id': ?_piaoId};

  Future<void> _prepara() async {
    setState(() {
      _azzera();
      _caricamento = true;
    });
    try {
      final r = await apiDi(context).get('$apiRelazioni/$_tipo', query: _parametri) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _relazione = r;
        _sezioni = [for (final s in (r['sezioni'] as List).cast<Map<String, dynamic>>()) _SezioneBozza(s)];
      });
    } catch (e) {
      if (mounted) setState(() => _errore = '$e');
    } finally {
      if (mounted) setState(() => _caricamento = false);
    }
  }

  Future<void> _scrivi(_SezioneBozza s) async {
    setState(() => s.inCorso = true);
    try {
      final r = await apiDi(context).post('$apiRelazioni/$_tipo/testo', {
        'sezione': s.dati['id'],
        'anno': _anno,
        'piao_id': ?_piaoId,
      }) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        s.testo.text = r['testo'] as String? ?? '';
        s.daVerificare = List<String>.from(r['numeri_da_verificare'] as List? ?? const []);
      });
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => s.inCorso = false);
    }
  }

  Future<void> _scriviTutte() async {
    for (final s in _sezioni) {
      if (!mounted) return;
      if (s.testo.text.trim().isEmpty) await _scrivi(s);
    }
  }

  Future<void> _esporta(String formato) async {
    final r = _relazione!;
    try {
      final bytes = await apiDi(context).postBytes('$apiRelazioni/esporta', {
        'titolo': r['titolo'],
        'sottotitolo': r['sottotitolo'],
        'formato': formato,
        'sezioni': [
          for (final s in _sezioni) {'titolo': s.dati['titolo'], 'testo': s.testo.text, 'tabelle': s.dati['tabelle']},
        ],
      });
      scaricaBytes(bytes, '${(r['titolo'] as String).toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '-')}.$formato');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _tabella(Map<String, dynamic> t) {
    final intestazioni = List<String>.from(t['intestazioni'] as List);
    final righe = (t['righe'] as List).cast<List>();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${t['titolo']}', style: const TextStyle(fontWeight: FontWeight.w600)),
        if (righe.isEmpty)
          const Text('Nessun dato.')
        else
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowHeight: 36,
              dataRowMinHeight: 32,
              dataRowMaxHeight: 56,
              columns: [for (final c in intestazioni) DataColumn(label: Text(c))],
              rows: [
                for (final r in righe)
                  DataRow(cells: [for (final c in r) DataCell(ConstrainedBox(constraints: const BoxConstraints(maxWidth: 360), child: Text(c == null ? '—' : '$c')))]),
              ],
            ),
          ),
      ]),
    );
  }

  Widget _sezione(_SezioneBozza s) => Sezione(
        titolo: s.dati['titolo'] as String,
        azioni: [
          TextButton.icon(
            icon: s.inCorso
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.auto_awesome_outlined, size: 18),
            label: Text(s.testo.text.trim().isEmpty ? 'Scrivi il testo' : 'Riscrivi'),
            onPressed: s.inCorso ? null : () => _scrivi(s),
          ),
        ],
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TextField(
            controller: s.testo,
            minLines: 3,
            maxLines: 20,
            decoration: const InputDecoration(
              labelText: 'Testo della sezione',
              helperText: 'Scritto dal modello dai soli dati della sezione: rileggilo e correggilo prima di usarlo',
            ),
          ),
          if (s.daVerificare.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Icon(Icons.warning_amber_rounded, size: 20, color: Colors.orange.shade800),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('Numeri da verificare (non compaiono nei dati): ${s.daVerificare.join(', ')}',
                      style: TextStyle(color: Colors.orange.shade900)),
                ),
              ]),
            ),
          for (final t in (s.dati['tabelle'] as List? ?? const []).cast<Map<String, dynamic>>()) _tabella(t),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Caricamento<List<Map<String, dynamic>>>(
      future: _tipi,
      builder: (context, tipi) {
        if (tipi.isEmpty) return const Center(child: Text('Nessuna relazione disponibile.'));
        final tipo = tipi.where((t) => t['id'] == _tipo).firstOrNull;
        final conPiao = tipo?['piao'] == true;
        final relazione = _relazione;
        return ListView(padding: const EdgeInsets.all(16), children: [
          Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            if (tipi.length > 1)
              SizedBox(
                width: 380,
                child: DropdownButtonFormField<String>(
                  initialValue: _tipo,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Relazione', isDense: true),
                  items: [for (final t in tipi) DropdownMenuItem(value: t['id'] as String, child: Text('${t['titolo']}'))],
                  onChanged: (v) => _scegliTipo(tipi.firstWhere((t) => t['id'] == v)),
                ),
              ),
            if (conPiao)
              SizedBox(
                width: 240,
                child: DropdownButtonFormField<String>(
                  initialValue: _piaoId,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'PIAO', isDense: true),
                  items: [for (final p in _piao) DropdownMenuItem(value: p['id'] as String, child: Text('${p['titolo']}'))],
                  onChanged: (v) => setState(() {
                    _piaoId = v;
                    _azzera();
                  }),
                ),
              ),
            SizedBox(
              width: 120,
              child: DropdownButtonFormField<int>(
                initialValue: _anno,
                decoration: InputDecoration(labelText: _tipo == 'PIAO' ? 'Primo anno' : 'Anno', isDense: true),
                items: [for (var a = DateTime.now().year + 1; a >= DateTime.now().year - 4; a--) DropdownMenuItem(value: a, child: Text('$a'))],
                onChanged: (v) => setState(() {
                  _anno = v ?? _anno;
                  _azzera();
                }),
              ),
            ),
            FilledButton.icon(
              icon: _caricamento ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.summarize_outlined),
              label: const Text('Prepara la bozza'),
              onPressed: _caricamento || (conPiao && _piaoId == null) ? null : _prepara,
            ),
          ]),
          const SizedBox(height: 8),
          const Text('I dati e le tabelle si calcolano dal sistema; il testo di ogni sezione lo scrive il modello usando '
              'solo quei dati. Rivedi sempre il testo prima di usarlo.'),
          if (_errore != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_errore!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
          if (relazione != null) ...[
            const SizedBox(height: 16),
            Text('${relazione['titolo']}', style: Theme.of(context).textTheme.titleLarge),
            Text('${relazione['ente']} - ${relazione['sottotitolo']}'),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              OutlinedButton.icon(
                icon: const Icon(Icons.auto_awesome_outlined),
                label: const Text('Scrivi i testi mancanti'),
                onPressed: _sezioni.any((s) => s.inCorso) ? null : _scriviTutte,
              ),
              OutlinedButton.icon(icon: const Icon(Icons.download), label: const Text('Scarica DOCX'), onPressed: () => _esporta('docx')),
              OutlinedButton.icon(icon: const Icon(Icons.download), label: const Text('Scarica ODT'), onPressed: () => _esporta('odt')),
            ]),
            const SizedBox(height: 12),
            for (final s in _sezioni) _sezione(s),
          ],
        ]);
      },
    );
  }
}
