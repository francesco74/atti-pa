import 'package:flutter/material.dart';

import '../bozze/scelta_riferimenti.dart';
import '../comuni.dart';
import 'editor_comune.dart';

/// Livello di una checklist: generica della tipologia, di un modello di atto o di una
/// specificità (modulo di regole). La verifica di un atto le applica tutte.
String livelloChecklist(Map<String, dynamic> c) => c['modello'] != null
    ? 'modello ${c['modello']}'
    : c['modulo'] != null
        ? 'specificità ${c['modulo']}'
        : 'generica della tipologia';

/// Parti di una regola: cosa verificare, gli esiti e le note. Il modello linguistico riceve
/// la regola come testo; i campi guidati la scompongono e la ricompongono.
class _Regola {
  static const esiti = {
    'CONFORME': 'È conforme se',
    'NON_CONFORME': 'Non è conforme se',
    'DUBBIO': 'È dubbio se',
    'NON_APPLICABILE': 'Non si applica se',
  };

  String cosa = '';
  final Map<String, String> quando = {for (final e in esiti.keys) e: ''};
  String note = '';

  static final _riga = RegExp(r'^È (CONFORME|NON_CONFORME|DUBBIO|NON_APPLICABILE) se (.*)$');

  /// null se la regola non segue lo schema (va modificata come testo libero).
  static _Regola? analizza(String testo) {
    final r = _Regola();
    final cosa = <String>[];
    final note = <String>[];
    var dopo = false;
    for (final riga in testo.split('\n')) {
      final m = _riga.firstMatch(riga);
      if (m != null) {
        if (r.quando[m.group(1)!]!.isNotEmpty) return null; // esito ripetuto
        r.quando[m.group(1)!] = m.group(2)!;
        dopo = true;
      } else {
        (dopo ? note : cosa).add(riga);
      }
    }
    r.cosa = cosa.join('\n');
    r.note = note.join('\n');
    return r.componi() == testo ? r : null;
  }

  String componi() => [
        if (cosa.isNotEmpty) cosa,
        for (final e in quando.entries)
          if (e.value.isNotEmpty) 'È ${e.key} se ${e.value}',
        if (note.isNotEmpty) note,
      ].join('\n');
}

/// Editor di una checklist: i controlli a sinistra, il controllo scelto a destra con i campi
/// guidati della regola, le norme e i capoversi del modello che lo soddisfano.
class EditorChecklistPage extends StatefulWidget {
  const EditorChecklistPage({super.key, required this.codice});

  final String codice;

  @override
  State<EditorChecklistPage> createState() => _EditorChecklistPageState();
}

class _EditorChecklistPageState extends State<EditorChecklistPage> with EditorConfigurazione {
  @override
  String get tipo => 'checklist';
  @override
  String get codice => widget.codice;

  int? _sel; // null: dati generali
  int _generazione = 0;
  // regola scomposta di ogni controllo; null se non segue lo schema (testo libero)
  final Map<int, _Regola?> _regole = {};

  @override
  void initState() {
    super.initState();
    carica();
  }

  @override
  void dopoCaricamento() => _rianalizza();

  /// Da chiamare quando i controlli cambiano posizione: ricrea campi e regole scomposte.
  void _rianalizza() {
    _generazione++;
    _regole
      ..clear()
      ..addAll({for (var i = 0; i < _elementi.length; i++) i: _Regola.analizza(_elemento(i)['regola']?.toString() ?? '')});
  }

  List<dynamic> get _elementi => (definizione['elementi'] ??= <dynamic>[]) as List;
  Map<String, dynamic> _elemento(int i) => _elementi[i] as Map<String, dynamic>;

  /// Capoversi a cui si possono collegare i controlli: quelli del modello o della specificità
  /// della checklist (per un modello anche quelli delle sue specificità).
  List<Map<String, dynamic>> get _capoversiCollegabili {
    final m = definizione['modello'];
    final s = definizione['modulo'];
    if (m != null) {
      final modello = listaDi(contesto['modelli']).where((x) => x['codice'] == m).firstOrNull;
      return listaDi(modello?['capoversi']);
    }
    if (s != null) {
      final modulo = listaDi(contesto['moduli']).where((x) => x['codice'] == s).firstOrNull;
      return listaDi(modulo?['capoversi']);
    }
    return [];
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

  void _seleziona(int? i) => setState(() => _sel = i);

  Widget _campo(String etichetta, Object? valore, ValueChanged<String> cambia, {int righe = 1, String? aiuto}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextFormField(
        initialValue: valore?.toString() ?? '',
        minLines: righe,
        maxLines: righe == 1 ? 1 : null,
        decoration: InputDecoration(
          labelText: etichetta,
          helperText: aiuto,
          helperMaxLines: 3,
          border: const OutlineInputBorder(),
          alignLabelWithHint: true,
        ),
        onChanged: (v) => modifica(() => cambia(v)),
      ),
    );
  }

  // --- elenco ------------------------------------------------------------------------------

  Widget _elenco() {
    return ListView(children: [
      ListTile(
        dense: true,
        leading: const Icon(Icons.info_outline, size: 18),
        title: const Text('Dati generali'),
        subtitle: Text('Si applica a: ${livelloChecklist(definizione)}'),
        selected: _sel == null,
        onTap: () => _seleziona(null),
      ),
      const Divider(height: 1),
      for (var i = 0; i < _elementi.length; i++)
        ListTile(
          dense: true,
          leading: CircleAvatar(radius: 12, child: Text('${i + 1}', style: const TextStyle(fontSize: 11))),
          title: Text(_elemento(i)['titolo']?.toString() ?? '', maxLines: 2, overflow: TextOverflow.ellipsis),
          subtitle: Text([
            if (_elemento(i)['obbligatorio'] == false) 'facoltativo',
            if ((_elemento(i)['capoversi'] as List? ?? const []).isNotEmpty)
              'collegato a ${(_elemento(i)['capoversi'] as List).length} capoversi',
          ].join(' · ')),
          selected: _sel == i,
          onTap: () => _seleziona(i),
        ),
      Padding(
        padding: const EdgeInsets.all(8),
        child: OutlinedButton.icon(
          onPressed: () {
            modifica(() {
              _elementi.add(<String, dynamic>{'titolo': 'Nuovo controllo', 'regola': 'Verifica che ', 'obbligatorio': true});
              _regole[_elementi.length - 1] = _Regola()..cosa = 'Verifica che ';
            });
            _seleziona(_elementi.length - 1);
          },
          icon: const Icon(Icons.add),
          label: const Text('Aggiungi un controllo'),
        ),
      ),
    ]);
  }

  // --- dati generali -----------------------------------------------------------------------

  Widget _editorGenerale() {
    final d = definizione;
    final tipologie = listaDi(contesto['tipologie']);
    final voci = <String, String>{
      '': 'Ogni atto della tipologia (generica)',
      for (final m in listaDi(contesto['modelli'])) 'modello:${m['codice']}': 'Modello: ${m['titolo']}',
      for (final m in listaDi(contesto['moduli'])) 'modulo:${m['codice']}': 'Specificità: ${m['etichetta']}',
    };
    final attuale = d['modello'] != null
        ? 'modello:${d['modello']}'
        : d['modulo'] != null
            ? 'modulo:${d['modulo']}'
            : '';
    voci.putIfAbsent(attuale, () => livelloChecklist(d));
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('Checklist ${d['codice']}', style: Theme.of(context).textTheme.titleMedium),
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
      DropdownButtonFormField<String>(
        initialValue: attuale,
        isExpanded: true,
        decoration: const InputDecoration(
          labelText: 'Si applica a',
          helperText: 'La verifica di un atto applica la checklist generica, quella del suo modello e '
              'quelle delle specificità scelte',
          helperMaxLines: 2,
          border: OutlineInputBorder(),
        ),
        items: [for (final v in voci.entries) DropdownMenuItem(value: v.key, child: Text(v.value))],
        onChanged: (v) => modifica(() {
          d['modello'] = v != null && v.startsWith('modello:') ? v.substring(8) : null;
          d['modulo'] = v != null && v.startsWith('modulo:') ? v.substring(7) : null;
        }),
      ),
    ]);
  }

  // --- controllo ---------------------------------------------------------------------------

  Widget _editorElemento(int i) {
    final tema = Theme.of(context);
    final e = _elemento(i);
    final regola = _regole[i];
    final collegati = List<String>.from(e['capoversi'] as List? ?? const []);
    final collegabili = _capoversiCollegabili;
    final noti = {for (final c in collegabili) c['id']: c};
    void aggiornaRegola(_Regola r) => e['regola'] = r.componi();

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Expanded(child: Text('Controllo ${i + 1}', style: tema.textTheme.titleMedium)),
        IconButton(
          tooltip: 'Sposta su',
          icon: const Icon(Icons.arrow_upward),
          onPressed: i == 0
              ? null
              : () {
                  modifica(() => _elementi.insert(i - 1, _elementi.removeAt(i)));
                  _seleziona(i - 1);
                  setState(_rianalizza);
                },
        ),
        IconButton(
          tooltip: 'Sposta giù',
          icon: const Icon(Icons.arrow_downward),
          onPressed: i == _elementi.length - 1
              ? null
              : () {
                  modifica(() => _elementi.insert(i + 1, _elementi.removeAt(i)));
                  _seleziona(i + 1);
                  setState(_rianalizza);
                },
        ),
        IconButton(
          tooltip: 'Duplica',
          icon: const Icon(Icons.copy),
          onPressed: () {
            modifica(() => _elementi.insert(i + 1, copia(e)));
            _seleziona(i + 1);
            setState(_rianalizza);
          },
        ),
        IconButton(
          tooltip: 'Elimina',
          icon: Icon(Icons.delete_outline, color: tema.colorScheme.error),
          onPressed: () async {
            if (await conferma(context, 'Eliminare il controllo?', 'L\'eliminazione diventa effettiva solo alla pubblicazione.')) {
              modifica(() => _elementi.removeAt(i));
              _seleziona(null);
              setState(_rianalizza);
            }
          },
        ),
      ]),
      const SizedBox(height: 12),
      _campo('Titolo del controllo', e['titolo'], (v) => e['titolo'] = v),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Obbligatorio'),
        subtitle: const Text('Se non è soddisfatto l\'atto non è conforme'),
        value: e['obbligatorio'] != false,
        onChanged: (v) => modifica(() => e['obbligatorio'] = v),
      ),
      const SizedBox(height: 8),
      if (regola == null) ...[
        _campo('Regola (testo libero)', e['regola'], (v) => e['regola'] = v, righe: 6,
            aiuto: 'La regola non segue lo schema "Verifica che… / È CONFORME se…": si modifica come testo.'),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () {
              // il testo diventa "cosa verificare"; gli esiti si completano nei campi
              final r = _Regola()..cosa = e['regola']?.toString() ?? '';
              modifica(() => _regole[i] = r);
              setState(() => _generazione++);
            },
            icon: const Icon(Icons.view_agenda_outlined),
            label: const Text('Usa i campi guidati'),
          ),
        ),
      ] else ...[
        _campo('Cosa verificare', regola.cosa, (v) => aggiornaRegola(regola..cosa = v), righe: 3,
            aiuto: 'Es. Verifica che l\'atto indichi il CIG acquisito per l\'affidamento.'),
        for (final x in _Regola.esiti.entries)
          _campo(x.value, regola.quando[x.key], (v) => aggiornaRegola(regola..quando[x.key] = v.replaceAll('\n', ' ')), righe: 2),
        _campo('Note per chi valuta', regola.note, (v) => aggiornaRegola(regola..note = v), righe: 2),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => setState(() {
              _regole[i] = null;
              _generazione++;
            }),
            icon: const Icon(Icons.notes),
            label: const Text('Modifica come testo libero'),
          ),
        ),
      ],
      const SizedBox(height: 8),
      NormeEditor(
        norme: List<String>.from(e['riferimenti'] as List? ?? const []),
        onChanged: (n) => modifica(() => e['riferimenti'] = n),
        aggiungiDaLibreria: _normeDaLibreria,
      ),
      const SizedBox(height: 4),
      Text('Il testo vigente delle norme è passato a chi valuta insieme alla regola.', style: tema.textTheme.bodySmall),
      const SizedBox(height: 16),
      Text('Collegato a', style: tema.textTheme.titleSmall),
      Text(
        collegabili.isEmpty
            ? 'Una checklist generica non si collega ai capoversi: vale per ogni modello.'
            : 'I capoversi che, nella bozza dell\'atto, soddisfano questo controllo. Se un capoverso '
                'collegato cambia o sparisce, il controllo lo segnala.',
        style: tema.textTheme.bodySmall,
      ),
      const SizedBox(height: 6),
      for (final id in collegati)
        Card(
          child: ListTile(
            dense: true,
            leading: Icon(noti.containsKey(id) ? Icons.link : Icons.link_off,
                color: noti.containsKey(id) ? null : tema.colorScheme.error),
            title: Text(noti[id]?['testo']?.toString() ?? '$id: capoverso inesistente', maxLines: 3, overflow: TextOverflow.ellipsis),
            subtitle: Text([id, if (noti[id]?['dove'] != null) noti[id]!['dove']].join(' · ')),
            trailing: IconButton(
              icon: const Icon(Icons.close),
              onPressed: () => modifica(() => e['capoversi'] = [...collegati]..remove(id)),
            ),
          ),
        ),
      if (collegabili.isNotEmpty)
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () async {
              final scelti = await showDialog<List<String>>(
                context: context,
                builder: (_) => _SceltaCapoversi(capoversi: collegabili, scelti: collegati),
              );
              if (scelti != null) modifica(() => e['capoversi'] = scelti);
            },
            icon: const Icon(Icons.add_link),
            label: const Text('Scegli i capoversi'),
          ),
        ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    if (erroreCaricamento != null) {
      return Scaffold(appBar: AppBar(), body: Center(child: Text(erroreCaricamento.toString())));
    }
    if (dettaglio == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final sel = _sel != null && _sel! < _elementi.length ? _sel : null;
    return PopScope(
      canPop: !modificata,
      onPopInvokedWithResult: (fatto, _) async {
        if (fatto) return;
        if (await puoUscire() && context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Checklist: ${definizione['titolo']}'),
            statoVersione(),
          ]),
          actions: azioniEditor(),
        ),
        body: LayoutBuilder(builder: (context, vincoli) {
          final elenco = Column(children: [Expanded(child: _elenco()), const Divider(height: 1), pannelloControllo()]);
          final centro = SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Align(
              alignment: Alignment.topLeft,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 900),
                child: KeyedSubtree(
                  key: ValueKey('$sel#$_generazione'),
                  child: sel == null ? _editorGenerale() : _editorElemento(sel),
                ),
              ),
            ),
          );
          if (vincoli.maxWidth < 900) {
            return DefaultTabController(
              length: 2,
              child: Column(children: [
                const TabBar(tabs: [Tab(text: 'Controlli'), Tab(text: 'Controllo scelto')]),
                Expanded(child: TabBarView(children: [elenco, centro])),
              ]),
            );
          }
          return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SizedBox(width: 340, child: elenco),
            const VerticalDivider(width: 1),
            Expanded(child: centro),
          ]);
        }),
      ),
    );
  }
}

class _SceltaCapoversi extends StatefulWidget {
  const _SceltaCapoversi({required this.capoversi, required this.scelti});

  final List<Map<String, dynamic>> capoversi;
  final List<String> scelti;

  @override
  State<_SceltaCapoversi> createState() => _SceltaCapoversiState();
}

class _SceltaCapoversiState extends State<_SceltaCapoversi> {
  late final Set<String> _scelti = {...widget.scelti};
  String _filtro = '';

  @override
  Widget build(BuildContext context) {
    final f = _filtro.toLowerCase();
    final visibili = widget.capoversi
        .where((c) => f.isEmpty || '${c['id']} ${c['testo']} ${c['dove']}'.toLowerCase().contains(f))
        .toList();
    return AlertDialog(
      title: const Text('Capoversi collegati'),
      content: SizedBox(
        width: 720,
        height: 520,
        child: Column(children: [
          TextField(
            autofocus: true,
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Cerca nel testo'),
            onChanged: (v) => setState(() => _filtro = v),
          ),
          Expanded(
            child: ListView(children: [
              for (final c in visibili)
                CheckboxListTile(
                  dense: true,
                  value: _scelti.contains(c['id']),
                  title: Text(c['testo']?.toString() ?? '', maxLines: 3, overflow: TextOverflow.ellipsis),
                  subtitle: Text([c['id'], c['dove'], if (c['se'] != null) 'se ${c['se']}'].join(' · ')),
                  onChanged: (v) => setState(() => v == true ? _scelti.add(c['id'] as String) : _scelti.remove(c['id'])),
                ),
            ]),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FilledButton(
          // nell'ordine del modello
          onPressed: () => Navigator.pop(context, [
            for (final c in widget.capoversi)
              if (_scelti.contains(c['id'])) c['id'] as String,
            ...widget.scelti.where((id) => !widget.capoversi.any((c) => c['id'] == id) && _scelti.contains(id)),
          ]),
          child: const Text('Conferma'),
        ),
      ],
    );
  }
}
