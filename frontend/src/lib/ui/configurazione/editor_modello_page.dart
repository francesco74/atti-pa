import 'dart:async';

import 'package:flutter/material.dart';

import '../bozze/scelta_riferimenti.dart';
import '../comuni.dart';
import 'condizione.dart';
import 'editor_comune.dart';
import 'testo_dati.dart';

/// Elemento selezionato nell'albero.
class _Sel {
  const _Sel(this.tipo, [this.i = 0, this.j = 0, this.k = 0, this.nome]);

  final String tipo; // generale, domanda, dato, derivato, fase, sezione, capoverso, inserto,
  // capoverso_inserto, suggerimento, scenario
  final int i, j, k;
  final String? nome;

  String get chiave => '$tipo/$i/$j/$k/$nome';

  @override
  bool operator ==(Object other) => other is _Sel && other.chiave == chiave;

  @override
  int get hashCode => chiave.hashCode;
}

/// Editor di un modello di atto o di una specificità (modulo di regole): a sinistra la
/// struttura, al centro l'elemento scelto, a destra l'atto composto con le risposte di prova.
class EditorModelloPage extends StatefulWidget {
  const EditorModelloPage({super.key, required this.tipo, required this.codice});

  final String tipo; // modello, modulo
  final String codice;

  @override
  State<EditorModelloPage> createState() => _EditorModelloPageState();
}

class _EditorModelloPageState extends State<EditorModelloPage> with EditorConfigurazione {
  @override
  String get tipo => widget.tipo;
  @override
  String get codice => widget.codice;
  bool get modulo => widget.tipo == 'modulo';

  _Sel _sel = const _Sel('generale');
  int _generazione = 0; // cambia quando la definizione è sostituita: ricrea i campi

  // anteprima
  Map<String, dynamic>? _anteprima;
  String? _erroreAnteprima;
  Map<String, dynamic> _risposte = {};
  String? _modelloAnteprima;
  Timer? _timerAnteprima;
  List<Map<String, dynamic>> _proposte = [];

  @override
  void initState() {
    super.initState();
    carica();
  }

  @override
  void dispose() {
    _timerAnteprima?.cancel();
    super.dispose();
  }

  @override
  void dopoCaricamento() {
    _generazione++;
    if (modulo) {
      final modelli = List<String>.from(definizione['modelli'] as List? ?? const []);
      _modelloAnteprima ??= modelli.isNotEmpty ? modelli.first : null;
    } else {
      _caricaProposte();
    }
    _aggiornaAnteprima();
  }

  @override
  void dopoModifica() {
    _timerAnteprima?.cancel();
    _timerAnteprima = Timer(const Duration(milliseconds: 900), _aggiornaAnteprima);
  }

  Future<void> _aggiornaAnteprima() async {
    try {
      final r = await apiDi(context).post('$percorso/anteprima', {
        'definizione': definizione,
        'risposte': _risposte,
        'modello': ?_modelloAnteprima,
      }) as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _anteprima = r;
          _erroreAnteprima = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _erroreAnteprima = e.toString());
    }
  }

  Future<void> _caricaProposte() async {
    try {
      final r = await apiDi(context).get('/api/v1/proposte', query: {'modello': codice}) as List;
      if (mounted) setState(() => _proposte = listaDi(r));
    } catch (_) {}
  }

  // --- accesso alla definizione ----------------------------------------------------------

  List<dynamic> _lista(String chiave) => (definizione[chiave] ??= <dynamic>[]) as List;
  Map<String, dynamic> _mappa(String chiave) =>
      (definizione[chiave] ??= <String, dynamic>{}) as Map<String, dynamic>;
  List<dynamic> get _fasi => _lista('fasi');
  Map<String, dynamic> _fase(int i) => _fasi[i] as Map<String, dynamic>;
  List<dynamic> _sezioni(int i) => (_fase(i)['sezioni'] ??= <dynamic>[]) as List;
  Map<String, dynamic> _sezione(int i, int j) => _sezioni(i)[j] as Map<String, dynamic>;
  List<dynamic> _capoversi(int i, int j) => (_sezione(i, j)['capoversi'] ??= <dynamic>[]) as List;
  List<dynamic> get _inserti => _lista('inserti');
  List<dynamic> _capoversiInserto(int i) =>
      ((_inserti[i] as Map<String, dynamic>)['capoversi'] ??= <dynamic>[]) as List;

  Iterable<Map<String, dynamic>> get _tuttiCapoversi sync* {
    if (modulo) {
      for (final ins in _inserti) {
        yield* ((ins as Map)['capoversi'] as List? ?? const []).cast<Map<String, dynamic>>();
      }
    } else {
      for (final f in _fasi) {
        for (final s in ((f as Map)['sezioni'] as List? ?? const [])) {
          yield* ((s as Map)['capoversi'] as List? ?? const []).cast<Map<String, dynamic>>();
        }
      }
    }
  }

  String _nuovoId(String base) {
    final usati = _tuttiCapoversi.map((c) => c['id']).toSet();
    var n = 1;
    while (usati.contains('${base}_$n')) {
      n++;
    }
    return '${base}_$n';
  }

  _Sel? _posizioneCapoverso(String id) {
    if (modulo) {
      for (var i = 0; i < _inserti.length; i++) {
        final cs = _capoversiInserto(i);
        for (var k = 0; k < cs.length; k++) {
          if ((cs[k] as Map)['id'] == id) return _Sel('capoverso_inserto', i, 0, k);
        }
      }
    } else {
      for (var i = 0; i < _fasi.length; i++) {
        for (var j = 0; j < _sezioni(i).length; j++) {
          final cs = _capoversi(i, j);
          for (var k = 0; k < cs.length; k++) {
            if ((cs[k] as Map)['id'] == id) return _Sel('capoverso', i, j, k);
          }
        }
      }
    }
    return null;
  }

  Map<String, dynamic>? _capoversoStandard(String id) {
    final s = standard;
    if (s == null) return null;
    if (modulo) {
      for (final ins in listaDi(s['inserti'])) {
        for (final c in listaDi(ins['capoversi'])) {
          if (c['id'] == id) return c;
        }
      }
    } else {
      for (final f in listaDi(s['fasi'])) {
        for (final sz in listaDi(f['sezioni'])) {
          for (final c in listaDi(sz['capoversi'])) {
            if (c['id'] == id) return c;
          }
        }
      }
    }
    return null;
  }

  // --- variabili e dati disponibili --------------------------------------------------------

  List<Map<String, dynamic>> get _modelliContesto => listaDi(contesto['modelli']);
  List<Map<String, dynamic>> get _moduliContesto => listaDi(contesto['moduli']);

  List<Map<String, dynamic>> get _modelliBersaglio {
    final scelti = List<String>.from(definizione['modelli'] as List? ?? const []);
    return _modelliContesto.where((m) => scelti.contains(m['codice'])).toList();
  }

  List<Variabile> get _variabili {
    final altre = <Variabile>[];
    if (modulo) {
      altre.add(Variabile(definizione['fattore']?.toString() ?? '', 'Questa specificità è scelta', 'si_no'));
      for (final m in _modelliBersaglio) {
        altre.addAll(variabiliDi({'domande': m['domande'], 'derivati': {for (final d in m['derivati'] as List) d: ''}}));
      }
    } else {
      for (final mo in _moduliContesto) {
        if ((mo['modelli'] as List).contains(codice)) {
          altre.add(Variabile(mo['fattore'] as String, 'Caratteristica: ${mo['etichetta']}', 'si_no'));
        }
      }
    }
    // senza doppioni: i menu a tendina delle condizioni non li ammettono
    final viste = <String>{};
    return [for (final v in variabiliDi(definizione, altre: altre)) if (v.nome.isNotEmpty && viste.add(v.nome)) v];
  }

  List<DatoInseribile> get _dati {
    final altri = <DatoInseribile>[];
    if (modulo) {
      for (final m in _modelliBersaglio) {
        final campi = Map<String, dynamic>.from(m['campi'] as Map);
        for (final c in campi.entries) {
          altri.add(DatoInseribile(c.key, '${c.value}', 'Dati del modello ${m['titolo']}'));
        }
      }
    }
    return datiDi(definizione, altri: altri);
  }

  Future<List<String>> _normeDaLibreria() async {
    final r = await showDialog<List<Map<String, dynamic>>>(
      context: context,
      builder: (_) => const SceltaRiferimentiDialog(),
    );
    return [
      for (final x in r ?? const <Map<String, dynamic>>[])
        if (x['articolo'] != null) '${x['urn_atto']}~art${x['articolo']}',
    ];
  }

  void _seleziona(_Sel s) => setState(() => _sel = s);

  // --- albero -------------------------------------------------------------------------------

  // ricerca nella struttura: testo e tipo di elemento (tutto, capoversi, domande, dati)
  String _ricerca = '';
  String _tipoRicerca = 'tutto';
  int _risultati = 0;

  bool get _filtroAttivo => _ricerca.trim().isNotEmpty || _tipoRicerca != 'tutto';

  static const _tipiRicerca = {'tutto': 'Tutto', 'capoversi': 'Capoversi', 'domande': 'Domande', 'dati': 'Dati'};

  String _famiglia(String tipo) => switch (tipo) {
        'capoverso' || 'capoverso_inserto' => 'capoversi',
        'domanda' => 'domande',
        'dato' => 'dati',
        _ => 'altro',
      };

  /// La voce supera il filtro? testi: dove cercare (oltre al titolo).
  bool _visibile(_Sel s, String titolo, Iterable<Object?> testi) {
    if (!_filtroAttivo) return true;
    if (_tipoRicerca != 'tutto' && _famiglia(s.tipo) != _tipoRicerca) return false;
    return corrisponde(_ricerca, [titolo, ...testi]);
  }

  /// Voce dell'albero; null se esclusa dalla ricerca. contesto: mostrata comunque (es. la
  /// sezione di un capoverso trovato), senza contarla tra i risultati.
  Widget? _voce(String titolo, _Sel s,
      {String? sotto, IconData? icona, int livello = 0, Color? colore, Iterable<Object?> cerca = const [], bool contesto = false}) {
    final trovata = _visibile(s, titolo, [sotto, ...cerca]);
    if (!trovata && !contesto) return null;
    if (trovata && _filtroAttivo) _risultati++;
    final q = trovata ? _ricerca : '';
    return ListTile(
      dense: true,
      visualDensity: VisualDensity.compact,
      contentPadding: EdgeInsets.only(left: 8.0 + 16 * livello, right: 4),
      leading: icona == null ? null : Icon(icona, size: 18, color: colore),
      title: testoEvidenziato(context, titolo, q),
      subtitle: sotto == null ? null : testoEvidenziato(context, sotto, q),
      selected: _sel == s,
      onTap: () => _seleziona(s),
    );
  }

  /// Gruppo dell'albero; con la ricerca attiva, solo se contiene risultati (e aperto).
  Widget? _gruppo(String titolo, List<Widget?> figli, {VoidCallback? aggiungi, String? aggiungiEtichetta}) {
    final visibili = figli.whereType<Widget>().toList();
    if (_filtroAttivo && visibili.isEmpty) return null;
    return ExpansionTile(
      key: PageStorageKey('$titolo#$_filtroAttivo'),
      initiallyExpanded: true,
      dense: true,
      tilePadding: const EdgeInsets.symmetric(horizontal: 8),
      title: Text(titolo, style: Theme.of(context).textTheme.titleSmall),
      trailing: aggiungi == null || _filtroAttivo
          ? null
          : IconButton(tooltip: aggiungiEtichetta ?? 'Aggiungi', icon: const Icon(Icons.add), onPressed: aggiungi),
      children: visibili,
    );
  }

  String _anteprimaTesto(Object? t) {
    final s = (t ?? '').toString().replaceAll('\n', ' ');
    // con la ricerca il testo intero: la parola trovata può essere oltre i primi caratteri
    if (_filtroAttivo) return s;
    return s.length > 60 ? '${s.substring(0, 60)}…' : s;
  }

  bool _capoversoCambiato(Map<String, dynamic> c) {
    final st = _capoversoStandard(c['id'] as String);
    return st != null && st.toString() != c.toString();
  }

  Widget? _vocCapoverso(Map<String, dynamic> c, _Sel s, Set<Object?> proposteAperte, Color colCambiato) {
    final proposta = proposteAperte.contains(c['id']);
    return _voce(_anteprimaTesto(c['testo']), s,
        sotto: [c['id'], if (c['se'] != null) 'condizionato', if (c['facoltativo'] == true) 'facoltativo', if (proposta) 'proposta di modifica']
            .join(' · '),
        cerca: [c['testo'], c['aiuto']],
        icona: proposta ? Icons.feedback_outlined : Icons.notes,
        colore: _capoversoCambiato(c) || proposta ? colCambiato : null,
        livello: 2);
  }

  Widget _albero() {
    final tema = Theme.of(context);
    final campi = _mappa('campi');
    final derivati = _mappa('derivati');
    final domande = _lista('domande');
    final colCambiato = tema.colorScheme.tertiary;
    final proposteAperte = {for (final p in _proposte) p['capoverso']};
    _risultati = 0;

    List<Widget?> sezioniDellaFase(int i) => [
          _voce('Impostazioni della fase', _Sel('fase', i), icona: Icons.tune, livello: 1, cerca: [_fase(i)['titolo']]),
          for (var j = 0; j < _sezioni(i).length; j++) ...() {
            final capoversi = [
              for (var k = 0; k < _capoversi(i, j).length; k++)
                _vocCapoverso(_capoversi(i, j)[k] as Map<String, dynamic>, _Sel('capoverso', i, j, k), proposteAperte, colCambiato),
            ].whereType<Widget>().toList();
            return [
              _voce(_sezione(i, j)['titolo']?.toString() ?? '', _Sel('sezione', i, j),
                  icona: Icons.segment,
                  livello: 1,
                  sotto: _sezione(i, j)['innesto'] != null ? 'punto di innesto: ${_sezione(i, j)['innesto']}' : null,
                  contesto: capoversi.isNotEmpty),
              ...capoversi,
            ];
          }(),
        ];

    final voci = <Widget?>[
      _voce(modulo ? 'Specificità' : 'Dati generali', const _Sel('generale'), icona: Icons.info_outline,
          cerca: [definizione['titolo'], definizione['etichetta'], definizione['codice']]),
      _gruppo('Domande iniziali', [
        for (var i = 0; i < domande.length; i++)
          _voce((domande[i] as Map)['testo']?.toString() ?? '', _Sel('domanda', i),
              sotto: (domande[i] as Map)['id']?.toString(),
              cerca: [...((domande[i] as Map)['opzioni'] as Map? ?? const {}).values, (domande[i] as Map)['aiuto']],
              icona: Icons.help_outline,
              livello: 1),
      ], aggiungi: () {
        modifica(() => domande.add(<String, dynamic>{'id': 'nuova_domanda_${domande.length + 1}', 'testo': 'Nuova domanda', 'tipo': 'si_no'}));
        _seleziona(_Sel('domanda', domande.length - 1));
      }, aggiungiEtichetta: 'Aggiungi una domanda'),
      if (!modulo)
        for (var i = 0; i < _fasi.length; i++)
          _gruppo('Fase ${_fase(i)['numero']} · ${_fase(i)['titolo']}', sezioniDellaFase(i), aggiungi: () {
            modifica(() => _sezioni(i).add(<String, dynamic>{'titolo': 'Nuova sezione', 'capoversi': <dynamic>[]}));
            _seleziona(_Sel('sezione', i, _sezioni(i).length - 1));
          }, aggiungiEtichetta: 'Aggiungi una sezione'),
      if (modulo)
        _gruppo('Testi inseriti nei modelli', [
          for (var i = 0; i < _inserti.length; i++) ...() {
            final capoversi = [
              for (var k = 0; k < _capoversiInserto(i).length; k++)
                _vocCapoverso(_capoversiInserto(i)[k] as Map<String, dynamic>, _Sel('capoverso_inserto', i, 0, k), proposteAperte, colCambiato),
            ].whereType<Widget>().toList();
            return [
              _voce('Innesto: ${(_inserti[i] as Map)['innesto']}', _Sel('inserto', i),
                  icona: Icons.call_merge, livello: 1, contesto: capoversi.isNotEmpty),
              ...capoversi,
            ];
          }(),
        ], aggiungi: () {
          modifica(() => _inserti.add(<String, dynamic>{'innesto': 'dispositivo', 'capoversi': <dynamic>[
                <String, dynamic>{'id': _nuovoId(definizione['codice'].toString().toLowerCase()), 'testo': 'Nuovo testo'}
              ]}));
          _seleziona(_Sel('inserto', _inserti.length - 1));
        }, aggiungiEtichetta: 'Aggiungi un punto di inserimento'),
      _gruppo('Dati da compilare', [
        for (final n in campi.keys)
          _voce((campi[n] as Map)['etichetta']?.toString() ?? n, _Sel('dato', 0, 0, 0, n),
              sotto: '$n · ${(campi[n] as Map)['tipo'] ?? 'testo'}',
              cerca: [(campi[n] as Map)['aiuto']],
              icona: Icons.label_outline,
              livello: 1),
      ], aggiungi: () {
        var n = 1;
        while (campi.containsKey('nuovo_dato_$n')) {
          n++;
        }
        modifica(() => campi['nuovo_dato_$n'] = <String, dynamic>{'etichetta': 'Nuovo dato', 'tipo': 'testo'});
        _seleziona(_Sel('dato', 0, 0, 0, 'nuovo_dato_$n'));
      }, aggiungiEtichetta: 'Aggiungi un dato'),
      _gruppo('Valori calcolati', [
        for (final n in derivati.keys) _voce(n, _Sel('derivato', 0, 0, 0, n), icona: Icons.functions, livello: 1),
      ], aggiungi: () {
        var n = 1;
        while (derivati.containsKey('calcolato_$n')) {
          n++;
        }
        modifica(() => derivati['calcolato_$n'] = <dynamic>[<String, dynamic>{'valore': ''}]);
        _seleziona(_Sel('derivato', 0, 0, 0, 'calcolato_$n'));
      }, aggiungiEtichetta: 'Aggiungi un valore calcolato'),
      _gruppo('Risposte consigliate', [
        for (var i = 0; i < _lista('suggerimenti').length; i++)
          _voce('Per «${(_lista('suggerimenti')[i] as Map)['domanda']}»', _Sel('suggerimento', i),
              cerca: [(_lista('suggerimenti')[i] as Map)['messaggio']], icona: Icons.lightbulb_outline, livello: 1),
      ], aggiungi: domande.isEmpty && !modulo
          ? null
          : () {
              modifica(() => _lista('suggerimenti').add(<String, dynamic>{
                    'domanda': domande.isNotEmpty ? (domande.first as Map)['id'] : 'garanzia',
                    'valore': true,
                    'messaggio': 'Perché è consigliato',
                  }));
              _seleziona(_Sel('suggerimento', _lista('suggerimenti').length - 1));
            }),
      if (!modulo)
        _gruppo('Scenari di prova', [
          for (var i = 0; i < _lista('scenari').length; i++)
            _voce((_lista('scenari')[i] as Map)['nome']?.toString() ?? '', _Sel('scenario', i), icona: Icons.science_outlined, livello: 1),
        ]),
    ];
    return Column(children: [
      CampoRicerca(
        suggerimento: 'Cerca capoversi, domande, dati...',
        valore: _ricerca,
        risultati: _filtroAttivo ? _risultati : null,
        filtri: _tipiRicerca,
        filtro: _tipoRicerca,
        onFiltro: (f) => setState(() => _tipoRicerca = f),
        onChanged: (v) => setState(() => _ricerca = v),
      ),
      Expanded(child: ListView(children: voci.whereType<Widget>().toList())),
    ]);
  }

  // --- editor degli elementi ----------------------------------------------------------------

  Widget _campo(String etichetta, Object? valore, ValueChanged<String> cambia,
      {int righe = 1, String? aiuto, bool abilitato = true}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextFormField(
        initialValue: valore?.toString() ?? '',
        enabled: abilitato,
        minLines: righe,
        maxLines: righe == 1 ? 1 : null,
        decoration: InputDecoration(labelText: etichetta, helperText: aiuto, helperMaxLines: 3, border: const OutlineInputBorder()),
        onChanged: (v) => modifica(() => cambia(v)),
      ),
    );
  }

  Widget _interruttore(String etichetta, bool valore, ValueChanged<bool> cambia, {String? aiuto}) => SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(etichetta),
        subtitle: aiuto == null ? null : Text(aiuto),
        value: valore,
        onChanged: (v) => modifica(() => cambia(v)),
      );

  Widget _barraElemento(String titolo, {VoidCallback? su, VoidCallback? giu, VoidCallback? duplica, VoidCallback? elimina, List<Widget> altro = const []}) {
    return Row(children: [
      Expanded(child: Text(titolo, style: Theme.of(context).textTheme.titleMedium)),
      ...altro,
      if (su != null) IconButton(tooltip: 'Sposta su', icon: const Icon(Icons.arrow_upward), onPressed: su),
      if (giu != null) IconButton(tooltip: 'Sposta giù', icon: const Icon(Icons.arrow_downward), onPressed: giu),
      if (duplica != null) IconButton(tooltip: 'Duplica', icon: const Icon(Icons.copy), onPressed: duplica),
      if (elimina != null)
        IconButton(
          tooltip: 'Elimina',
          icon: Icon(Icons.delete_outline, color: Theme.of(context).colorScheme.error),
          onPressed: () async {
            if (await conferma(context, 'Eliminare?', 'L\'eliminazione diventa effettiva solo alla pubblicazione.')) {
              elimina();
            }
          },
        ),
    ]);
  }

  void _sposta(List<dynamic> lista, int da, int a, _Sel nuova) {
    if (a < 0 || a >= lista.length) return;
    modifica(() => lista.insert(a, lista.removeAt(da)));
    _seleziona(nuova);
  }

  Widget _editorGenerale() {
    final d = definizione;
    if (modulo) {
      final scelti = List<String>.from(d['modelli'] as List? ?? const []);
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _barraElemento('Specificità ${d['codice']}'),
        const SizedBox(height: 12),
        _campo('Nome (come compare tra le caratteristiche dell\'atto)', d['etichetta'], (v) => d['etichetta'] = v),
        _campo('Variabile (fattore) usata nelle condizioni', d['fattore'], (v) => d['fattore'] = v,
            aiuto: 'Lettere minuscole e trattini bassi, es. servizi_cloud'),
        _campo('Descrizione (cosa attiva)', d['descrizione'], (v) => d['descrizione'] = v.isEmpty ? null : v, righe: 2),
        Text('Si applica ai modelli', style: Theme.of(context).textTheme.titleSmall),
        Wrap(spacing: 6, children: [
          for (final m in _modelliContesto)
            FilterChip(
              label: Text(m['titolo'] as String),
              selected: scelti.contains(m['codice']),
              onSelected: (s) => modifica(() {
                s ? scelti.add(m['codice'] as String) : scelti.remove(m['codice']);
                d['modelli'] = scelti;
                if (_modelloAnteprima == null && scelti.isNotEmpty) _modelloAnteprima = scelti.first;
              }),
            ),
        ]),
      ]);
    }
    final tipologie = listaDi(contesto['tipologie']);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Modello ${d['codice']}'),
      const SizedBox(height: 12),
      _campo('Titolo', d['titolo'], (v) => d['titolo'] = v),
      _campo('Descrizione', d['descrizione'], (v) => d['descrizione'] = v.isEmpty ? null : v, righe: 2),
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: DropdownButtonFormField<String>(
          initialValue: tipologie.any((t) => t['codice'] == d['tipologia_atto']) ? d['tipologia_atto'] as String : null,
          decoration: const InputDecoration(labelText: 'Tipologia di atto', border: OutlineInputBorder()),
          items: [for (final t in tipologie) DropdownMenuItem(value: t['codice'] as String, child: Text(t['descrizione'] as String))],
          onChanged: (v) => modifica(() => d['tipologia_atto'] = v),
        ),
      ),
      _campo('Provvedimento', d['provvedimento'], (v) => d['provvedimento'] = v, aiuto: 'Es. Determinazione dirigenziale'),
      _campo('Organo', d['organo'], (v) => d['organo'] = v),
      _campo('Formula del dispositivo', d['formula_dispositivo'], (v) => d['formula_dispositivo'] = v, aiuto: 'Es. DETERMINA'),
    ]);
  }

  Widget _editorFase(int i) {
    final f = _fase(i);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Fase ${f['numero']}'),
      const SizedBox(height: 12),
      _campo('Titolo', f['titolo'], (v) => f['titolo'] = v),
      _campo('Descrizione (aiuto per chi compila)', f['descrizione'], (v) => f['descrizione'] = v.isEmpty ? null : v, righe: 2),
      _campo('Formula iniziale', f['formula'], (v) => f['formula'] = v.isEmpty ? null : v, aiuto: 'Es. DETERMINA'),
      _campo('Premessa', f['premessa'], (v) => f['premessa'] = v.isEmpty ? null : v, righe: 2),
      _interruttore('Punti numerati automaticamente', f['numerazione'] == 'automatica',
          (v) => f['numerazione'] = v ? 'automatica' : null),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        onPressed: () {
          modifica(() => _sezioni(i).add(<String, dynamic>{'titolo': 'Nuova sezione', 'capoversi': <dynamic>[]}));
          _seleziona(_Sel('sezione', i, _sezioni(i).length - 1));
        },
        icon: const Icon(Icons.add),
        label: const Text('Aggiungi una sezione'),
      ),
    ]);
  }

  Widget _editorSezione(int i, int j) {
    final s = _sezione(i, j);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Sezione',
          su: j > 0 ? () => _sposta(_sezioni(i), j, j - 1, _Sel('sezione', i, j - 1)) : null,
          giu: j < _sezioni(i).length - 1 ? () => _sposta(_sezioni(i), j, j + 1, _Sel('sezione', i, j + 1)) : null,
          elimina: () {
            modifica(() => _sezioni(i).removeAt(j));
            _seleziona(_Sel('fase', i));
          }),
      const SizedBox(height: 12),
      _campo('Titolo', s['titolo'], (v) => s['titolo'] = v),
      _campo('Formula che introduce i capoversi', s['formula'], (v) => s['formula'] = v.isEmpty ? null : v,
          aiuto: 'Es. "Visti" o "Premesso che": i capoversi diventano un elenco'),
      CondizioneEditor(
        valore: s['se'] as String?,
        variabili: _variabili,
        etichetta: 'Quando compare la sezione',
        onChanged: (v) => modifica(() => v == null ? s.remove('se') : s['se'] = v),
      ),
      const SizedBox(height: 12),
      _campo('Aiuto per chi compila', s['aiuto'], (v) => s['aiuto'] = v.isEmpty ? null : v, righe: 2),
      _interruttore('È l\'oggetto dell\'atto', s['oggetto'] == true, (v) => s['oggetto'] = v),
      _interruttore('Qui si aggiungono i riferimenti scelti dalla libreria normativa', s['riferimenti_libreria'] == true,
          (v) => s['riferimenti_libreria'] = v),
      _campo('Punto di innesto per le specificità', s['innesto'], (v) => s['innesto'] = v.isEmpty ? null : v,
          aiuto: 'Nome con cui le specificità inseriscono qui i loro testi (es. visti_normativi, dato_atto, dispositivo)'),
      OutlinedButton.icon(
        onPressed: () {
          modifica(() => _capoversi(i, j).add(<String, dynamic>{'id': _nuovoId('capoverso'), 'testo': 'Nuovo testo'}));
          _seleziona(_Sel('capoverso', i, j, _capoversi(i, j).length - 1));
        },
        icon: const Icon(Icons.add),
        label: const Text('Aggiungi un capoverso'),
      ),
    ]);
  }

  Widget _editorCapoverso(List<dynamic> lista, int k, _Sel Function(int) sel, String dove) {
    final c = lista[k] as Map<String, dynamic>;
    final campi = _mappa('campi');
    final elenchi = [for (final e in campi.entries) if ((e.value as Map)['tipo'] == 'elenco') e.key];
    final st = _capoversoStandard(c['id'] as String);
    final proposte = _proposte.where((p) => p['capoverso'] == c['id']).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Capoverso',
          su: k > 0 ? () => _sposta(lista, k, k - 1, sel(k - 1)) : null,
          giu: k < lista.length - 1 ? () => _sposta(lista, k, k + 1, sel(k + 1)) : null,
          duplica: () {
            modifica(() => lista.insert(k + 1, {...copia(c), 'id': _nuovoId(c['id'] as String)}));
            _seleziona(sel(k + 1));
          },
          elimina: () {
            modifica(() => lista.removeAt(k));
            _seleziona(const _Sel('generale'));
          },
          altro: [
            if (st != null && st.toString() != c.toString())
              TextButton.icon(
                onPressed: () {
                  modifica(() {
                    c
                      ..clear()
                      ..addAll(copia(st));
                  });
                  setState(() => _generazione++);
                },
                icon: const Icon(Icons.restore),
                label: const Text('Ripristina lo standard'),
              ),
          ]),
      Text(dove, style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 12),
      for (final p in proposte) _proposta(p, c),
      _campo('Identificativo', c['id'], (v) => c['id'] = v,
          aiuto: 'Unico nel modello; le checklist lo usano per collegare i controlli'),
      TestoConDati(
        valore: c['testo']?.toString() ?? '',
        dati: _dati,
        onChanged: (v) => modifica(() => c['testo'] = v),
        onDato: (n) {
          if (campi.containsKey(n)) _seleziona(_Sel('dato', 0, 0, 0, n));
        },
      ),
      const SizedBox(height: 12),
      CondizioneEditor(
        valore: c['se'] as String?,
        variabili: _variabili,
        vuota: modulo ? 'Sempre, quando la specificità è scelta' : 'Sempre',
        onChanged: (v) => modifica(() => v == null ? c.remove('se') : c['se'] = v),
      ),
      _interruttore('Facoltativo', c['facoltativo'] == true, (v) => c['facoltativo'] = v,
          aiuto: 'Chi scrive l\'atto può toglierlo o aggiungerlo'),
      if (c['facoltativo'] == true)
        _interruttore('Incluso all\'inizio', c['incluso'] != false, (v) => c['incluso'] = v),
      _interruttore('Modificabile in bozza', c['modificabile'] != false, (v) => c['modificabile'] = v,
          aiuto: 'Chi scrive l\'atto può riscriverne il testo fisso'),
      if (elenchi.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: DropdownButtonFormField<String?>(
            initialValue: elenchi.contains(c['ripeti_per']) ? c['ripeti_per'] as String : null,
            decoration: const InputDecoration(labelText: 'Ripeti per ogni riga di', border: OutlineInputBorder()),
            items: [
              const DropdownMenuItem<String?>(value: null, child: Text('Non ripetere')),
              for (final e in elenchi) DropdownMenuItem<String?>(value: e, child: Text((campi[e] as Map)['etichetta'].toString())),
            ],
            onChanged: (v) => modifica(() => v == null ? c.remove('ripeti_per') : c['ripeti_per'] = v),
          ),
        ),
      _campo('Aiuto per chi compila (base normativa, quando usarlo)', c['aiuto'], (v) => c['aiuto'] = v.isEmpty ? null : v, righe: 2),
      NormeEditor(
        norme: List<String>.from(c['norme'] as List? ?? const []),
        onChanged: (n) => modifica(() => c['norme'] = n),
        aggiungiDaLibreria: _normeDaLibreria,
      ),
      const SizedBox(height: 12),
      _campo('Fonte del testo', c['fonte'], (v) => c['fonte'] = v.isEmpty ? null : v, aiuto: 'Es. ANCI-1, aggiunto, delibera n. ...'),
    ]);
  }

  Widget _proposta(Map<String, dynamic> p, Map<String, dynamic> capoverso) {
    final tema = Theme.of(context);
    return Card(
      color: tema.colorScheme.tertiaryContainer.withValues(alpha: 0.4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('Proposta di ${p['autore'] ?? 'un redattore'} del ${formatData(p['created_at'])}', style: tema.textTheme.titleSmall),
          if (p['motivazione'] != null) Text('Motivazione: ${p['motivazione']}'),
          const SizedBox(height: 6),
          SelectableText(p['testo_proposto'] as String),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: () => _gestisciProposta(p, 'RESPINTA'), child: const Text('Respingi')),
            FilledButton.tonal(
              onPressed: () async {
                if (!inModifica) {
                  mostraErrore(context, 'Prendi in carico il modello per applicare la proposta');
                  return;
                }
                modifica(() => capoverso['testo'] = p['testo_proposto']);
                setState(() => _generazione++);
                await _gestisciProposta(p, 'ACCOLTA');
              },
              child: const Text('Applica alla bozza'),
            ),
          ]),
        ]),
      ),
    );
  }

  Future<void> _gestisciProposta(Map<String, dynamic> p, String stato) async {
    String? nota;
    if (stato == 'RESPINTA') {
      final controller = TextEditingController();
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Respingere la proposta?'),
          content: TextField(controller: controller, decoration: const InputDecoration(labelText: 'Motivo (facoltativo)')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Respingi')),
          ],
        ),
      );
      nota = controller.text.trim().isEmpty ? null : controller.text.trim();
      controller.dispose();
      if (ok != true) return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).put('/api/v1/proposte/${p['id']}', {'stato': stato, 'nota': nota});
      await _caricaProposte();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _editorDomanda(int i) {
    final domande = _lista('domande');
    final q = domande[i] as Map<String, dynamic>;
    final opzioni = Map<String, dynamic>.from(q['opzioni'] as Map? ?? const {});
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Domanda iniziale',
          su: i > 0 ? () => _sposta(domande, i, i - 1, _Sel('domanda', i - 1)) : null,
          giu: i < domande.length - 1 ? () => _sposta(domande, i, i + 1, _Sel('domanda', i + 1)) : null,
          elimina: q['opzioni_da_regole'] == true
              ? null
              : () {
                  modifica(() => domande.removeAt(i));
                  _seleziona(const _Sel('generale'));
                }),
      const SizedBox(height: 12),
      _campo('Identificativo (usato nelle condizioni)', q['id'], (v) => q['id'] = v),
      _campo('Domanda', q['testo'], (v) => q['testo'] = v, righe: 2),
      if (q['opzioni_da_regole'] == true)
        const Padding(
          padding: EdgeInsets.only(bottom: 12),
          child: Text('Le opzioni sono le specificità che si applicano a questo modello: si gestiscono '
              'dalle specificità.'),
        )
      else ...[
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: DropdownButtonFormField<String>(
            initialValue: q['tipo'] as String?,
            decoration: const InputDecoration(labelText: 'Tipo di risposta', border: OutlineInputBorder()),
            items: const [
              DropdownMenuItem(value: 'si_no', child: Text('Sì / No')),
              DropdownMenuItem(value: 'scelta', child: Text('Scelta tra opzioni')),
              DropdownMenuItem(value: 'scelta_multipla', child: Text('Più scelte tra opzioni')),
              DropdownMenuItem(value: 'importo', child: Text('Importo')),
              DropdownMenuItem(value: 'numero', child: Text('Numero')),
              DropdownMenuItem(value: 'testo', child: Text('Testo')),
            ],
            onChanged: (v) => modifica(() {
              q['tipo'] = v;
              if (v == 'scelta' || v == 'scelta_multipla') q['opzioni'] ??= <String, dynamic>{'opzione_1': 'Prima opzione'};
            }),
          ),
        ),
        if (q['tipo'] == 'scelta' || q['tipo'] == 'scelta_multipla') ...[
          Text('Opzioni', style: Theme.of(context).textTheme.titleSmall),
          for (final o in opzioni.entries)
            Row(children: [
              SizedBox(
                width: 180,
                child: TextFormField(
                  initialValue: o.key,
                  decoration: const InputDecoration(labelText: 'Codice', isDense: true),
                  onChanged: (v) => modifica(() {
                    final nuove = <String, dynamic>{};
                    for (final e in (q['opzioni'] as Map).entries) {
                      nuove[e.key == o.key ? v : e.key as String] = e.value;
                    }
                    q['opzioni'] = nuove;
                  }),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextFormField(
                  initialValue: o.value.toString(),
                  decoration: const InputDecoration(labelText: 'Testo dell\'opzione', isDense: true),
                  onChanged: (v) => modifica(() => (q['opzioni'] as Map)[o.key] = v),
                ),
              ),
              IconButton(icon: const Icon(Icons.close), onPressed: () => modifica(() => (q['opzioni'] as Map).remove(o.key))),
            ]),
          TextButton.icon(
            onPressed: () => modifica(() => (q['opzioni'] as Map)['opzione_${opzioni.length + 1}'] = 'Nuova opzione'),
            icon: const Icon(Icons.add),
            label: const Text('Aggiungi un\'opzione'),
          ),
          const SizedBox(height: 12),
        ],
      ],
      _campo('Spiegazione', q['aiuto'], (v) => q['aiuto'] = v.isEmpty ? null : v, righe: 2),
      CondizioneEditor(
        valore: q['se'] as String?,
        variabili: _variabili,
        etichetta: 'Quando si chiede',
        onChanged: (v) => modifica(() => v == null ? q.remove('se') : q['se'] = v),
      ),
      const SizedBox(height: 12),
      CondizioneEditor(
        valore: q['blocca_se'] as String?,
        variabili: _variabili,
        etichetta: 'Risposte che bloccano l\'atto',
        vuota: 'Nessun blocco',
        onChanged: (v) => modifica(() => v == null ? q.remove('blocca_se') : q['blocca_se'] = v),
      ),
      if (q['blocca_se'] != null) ...[
        const SizedBox(height: 12),
        _campo('Messaggio di blocco', q['messaggio_blocco'], (v) => q['messaggio_blocco'] = v.isEmpty ? null : v, righe: 2),
      ],
    ]);
  }

  /// Rinomina un dato e aggiorna i testi che lo usano.
  void _rinominaDato(String vecchio, String nuovo) {
    if (nuovo == vecchio || nuovo.isEmpty) return;
    final campi = _mappa('campi');
    final re = RegExp('\\{\\{(\\s*)$vecchio(\\s*\\}\\}|\\.)');
    String sostituisci(String t) => t.replaceAllMapped(re, (m) => '{{${m.group(1)}$nuovo${m.group(2)}');
    final nuovi = <String, dynamic>{};
    for (final e in campi.entries) {
      nuovi[e.key == vecchio ? nuovo : e.key] = e.value;
    }
    definizione['campi'] = nuovi;
    for (final c in _tuttiCapoversi) {
      c['testo'] = sostituisci(c['testo']?.toString() ?? '');
      if (c['ripeti_per'] == vecchio) c['ripeti_per'] = nuovo;
    }
    for (final v in nuovi.values) {
      final m = v as Map;
      if (m['predefinito'] != null) m['predefinito'] = sostituisci(m['predefinito'].toString());
    }
  }

  Widget _editorDato(String nome) {
    final campi = _mappa('campi');
    final c = campi[nome] as Map<String, dynamic>?;
    if (c == null) return const Text('Dato non trovato');
    final usatoIn = [for (final cap in _tuttiCapoversi) if (RegExp('\\{\\{\\s*$nome[\\s.}]').hasMatch(cap['testo']?.toString() ?? '')) cap['id']];
    final sotto = Map<String, dynamic>.from(c['sottocampi'] as Map? ?? const {});
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Dato da compilare', elimina: () {
        modifica(() => campi.remove(nome));
        _seleziona(const _Sel('generale'));
      }),
      const SizedBox(height: 12),
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: TextFormField(
          initialValue: nome,
          decoration: const InputDecoration(
            labelText: 'Nome nel testo',
            helperText: 'Rinominandolo si aggiornano i testi che lo usano (premi Invio)',
            border: OutlineInputBorder(),
          ),
          onFieldSubmitted: (v) {
            final nuovo = v.trim();
            if (!RegExp(r'^[a-z_][a-z0-9_]*$').hasMatch(nuovo) || campi.containsKey(nuovo)) {
              mostraErrore(context, 'Nome non valido o già usato (minuscole, cifre, _)');
              return;
            }
            modifica(() => _rinominaDato(nome, nuovo));
            _seleziona(_Sel('dato', 0, 0, 0, nuovo));
            setState(() => _generazione++);
          },
        ),
      ),
      _campo('Etichetta (come compare a chi compila)', c['etichetta'], (v) => c['etichetta'] = v),
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: DropdownButtonFormField<String>(
          initialValue: c['tipo'] as String? ?? 'testo',
          decoration: const InputDecoration(labelText: 'Tipo', border: OutlineInputBorder()),
          items: const [
            DropdownMenuItem(value: 'testo', child: Text('Testo breve')),
            DropdownMenuItem(value: 'testo_lungo', child: Text('Testo lungo')),
            DropdownMenuItem(value: 'data', child: Text('Data')),
            DropdownMenuItem(value: 'importo', child: Text('Importo')),
            DropdownMenuItem(value: 'numero', child: Text('Numero')),
            DropdownMenuItem(value: 'cig', child: Text('CIG')),
            DropdownMenuItem(value: 'cup', child: Text('CUP')),
            DropdownMenuItem(value: 'codice_fiscale_piva', child: Text('Codice fiscale o partita IVA')),
            DropdownMenuItem(value: 'elenco', child: Text('Elenco di righe (es. impegni)')),
          ],
          onChanged: (v) => modifica(() {
            c['tipo'] = v;
            if (v == 'elenco') c['sottocampi'] ??= <String, dynamic>{'voce': <String, dynamic>{'etichetta': 'Voce'}};
          }),
        ),
      ),
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: DropdownButtonFormField<String>(
          initialValue: c['fonte'] as String? ?? 'utente',
          decoration: const InputDecoration(labelText: 'Chi lo fornisce', border: OutlineInputBorder()),
          items: const [
            DropdownMenuItem(value: 'utente', child: Text('Chi scrive l\'atto')),
            DropdownMenuItem(value: 'ente', child: Text('Dati dell\'ente (Amministrazione)')),
            DropdownMenuItem(value: 'profilo', child: Text('Profilo dell\'utente')),
            DropdownMenuItem(value: 'sistema', child: Text('Assegnato alla registrazione (es. numero)')),
          ],
          onChanged: (v) => modifica(() => c['fonte'] = v),
        ),
      ),
      _interruttore('Obbligatorio', c['obbligatorio'] != false, (v) => c['obbligatorio'] = v),
      _campo('Valore proposto', c['predefinito'], (v) => c['predefinito'] = v.isEmpty ? null : v,
          aiuto: 'Anche con altri dati, es. {{importo}}'),
      _campo('Aiuto per chi compila', c['aiuto'], (v) => c['aiuto'] = v.isEmpty ? null : v, righe: 2),
      if (c['tipo'] == 'elenco') ...[
        Text('Colonne dell\'elenco', style: Theme.of(context).textTheme.titleSmall),
        for (final s in sotto.entries)
          Row(children: [
            SizedBox(width: 160, child: Text(s.key)),
            Expanded(
              child: TextFormField(
                initialValue: (s.value as Map)['etichetta']?.toString(),
                decoration: const InputDecoration(labelText: 'Etichetta', isDense: true),
                onChanged: (v) => modifica(() => ((c['sottocampi'] as Map)[s.key] as Map)['etichetta'] = v),
              ),
            ),
            IconButton(icon: const Icon(Icons.close), onPressed: () => modifica(() => (c['sottocampi'] as Map).remove(s.key))),
          ]),
        TextButton.icon(
          onPressed: () => modifica(() => (c['sottocampi'] as Map)['colonna_${sotto.length + 1}'] = <String, dynamic>{'etichetta': 'Nuova colonna'}),
          icon: const Icon(Icons.add),
          label: const Text('Aggiungi una colonna'),
        ),
      ],
      const SizedBox(height: 8),
      Text(usatoIn.isEmpty ? 'Non usato in nessun capoverso.' : 'Usato nei capoversi:',
          style: Theme.of(context).textTheme.bodySmall),
      Wrap(spacing: 6, children: [
        for (final id in usatoIn)
          ActionChip(
            label: Text(id.toString()),
            onPressed: () {
              final s = _posizioneCapoverso(id.toString());
              if (s != null) _seleziona(s);
            },
          ),
      ]),
    ]);
  }

  Widget _editorDerivato(String nome) {
    final derivati = _mappa('derivati');
    final r = derivati[nome];
    final booleano = r is String;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Valore calcolato «$nome»', elimina: () {
        modifica(() => derivati.remove(nome));
        _seleziona(const _Sel('generale'));
      }),
      const SizedBox(height: 12),
      SegmentedButton<bool>(
        segments: const [
          ButtonSegment(value: true, label: Text('Sì / No secondo una condizione')),
          ButtonSegment(value: false, label: Text('Valore secondo i casi')),
        ],
        selected: {booleano},
        onSelectionChanged: (s) => modifica(() => derivati[nome] = s.first ? '' : <dynamic>[<String, dynamic>{'valore': ''}]),
      ),
      const SizedBox(height: 12),
      if (booleano)
        CondizioneEditor(
          valore: r.isEmpty ? null : r,
          variabili: _variabili.where((v) => v.nome != nome).toList(),
          etichetta: 'È vero quando',
          onChanged: (v) => modifica(() => derivati[nome] = v ?? ''),
        )
      else ...[
        const Text('Il primo caso la cui condizione è vera dà il valore; l\'ultimo, senza condizione, vale negli altri casi.'),
        const SizedBox(height: 8),
        for (var i = 0; i < (r as List).length; i++)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                CondizioneEditor(
                  key: ValueKey('$nome-$i-$_generazione'),
                  valore: (r[i] as Map)['se'] as String?,
                  variabili: _variabili.where((v) => v.nome != nome).toList(),
                  etichetta: 'Caso ${i + 1}: quando',
                  vuota: 'In tutti gli altri casi',
                  onChanged: (v) => modifica(() => v == null ? (r[i] as Map).remove('se') : (r[i] as Map)['se'] = v),
                ),
                Row(children: [
                  Expanded(
                    child: TextFormField(
                      initialValue: (r[i] as Map)['valore']?.toString(),
                      decoration: const InputDecoration(labelText: 'Valore'),
                      onChanged: (v) => modifica(() => (r[i] as Map)['valore'] = v),
                    ),
                  ),
                  IconButton(icon: const Icon(Icons.close), onPressed: () => modifica(() => r.removeAt(i))),
                ]),
              ]),
            ),
          ),
        TextButton.icon(
          onPressed: () => modifica(() => r.insert(r.isEmpty ? 0 : r.length - 1, <String, dynamic>{'se': '', 'valore': ''})),
          icon: const Icon(Icons.add),
          label: const Text('Aggiungi un caso'),
        ),
      ],
    ]);
  }

  Widget _editorInserto(int i) {
    final ins = _inserti[i] as Map<String, dynamic>;
    final innesti = <String, String>{};
    final capoversiDi = <String, Set<String>>{};
    for (final m in _modelliBersaglio) {
      for (final p in listaDi(m['innesti'])) {
        innesti[p['innesto'] as String] = '${p['innesto']} (${p['sezione']})';
        capoversiDi.putIfAbsent(p['innesto'] as String, () => {}).addAll(List<String>.from(p['capoversi'] as List));
      }
    }
    final prima = capoversiDi[ins['innesto']] ?? <String>{};
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Punto di inserimento', elimina: () {
        modifica(() => _inserti.removeAt(i));
        _seleziona(const _Sel('generale'));
      }),
      const SizedBox(height: 12),
      if (innesti.isEmpty) const Text('Scegli prima i modelli a cui si applica la specificità (Dati generali).'),
      DropdownButtonFormField<String>(
        initialValue: innesti.containsKey(ins['innesto']) ? ins['innesto'] as String : null,
        decoration: const InputDecoration(labelText: 'Dove inserire i testi', border: OutlineInputBorder()),
        items: [for (final e in innesti.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
        onChanged: (v) => modifica(() {
          ins['innesto'] = v;
          ins.remove('prima_di');
        }),
      ),
      const SizedBox(height: 12),
      DropdownButtonFormField<String?>(
        initialValue: prima.contains(ins['prima_di']) ? ins['prima_di'] as String : null,
        decoration: const InputDecoration(labelText: 'Posizione nella sezione', border: OutlineInputBorder()),
        items: [
          const DropdownMenuItem<String?>(value: null, child: Text('In fondo alla sezione')),
          for (final c in prima) DropdownMenuItem<String?>(value: c, child: Text('Prima del capoverso $c')),
        ],
        onChanged: (v) => modifica(() => v == null ? ins.remove('prima_di') : ins['prima_di'] = v),
      ),
      const SizedBox(height: 12),
      OutlinedButton.icon(
        onPressed: () {
          modifica(() => _capoversiInserto(i).add(<String, dynamic>{'id': _nuovoId(definizione['codice'].toString().toLowerCase()), 'testo': 'Nuovo testo'}));
          _seleziona(_Sel('capoverso_inserto', i, 0, _capoversiInserto(i).length - 1));
        },
        icon: const Icon(Icons.add),
        label: const Text('Aggiungi un capoverso'),
      ),
    ]);
  }

  Widget _editorSuggerimento(int i) {
    final lista = _lista('suggerimenti');
    final s = lista[i] as Map<String, dynamic>;
    final domande = _variabili.where((v) => v.tipo == 'si_no' || v.tipo == 'scelta').toList();
    final v = domande.where((x) => x.nome == s['domanda']).firstOrNull;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Risposta consigliata', elimina: () {
        modifica(() => lista.removeAt(i));
        _seleziona(const _Sel('generale'));
      }),
      const SizedBox(height: 12),
      DropdownButtonFormField<String>(
        initialValue: v?.nome,
        decoration: const InputDecoration(labelText: 'Domanda', border: OutlineInputBorder()),
        items: [for (final d in domande) DropdownMenuItem(value: d.nome, child: Text(d.etichetta, overflow: TextOverflow.ellipsis))],
        onChanged: (x) => modifica(() {
          s['domanda'] = x;
          s['valore'] = domande.firstWhere((d) => d.nome == x).tipo == 'si_no' ? true : null;
        }),
      ),
      const SizedBox(height: 12),
      if (v?.tipo == 'scelta')
        DropdownButtonFormField<String>(
          initialValue: v!.opzioni.containsKey(s['valore']) ? s['valore'] as String : null,
          decoration: const InputDecoration(labelText: 'Risposta consigliata', border: OutlineInputBorder()),
          items: [for (final o in v.opzioni.entries) DropdownMenuItem(value: o.key, child: Text(o.value))],
          onChanged: (x) => modifica(() => s['valore'] = x),
        )
      else
        _interruttore('Risposta consigliata: Sì', s['valore'] == true, (x) => s['valore'] = x),
      const SizedBox(height: 12),
      CondizioneEditor(
        valore: s['se'] as String?,
        variabili: _variabili,
        etichetta: 'Quando consigliarla',
        onChanged: (x) => modifica(() => x == null ? s.remove('se') : s['se'] = x),
      ),
      const SizedBox(height: 12),
      _campo('Perché (mostrato a chi compila)', s['messaggio'], (x) => s['messaggio'] = x, righe: 3),
    ]);
  }

  Widget _editorScenario(int i) {
    final lista = _lista('scenari');
    final s = lista[i] as Map<String, dynamic>;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _barraElemento('Scenario di prova', elimina: () {
        modifica(() => lista.removeAt(i));
        _seleziona(const _Sel('generale'));
      }),
      const SizedBox(height: 12),
      _campo('Nome', s['nome'], (v) => s['nome'] = v),
      Text('Risposte: ${Map<String, dynamic>.from(s['risposte'] as Map? ?? const {}).length}'),
      const SizedBox(height: 8),
      FilledButton.tonal(
        onPressed: () {
          setState(() => _risposte = Map<String, dynamic>.from(s['risposte'] as Map? ?? const {}));
          _aggiornaAnteprima();
        },
        child: const Text('Usa nell\'anteprima'),
      ),
    ]);
  }

  Widget _editorCorrente() {
    final s = _sel;
    try {
      return switch (s.tipo) {
        'domanda' => _editorDomanda(s.i),
        'dato' => _editorDato(s.nome!),
        'derivato' => _editorDerivato(s.nome!),
        'fase' => _editorFase(s.i),
        'sezione' => _editorSezione(s.i, s.j),
        'capoverso' => _editorCapoverso(_capoversi(s.i, s.j), s.k, (k) => _Sel('capoverso', s.i, s.j, k),
            'Fase ${_fase(s.i)['numero']} › ${_sezione(s.i, s.j)['titolo']}'),
        'inserto' => _editorInserto(s.i),
        'capoverso_inserto' => _editorCapoverso(_capoversiInserto(s.i), s.k, (k) => _Sel('capoverso_inserto', s.i, 0, k),
            'Inserito in: ${(_inserti[s.i] as Map)['innesto']}'),
        'suggerimento' => _editorSuggerimento(s.i),
        'scenario' => _editorScenario(s.i),
        _ => _editorGenerale(),
      };
    } on RangeError {
      return _editorGenerale();
    }
  }

  // --- anteprima ------------------------------------------------------------------------------

  static final _mancante = RegExp(r'\[\[([^\]]+)\]\]');

  TextSpan _testoAnteprima(String testo, Map<String, dynamic> etichette) {
    final colori = Theme.of(context).colorScheme;
    final parti = <TextSpan>[];
    var da = 0;
    for (final m in _mancante.allMatches(testo)) {
      if (m.start > da) parti.add(TextSpan(text: testo.substring(da, m.start)));
      parti.add(TextSpan(
        text: '«${etichette[m.group(1)] ?? m.group(1)}»',
        style: TextStyle(backgroundColor: colori.secondaryContainer, color: colori.onSecondaryContainer),
      ));
      da = m.end;
    }
    if (da < testo.length) parti.add(TextSpan(text: testo.substring(da)));
    return TextSpan(children: parti);
  }

  Widget _rispostaProva(Map<String, dynamic> q) {
    final id = q['id'] as String;
    final opzioni = Map<String, dynamic>.from(q['opzioni'] as Map? ?? const {});
    void imposta(Object? v) {
      setState(() => v == null ? _risposte.remove(id) : _risposte[id] = v);
      _aggiornaAnteprima();
    }

    final Widget campo = switch (q['tipo']) {
      'si_no' => SegmentedButton<bool>(
          emptySelectionAllowed: true,
          segments: const [ButtonSegment(value: true, label: Text('Sì')), ButtonSegment(value: false, label: Text('No'))],
          selected: _risposte[id] is bool ? {_risposte[id] as bool} : const {},
          onSelectionChanged: (s) => imposta(s.isEmpty ? null : s.first),
        ),
      'scelta' => DropdownButton<String>(
          isExpanded: true,
          value: opzioni.containsKey(_risposte[id]) ? _risposte[id] as String : null,
          hint: const Text('—'),
          items: [for (final o in opzioni.entries) DropdownMenuItem(value: o.key, child: Text(o.value.toString(), overflow: TextOverflow.ellipsis))],
          onChanged: imposta,
        ),
      'scelta_multipla' => Wrap(spacing: 4, children: [
          for (final o in opzioni.entries)
            FilterChip(
              label: Text(o.value.toString()),
              selected: (List<dynamic>.from(_risposte[id] as List? ?? const [])).contains(o.key),
              onSelected: (s) {
                final l = List<dynamic>.from(_risposte[id] as List? ?? const []);
                s ? l.add(o.key) : l.remove(o.key);
                imposta(l);
              },
            ),
        ]),
      _ => TextFormField(
          initialValue: _risposte[id]?.toString() ?? '',
          decoration: const InputDecoration(isDense: true),
          onFieldSubmitted: (v) => imposta(v.trim().isEmpty ? null : v.trim()),
        ),
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(q['testo'] as String, style: Theme.of(context).textTheme.bodySmall),
        campo,
      ]),
    );
  }

  Widget _pannelloAnteprima() {
    final tema = Theme.of(context);
    final a = _anteprima;
    final scenari = _lista('scenari');
    final idSelezionato = switch (_sel.tipo) {
      'capoverso' => (() {
          try {
            return (_capoversi(_sel.i, _sel.j)[_sel.k] as Map)['id'];
          } catch (_) {
            return null;
          }
        })(),
      'capoverso_inserto' => (() {
          try {
            return (_capoversiInserto(_sel.i)[_sel.k] as Map)['id'];
          } catch (_) {
            return null;
          }
        })(),
      _ => null,
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
        child: Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text('Anteprima', style: tema.textTheme.titleMedium),
          if (modulo)
            DropdownButton<String>(
              value: _modelliBersaglio.any((m) => m['codice'] == _modelloAnteprima) ? _modelloAnteprima : null,
              hint: const Text('Modello'),
              items: [for (final m in _modelliBersaglio) DropdownMenuItem(value: m['codice'] as String, child: Text(m['titolo'] as String, overflow: TextOverflow.ellipsis))],
              onChanged: (v) {
                setState(() => _modelloAnteprima = v);
                _aggiornaAnteprima();
              },
            ),
          if (!modulo && scenari.isNotEmpty)
            PopupMenuButton<int>(
              tooltip: 'Scenari di prova',
              icon: const Icon(Icons.science_outlined),
              onSelected: (i) {
                setState(() => _risposte = Map<String, dynamic>.from((scenari[i] as Map)['risposte'] as Map? ?? const {}));
                _aggiornaAnteprima();
              },
              itemBuilder: (_) => [
                for (var i = 0; i < scenari.length; i++) PopupMenuItem(value: i, child: Text((scenari[i] as Map)['nome'].toString())),
              ],
            ),
          if (!modulo)
            TextButton.icon(
              onPressed: () async {
                final nome = TextEditingController();
                final ok = await showDialog<bool>(
                  context: context,
                  builder: (c) => AlertDialog(
                    title: const Text('Salva le risposte come scenario'),
                    content: TextField(controller: nome, autofocus: true, decoration: const InputDecoration(labelText: 'Nome')),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
                      FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Salva')),
                    ],
                  ),
                );
                if (ok == true && nome.text.trim().isNotEmpty) {
                  modifica(() => _lista('scenari').add(<String, dynamic>{'nome': nome.text.trim(), 'risposte': copia(_risposte)}));
                }
                nome.dispose();
              },
              icon: const Icon(Icons.bookmark_add_outlined, size: 18),
              label: const Text('Salva scenario'),
            ),
        ]),
      ),
      if (a != null)
        ExpansionTile(
          dense: true,
          title: Text('Risposte di prova (${_risposte.length})'),
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                for (final q in listaDi(a['domande'])) _rispostaProva(q),
                TextButton(
                  onPressed: () {
                    setState(() => _risposte = {});
                    _aggiornaAnteprima();
                  },
                  child: const Text('Azzera le risposte'),
                ),
              ]),
            ),
          ],
        ),
      const Divider(height: 1),
      Expanded(
        child: _erroreAnteprima != null
            ? Padding(padding: const EdgeInsets.all(12), child: Text(_erroreAnteprima!, style: TextStyle(color: tema.colorScheme.error)))
            : a == null
                ? const Center(child: CircularProgressIndicator())
                : ListView(padding: const EdgeInsets.all(12), children: [
                    for (final b in List<String>.from(a['blocchi'] as List))
                      Card(color: tema.colorScheme.errorContainer, child: ListTile(leading: const Icon(Icons.block), title: Text(b))),
                    for (final f in listaDi(a['fasi'])) ...[
                      Padding(
                        padding: const EdgeInsets.only(top: 12, bottom: 4),
                        child: Text('Fase ${f['numero']} · ${f['titolo']}', style: tema.textTheme.labelLarge?.copyWith(color: tema.colorScheme.primary)),
                      ),
                      if (f['formula'] != null) Center(child: Text(f['formula'] as String, style: const TextStyle(fontWeight: FontWeight.bold))),
                      for (final s in listaDi(f['sezioni']))
                        for (final c in listaDi(s['capoversi']))
                          if (c['escluso'] != true)
                            InkWell(
                              onTap: () {
                                final p = _posizioneCapoverso(c['id'] as String);
                                if (p != null) _seleziona(p);
                              },
                              child: Container(
                                margin: const EdgeInsets.only(bottom: 6),
                                padding: const EdgeInsets.all(6),
                                decoration: BoxDecoration(
                                  color: c['id'] == idSelezionato
                                      ? const Color(0x55FFD54F)
                                      : c['evidenziato'] == true
                                          ? tema.colorScheme.tertiaryContainer.withValues(alpha: 0.4)
                                          : null,
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: Text.rich(_testoAnteprima(c['testo'] as String, Map<String, dynamic>.from(a['etichette'] as Map))),
                              ),
                            ),
                    ],
                  ]),
      ),
    ]);
  }

  // --- pagina ---------------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (erroreCaricamento != null) {
      return Scaffold(appBar: AppBar(), body: Center(child: Text(erroreCaricamento.toString())));
    }
    if (dettaglio == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final titolo = modulo ? definizione['etichetta'] : definizione['titolo'];
    return PopScope(
      canPop: !modificata,
      onPopInvokedWithResult: (fatto, _) async {
        if (fatto) return;
        if (await puoUscire() && context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${modulo ? 'Specificità' : 'Modello'}: $titolo'),
            statoVersione(),
          ]),
          actions: azioniEditor(),
        ),
        body: Column(children: [
          avvisoStato(),
          Expanded(
            child: LayoutBuilder(builder: (context, vincoli) {
          final largo = vincoli.maxWidth >= 1200;
          final albero = Column(children: [Expanded(child: _albero()), const Divider(height: 1), pannelloControllo()]);
          // in sola lettura si scorre ma non si modifica
          final centro = SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: IgnorePointer(
              ignoring: !inModifica,
              child: KeyedSubtree(key: ValueKey('${_sel.chiave}#$_generazione'), child: _editorCorrente()),
            ),
          );
          if (!largo) {
            return DefaultTabController(
              length: 3,
              child: Column(children: [
                const TabBar(tabs: [Tab(text: 'Struttura'), Tab(text: 'Elemento'), Tab(text: 'Anteprima')]),
                Expanded(child: TabBarView(children: [albero, centro, _pannelloAnteprima()])),
              ]),
            );
          }
          return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SizedBox(width: 320, child: albero),
            const VerticalDivider(width: 1),
            Expanded(flex: 5, child: centro),
            const VerticalDivider(width: 1),
            Expanded(flex: 4, child: _pannelloAnteprima()),
          ]);
        }),
          ),
        ]),
      ),
    );
  }
}
