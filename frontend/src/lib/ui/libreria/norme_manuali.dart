import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../../util/download.dart';
import '../comuni.dart';
import '../visualizzatore_pdf.dart';
import 'libreria_page.dart' show ConsultaArticolo;

const _base = '/api/v1/norme-manuali';

const _statiTesto = {
  'IN_CONVERSIONE': ('In conversione', Colors.blueGrey),
  'DA_CONFERMARE': ('Da confermare', Colors.orange),
  'ATTIVO': ('In uso', Colors.green),
  'SOSTITUITO': ('Sostituito', Colors.grey),
  'ERRORE_CONVERSIONE': ('Conversione non riuscita', Colors.red),
};

class _StatoTesto extends StatelessWidget {
  const _StatoTesto(this.stato);

  final String stato;

  @override
  Widget build(BuildContext context) {
    final (etichetta, colore) = _statiTesto[stato] ?? (stato, Colors.grey);
    return Chip(
      label: Text(etichetta, style: const TextStyle(fontSize: 12)),
      side: BorderSide(color: colore),
      backgroundColor: colore.withValues(alpha: 0.08),
      visualDensity: VisualDensity.compact,
    );
  }
}

/// Regolamenti interni, leggi regionali e altre norme non presenti su Normattiva.
///
/// Ogni norma ha uno o più testi caricati, ciascuno vigente da una data: il file viene
/// convertito, diviso in articoli, rivisto e confermato.
class NormeManuali extends StatefulWidget {
  const NormeManuali({super.key});

  @override
  State<NormeManuali> createState() => _NormeManualiState();
}

class _NormeManualiState extends State<NormeManuali> {
  late Future<List<dynamic>> _lista;
  Timer? _aggiornamento;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _aggiornamento?.cancel();
    super.dispose();
  }

  void _carica() {
    setState(() {
      _lista = apiDi(context).get(_base).then((v) {
        final lista = v as List;
        _aggiornaSeInConversione(lista);
        return lista;
      });
    });
  }

  /// Finché un file è in conversione l'elenco si aggiorna da solo.
  void _aggiornaSeInConversione(List<dynamic> lista) {
    _aggiornamento?.cancel();
    final inConversione = lista.any((n) => (n['testi'] as List)
        .any((t) => t['stato'] == 'IN_CONVERSIONE'));
    if (inConversione) {
      _aggiornamento = Timer(const Duration(seconds: 3), () {
        if (mounted) _carica();
      });
    }
  }

  Future<void> _esegui(Future<void> Function() azione, [String? messaggio]) async {
    try {
      await azione();
      if (mounted && messaggio != null) mostraMessaggio(context, messaggio);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
    if (mounted) _carica();
  }

  Future<void> _aggiungi() async {
    final ok = await showDialog<bool>(context: context, builder: (_) => const _NuovaNorma());
    if (ok == true) {
      if (mounted) mostraMessaggio(context, 'Norma aggiunta: il testo è in conversione');
      _carica();
    }
  }

  Future<void> _nuovoTesto(Map<String, dynamic> norma) async {
    final ok = await showDialog<bool>(
        context: context, builder: (_) => _NuovoTesto(norma: norma));
    if (ok == true) _carica();
  }

  Future<void> _modifica(Map<String, dynamic> norma) async {
    final ok = await showDialog<bool>(
        context: context, builder: (_) => _ModificaNorma(norma: norma));
    if (ok == true) _carica();
  }

  Future<void> _rivedi(Map<String, dynamic> norma, Map<String, dynamic> testo) async {
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => RevisioneTesto(norma: norma, testoId: testo['id'] as String),
    ));
    if (mounted) _carica();
  }

  @override
  Widget build(BuildContext context) {
    final puoGestire = context.watch<AuthState>().utente!.isControllore;
    return Scaffold(
      floatingActionButton: puoGestire
          ? FloatingActionButton.extended(
              onPressed: _aggiungi,
              icon: const Icon(Icons.upload_file),
              label: const Text('Aggiungi norma'),
            )
          : null,
      body: Caricamento<List<dynamic>>(
        future: _lista,
        riprova: _carica,
        builder: (context, lista) => lista.isEmpty
            ? const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text(
                    'Nessuna norma inserita.\nQui si caricano i regolamenti dell\'ente, le leggi '
                    'regionali e le altre norme che non si trovano su Normattiva.',
                    textAlign: TextAlign.center,
                  ),
                ),
              )
            : ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 88), children: [
                for (final n in lista.cast<Map<String, dynamic>>())
                  _schedaNorma(n, puoGestire),
              ]),
      ),
    );
  }

  Widget _schedaNorma(Map<String, dynamic> n, bool puoGestire) {
    final api = apiDi(context);
    final testi = List<Map<String, dynamic>>.from(n['testi'] as List);
    final daConfermare = testi.where((t) => t['stato'] == 'DA_CONFERMARE').length;
    return Card(
      child: ExpansionTile(
        leading: const Icon(Icons.account_balance_outlined),
        title: Text(n['citazione'].toString()),
        subtitle: Text([
          '${n['tipo_descrizione']} n. ${n['numero']} del ${formatData(n['data_provvedimento'])}',
          if (n['abrogata_dal'] != null) 'abrogata dal ${formatData(n['abrogata_dal'])}',
          if (daConfermare > 0) '$daConfermare testo da confermare',
        ].join(' · ')),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (n['titolo'] != null) Text(n['titolo'].toString()),
          const SizedBox(height: 8),
          Text('Riconosciuta negli atti come:', style: Theme.of(context).textTheme.labelMedium),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final d in List<String>.from(n['denominazioni'] as List))
              Chip(label: Text(d), visualDensity: VisualDensity.compact),
          ]),
          const Divider(height: 24),
          Text('Testi', style: Theme.of(context).textTheme.titleSmall),
          for (final t in testi)
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('In vigore dal ${formatData(t['vigenza_inizio'])}'),
              subtitle: Text([
                t['file_nome'],
                if (t['errore'] != null) t['errore'],
              ].join(' · ')),
              trailing: Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 4, children: [
                _StatoTesto(t['stato'] as String),
                if (t['stato'] == 'DA_CONFERMARE' || t['stato'] == 'ATTIVO')
                  IconButton(
                    tooltip: t['stato'] == 'DA_CONFERMARE' ? 'Rivedi e conferma' : 'Rivedi il testo',
                    icon: const Icon(Icons.fact_check_outlined),
                    onPressed: () => _rivedi(n, t),
                  ),
                IconButton(
                  tooltip: 'Scarica il file originale',
                  icon: const Icon(Icons.download),
                  onPressed: () =>
                      salvaFile(api, '$_base/testi/${t['id']}/file', t['file_nome'] as String),
                ),
                if (puoGestire)
                  IconButton(
                    tooltip: 'Elimina il testo',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () async {
                      if (!await conferma(context, 'Eliminare il testo?',
                          'Il testo in vigore dal ${formatData(t['vigenza_inizio'])} non sarà più usato nelle verifiche.')) {
                        return;
                      }
                      await _esegui(() => api.delete('$_base/testi/${t['id']}'));
                    },
                  ),
              ]),
            ),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => Scaffold(
                  appBar: AppBar(title: Text(n['citazione'].toString())),
                  body: ConsultaArticolo(urnAtto: n['urn'] as String),
                ),
              )),
              icon: const Icon(Icons.search),
              label: const Text('Consulta articoli'),
            ),
            if (puoGestire) ...[
              OutlinedButton.icon(
                onPressed: () => _nuovoTesto(n),
                icon: const Icon(Icons.upload_file),
                label: const Text('Nuovo testo (modifica)'),
              ),
              OutlinedButton.icon(
                onPressed: () => _modifica(n),
                icon: const Icon(Icons.edit_outlined),
                label: const Text('Modifica dati'),
              ),
              OutlinedButton.icon(
                onPressed: () async {
                  if (!await conferma(context, 'Eliminare la norma?',
                      '${n['citazione']} e tutti i suoi testi saranno eliminati.')) {
                    return;
                  }
                  await _esegui(
                    () => api.delete('$_base/norma?urn=${Uri.encodeQueryComponent(n['urn'] as String)}'),
                    'Norma eliminata',
                  );
                },
                icon: const Icon(Icons.delete_outline),
                label: const Text('Elimina norma'),
              ),
            ],
          ]),
        ],
      ),
    );
  }
}

/// Scelta di un file PDF, ODT, DOCX o DOC.
class _SceltaFile extends StatelessWidget {
  const _SceltaFile({required this.file, required this.suScelta});

  final PlatformFile? file;
  final ValueChanged<PlatformFile> suScelta;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.attach_file),
      title: Text(file?.name ?? 'File del testo (PDF, ODT, DOCX o DOC)'),
      trailing: OutlinedButton(
        onPressed: () async {
          final scelto = await FilePicker.pickFile(
            type: FileType.custom,
            allowedExtensions: ['pdf', 'odt', 'docx', 'doc'],
          );
          if (scelto != null) suScelta(scelto);
        },
        child: Text(file == null ? 'Scegli' : 'Cambia'),
      ),
    );
  }
}

class _CampoData extends StatelessWidget {
  const _CampoData({required this.etichetta, required this.valore, required this.suScelta});

  final String etichetta;
  final DateTime? valore;
  final ValueChanged<DateTime> suScelta;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(valore == null ? etichetta : '$etichetta: ${formatData(isoData(valore!))}'),
      trailing: const Icon(Icons.calendar_month),
      onTap: () async {
        final d = await scegliData(context, valore);
        if (d != null) suScelta(d);
      },
    );
  }
}

class _NuovaNorma extends StatefulWidget {
  const _NuovaNorma();

  @override
  State<_NuovaNorma> createState() => _NuovaNormaState();
}

class _NuovaNormaState extends State<_NuovaNorma> {
  late final Future<List<dynamic>> _tipi;
  final _citazione = TextEditingController();
  final _titolo = TextEditingController();
  final _numero = TextEditingController();
  final _denominazioni = TextEditingController();
  String _tipo = 'regolamento';
  DateTime? _data;
  DateTime? _vigenza;
  PlatformFile? _file;
  bool _invio = false;

  @override
  void initState() {
    super.initState();
    _tipi = apiDi(context).get('$_base/tipi').then((v) => v as List);
  }

  @override
  void dispose() {
    for (final c in [_citazione, _titolo, _numero, _denominazioni]) {
      c.dispose();
    }
    super.dispose();
  }

  bool get _completo =>
      _citazione.text.trim().length >= 3 &&
      _numero.text.trim().isNotEmpty &&
      _data != null &&
      _vigenza != null &&
      _file != null;

  Future<void> _salva() async {
    setState(() => _invio = true);
    try {
      await apiDi(context).postMultipart(
        _base,
        campi: {
          'tipo': _tipo,
          'data': isoData(_data!),
          'numero': _numero.text.trim(),
          'citazione': _citazione.text.trim(),
          'titolo': _titolo.text.trim(),
          'denominazioni': _denominazioni.text,
          'vigenza_inizio': isoData(_vigenza!),
        },
        campoFile: 'file',
        bytes: await _file!.readAsBytes(),
        nomeFile: _file!.name,
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() => _invio = false);
        mostraErrore(context, e);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Aggiungi norma non presente su Normattiva'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            FutureBuilder<List<dynamic>>(
              future: _tipi,
              builder: (context, s) => DropdownButtonFormField<String>(
                initialValue: _tipo,
                decoration: const InputDecoration(labelText: 'Tipo'),
                items: [
                  for (final t in (s.data ?? [
                    {'codice': 'regolamento', 'descrizione': 'Regolamento'}
                  ]).cast<Map<String, dynamic>>())
                    DropdownMenuItem(
                        value: t['codice'] as String, child: Text(t['descrizione'] as String)),
                ],
                onChanged: (v) => setState(() => _tipo = v ?? _tipo),
              ),
            ),
            TextField(
              controller: _citazione,
              decoration: const InputDecoration(
                labelText: 'Nome con cui la si cita',
                hintText: 'Regolamento di contabilità',
              ),
              onChanged: (_) => setState(() {}),
            ),
            TextField(
              controller: _titolo,
              decoration: const InputDecoration(labelText: 'Titolo completo (facoltativo)'),
            ),
            Row(children: [
              Expanded(
                child: _CampoData(
                  etichetta: 'Approvata il',
                  valore: _data,
                  suScelta: (d) => setState(() {
                    _data = d;
                    _vigenza ??= d;
                  }),
                ),
              ),
              const SizedBox(width: 16),
              SizedBox(
                width: 140,
                child: TextField(
                  controller: _numero,
                  decoration: const InputDecoration(labelText: 'Numero', hintText: 'n. delibera'),
                  onChanged: (_) => setState(() {}),
                ),
              ),
            ]),
            TextField(
              controller: _denominazioni,
              minLines: 2,
              maxLines: 5,
              decoration: const InputDecoration(
                labelText: 'Altri modi in cui è citata negli atti (uno per riga)',
                hintText: 'Regolamento comunale di contabilità\ndeliberazione C.C. n. 12/2018',
                helperText: 'Il nome con cui la si cita è già compreso. Le citazioni scritte in '
                    'altre forme vengono cercate anche dal modello linguistico.',
                helperMaxLines: 3,
              ),
            ),
            const SizedBox(height: 8),
            _CampoData(
              etichetta: 'Testo in vigore dal',
              valore: _vigenza,
              suScelta: (d) => setState(() => _vigenza = d),
            ),
            _SceltaFile(file: _file, suScelta: (f) => setState(() => _file = f)),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annulla')),
        FilledButton(
          onPressed: _completo && !_invio ? _salva : null,
          child: Text(_invio ? 'Caricamento…' : 'Carica'),
        ),
      ],
    );
  }
}

class _NuovoTesto extends StatefulWidget {
  const _NuovoTesto({required this.norma});

  final Map<String, dynamic> norma;

  @override
  State<_NuovoTesto> createState() => _NuovoTestoState();
}

class _NuovoTestoState extends State<_NuovoTesto> {
  DateTime? _vigenza;
  PlatformFile? _file;
  bool _invio = false;

  Future<void> _salva() async {
    setState(() => _invio = true);
    try {
      await apiDi(context).postMultipart(
        '$_base/testi?urn=${Uri.encodeQueryComponent(widget.norma['urn'] as String)}',
        campi: {'vigenza_inizio': isoData(_vigenza!)},
        campoFile: 'file',
        bytes: await _file!.readAsBytes(),
        nomeFile: _file!.name,
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() => _invio = false);
        mostraErrore(context, e);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Nuovo testo di ${widget.norma['citazione']}'),
      content: SizedBox(
        width: 480,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text(
            'Carica il testo coordinato dopo una modifica. Il testo precedente resta valido '
            'fino al giorno prima della data indicata: gli atti adottati prima continuano a '
            'essere verificati sul testo di allora.',
          ),
          const SizedBox(height: 12),
          _CampoData(
            etichetta: 'Testo in vigore dal',
            valore: _vigenza,
            suScelta: (d) => setState(() => _vigenza = d),
          ),
          _SceltaFile(file: _file, suScelta: (f) => setState(() => _file = f)),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annulla')),
        FilledButton(
          onPressed: _vigenza != null && _file != null && !_invio ? _salva : null,
          child: Text(_invio ? 'Caricamento…' : 'Carica'),
        ),
      ],
    );
  }
}

class _ModificaNorma extends StatefulWidget {
  const _ModificaNorma({required this.norma});

  final Map<String, dynamic> norma;

  @override
  State<_ModificaNorma> createState() => _ModificaNormaState();
}

class _ModificaNormaState extends State<_ModificaNorma> {
  late final _citazione = TextEditingController(text: widget.norma['citazione'] as String);
  late final _titolo = TextEditingController(text: widget.norma['titolo'] as String? ?? '');
  late final _denominazioni = TextEditingController(
      text: List<String>.from(widget.norma['denominazioni'] as List).join('\n'));
  late DateTime? _abrogata = daIso(widget.norma['abrogata_dal'] as String?);

  @override
  void dispose() {
    for (final c in [_citazione, _titolo, _denominazioni]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _salva() async {
    try {
      await apiDi(context).put(
        '$_base/norma?urn=${Uri.encodeQueryComponent(widget.norma['urn'] as String)}',
        {
          'citazione': _citazione.text.trim(),
          'titolo': _titolo.text.trim(),
          'denominazioni': _denominazioni.text
              .split('\n')
              .map((r) => r.trim())
              .where((r) => r.isNotEmpty)
              .toList(),
          'abrogata_dal': _abrogata == null ? null : isoData(_abrogata!),
        },
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Modifica norma'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
              controller: _citazione,
              decoration: const InputDecoration(labelText: 'Nome con cui la si cita'),
            ),
            TextField(
              controller: _titolo,
              decoration: const InputDecoration(labelText: 'Titolo completo'),
            ),
            TextField(
              controller: _denominazioni,
              minLines: 3,
              maxLines: 8,
              decoration: const InputDecoration(
                labelText: 'Modi in cui è citata negli atti (uno per riga)',
              ),
            ),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                child: _CampoData(
                  etichetta: _abrogata == null ? 'Abrogata dal (se abrogata)' : 'Abrogata dal',
                  valore: _abrogata,
                  suScelta: (d) => setState(() => _abrogata = d),
                ),
              ),
              if (_abrogata != null)
                IconButton(
                  tooltip: 'Non abrogata',
                  icon: const Icon(Icons.clear),
                  onPressed: () => setState(() => _abrogata = null),
                ),
            ]),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annulla')),
        FilledButton(onPressed: _salva, child: const Text('Salva')),
      ],
    );
  }
}

/// Revisione del testo convertito: articoli riconosciuti, testo da correggere e file
/// originale, con la ricerca di un testo in tutte le viste.
class RevisioneTesto extends StatefulWidget {
  const RevisioneTesto({super.key, required this.norma, required this.testoId});

  final Map<String, dynamic> norma;
  final String testoId;

  @override
  State<RevisioneTesto> createState() => _RevisioneTestoState();
}

enum _Vista { testo, originale }

class _RevisioneTestoState extends State<RevisioneTesto> with SingleTickerProviderStateMixin {
  final _testo = TextEditingController();
  final _cerca = TextEditingController();
  final _focusEditor = FocusNode();
  final _chiaveEditor = GlobalKey();
  late final _schede = TabController(length: 3, vsync: this);
  Map<String, dynamic>? _dati;
  Object? _errore;
  bool _modificato = false;
  bool _invio = false;
  _Vista _vista = _Vista.testo; // pannello di destra su schermo largo
  bool _largo = true;

  // ricerca: posizioni delle occorrenze nel testo e quella selezionata
  String _q = '';
  List<int> _occorrenze = [];
  int _corrente = -1;

  String get _percorso => '$_base/testi/${widget.testoId}';

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _testo.dispose();
    _cerca.dispose();
    _focusEditor.dispose();
    _schede.dispose();
    super.dispose();
  }

  void _impostaDati(Map<String, dynamic> dati) {
    _dati = dati;
    _testo.text = dati['testo'] as String? ?? '';
    _modificato = false;
    _aggiornaOccorrenze();
  }

  Future<void> _carica() async {
    try {
      final dati = await apiDi(context).get(_percorso) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _impostaDati(dati);
        _errore = null;
      });
    } catch (e) {
      if (mounted) setState(() => _errore = e);
    }
  }

  Future<void> _azione(Future<dynamic> Function() chiamata, String messaggio) async {
    setState(() => _invio = true);
    try {
      final dati = await chiamata() as Map<String, dynamic>;
      if (!mounted) return;
      setState(() => _impostaDati(dati));
      mostraMessaggio(context, messaggio);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _invio = false);
    }
  }

  Future<void> _salvaTesto() => _azione(
        () => apiDi(context).put(_percorso, {'testo': _testo.text}),
        _dati?['stato'] == 'ATTIVO'
            ? 'Testo corretto: le verifiche useranno la nuova versione'
            : 'Testo salvato: controlla di nuovo gli articoli',
      );

  Future<void> _conferma() async {
    final api = apiDi(context);
    await _azione(() async {
      if (_modificato) await api.put(_percorso, {'testo': _testo.text});
      return api.post('$_percorso/conferma');
    }, 'Testo confermato: da ora è usato nelle verifiche degli atti');
  }

  // --- ricerca -------------------------------------------------------------------------

  void _aggiornaOccorrenze() {
    _q = _cerca.text.trim().toLowerCase();
    _occorrenze = [];
    if (_q.isNotEmpty) {
      final testo = _testo.text.toLowerCase();
      for (var i = testo.indexOf(_q); i >= 0; i = testo.indexOf(_q, i + _q.length)) {
        _occorrenze.add(i);
      }
    }
    if (_corrente >= _occorrenze.length) _corrente = _occorrenze.isEmpty ? -1 : 0;
  }

  void _suRicerca(String _) => setState(() {
        _corrente = -1;
        _aggiornaOccorrenze();
      });

  void _vaiOccorrenza(int passo) {
    if (_occorrenze.isEmpty) return;
    setState(() => _corrente = (_corrente + passo) % _occorrenze.length);
    _seleziona(_occorrenze[_corrente], _q.length);
  }

  /// Seleziona un tratto del testo, mostrando la vista del testo e scorrendo fino a lì.
  void _seleziona(int inizio, int lunghezza) {
    var attesa = Duration.zero;
    if (_largo && _vista != _Vista.testo) {
      setState(() => _vista = _Vista.testo);
    } else if (!_largo && _schede.index != 1) {
      _schede.animateTo(1);
      attesa = const Duration(milliseconds: 350); // la scheda del testo si costruisce dopo
    }
    Future.delayed(attesa, () {
      if (!mounted) return;
      _focusEditor.requestFocus();
      _testo.selection = TextSelection(baseOffset: inizio, extentOffset: inizio + lunghezza);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _statoEditor()?.bringIntoView(TextPosition(offset: inizio + lunghezza));
      });
    });
  }

  EditableTextState? _statoEditor() {
    EditableTextState? trovato;
    void visita(Element e) {
      if (trovato != null) return;
      if (e is StatefulElement && e.state is EditableTextState) {
        trovato = e.state as EditableTextState;
        return;
      }
      e.visitChildren(visita);
    }

    _chiaveEditor.currentContext?.visitChildElements(visita);
    return trovato;
  }

  /// Dall'anteprima al testo: seleziona la riga del titolo dell'articolo.
  void _vaiArticolo(String numero) {
    final titolo = RegExp(
      '^[\\s#*_>]*(?:art(?:icolo|\\.)?)\\s*${RegExp.escape(numero).replaceAll('-', '\\s*-?\\s*')}\\b.*\$',
      caseSensitive: false,
      multiLine: true,
    );
    final m = titolo.firstMatch(_testo.text);
    if (m != null) _seleziona(m.start, m.end - m.start);
  }

  // --- interfaccia -----------------------------------------------------------------------

  Widget _barraRicerca() {
    final testoOccorrenze = _q.isEmpty
        ? ''
        : _occorrenze.isEmpty
            ? 'nessuna nel testo'
            : '${_corrente < 0 ? '–' : _corrente + 1} di ${_occorrenze.length} nel testo';
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
      child: Row(children: [
        Expanded(
          child: TextField(
            controller: _cerca,
            decoration: InputDecoration(
              isDense: true,
              prefixIcon: const Icon(Icons.search),
              hintText: 'Cerca negli articoli e nel testo',
              suffixIcon: _q.isEmpty
                  ? null
                  : IconButton(
                      tooltip: 'Cancella',
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _cerca.clear();
                        _suRicerca('');
                      },
                    ),
            ),
            onChanged: _suRicerca,
            onSubmitted: (_) => _vaiOccorrenza(1),
          ),
        ),
        const SizedBox(width: 12),
        Text(testoOccorrenze),
        IconButton(
          tooltip: 'Precedente nel testo',
          icon: const Icon(Icons.keyboard_arrow_up),
          onPressed: _occorrenze.isEmpty ? null : () => _vaiOccorrenza(-1),
        ),
        IconButton(
          tooltip: 'Successiva nel testo (Invio)',
          icon: const Icon(Icons.keyboard_arrow_down),
          onPressed: _occorrenze.isEmpty ? null : () => _vaiOccorrenza(1),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final puoGestire = context.watch<AuthState>().utente!.isControllore;
    final dati = _dati;
    return Scaffold(
      appBar: AppBar(
        title: Text('${widget.norma['citazione']}'
            '${dati != null ? ' — testo in vigore dal ${formatData(dati['vigenza_inizio'])}' : ''}'),
        actions: [
          if (dati != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: _StatoTesto(dati['stato'] as String),
            ),
        ],
      ),
      body: _errore != null
          ? Center(child: Text(_errore.toString()))
          : dati == null
              ? const Center(child: CircularProgressIndicator())
              : LayoutBuilder(builder: (context, vincoli) {
                  _largo = vincoli.maxWidth > 1000;
                  final articoli = _Articoli(
                    anteprima: dati['anteprima'] as Map<String, dynamic>?,
                    ricerca: _q,
                    suArticolo: _vaiArticolo,
                  );
                  final editor = _Editor(
                    chiave: _chiaveEditor,
                    controller: _testo,
                    focusNode: _focusEditor,
                    modificabile: puoGestire,
                    suModifica: () => setState(() {
                      _modificato = true;
                      _aggiornaOccorrenze();
                    }),
                  );
                  final originale = DecoratedBox(
                    decoration:
                        BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor)),
                    child: VisualizzatorePdf(url: apiDi(context).uri('$_percorso/anteprima')),
                  );
                  return Column(children: [
                    _barraRicerca(),
                    Expanded(
                      child: _largo
                          ? Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                              Expanded(child: articoli),
                              const VerticalDivider(width: 1),
                              Expanded(
                                child: Column(children: [
                                  Padding(
                                    padding: const EdgeInsets.only(top: 8),
                                    child: SegmentedButton<_Vista>(
                                      segments: const [
                                        ButtonSegment(
                                          value: _Vista.testo,
                                          icon: Icon(Icons.edit_note),
                                          label: Text('Testo letto dal sistema'),
                                        ),
                                        ButtonSegment(
                                          value: _Vista.originale,
                                          icon: Icon(Icons.picture_as_pdf_outlined),
                                          label: Text('Documento originale'),
                                        ),
                                      ],
                                      selected: {_vista},
                                      onSelectionChanged: (v) => setState(() => _vista = v.first),
                                    ),
                                  ),
                                  Expanded(
                                    // il testo resta costruito anche quando è nascosto, per
                                    // non perdere le modifiche e la posizione
                                    child: IndexedStack(
                                      index: _vista.index,
                                      children: [
                                        editor,
                                        // il riquadro del PDF solo quando è visibile: nel
                                        // browser un iframe nascosto resterebbe sopra il testo
                                        if (_vista == _Vista.originale)
                                          Padding(padding: const EdgeInsets.all(16), child: originale)
                                        else
                                          const SizedBox.shrink(),
                                      ],
                                    ),
                                  ),
                                ]),
                              ),
                            ])
                          : Column(children: [
                              TabBar(controller: _schede, tabs: const [
                                Tab(text: 'Articoli riconosciuti'),
                                Tab(text: 'Testo'),
                                Tab(text: 'Originale'),
                              ]),
                              Expanded(
                                child: TabBarView(
                                  controller: _schede,
                                  children: [articoli, editor, originale],
                                ),
                              ),
                            ]),
                    ),
                    if (puoGestire)
                      Material(
                        elevation: 4,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Row(children: [
                            Expanded(
                              child: Text(
                                dati['stato'] == 'DA_CONFERMARE'
                                    ? 'Controlla che articoli, commi e lettere siano riconosciuti '
                                        'correttamente confrontandoli con il documento originale; '
                                        'se serve correggi il testo e aggiorna l\'anteprima. '
                                        'Poi conferma.'
                                    : 'Il testo è in uso nelle verifiche: una correzione vale '
                                        'subito.',
                              ),
                            ),
                            const SizedBox(width: 12),
                            OutlinedButton.icon(
                              onPressed: _modificato && !_invio ? _salvaTesto : null,
                              icon: const Icon(Icons.refresh),
                              label: Text(dati['stato'] == 'ATTIVO'
                                  ? 'Salva la correzione'
                                  : 'Salva e aggiorna l\'anteprima'),
                            ),
                            if (dati['stato'] == 'DA_CONFERMARE') ...[
                              const SizedBox(width: 8),
                              FilledButton.icon(
                                onPressed: _invio ? null : _conferma,
                                icon: const Icon(Icons.check),
                                label: const Text('Conferma il testo'),
                              ),
                            ],
                          ]),
                        ),
                      ),
                  ]);
                }),
    );
  }
}

class _Editor extends StatelessWidget {
  const _Editor({
    required this.chiave,
    required this.controller,
    required this.focusNode,
    required this.modificabile,
    required this.suModifica,
  });

  final GlobalKey chiave;
  final TextEditingController controller;
  final FocusNode focusNode;
  final bool modificabile;
  final VoidCallback suModifica;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: chiave,
      padding: const EdgeInsets.all(16),
      child: TextField(
        controller: controller,
        focusNode: focusNode,
        readOnly: !modificabile,
        expands: true,
        maxLines: null,
        textAlignVertical: TextAlignVertical.top,
        style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
        decoration: const InputDecoration(
          border: OutlineInputBorder(),
          helperText: 'Ogni articolo inizia con una riga "Art. N - Rubrica", i commi con "1.", '
              '"2."..., le lettere con "a)", "b)"...',
          helperMaxLines: 2,
        ),
        onChanged: (_) => suModifica(),
      ),
    );
  }
}

/// Testo con le occorrenze di `ricerca` evidenziate.
TextSpan _evidenzia(String testo, String ricerca, Color colore) {
  if (ricerca.isEmpty) return TextSpan(text: testo);
  final minuscolo = testo.toLowerCase();
  final parti = <TextSpan>[];
  var da = 0;
  for (var i = minuscolo.indexOf(ricerca); i >= 0; i = minuscolo.indexOf(ricerca, da)) {
    if (i > da) parti.add(TextSpan(text: testo.substring(da, i)));
    parti.add(TextSpan(
      text: testo.substring(i, i + ricerca.length),
      style: TextStyle(backgroundColor: colore),
    ));
    da = i + ricerca.length;
  }
  if (da < testo.length) parti.add(TextSpan(text: testo.substring(da)));
  return TextSpan(children: parti);
}

class _Articoli extends StatelessWidget {
  const _Articoli({required this.anteprima, required this.ricerca, required this.suArticolo});

  final Map<String, dynamic>? anteprima;
  final String ricerca; // minuscolo; vuoto = tutti gli articoli
  final ValueChanged<String> suArticolo;

  static bool _contiene(Map<String, dynamic> a, String q) {
    final testi = [
      'art. ${a['numero']}',
      a['rubrica'] ?? '',
      for (final c in a['commi'] as List) ...[
        c['testo'] ?? '',
        for (final l in c['lettere'] as List? ?? []) l['testo'] ?? '',
      ],
    ];
    return testi.any((t) => t.toString().toLowerCase().contains(q));
  }

  @override
  Widget build(BuildContext context) {
    final tutti = List<Map<String, dynamic>>.from(anteprima?['articoli'] as List? ?? []);
    final articoli = ricerca.isEmpty ? tutti : tutti.where((a) => _contiene(a, ricerca)).toList();
    final colore = Colors.yellow.withValues(alpha: 0.6);
    final base = DefaultTextStyle.of(context).style;
    Widget testo(String t, {TextStyle? stile}) =>
        Text.rich(_evidenzia(t, ricerca, colore), style: stile ?? base);
    return ListView(padding: const EdgeInsets.all(16), children: [
      if (anteprima?['senza_articoli'] == true)
        Card(
          color: Colors.orange.withValues(alpha: 0.1),
          child: const ListTile(
            leading: Icon(Icons.warning_amber, color: Colors.orange),
            title: Text('Nessun articolo riconosciuto'),
            subtitle: Text('Tutto il testo è trattato come articolo 1. Se la norma ha articoli, '
                'controlla che ciascuno inizi con una riga "Art. N".'),
          ),
        ),
      Text(
        ricerca.isEmpty
            ? '${tutti.length} articoli riconosciuti (clic su un articolo per trovarlo nel testo)'
            : '${articoli.length} articoli su ${tutti.length} contengono il testo cercato',
        style: Theme.of(context).textTheme.titleSmall,
      ),
      const SizedBox(height: 8),
      for (final a in articoli)
        Card(
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: () => suArticolo(a['numero'] as String),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                testo('Art. ${a['numero']}${a['rubrica'] != null ? ' — ${a['rubrica']}' : ''}',
                    stile: base.copyWith(fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                for (final c in List<Map<String, dynamic>>.from(a['commi'] as List)) ...[
                  testo('${c['numero']}. ${c['alinea'] ?? c['testo']}'),
                  for (final l in List<Map<String, dynamic>>.from(c['lettere'] as List? ?? []))
                    Padding(
                      padding: const EdgeInsets.only(left: 20),
                      child: testo('${l['lettera']}) ${l['testo']}'),
                    ),
                  const SizedBox(height: 4),
                ],
              ]),
            ),
          ),
        ),
    ]);
  }
}
