import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../../util/scelta_file.dart';
import '../comuni.dart';
import 'comune.dart';

const _estensioni = ['pdf', 'doc', 'docx', 'odt', 'xls', 'xlsx', 'ods', 'csv'];

/// Importazione degli obiettivi di un anno del PIAO dal documento (il PIAO o il Piano della
/// performance): il worker lo legge a parti con l'intelligenza artificiale, che trascrive le
/// schede degli obiettivi (codice, titolo, struttura, fasi, indicatori). Poi si rivedono gli
/// obiettivi trovati, con la struttura proposta e gli avvisi, e si salvano quelli scelti, con
/// impegni a 0 da distribuire. Nulla si salva senza conferma.
class ImportaObiettiviPage extends StatefulWidget {
  const ImportaObiettiviPage({super.key, required this.dati, required this.piao, required this.anno});

  final DatiPerformance dati;
  final Map<String, dynamic> piao;
  final int anno;

  @override
  State<ImportaObiettiviPage> createState() => _ImportaObiettiviPageState();
}

/// Un obiettivo trovato nel documento, con le scelte della revisione.
class _Trovato {
  _Trovato(this.dati)
      : struttura = dati['struttura_id'] as String?,
        importa = dati['struttura_id'] != null && dati['presente'] == null;

  final Map<String, dynamic> dati;
  String? struttura;
  bool importa;

  List<Map<String, dynamic>> get elementi => (dati['elementi'] as List).cast<Map<String, dynamic>>();
  List<String> get avvisi => List<String>.from(dati['avvisi'] as List? ?? const []);
  String get nome => [?dati['codice'] as String?, dati['titolo'] as String].join(' - ');
}

enum _Fase { fonte, attesa, revisione }

class _ImportaObiettiviPageState extends State<ImportaObiettiviPage> {
  var _fase = _Fase.fonte;
  late int _anno = widget.anno;
  final _url = TextEditingController();
  List<FileScelto> _files = [];
  String? _lavoroId, _errore, _avanzamento;
  Timer? _attesa;
  List<_Trovato> _trovati = [];
  List<String> _avvisi = [];
  bool _salvataggio = false;

  String get _api => '$apiPerformance/importazioni';

  String get _fonte => _files.isEmpty ? _url.text.trim() : _files.map((f) => f.name).join(', ');

  @override
  void dispose() {
    _attesa?.cancel();
    _url.dispose();
    super.dispose();
  }

  Future<void> _avvia() async {
    final api = apiDi(context);
    setState(() => _errore = null);
    try {
      final r = _files.isEmpty
          ? await api.post(_api, {'url': _url.text.trim()})
          : await api.postMultipartFiles(_api,
              campi: {'dati': jsonEncode(<String, Object>{})}, campoFile: 'file', files: [for (final f in _files) (f.name, f.bytes)]);
      _lavoroId = (r as Map)['id'] as String;
      setState(() {
        _fase = _Fase.attesa;
        _avanzamento = null;
      });
      _attesa = Timer.periodic(const Duration(seconds: 3), (_) => _controlla());
    } catch (e) {
      if (mounted) setState(() => _errore = '$e');
    }
  }

  Future<void> _controlla() async {
    try {
      final r = await apiDi(context).get('$_api/$_lavoroId', query: {'piao_id': widget.piao['id'] as String, 'anno': '$_anno'})
          as Map<String, dynamic>;
      if (!mounted) return;
      switch (r['stato']) {
        case 'ERRORE':
          _attesa?.cancel();
          setState(() {
            _fase = _Fase.fonte;
            _errore = 'Lettura non riuscita: ${r['errore'] ?? 'errore sconosciuto'}';
          });
        case 'COMPLETATA':
          _attesa?.cancel();
          setState(() {
            _trovati = [for (final o in (r['obiettivi'] as List? ?? const [])) _Trovato((o as Map).cast<String, dynamic>())];
            _avvisi = List<String>.from(r['avvisi'] as List? ?? const []);
            _fase = _Fase.revisione;
          });
        default:
          final a = r['avanzamento'] as List?;
          setState(() => _avanzamento = a == null ? null : 'Lette ${a[0]} parti su ${a[1]}');
      }
    } catch (_) {
      // nuovo tentativo al prossimo giro
    }
  }

  Future<void> _salva() async {
    final scelti = _trovati.where((t) => t.importa).toList();
    if (scelti.any((t) => t.struttura == null)) {
      setState(() => _errore = 'Scegli la struttura di ogni obiettivo da importare');
      return;
    }
    final api = apiDi(context);
    setState(() {
      _errore = null;
      _salvataggio = true;
    });
    try {
      final r = await api.post('$apiPerformance/obiettivi/importati', {
        'piao_id': widget.piao['id'],
        'anno': _anno,
        'fonte': _fonte.length > 500 ? _fonte.substring(0, 500) : _fonte,
        'obiettivi': [
          for (final t in scelti)
            {
              'struttura_id': t.struttura,
              for (final k in const ['codice', 'titolo', 'descrizione', 'tipo']) k: t.dati[k],
              'elementi': t.elementi,
            },
        ],
      }) as Map<String, dynamic>;
      if (!mounted) return;
      mostraMessaggio(context, '${r['creati']} obiettivi importati: ora distribuisci gli impegni tra obiettivi e azioni.');
      Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _errore = '$e';
          _salvataggio = false;
        });
      }
    }
  }

  // --- fasi ------------------------------------------------------------------------------------

  Widget _sceltaFonte() {
    final inizio = widget.piao['anno_inizio'] as int;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Sezione(
        titolo: 'Da quale documento leggere gli obiettivi',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('Carica il PIAO o il Piano della performance (PDF, Word, ODT o foglio di calcolo), o indica l\'indirizzo del '
              'documento. L\'intelligenza artificiale legge le schede degli obiettivi e ne trascrive codice, titolo, struttura, '
              'fasi e indicatori: poi li rivedi e scegli quali salvare. Per un documento lungo conviene caricare solo la parte '
              'con le schede degli obiettivi: la lettura è più rapida.'),
          const SizedBox(height: 12),
          SizedBox(
            width: 240,
            child: DropdownButtonFormField<int>(
              initialValue: _anno,
              decoration: const InputDecoration(labelText: 'Anno degli obiettivi', isDense: true),
              items: [for (var a = inizio; a < inizio + 3; a++) DropdownMenuItem(value: a, child: Text('$a'))],
              onChanged: (v) => setState(() => _anno = v ?? _anno),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _url,
            enabled: _files.isEmpty,
            decoration: const InputDecoration(labelText: 'Indirizzo del documento', hintText: 'https://www.ente.it/.../piao.pdf'),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            OutlinedButton.icon(
              icon: const Icon(Icons.upload_file),
              label: const Text('Oppure scegli il documento'),
              onPressed: () async {
                final f = await scegliFiles(_estensioni);
                if (f.isNotEmpty && mounted) {
                  setState(() {
                    _files = f.take(10).toList();
                    _url.clear();
                  });
                }
              },
            ),
            for (final f in _files) Chip(label: Text(f.name), onDeleted: () => setState(() => _files.remove(f))),
          ]),
          if (_errore != null)
            Padding(padding: const EdgeInsets.only(top: 12), child: Text(_errore!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
          const SizedBox(height: 16),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              icon: const Icon(Icons.auto_awesome),
              label: const Text('Leggi gli obiettivi'),
              onPressed: _files.isEmpty && !_url.text.trim().startsWith('http') ? null : _avvia,
            ),
          ),
        ]),
      ),
    ]);
  }

  Widget _inAttesa() => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const CircularProgressIndicator(),
            const SizedBox(height: 16),
            Text(_avanzamento ?? 'Lettura del documento in corso…'),
            const SizedBox(height: 8),
            Text('Il documento si legge a parti: per un PIAO completo servono diversi minuti.',
                style: Theme.of(context).textTheme.bodySmall, textAlign: TextAlign.center),
          ]),
        ),
      );

  Widget _trovato(_Trovato t) {
    final tema = Theme.of(context);
    final presente = t.dati['presente'] as Map?;
    final strutture = [for (final s in widget.dati.strutture) if (s['attiva'] != false) s];
    return Card(
      child: ExpansionTile(
        leading: Checkbox(value: t.importa, onChanged: (v) => setState(() => t.importa = v ?? false)),
        title: Text(t.nome),
        subtitle: Text([
          '${t.elementi.length} ${t.elementi.length == 1 ? 'azione' : 'azioni'}',
          '${t.elementi.fold<int>(0, (n, a) => n + (a['indicatori'] as List).length)} indicatori',
          if (t.dati['struttura'] != null) 'nel documento: ${t.dati['struttura']}',
          if (presente != null) 'già presente',
          if (t.avvisi.isNotEmpty) '${t.avvisi.length} avvisi',
        ].join(' · ')),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DropdownButtonFormField<String?>(
            initialValue: t.struttura,
            isExpanded: true,
            decoration: InputDecoration(
              labelText: 'Struttura',
              helperText: t.dati['responsabile'] == null ? null : 'Responsabile nel documento: ${t.dati['responsabile']}',
              isDense: true,
            ),
            items: [
              const DropdownMenuItem<String?>(value: null, child: Text('Da scegliere')),
              for (final s in strutture)
                DropdownMenuItem<String?>(value: s['id'] as String, child: Text('${s['codice']} - ${s['descrizione']}', overflow: TextOverflow.ellipsis)),
            ],
            onChanged: (v) => setState(() => t.struttura = v),
          ),
          if (presente != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('Nel PIAO c\'è già l\'obiettivo ${[?presente['codice'], presente['titolo']].join(' - ')} '
                  '(${widget.dati.struttura(presente['struttura_id'])}): importandolo se ne crea un altro.',
                  style: TextStyle(color: tema.colorScheme.error)),
            ),
          if ((t.dati['descrizione'] as String?)?.isNotEmpty ?? false) ...[
            const SizedBox(height: 8),
            Text(t.dati['descrizione'] as String, maxLines: 6, overflow: TextOverflow.ellipsis),
          ],
          const SizedBox(height: 8),
          for (final a in t.elementi) ...[
            Text('• ${a['descrizione']} (entro il ${formatData(a['scadenza'] as String)})', style: const TextStyle(fontWeight: FontWeight.w600)),
            for (final i in (a['indicatori'] as List).cast<Map<String, dynamic>>())
              Padding(padding: const EdgeInsets.only(left: 16), child: Text('– ${testoIndicatore(i)}')),
          ],
          for (final a in t.avvisi)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Avviso: $a', style: TextStyle(color: tema.colorScheme.onSurfaceVariant)),
            ),
        ],
      ),
    );
  }

  void _seleziona(bool v) => setState(() {
        for (final t in _trovati) {
          t.importa = v;
        }
      });

  Widget _revisione() {
    final scelti = _trovati.where((t) => t.importa).length;
    return Column(children: [
      Expanded(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Text(_trovati.isEmpty
              ? 'Nel documento non sono stati trovati obiettivi.'
              : 'Trovati ${_trovati.length} obiettivi per il $_anno. Controlla la struttura di ciascuno e scegli quali importare: '
                  'gli impegni partono da 0% e si distribuiscono dopo. Il testo è trascritto dal documento: verificalo.'),
          for (final a in _avvisi)
            Padding(padding: const EdgeInsets.only(top: 4), child: Text('Avviso: $a', style: Theme.of(context).textTheme.bodySmall)),
          const SizedBox(height: 8),
          Wrap(spacing: 8, children: [
            TextButton(onPressed: () => _seleziona(true), child: const Text('Seleziona tutti')),
            TextButton(onPressed: () => _seleziona(false), child: const Text('Nessuno')),
          ]),
          for (final t in _trovati) _trovato(t),
        ]),
      ),
      const Divider(height: 1),
      Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          if (_errore != null) Expanded(child: Text(_errore!, style: TextStyle(color: Theme.of(context).colorScheme.error))) else const Spacer(),
          FilledButton.icon(
            icon: const Icon(Icons.save_outlined),
            label: Text(_salvataggio ? 'Salvataggio…' : 'Importa $scelti obiettivi'),
            onPressed: scelti == 0 || _salvataggio ? null : _salva,
          ),
        ]),
      ),
    ]);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text('Importa gli obiettivi nel ${widget.piao['titolo']}')),
        body: switch (_fase) {
          _Fase.fonte => _sceltaFonte(),
          _Fase.attesa => _inAttesa(),
          _Fase.revisione => _revisione(),
        },
      );
}
