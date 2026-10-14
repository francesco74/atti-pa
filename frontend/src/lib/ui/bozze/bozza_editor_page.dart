import 'dart:async';

import 'package:flutter/material.dart';

import '../../util/download.dart';
import '../comuni.dart';
import '../verifica/pannello_verifica.dart';
import 'scelta_riferimenti.dart';

/// Wizard di redazione: dati generali, contenuto, riferimenti normativi, verifica.
class BozzaEditorPage extends StatefulWidget {
  const BozzaEditorPage({super.key, this.bozzaId});

  final String? bozzaId;

  @override
  State<BozzaEditorPage> createState() => _BozzaEditorPageState();
}

class _BozzaEditorPageState extends State<BozzaEditorPage> {
  String? _id;
  int _passo = 0;
  bool _caricamento = true;
  bool _salvataggio = false;
  bool _modificata = false;

  final _oggetto = TextEditingController();
  String? _tipologia;
  String? _templateId;
  DateTime? _dataAdozione;
  final Map<String, TextEditingController> _campi = {};
  List<Map<String, dynamic>> _riferimenti = [];
  String _testo = '';

  List<Map<String, dynamic>> _tipologie = [];
  List<Map<String, dynamic>> _templates = [];

  Map<String, dynamic>? _controllo;
  Map<String, dynamic>? _verifica;
  Timer? _polling;

  static const _campiLiberi = [
    {'nome': 'premesse', 'etichetta': 'Premesse', 'tipo': 'testo_lungo', 'obbligatorio': true},
    {'nome': 'motivazione', 'etichetta': 'Motivazione', 'tipo': 'testo_lungo', 'obbligatorio': true},
    {'nome': 'dispositivo', 'etichetta': 'Dispositivo', 'tipo': 'testo_lungo', 'obbligatorio': true},
  ];

  @override
  void initState() {
    super.initState();
    _id = widget.bozzaId;
    _oggetto.addListener(_segnaModifica);
    _inizializza();
  }

  @override
  void dispose() {
    _polling?.cancel();
    _oggetto.dispose();
    for (final c in _campi.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _segnaModifica() => _modificata = true;

  Future<void> _inizializza() async {
    final api = apiDi(context);
    try {
      _tipologie = List<Map<String, dynamic>>.from(await api.get('/api/v1/tipologie') as List);
      if (_id != null) {
        final b = await api.get('/api/v1/bozze/$_id') as Map<String, dynamic>;
        _oggetto.text = b['oggetto'] as String;
        _tipologia = b['tipologia_atto'] as String;
        _templateId = b['template_id'] as String?;
        _dataAdozione = daIso(b['data_adozione_prevista'] as String?);
        _riferimenti = List<Map<String, dynamic>>.from(b['riferimenti_json'] as List);
        _testo = (b['contenuto_testo'] as String?) ?? '';
        (b['dati_json'] as Map<String, dynamic>).forEach((k, v) => _campo(k).text = v?.toString() ?? '');
        await _caricaTemplates();
        _modificata = false;
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
    if (mounted) setState(() => _caricamento = false);
  }

  TextEditingController _campo(String nome) =>
      _campi.putIfAbsent(nome, () => TextEditingController()..addListener(_segnaModifica));

  Future<void> _caricaTemplates() async {
    if (_tipologia == null) return;
    final lista = await apiDi(context).get('/api/v1/templates', query: {'tipologia': _tipologia!});
    _templates = List<Map<String, dynamic>>.from(lista as List);
    if (_templateId != null && !_templates.any((t) => t['id'] == _templateId)) _templateId = null;
  }

  List<Map<String, dynamic>> get _definizioneCampi {
    final t = _templates.where((t) => t['id'] == _templateId).firstOrNull;
    if (t == null) return _campiLiberi.map((c) => Map<String, dynamic>.from(c)).toList();
    return List<Map<String, dynamic>>.from(t['campi_json'] as List);
  }

  Map<String, dynamic> _corpo() => {
        'oggetto': _oggetto.text.trim(),
        'tipologia_atto': _tipologia,
        'template_id': _templateId,
        'data_adozione_prevista': _dataAdozione == null ? null : isoData(_dataAdozione!),
        'dati': {for (final c in _definizioneCampi) c['nome']: _campo(c['nome'] as String).text},
        'riferimenti': _riferimenti,
      };

  Future<bool> _salva({bool silenzioso = false}) async {
    if (_oggetto.text.trim().length < 3 || _tipologia == null) {
      mostraErrore(context, 'Indicare oggetto e tipologia di atto');
      setState(() => _passo = 0);
      return false;
    }
    setState(() => _salvataggio = true);
    final api = apiDi(context);
    try {
      final b = (_id == null
          ? await api.post('/api/v1/bozze', _corpo())
          : await api.put('/api/v1/bozze/$_id', _corpo())) as Map<String, dynamic>;
      _id = b['id'] as String;
      _testo = (b['contenuto_testo'] as String?) ?? '';
      _riferimenti = List<Map<String, dynamic>>.from(b['riferimenti_json'] as List);
      _modificata = false;
      if (!silenzioso && mounted) mostraMessaggio(context, 'Bozza salvata');
      return true;
    } catch (e) {
      if (mounted) mostraErrore(context, e);
      return false;
    } finally {
      if (mounted) setState(() => _salvataggio = false);
    }
  }

  Future<void> _controlloRapido() async {
    if (!await _salva(silenzioso: true)) return;
    if (!mounted) return;
    try {
      final r = await apiDi(context).get('/api/v1/bozze/$_id/controllo-rapido');
      setState(() => _controllo = r as Map<String, dynamic>);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _verificaCompleta() async {
    if (!await _salva(silenzioso: true)) return;
    if (!mounted) return;
    try {
      final v = await apiDi(context).post('/api/v1/verifiche', {'bozza_id': _id});
      setState(() => _verifica = v as Map<String, dynamic>);
      _avviaPolling();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  void _avviaPolling() {
    _polling?.cancel();
    _polling = Timer.periodic(const Duration(seconds: 3), (_) async {
      if (!mounted || _verifica == null) return;
      try {
        final v = await apiDi(context).get('/api/v1/verifiche/${_verifica!['id']}');
        if (!mounted) return;
        setState(() => _verifica = v as Map<String, dynamic>);
        if (v['stato'] == 'COMPLETATA' || v['stato'] == 'ERRORE') _polling?.cancel();
      } catch (_) {
        // nuovo tentativo al prossimo giro
      }
    });
  }

  Future<void> _scarica(String formato, {bool omissis = false}) async {
    if (_templateId == null) {
      mostraErrore(context, 'Scegliere un template per generare il documento');
      return;
    }
    if (_modificata && !await _salva(silenzioso: true)) return;
    if (!mounted) return;
    try {
      await salvaFile(
        apiDi(context),
        '/api/v1/bozze/$_id/documento',
        'determina${omissis ? '-omissis' : ''}.${formato == 'odt' ? 'odt' : 'pdf'}',
        query: {'formato': formato, 'omissis': omissis.toString()},
      );
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _espandi(Map<String, dynamic> definizione) async {
    final controller = _campo(definizione['nome'] as String);
    final appunti = TextEditingController(text: controller.text);
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Riscrivi «${definizione['etichetta']}»'),
        content: SizedBox(
          width: 560,
          child: TextField(
            controller: appunti,
            maxLines: 8,
            decoration: const InputDecoration(
              hintText: 'Scrivi gli appunti: il modello li trasforma in testo amministrativo '
                  'senza aggiungere fatti, importi o norme.',
            ),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton.icon(
            onPressed: () => Navigator.pop(c, true),
            icon: const Icon(Icons.auto_fix_high),
            label: const Text('Riscrivi'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final r = await apiDi(context).post('/api/v1/bozze/espandi', {
        'sezione': definizione['etichetta'],
        'appunti': appunti.text,
        'oggetto': _oggetto.text,
      });
      controller.text = (r as Map<String, dynamic>)['testo'] as String;
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      appunti.dispose();
    }
  }

  Future<void> _aggiungiRiferimenti() async {
    final scelti = await showDialog<List<Map<String, dynamic>>>(
      context: context,
      builder: (_) => SceltaRiferimentiDialog(tipologia: _tipologia),
    );
    if (scelti == null || scelti.isEmpty) return;
    setState(() {
      for (final r in scelti) {
        final doppio = _riferimenti.any((x) =>
            x['urn_atto'] == r['urn_atto'] &&
            x['articolo'] == r['articolo'] &&
            x['comma'] == r['comma'] &&
            x['lettera'] == r['lettera']);
        if (!doppio) _riferimenti.add(r);
      }
      _modificata = true;
    });
  }

  // --- Passi ------------------------------------------------------------------------

  Widget _passoGenerale() {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      TextField(
        controller: _oggetto,
        maxLines: 2,
        decoration: const InputDecoration(labelText: 'Oggetto della determinazione'),
      ),
      const SizedBox(height: 12),
      DropdownButtonFormField<String>(
        initialValue: _tipologia,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'Tipologia di atto'),
        items: [
          for (final t in _tipologie)
            DropdownMenuItem(value: t['codice'] as String, child: Text(t['descrizione'] as String)),
        ],
        onChanged: (v) async {
          setState(() {
            _tipologia = v;
            _templateId = null;
            _templates = [];
            _modificata = true;
          });
          try {
            await _caricaTemplates();
          } catch (e) {
            if (mounted) mostraErrore(context, e);
          }
          if (mounted) setState(() {});
        },
      ),
      const SizedBox(height: 12),
      DropdownButtonFormField<String?>(
        initialValue: _templateId,
        isExpanded: true,
        decoration: const InputDecoration(
          labelText: 'Template',
          helperText: 'Il template determina i campi da compilare e il documento finale',
        ),
        items: [
          const DropdownMenuItem<String?>(value: null, child: Text('Nessun template (testo libero)')),
          for (final t in _templates)
            DropdownMenuItem<String?>(
                value: t['id'] as String, child: Text('${t['nome']} (v${t['versione']})')),
        ],
        onChanged: (v) => setState(() {
          _templateId = v;
          _modificata = true;
        }),
      ),
      const SizedBox(height: 12),
      InputDecorator(
        decoration: const InputDecoration(
          labelText: 'Data di adozione prevista',
          helperText: 'I riferimenti normativi sono verificati alla norma vigente in questa data',
        ),
        child: Row(children: [
          Expanded(child: Text(_dataAdozione == null ? 'Oggi' : formatData(isoData(_dataAdozione!)))),
          TextButton(
            onPressed: () async {
              final d = await scegliData(context, _dataAdozione);
              if (d != null) {
                setState(() {
                  _dataAdozione = d;
                  _modificata = true;
                });
              }
            },
            child: const Text('Scegli'),
          ),
        ]),
      ),
    ]);
  }

  Widget _passoContenuto() {
    final definizioni = _definizioneCampi;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final d in definizioni) ...[
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: TextField(
              controller: _campo(d['nome'] as String),
              minLines: d['tipo'] == 'testo_lungo' ? 4 : 1,
              maxLines: d['tipo'] == 'testo_lungo' ? 12 : 1,
              keyboardType: d['tipo'] == 'importo' || d['tipo'] == 'numero'
                  ? const TextInputType.numberWithOptions(decimal: true)
                  : TextInputType.text,
              decoration: InputDecoration(
                labelText: '${d['etichetta']}${d['obbligatorio'] == true ? ' *' : ''}',
                helperText: d['aiuto'] as String?,
                alignLabelWithHint: true,
              ),
            ),
          ),
          if (d['tipo'] == 'testo_lungo')
            IconButton(
              tooltip: 'Riscrivi dagli appunti (IA)',
              icon: const Icon(Icons.auto_fix_high),
              onPressed: () => _espandi(d),
            ),
        ]),
        const SizedBox(height: 12),
      ],
    ]);
  }

  Widget _passoRiferimenti() {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (_riferimenti.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 8),
          child: Text('Nessun riferimento. Aggiungili dalla libreria normativa.'),
        ),
      ReorderableListView(
        shrinkWrap: true,
        buildDefaultDragHandles: true,
        physics: const NeverScrollableScrollPhysics(),
        onReorderItem: (da, a) => setState(() {
          _riferimenti.insert(a, _riferimenti.removeAt(da));
          _modificata = true;
        }),
        children: [
          for (var i = 0; i < _riferimenti.length; i++)
            ListTile(
              key: ValueKey('${_riferimenti[i]['urn_atto']}|${_riferimenti[i]['articolo']}|'
                  '${_riferimenti[i]['comma']}|${_riferimenti[i]['lettera']}'),
              leading: const Icon(Icons.balance),
              title: Text('Visto l\'${_riferimenti[i]['citazione'] ?? _citazioneProvvisoria(_riferimenti[i])};'),
              trailing: IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => setState(() {
                  _riferimenti.removeAt(i);
                  _modificata = true;
                }),
              ),
            ),
        ],
      ),
      const SizedBox(height: 8),
      Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton.icon(
          onPressed: _aggiungiRiferimenti,
          icon: const Icon(Icons.add),
          label: const Text('Aggiungi riferimenti'),
        ),
      ),
    ]);
  }

  String _citazioneProvvisoria(Map<String, dynamic> r) =>
      'art. ${r['articolo']}${r['comma'] != null ? ', comma ${r['comma']}' : ''}'
      '${r['lettera'] != null ? ', lett. ${r['lettera']})' : ''} (${r['urn_atto']})';

  Widget _passoVerifica() {
    final esitiChecklist = _verifica?['stato'] == 'COMPLETATA'
        ? List<Map<String, dynamic>>.from(_verifica!['esito_automatico'] as List? ?? [])
        : <Map<String, dynamic>>[];
    final controlli = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Wrap(spacing: 8, runSpacing: 8, children: [
        FilledButton.tonalIcon(
          onPressed: _controlloRapido,
          icon: const Icon(Icons.rule),
          label: const Text('Controllo rapido'),
        ),
        FilledButton.icon(
          onPressed: _verificaCompleta,
          icon: const Icon(Icons.fact_check),
          label: const Text('Verifica con checklist'),
        ),
      ]),
      const SizedBox(height: 12),
      if (_verifica != null) StatoVerificaBanner(verifica: _verifica!),
      if (_verifica?['stato'] == 'COMPLETATA') ...[
        PannelloRiferimenti(esito: Map<String, dynamic>.from(_verifica!['esito_riferimenti'] as Map)),
        PannelloChecklist(esiti: esitiChecklist, modello: _verifica!['modello_llm'] as String?),
      ] else if (_controllo != null)
        PannelloRiferimenti(esito: _controllo!),
      Sezione(
        titolo: 'Documento',
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          OutlinedButton(onPressed: () => _scarica('odt'), child: const Text('ODT')),
          OutlinedButton(onPressed: () => _scarica('pdf'), child: const Text('PDF')),
          OutlinedButton(onPressed: () => _scarica('pdfa'), child: const Text('PDF/A')),
          OutlinedButton.icon(
            onPressed: () => _scarica('pdfa', omissis: true),
            icon: const Icon(Icons.visibility_off, size: 18),
            label: const Text('PDF/A con omissis'),
          ),
        ]),
      ),
    ]);

    final anteprima = Sezione(
      titolo: 'Anteprima del testo',
      child: SelectableText(_testo.isEmpty ? 'Salva la bozza per vedere il testo.' : _testo),
    );

    return LayoutBuilder(builder: (context, vincoli) {
      if (vincoli.maxWidth < 900) {
        return Column(children: [controlli, anteprima]);
      }
      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: anteprima),
        const SizedBox(width: 16),
        Expanded(child: controlli),
      ]);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_caricamento) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final passi = [
      Step(title: const Text('Dati generali'), content: _passoGenerale(), isActive: _passo >= 0),
      Step(title: const Text('Contenuto'), content: _passoContenuto(), isActive: _passo >= 1),
      Step(title: const Text('Riferimenti normativi'), content: _passoRiferimenti(), isActive: _passo >= 2),
      Step(title: const Text('Verifica e documento'), content: _passoVerifica(), isActive: _passo >= 3),
    ];
    return PopScope(
      canPop: !_modificata,
      onPopInvokedWithResult: (fatto, _) async {
        if (fatto) return;
        final esci = await conferma(context, 'Modifiche non salvate', 'Uscire senza salvare?');
        if (esci && context.mounted) {
          _modificata = false;
          Navigator.of(context).pop();
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(_id == null ? 'Nuova determina' : 'Modifica determina'),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: FilledButton.icon(
                onPressed: _salvataggio ? null : () => _salva(),
                icon: _salvataggio
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.save),
                label: const Text('Salva'),
              ),
            ),
          ],
        ),
        body: Stepper(
          currentStep: _passo,
          onStepTapped: (i) => setState(() => _passo = i),
          onStepContinue: () async {
            if (_passo == 2) await _controlloRapido();
            if (_passo < passi.length - 1) setState(() => _passo += 1);
          },
          onStepCancel: _passo == 0 ? null : () => setState(() => _passo -= 1),
          controlsBuilder: (context, dettagli) => Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Row(children: [
              if (_passo < passi.length - 1)
                FilledButton(onPressed: dettagli.onStepContinue, child: const Text('Avanti')),
              const SizedBox(width: 8),
              if (_passo > 0)
                TextButton(onPressed: dettagli.onStepCancel, child: const Text('Indietro')),
            ]),
          ),
          steps: passi,
        ),
      ),
    );
  }
}
