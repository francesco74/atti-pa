import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../../util/scelta_file.dart';
import '../comuni.dart';
import 'art35.dart';
import 'comune.dart';

/// Importazione dei procedimenti (art. 35) dalla pagina "Tipologie di procedimento" del sito di
/// Amministrazione trasparente o da documenti (Word, ODT, PDF, fogli di calcolo). La lettura la
/// fa il worker con l'estrazione della trasparenza: il modello trascrive i dati, non li inventa.
/// Poi, per ogni procedimento trovato, si sceglie se aggiornarne uno della mappatura o crearne
/// uno nuovo, quali dati prendere e a quali strutture corrispondono gli uffici. Si salva con le
/// API della mappatura (e, per l'amministratore, delle strutture).
class ImportaProcedimentiPage extends StatefulWidget {
  const ImportaProcedimentiPage({super.key, required this.dati});

  final DatiAnticorruzione dati;

  @override
  State<ImportaProcedimentiPage> createState() => _ImportaProcedimentiPageState();
}

const _estensioni = ['pdf', 'doc', 'docx', 'odt', 'xls', 'xlsx', 'ods', 'csv'];

/// Campi del procedimento (processo) e dati art. 35 di testo che si possono prendere dalla fonte.
const _campiProcesso = {
  'denominazione': 'Denominazione',
  'descrizione': 'Descrizione',
  'riferimenti_normativi': 'Riferimenti normativi',
  'termine_conclusione': 'Termine di conclusione',
};
const _daSchedaAProcesso = {'riferimenti_normativi': 'norma_riferimento'};
const _campiArt35 = [
  'tipologia', 'istanza_di_parte', 'ist_modulistica', 'modalita_info', 'dichiarazione_sostitutiva', 'silenzio_assenso',
  'strumenti_tutela', 'servizio_online_link', 'servizio_online_tempi', 'link_pagamenti', 'sost_attivazione',
];

/// Recapiti delle strutture che la fonte può completare: campo della scheda -> campo della struttura.
const _recapiti = {
  'uff_resp_struttura_id': {'uff_resp_tel': 'telefono', 'uff_resp_peo': 'peo', 'uff_resp_pec': 'pec'},
  'uff_finale_struttura_id': {
    'uff_finale_resp': 'responsabile', 'uff_finale_tel': 'telefono', 'uff_finale_peo': 'peo', 'uff_finale_pec': 'pec',
  },
  'ist_struttura_id': {'ist_indirizzo': 'sede', 'ist_telefono': 'telefono', 'ist_peo': 'peo', 'ist_pec': 'pec'},
  'sost_struttura_id': {
    'sost_nominativo': 'responsabile', 'sost_qualifica': 'qualifica', 'sost_tel': 'telefono', 'sost_peo': 'peo', 'sost_pec': 'pec',
  },
};

const _ruoliUffici = {
  'struttura_id': 'Unità responsabile dell\'istruttoria (struttura del procedimento)',
  'uff_resp_struttura_id': 'Ufficio responsabile del procedimento',
  'uff_finale_struttura_id': 'Ufficio del provvedimento finale',
  'ist_struttura_id': 'Ufficio per informazioni e istanze',
  'sost_struttura_id': 'Ufficio del potere sostitutivo',
};

/// Un procedimento trovato nella fonte, con le scelte della revisione.
class _Trovato {
  _Trovato(Map<String, dynamic> j)
      : elemento = (j['elemento'] as Map).cast<String, dynamic>(),
        destinazione = j['procedimento_id'] as String?,
        uffici = {
          for (final e in (j['uffici'] as Map? ?? const {}).entries)
            e.key as String: ((e.value as Map)['nome'] as String, (e.value as Map)['struttura_id'] as String?),
        };

  final Map<String, dynamic> elemento;
  bool importa = true;
  String? destinazione; // procedimento della mappatura; null: nuovo
  String? area; // per un nuovo procedimento
  final Map<String, (String, String?)> uffici; // ruolo -> (nome nella fonte, struttura scelta)
  final Set<String> campi = {}; // campi da prendere dalla fonte
  String? esito;

  String valore(String k) => '${elemento[k] ?? ''}'.trim();
}

enum _Fase { fonte, attesa, revisione, fatto }

class _ImportaProcedimentiPageState extends State<ImportaProcedimentiPage> {
  var _fase = _Fase.fonte;
  final _url = TextEditingController();
  bool _seguiLink = true, _analizzaPdf = false;
  int _maxLink = linkPredefiniti;
  List<FileScelto> _files = [];
  String? _lavoroId, _errore;
  Timer? _attesa;
  List<_Trovato> _trovati = [];
  List<String> _avvisi = [];
  Map<String, Map<String, dynamic>> _procedimenti = {}; // della mappatura, per id
  bool _completaRecapiti = true;
  bool _inCorso = false;

  bool get _amministratore => context.read<AuthState>().utente?.isAdmin ?? false;

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
      final opzioni = {'segui_link': _seguiLink, 'max_link': _maxLink, 'analizza_pdf': _analizzaPdf};
      final r = _files.isEmpty
          ? await api.post('$apiAnticorruzione/procedimenti/importazioni', {'url': _url.text.trim(), ...opzioni})
          : await api.postMultipartFiles('$apiAnticorruzione/procedimenti/importazioni',
              campi: {'dati': jsonEncode(<String, Object>{})},
              campoFile: 'file',
              files: [for (final f in _files) (f.name, f.bytes)]);
      _lavoroId = (r as Map)['id'] as String;
      setState(() => _fase = _Fase.attesa);
      _attesa = Timer.periodic(const Duration(seconds: 3), (_) => _controlla());
    } catch (e) {
      if (mounted) setState(() => _errore = '$e');
    }
  }

  Future<void> _controlla() async {
    try {
      final api = apiDi(context);
      final r = await api.get('$apiAnticorruzione/procedimenti/importazioni/$_lavoroId') as Map<String, dynamic>;
      if (r['stato'] == 'ERRORE') {
        _attesa?.cancel();
        if (mounted) {
          setState(() {
            _fase = _Fase.fonte;
            _errore = 'Lettura non riuscita: ${r['errore'] ?? 'errore sconosciuto'}';
          });
        }
      } else if (r['stato'] == 'COMPLETATA') {
        _attesa?.cancel();
        final procedimenti = await api.get('$apiAnticorruzione/processi', query: {'tipo': 'PROCEDIMENTO'}) as List;
        if (!mounted) return;
        setState(() {
          _procedimenti = {for (final p in procedimenti.cast<Map<String, dynamic>>()) p['id'] as String: p};
          _trovati = [for (final p in (r['procedimenti'] as List? ?? const [])) _Trovato((p as Map).cast<String, dynamic>())];
          _avvisi = List<String>.from(r['avvisi'] as List? ?? const []);
          for (final t in _trovati) {
            _sceltePredefinite(t);
          }
          _fase = _Fase.revisione;
        });
      }
    } catch (_) {
      // nuovo tentativo al prossimo giro
    }
  }

  /// Valore attuale nella mappatura del campo [k] (della scheda) per il procedimento [id].
  String _attuale(String? id, String k) {
    final p = id == null ? null : _procedimenti[id];
    if (p == null) return '';
    if (_campiProcesso.containsKey(k)) return '${p[_daSchedaAProcesso[k] ?? k] ?? ''}'.trim();
    return '${(p['art35'] as Map?)?[k] ?? ''}'.trim();
  }

  /// Si propone di prendere i dati presenti nella fonte e diversi da quelli della mappatura;
  /// la denominazione di un procedimento esistente resta quella della mappatura.
  void _sceltePredefinite(_Trovato t) {
    t.campi
      ..clear()
      ..addAll([
        for (final k in [..._campiProcesso.keys, ..._campiArt35])
          if (t.valore(k).isNotEmpty && t.valore(k) != _attuale(t.destinazione, k) && !(k == 'denominazione' && t.destinazione != null)) k,
      ]);
  }

  Map<String, dynamic>? _struttura(String? id) => widget.dati.strutture.where((s) => s['id'] == id).firstOrNull;

  /// Recapiti vuoti delle strutture che la fonte completa: id struttura -> {campo: valore}.
  Map<String, Map<String, String>> _recapitiDaCompletare() {
    final risultato = <String, Map<String, String>>{};
    for (final t in _trovati.where((t) => t.importa)) {
      for (final MapEntry(key: ruolo, value: mappa) in _recapiti.entries) {
        final id = t.uffici[ruolo]?.$2;
        final s = _struttura(id);
        if (s == null) continue;
        for (final MapEntry(key: daScheda, value: campo) in mappa.entries) {
          final v = t.valore(daScheda);
          if (v.isNotEmpty && '${s[campo] ?? ''}'.trim().isEmpty) risultato.putIfAbsent(id!, () => {})[campo] ??= v;
        }
        if (ruolo == 'ist_struttura_id' && (s['orari'] as List? ?? const []).isEmpty && (t.elemento['orari'] as List? ?? const []).isNotEmpty) {
          risultato.putIfAbsent(id!, () => {})['orari'] ??= jsonEncode(t.elemento['orari']);
        }
      }
    }
    return risultato;
  }

  Future<void> _applica() async {
    final api = apiDi(context);
    setState(() => _inCorso = true);
    for (final t in _trovati.where((t) => t.importa)) {
      try {
        final attuale = t.destinazione == null ? null : _procedimenti[t.destinazione];
        final art35 = <String, dynamic>{...?(attuale?['art35'] as Map?)?.cast<String, dynamic>()};
        for (final k in _campiArt35.where(t.campi.contains)) {
          art35[k] = t.valore(k);
        }
        for (final ruolo in _ruoliUffici.keys.where((r) => r != 'struttura_id')) {
          final scelta = t.uffici[ruolo]?.$2;
          if (scelta != null) art35[ruolo] = scelta;
        }
        final corpo = <String, dynamic>{
          'tipo': 'PROCEDIMENTO',
          'area_id': attuale == null ? t.area : attuale['area_id'],
          for (final k in const ['denominazione', 'descrizione', 'tempi', 'attori_esterni', 'termine_conclusione', 'norma_riferimento'])
            k: attuale?[k],
          'struttura_id': t.uffici['struttura_id']?.$2 ?? attuale?['struttura_id'],
          'art35': art35,
        };
        for (final k in _campiProcesso.keys.where(t.campi.contains)) {
          corpo[_daSchedaAProcesso[k] ?? k] = t.valore(k);
        }
        if ((corpo['denominazione'] as String?)?.trim().isEmpty ?? true) corpo['denominazione'] = t.valore('denominazione');
        if (attuale == null) {
          await api.post('$apiAnticorruzione/processi', corpo);
          t.esito = 'Creato';
        } else {
          await api.put('$apiAnticorruzione/processi/${attuale['id']}', corpo);
          t.esito = 'Aggiornato';
        }
      } catch (e) {
        t.esito = 'Non salvato: $e';
      }
    }
    if (_completaRecapiti && _amministratore) {
      for (final MapEntry(key: id, value: valori) in _recapitiDaCompletare().entries) {
        final s = _struttura(id)!;
        try {
          await api.put('/api/v1/ente/strutture/$id', {
            ...s,
            for (final e in valori.entries) e.key: e.key == 'orari' ? jsonDecode(e.value) : e.value,
          });
        } catch (e) {
          _avvisi.add('Recapiti di ${s['codice']} non aggiornati: $e');
        }
      }
    }
    if (mounted) {
      setState(() {
        _fase = _Fase.fatto;
        _inCorso = false;
      });
    }
  }

  // --- fasi --------------------------------------------------------------------------------

  Widget _fonte() => ListView(padding: const EdgeInsets.all(16), children: [
        Sezione(
          titolo: 'Da dove leggere i procedimenti',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Indica la pagina "Tipologie di procedimento" della sezione Amministrazione trasparente del sito '
                'dell\'ente, oppure carica i documenti in cui l\'ente descrive i suoi procedimenti (Word, ODT, PDF, fogli di '
                'calcolo). I dati vengono letti e trascritti così come sono: nulla si salva senza la tua conferma.'),
            const SizedBox(height: 12),
            TextField(
              controller: _url,
              enabled: _files.isEmpty,
              decoration: const InputDecoration(labelText: 'Indirizzo della pagina', hintText: 'https://www.ente.it/amministrazione-trasparente/...'),
              onChanged: (_) => setState(() {}),
            ),
            SceltaLink(
              titolo: 'Segui i link alle pagine di dettaglio dei procedimenti',
              segui: _seguiLink,
              numero: _maxLink,
              onSegui: _files.isEmpty ? (v) => setState(() => _seguiLink = v) : null,
              onNumero: (v) => setState(() => _maxLink = v),
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: _analizzaPdf,
              onChanged: _files.isEmpty ? (v) => setState(() => _analizzaPdf = v ?? false) : null,
              title: const Text('Leggi anche i PDF collegati'),
            ),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              OutlinedButton.icon(
                icon: const Icon(Icons.upload_file),
                label: const Text('Oppure scegli i documenti'),
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
            if (_errore != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_errore!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
            const SizedBox(height: 16),
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.icon(
                icon: const Icon(Icons.play_arrow),
                label: const Text('Leggi i procedimenti'),
                onPressed: _files.isEmpty && !_url.text.trim().startsWith('http') ? null : _avvia,
              ),
            ),
          ]),
        ),
      ]);

  Widget _scelteUffici(_Trovato t) {
    final scelte = [
      const DropdownMenuItem<String?>(value: null, child: Text('Nessuna (non abbinare)')),
      for (final s in widget.dati.strutture)
        if (s['attiva'] != false) DropdownMenuItem<String?>(value: s['id'] as String, child: Text('${s['codice']} - ${s['descrizione']}', overflow: TextOverflow.ellipsis)),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final MapEntry(key: ruolo, value: (nome, scelta)) in t.uffici.entries)
        if (_ruoliUffici.containsKey(ruolo))
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: DropdownButtonFormField<String?>(
              initialValue: scelta,
              isExpanded: true,
              decoration: InputDecoration(labelText: '${_ruoliUffici[ruolo]} - nella fonte: "$nome"', isDense: true),
              items: scelte,
              onChanged: (v) => setState(() => t.uffici[ruolo] = (nome, v)),
            ),
          ),
    ]);
  }

  Widget _campi(_Trovato t) {
    final tema = Theme.of(context);
    final righe = [
      for (final k in [..._campiProcesso.keys, ..._campiArt35])
        if (t.valore(k).isNotEmpty) k,
    ];
    if (righe.isEmpty) return const Text('Nessun dato da prendere.');
    return Column(children: [
      for (final k in righe)
        CheckboxListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          value: t.campi.contains(k),
          onChanged: (v) => setState(() => v == true ? t.campi.add(k) : t.campi.remove(k)),
          title: Text(_campiProcesso[k] ?? etichetteArt35[k] ?? k, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (t.destinazione != null)
              Text('Ora: ${_attuale(t.destinazione, k).isEmpty ? '—' : _attuale(t.destinazione, k)}',
                  style: TextStyle(color: tema.colorScheme.onSurfaceVariant)),
            Text('Nella fonte: ${t.valore(k)}'),
          ]),
        ),
    ]);
  }

  Widget _trovato(_Trovato t) {
    final procedimenti = _procedimenti.values.toList()..sort((a, b) => '${a['codice']}'.compareTo('${b['codice']}'));
    return Card(
      child: ExpansionTile(
        initiallyExpanded: _trovati.length <= 3,
        leading: Checkbox(value: t.importa, onChanged: (v) => setState(() => t.importa = v ?? false)),
        title: Text(t.valore('denominazione').isEmpty ? '(senza denominazione)' : t.valore('denominazione')),
        subtitle: Text(t.destinazione == null
            ? 'Nuovo procedimento'
            : 'Aggiorna ${_procedimenti[t.destinazione]?['codice']} - ${_procedimenti[t.destinazione]?['denominazione']}'),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(spacing: 12, runSpacing: 8, children: [
            SizedBox(
              width: 420,
              child: DropdownButtonFormField<String?>(
                initialValue: t.destinazione,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Procedimento della mappatura', isDense: true),
                items: [
                  const DropdownMenuItem(value: null, child: Text('Nuovo procedimento')),
                  for (final p in procedimenti)
                    DropdownMenuItem(value: p['id'] as String, child: Text('${p['codice']} - ${p['denominazione']}', overflow: TextOverflow.ellipsis)),
                ],
                onChanged: (v) => setState(() {
                  t.destinazione = v;
                  _sceltePredefinite(t);
                }),
              ),
            ),
            if (t.destinazione == null)
              SizedBox(
                width: 320,
                child: DropdownButtonFormField<String?>(
                  initialValue: t.area,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Area di rischio', isDense: true),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('Senza area')),
                    for (final a in widget.dati.aree)
                      DropdownMenuItem(value: a['id'] as String, child: Text(widget.dati.area(a['id']) ?? '', overflow: TextOverflow.ellipsis)),
                  ],
                  onChanged: (v) => setState(() => t.area = v),
                ),
              ),
          ]),
          const SizedBox(height: 12),
          if (t.uffici.isNotEmpty) ...[
            Text('Uffici', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            _scelteUffici(t),
          ],
          Text('Dati da prendere', style: Theme.of(context).textTheme.titleSmall),
          _campi(t),
        ],
      ),
    );
  }

  Widget _revisione() {
    final recapiti = _recapitiDaCompletare();
    final scelti = _trovati.where((t) => t.importa).length;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text(_trovati.isEmpty ? 'Nella fonte non sono stati trovati procedimenti.' : 'Procedimenti trovati: ${_trovati.length}. '
          'Per ciascuno scegli se aggiornarne uno della mappatura o crearne uno nuovo, gli uffici e i dati da prendere.'),
      if (_avvisi.isNotEmpty)
        Card(
          color: Colors.amber.withValues(alpha: 0.12),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Avvisi della lettura', style: TextStyle(fontWeight: FontWeight.w600)),
              for (final a in _avvisi) Text('• $a'),
            ]),
          ),
        ),
      const SizedBox(height: 8),
      for (final t in _trovati) _trovato(t),
      if (recapiti.isNotEmpty)
        Sezione(
          titolo: 'Recapiti delle strutture',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(_amministratore
                ? 'Nella fonte ci sono recapiti che nelle strutture mancano: si possono completare (quelli già presenti non cambiano).'
                : 'Nella fonte ci sono recapiti che nelle strutture mancano: li inserisce l\'amministratore (Amministrazione → Strutture).'),
            for (final MapEntry(key: id, value: valori) in recapiti.entries)
              Text('• ${_struttura(id)?['codice']} - ${_struttura(id)?['descrizione']}: '
                  '${valori.entries.map((e) => e.key == 'orari' ? 'orari' : '${e.key} ${e.value}').join(', ')}'),
            if (_amministratore)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _completaRecapiti,
                onChanged: (v) => setState(() => _completaRecapiti = v ?? false),
                title: const Text('Completa i recapiti vuoti delle strutture'),
              ),
          ]),
        ),
      const SizedBox(height: 8),
      Align(
        alignment: Alignment.centerLeft,
        child: FilledButton.icon(
          icon: _inCorso ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.save),
          label: Text('Salva $scelti ${scelti == 1 ? 'procedimento' : 'procedimenti'}'),
          onPressed: _inCorso || scelti == 0 ? null : _applica,
        ),
      ),
    ]);
  }

  Widget _fatto() => ListView(padding: const EdgeInsets.all(16), children: [
        for (final t in _trovati.where((t) => t.esito != null))
          ListTile(
            leading: Icon(t.esito!.startsWith('Non') ? Icons.error_outline : Icons.check_circle_outline,
                color: t.esito!.startsWith('Non') ? Theme.of(context).colorScheme.error : Colors.green),
            title: Text(t.valore('denominazione')),
            subtitle: Text(t.esito!),
          ),
        for (final a in _avvisi.where((a) => a.startsWith('Recapiti'))) Text('• $a'),
        const SizedBox(height: 16),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Torna alla mappatura')),
        ),
      ]);

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Importa procedimenti dal sito o da documenti')),
        body: switch (_fase) {
          _Fase.fonte => _fonte(),
          _Fase.attesa => const Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                CircularProgressIndicator(),
                SizedBox(height: 16),
                Text('Lettura in corso: può richiedere qualche minuto.'),
              ]),
            ),
          _Fase.revisione => _revisione(),
          _Fase.fatto => _fatto(),
        },
      );
}
