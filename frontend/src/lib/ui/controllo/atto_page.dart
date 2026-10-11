import 'dart:async';

import 'package:flutter/material.dart';

import '../../util/download.dart';
import '../comuni.dart';
import '../verifica/pannello_verifica.dart';
import 'sessione_page.dart' show statiAtto;

const _esitiRevisione = ['CONFORME', 'NON_CONFORME', 'NON_APPLICABILE', 'DUBBIO'];

/// Revisione di un atto: testo a sinistra, proposta automatica e decisione a destra.
class AttoPage extends StatefulWidget {
  const AttoPage({super.key, required this.attoId});

  final String attoId;

  @override
  State<AttoPage> createState() => _AttoPageState();
}

class _AttoPageState extends State<AttoPage> {
  Map<String, dynamic>? _atto;
  String _testo = '';
  Map<String, dynamic>? _verifica;
  List<Map<String, dynamic>> _controllori = [];
  final Map<String, String> _esitoScelto = {};
  final Map<String, TextEditingController> _note = {};
  final _motivazione = TextEditingController();
  Timer? _polling;
  bool _caricamento = true;

  String get _base => '/api/v1/controllo/atti/${widget.attoId}';

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _polling?.cancel();
    _motivazione.dispose();
    for (final c in _note.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _carica() async {
    final api = apiDi(context);
    try {
      final risposte = await Future.wait([
        api.get(_base),
        api.get('$_base/testo'),
        api.get('/api/v1/verifiche', query: {'atto_controllato_id': widget.attoId}),
        api.get('/api/v1/controllo/controllori'),
      ]);
      _atto = risposte[0] as Map<String, dynamic>;
      _testo = (risposte[1] as Map<String, dynamic>)['testo'] as String;
      final verifiche = (risposte[2] as List).cast<Map<String, dynamic>>();
      _controllori = (risposte[3] as List).cast<Map<String, dynamic>>();
      _impostaVerifica(verifiche.isEmpty ? null : verifiche.first);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
    if (mounted) setState(() => _caricamento = false);
  }

  void _impostaVerifica(Map<String, dynamic>? v) {
    _verifica = v;
    if (v == null) return;
    if (v['stato'] == 'IN_CODA' || v['stato'] == 'IN_CORSO') {
      _avviaPolling();
      return;
    }
    // valori iniziali: esito finale se già revisionato, altrimenti proposta automatica
    final finale = (v['esito_finale'] as List?)?.cast<Map<String, dynamic>>();
    final proposta = (v['esito_automatico'] as List? ?? []).cast<Map<String, dynamic>>();
    for (final e in proposta) {
      final chiave = (e['elemento_id'] ?? e['titolo']).toString();
      final rev = finale?.where((f) => (f['elemento_id'] ?? f['titolo']).toString() == chiave).firstOrNull;
      final esito = (rev?['esito'] ?? e['esito']).toString();
      _esitoScelto[chiave] = _esitiRevisione.contains(esito) ? esito : 'DUBBIO';
      _note.putIfAbsent(chiave, () => TextEditingController()).text = (rev?['nota'] ?? '').toString();
    }
    _motivazione.text = (v['motivazione'] ?? '').toString();
  }

  void _avviaPolling() {
    _polling?.cancel();
    _polling = Timer.periodic(const Duration(seconds: 4), (_) async {
      if (!mounted || _verifica == null) return;
      try {
        final v = await apiDi(context).get('/api/v1/verifiche/${_verifica!['id']}') as Map<String, dynamic>;
        if (!mounted) return;
        if (v['stato'] == 'COMPLETATA' || v['stato'] == 'ERRORE') {
          _polling?.cancel();
          final atto = await apiDi(context).get(_base);
          _atto = atto as Map<String, dynamic>;
        }
        setState(() => _impostaVerifica(v));
      } catch (_) {
        // nuovo tentativo al prossimo giro
      }
    });
  }

  Future<void> _rianalizza() async {
    try {
      final v = await apiDi(context).post('/api/v1/verifiche', {'atto_controllato_id': widget.attoId});
      setState(() => _impostaVerifica(v as Map<String, dynamic>));
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _assegna(String? userId) async {
    try {
      final a = await apiDi(context).put('$_base/assegna', {'user_id': userId});
      setState(() => _atto = a as Map<String, dynamic>);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _salvaRevisione({required bool conclusa}) async {
    if (_motivazione.text.trim().isEmpty) {
      mostraErrore(context, 'Indicare la motivazione dell\'esito');
      return;
    }
    if (conclusa &&
        !await conferma(context, 'Concludere il controllo?', 'L\'esito non sarà più modificabile.')) {
      return;
    }
    if (!mounted) return;
    final proposta = (_verifica!['esito_automatico'] as List? ?? []).cast<Map<String, dynamic>>();
    try {
      final v = await apiDi(context).put('/api/v1/verifiche/${_verifica!['id']}/revisione', {
        'esiti': [
          for (final e in proposta)
            {
              'elemento_id': e['elemento_id'],
              'titolo': e['titolo'],
              'esito': _esitoScelto[(e['elemento_id'] ?? e['titolo']).toString()] ?? 'DUBBIO',
              'nota': _note[(e['elemento_id'] ?? e['titolo']).toString()]?.text,
            },
        ],
        'motivazione': _motivazione.text.trim(),
        'conclusa': conclusa,
      });
      final atto = await apiDi(context).get(_base);
      setState(() {
        _atto = atto as Map<String, dynamic>;
        _impostaVerifica(v as Map<String, dynamic>);
      });
      if (mounted) mostraMessaggio(context, conclusa ? 'Controllo concluso' : 'Revisione salvata');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _colonnaVerifica() {
    final v = _verifica;
    if (v == null) {
      return Sezione(
        titolo: 'Analisi',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Nessuna analisi eseguita.'),
          const SizedBox(height: 8),
          FilledButton(onPressed: _rianalizza, child: const Text('Avvia analisi')),
        ]),
      );
    }
    if (v['stato'] != 'COMPLETATA') {
      return Column(children: [
        StatoVerificaBanner(verifica: v),
        if (v['stato'] == 'ERRORE') FilledButton(onPressed: _rianalizza, child: const Text('Riprova')),
      ]);
    }
    final chiuso = _atto?['stato'] == 'CHIUSO';
    final proposta = (v['esito_automatico'] as List? ?? []).cast<Map<String, dynamic>>();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PannelloRiferimenti(esito: Map<String, dynamic>.from(v['esito_riferimenti'] as Map)),
      Sezione(
        titolo: 'Checklist: proposta automatica e decisione',
        azioni: [
          if (v['modello_llm'] != null)
            Tooltip(message: 'Proposta del modello ${v['modello_llm']}', child: const Icon(Icons.smart_toy_outlined)),
        ],
        child: proposta.isEmpty
            ? const Text('Nessuna checklist per questa tipologia di atto.')
            : Column(children: [
                for (final e in proposta)
                  SchedaEsito(
                    esito: e,
                    extra: Builder(builder: (context) {
                      final chiave = (e['elemento_id'] ?? e['titolo']).toString();
                      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        SizedBox(
                          width: 200,
                          child: DropdownButtonFormField<String>(
                            value: _esitoScelto[chiave],
                            decoration: const InputDecoration(labelText: 'Esito del controllore', isDense: true),
                            items: [
                              for (final x in _esitiRevisione)
                                DropdownMenuItem(value: x, child: Text(etichettaEsito(x))),
                            ],
                            onChanged: chiuso ? null : (x) => setState(() => _esitoScelto[chiave] = x!),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: TextField(
                            controller: _note.putIfAbsent(chiave, () => TextEditingController()),
                            enabled: !chiuso,
                            decoration: const InputDecoration(labelText: 'Nota', isDense: true),
                          ),
                        ),
                      ]);
                    }),
                  ),
              ]),
      ),
      Sezione(
        titolo: 'Esito del controllo',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TextField(
            controller: _motivazione,
            enabled: !chiuso,
            minLines: 3,
            maxLines: 8,
            decoration: const InputDecoration(labelText: 'Motivazione (obbligatoria)', alignLabelWithHint: true),
          ),
          const SizedBox(height: 12),
          if (!chiuso)
            Wrap(spacing: 8, children: [
              OutlinedButton(onPressed: () => _salvaRevisione(conclusa: false), child: const Text('Salva bozza')),
              FilledButton(onPressed: () => _salvaRevisione(conclusa: true), child: const Text('Concludi controllo')),
              TextButton.icon(
                  onPressed: _rianalizza, icon: const Icon(Icons.refresh), label: const Text('Rianalizza')),
            ])
          else
            const Text('Controllo concluso.'),
        ]),
      ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    if (_caricamento || _atto == null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(child: _caricamento ? const CircularProgressIndicator() : const Text('Atto non disponibile')),
      );
    }
    final a = _atto!;
    final testo = Sezione(
      titolo: 'Testo dell\'atto',
      azioni: [
        IconButton(
          tooltip: 'Scarica il file originale',
          icon: const Icon(Icons.download),
          onPressed: () async {
            try {
              await salvaFile(apiDi(context), '$_base/file', a['file_nome'].toString());
            } catch (e) {
              if (context.mounted) mostraErrore(context, e);
            }
          },
        ),
      ],
      child: SelectableText(_testo),
    );
    return Scaffold(
      appBar: AppBar(
        title: Text('${a['numero_registro'] ?? 's.n.'} · ${a['oggetto'] ?? a['file_nome']}'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Chip(label: Text(statiAtto[a['stato']] ?? a['stato'].toString())),
          ),
          SizedBox(
            width: 240,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              child: DropdownButtonFormField<String?>(
                value: a['assegnato_a'] as String?,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Assegnato a', isDense: true),
                items: [
                  const DropdownMenuItem<String?>(value: null, child: Text('Nessuno')),
                  for (final c in _controllori)
                    DropdownMenuItem<String?>(
                        value: c['id'] as String, child: Text((c['nome_completo'] ?? c['username']).toString())),
                ],
                onChanged: _assegna,
              ),
            ),
          ),
        ],
      ),
      body: LayoutBuilder(builder: (context, vincoli) {
        if (vincoli.maxWidth < 1000) {
          return ListView(padding: const EdgeInsets.all(16), children: [_colonnaVerifica(), testo]);
        }
        return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: ListView(padding: const EdgeInsets.all(16), children: [testo])),
          const VerticalDivider(width: 1),
          Expanded(child: ListView(padding: const EdgeInsets.all(16), children: [_colonnaVerifica()])),
        ]);
      }),
    );
  }
}
