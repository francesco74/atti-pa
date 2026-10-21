import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import '../../util/download.dart';
import '../comuni.dart';
import '../verifica/pannello_verifica.dart';
import 'scelta_riferimenti.dart';

/// Redazione guidata da un modello di atto.
///
/// A sinistra la barra delle fasi (domande iniziali e le 4 fasi dell'atto) e i dati della
/// fase scelta, raggruppati per sezione; a destra le azioni, gli esiti dei controlli e l'atto
/// completo, aggiornato mentre si scrive. Il testo lo compone il server dal modello: i
/// capoversi si correggono direttamente nell'atto e restano collegati ai dati.
class BozzaEditorPage extends StatefulWidget {
  const BozzaEditorPage({super.key, required this.bozzaId});

  final String bozzaId;

  @override
  State<BozzaEditorPage> createState() => _BozzaEditorPageState();
}

class _BozzaEditorPageState extends State<BozzaEditorPage> {
  // larghezza del pannello di compilazione rispetto alla pagina: la si sposta trascinando la
  // divisione e resta uguale per le altre bozze aperte nella stessa sessione
  static const _rapportoPredefinito = 0.4;
  static double _rapporto = _rapportoPredefinito;

  Map<String, dynamic>? _bozza;
  Object? _erroreCaricamento;
  int _passo = 0;
  // salvataggio automatico: uno alla volta; lo stato si mostra senza ridisegnare la pagina
  final _statoSalvataggio = ValueNotifier<String>('');
  bool _inSalvataggio = false;
  bool _daRisalvare = false;

  // colonna di sinistra e atto si ridisegnano solo quando cambiano (vedi setState)
  Widget? _cacheCompilazione;
  Widget? _cacheDocumento;
  final Map<int, GlobalKey> _chiaviPassi = {}; // inizio di ogni fase nella colonna di sinistra
  bool _scorrimentoGuidato = false; // la barra delle fasi sta facendo scorrere la colonna
  bool _modificata = false;
  bool _mostraMancanti = false;

  final Map<String, dynamic> _risposte = {};
  final Set<String> _esclusi = {};
  final Set<String> _inclusi = {};
  final Map<String, String> _testi = {};
  List<Map<String, dynamic>> _riferimenti = [];

  // valori dei campi: semplici (un controller) ed elenchi (righe di controller)
  final Map<String, TextEditingController> _campi = {};
  final Map<String, List<Map<String, TextEditingController>>> _elenchi = {};
  final Map<String, TextEditingController> _risposteTesto = {};
  final Set<String> _svuotati = {}; // campi svuotati dall'utente: restano vuoti
  Timer? _salvataggioDifferito;

  // capoversi modificabili direttamente nel testo
  final Map<String, _ControllerCapoverso> _capoversi = {};
  final Map<String, FocusNode> _focusCapoversi = {};
  final Map<String, GlobalKey> _chiaviCapoversi = {}; // per scorrere l'atto fino a un dato
  final Map<String, Map<String, dynamic>> _datiCapoversi = {};
  final _scrollSinistra = ScrollController();
  final _scrollAtto = ScrollController();
  DateTime? _oraSalvataggio;
  bool _esitiAperti = true;
  final Map<String, FocusNode> _focusCampi = {};
  final Map<String, GlobalKey> _chiaviCampi = {}; // caselle senza cursore (date, elenchi)
  final Map<String, TapGestureRecognizer> _tocchiDati = {}; // clic sui dati nei testi fissi
  String? _campoAttivo; // il campo su cui si sta scrivendo: evidenziato nel testo

  Map<String, dynamic>? _controllo;
  Map<String, dynamic>? _verifica;
  Timer? _polling;
  bool _controlloInCorso = false;
  bool _controlloLento = false; // oltre 10 secondi: norme da scaricare da Normattiva
  Timer? _timerControllo;
  DateTime? _oraControllo;
  bool _verificaInAvvio = false;

  String get _percorso => '/api/v1/bozze/${widget.bozzaId}';
  Map<String, dynamic> get _stato => _bozza!['stato'] as Map<String, dynamic>;
  List<Map<String, dynamic>> get _fasi => List<Map<String, dynamic>>.from(_stato['fasi'] as List);

  @override
  void initState() {
    super.initState();
    _scrollSinistra.addListener(_seguiScorrimento);
    _carica();
  }

  /// Ogni modifica dello stato ridisegna colonna di sinistra e atto; le modifiche che
  /// riguardano solo l'atto (casella attiva, cursore) usano [_ridisegnaAtto].
  @override
  void setState(VoidCallback fn) {
    _cacheCompilazione = null;
    _cacheDocumento = null;
    super.setState(fn);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies(); // tema o dimensioni cambiati: si ridisegna tutto
    _cacheCompilazione = null;
    _cacheDocumento = null;
  }

  void _ridisegnaAtto() {
    _cacheDocumento = null;
    super.setState(() {});
  }

  @override
  void dispose() {
    _polling?.cancel();
    _timerControllo?.cancel();
    _salvataggioDifferito?.cancel();
    for (final c in [..._campi.values, ..._risposteTesto.values, ..._capoversi.values]) {
      c.dispose();
    }
    _scrollSinistra.dispose();
    _statoSalvataggio.dispose();
    _scrollAtto.dispose();
    for (final f in [..._focusCapoversi.values, ..._focusCampi.values]) {
      f.dispose();
    }
    for (final t in _tocchiDati.values) {
      t.dispose();
    }
    for (final righe in _elenchi.values) {
      for (final r in righe) {
        for (final c in r.values) {
          c.dispose();
        }
      }
    }
    super.dispose();
  }

  // --- dati -----------------------------------------------------------------------------

  Future<void> _carica() async {
    try {
      final b = await apiDi(context).get(_percorso) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() => _applica(b, iniziale: true));
    } catch (e) {
      if (mounted) setState(() => _erroreCaricamento = e);
    }
  }

  /// Aggiorna lo stato dalla risposta del server. All'inizio crea i controller con i valori
  /// salvati; dopo un salvataggio non tocca il testo in corso di scrittura.
  void _applica(Map<String, dynamic> b, {bool iniziale = false}) {
    _bozza = b;
    if (iniziale) {
      _risposte
        ..clear()
        ..addAll(Map<String, dynamic>.from(b['risposte'] as Map));
      final p = Map<String, dynamic>.from(b['personalizzazioni'] as Map);
      _esclusi
        ..clear()
        ..addAll(List<String>.from(p['esclusi'] as List? ?? []));
      _inclusi
        ..clear()
        ..addAll(List<String>.from(p['inclusi'] as List? ?? []));
      _testi
        ..clear()
        ..addAll(Map<String, String>.from(p['testi'] as Map? ?? {}));
      _riferimenti = List<Map<String, dynamic>>.from(b['riferimenti'] as List);
      final valori = Map<String, dynamic>.from(b['valori'] as Map);
      valori.forEach((nome, valore) {
        if (valore is List) {
          _elenchi[nome] = [
            for (final riga in valore)
              {
                for (final e in Map<String, dynamic>.from(riga as Map).entries)
                  e.key: TextEditingController(text: e.value?.toString() ?? ''),
              }
          ];
        } else {
          _campo(nome).text = valore?.toString() ?? '';
        }
      });
      _modificata = false;
    } else {
      final testi = Map<String, dynamic>.from((b['personalizzazioni'] as Map)['testi'] as Map? ?? {});
      _testi
        ..clear()
        ..addAll(testi.map((k, v) => MapEntry(k, v.toString())));
    }
    final fasi = List<Map<String, dynamic>>.from((b['stato'] as Map)['fasi'] as List);
    for (final f in fasi) {
      // caselle precompilate con il valore proposto (dati dell'ente, profilo, modello)
      for (final c in List<Map<String, dynamic>>.from(f['campi'] as List)) {
        final nome = c['nome'] as String;
        final proposto = c['proposto'];
        if (c['impostato'] == true || c['tipo'] == 'elenco' || _svuotati.contains(nome)) continue;
        if (proposto == null || proposto.toString().isEmpty) continue;
        final controller = _campo(nome);
        if (controller.text.isEmpty) {
          controller.text = proposto.toString();
          _modificata = true;
        }
      }
      // testo dei capoversi: aggiornato se non lo si sta modificando
      for (final sez in List<Map<String, dynamic>>.from(f['sezioni'] as List)) {
        for (final cap in List<Map<String, dynamic>>.from(sez['capoversi'] as List)) {
          final id = cap['id'] as String;
          _datiCapoversi[id] = cap;
          // nell'atto si scrive solo il testo fisso: i dati si cambiano nella loro casella
          final controller = _capoversi.putIfAbsent(
            id,
            () => _ControllerCapoverso(
              suModificaRifiutata: () {
                if (!mounted) return;
                ScaffoldMessenger.of(context)
                  ..hideCurrentSnackBar()
                  ..showSnackBar(const SnackBar(
                    behavior: SnackBarBehavior.floating,
                    content: Text('I dati evidenziati si cambiano nella loro casella: '
                        'nell\'atto si modifica solo il testo che li circonda.'),
                  ));
              },
            ),
          );
          final inModifica = _focusCapoversi[id]?.hasFocus ?? false;
          if (!inModifica) controller.imposta(cap['testo'] as String, cap['segmenti'] as List?);
        }
      }
    }
  }

  TextEditingController _campo(String nome) =>
      _campi.putIfAbsent(nome, () => TextEditingController()..addListener(_segnaModifica));

  void _segnaModifica() => _modificata = true;

  Map<String, dynamic> _valori() => {
        for (final e in _campi.entries)
          if (e.value.text.trim().isNotEmpty || _svuotati.contains(e.key)) e.key: e.value.text.trim(),
        for (final e in _elenchi.entries)
          e.key: [
            for (final riga in e.value) {for (final c in riga.entries) c.key: c.value.text.trim()},
          ],
      };

  Future<bool> _salva({bool silenzioso = true}) async {
    _salvataggioDifferito?.cancel();
    if (_inSalvataggio) {
      // si salverà di nuovo appena finito, con i dati più recenti
      _daRisalvare = true;
      return true;
    }
    _inSalvataggio = true;
    _aggiornaStatoSalvataggio();
    final domandeComplete = _bozza != null && _stato['domande_complete'] == true;
    try {
      final b = await apiDi(context).put(_percorso, {
        'risposte': _risposte,
        'valori': _valori(),
        'personalizzazioni': {
          'esclusi': _esclusi.toList(),
          'inclusi': _inclusi.toList(),
          'testi': _testi,
        },
        'riferimenti': _riferimenti,
      }) as Map<String, dynamic>;
      if (!mounted) return false;
      setState(() {
        _applica(b);
        _modificata = false;
      });
      _oraSalvataggio = DateTime.now();
      // risposte complete per la prima volta: si va alla fase 1
      if (!domandeComplete && _stato['domande_complete'] == true) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _vaiA(1);
        });
      }
      if (!silenzioso && mounted) mostraMessaggio(context, 'Bozza salvata');
      return true;
    } catch (e) {
      if (mounted) mostraErrore(context, e);
      return false;
    } finally {
      _inSalvataggio = false;
      _aggiornaStatoSalvataggio();
      if (_daRisalvare && mounted) {
        _daRisalvare = false;
        unawaited(_salva());
      }
    }
  }

  /// Attende il salvataggio in corso e salva i dati attuali (prima di controlli e documenti).
  Future<bool> _salvaOra() async {
    while (_inSalvataggio) {
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    return _salva();
  }

  void _aggiornaStatoSalvataggio() {
    final ora = _oraSalvataggio;
    _statoSalvataggio.value = _inSalvataggio
        ? 'Salvataggio…'
        : _modificata
            ? 'Modifiche da salvare'
            : ora != null
                ? 'Salvato alle ${ora.hour.toString().padLeft(2, '0')}:'
                    '${ora.minute.toString().padLeft(2, '0')}'
                : '';
  }

  void _salvaPiuTardi() {
    // la pagina (uscita con salvataggio) si ridisegna solo alla prima modifica
    if (!_modificata) super.setState(() => _modificata = true);
    _aggiornaStatoSalvataggio();
    _salvataggioDifferito?.cancel();
    _salvataggioDifferito = Timer(const Duration(seconds: 1), () {
      if (mounted) _salva();
    });
  }

  // --- navigazione ------------------------------------------------------------------------

  bool get _domandeComplete => _stato['domande_complete'] == true;

  bool _passoCompleto(int passo) {
    if (passo == 0) return _domandeComplete;
    if (passo >= 1 && passo <= _fasi.length) return _fasi[passo - 1]['completa'] == true;
    return true;
  }

  int _numeroMancanti(int passo) {
    if (passo == 0) {
      return List<Map<String, dynamic>>.from(_stato['domande'] as List)
              .where((q) => q['mancante'] == true)
              .length +
          (_stato['blocchi'] as List).length;
    }
    return List<Map<String, dynamic>>.from(_fasi[passo - 1]['campi'] as List)
        .where((c) => c['mancante'] == true || c['errore'] != null)
        .length;
  }

  void _vaiA(int passo) {
    if (passo > 0 && !_domandeComplete) {
      mostraMessaggio(context, 'Rispondi prima alle domande iniziali');
      return;
    }
    _scorriAPasso(passo);
  }

  /// Scorre la colonna di sinistra fino all'inizio della fase.
  void _scorriAPasso(int passo) {
    if (passo != _passo) {
      _passo = passo;
      _ridisegnaAtto();
    }
    final oggetto = _chiaviPassi[passo]?.currentContext?.findRenderObject();
    final viewport = oggetto == null ? null : RenderAbstractViewport.maybeOf(oggetto);
    if (oggetto == null || viewport == null || !_scrollSinistra.hasClients) return;
    final posizione = _scrollSinistra.position;
    final arrivo = viewport
        .getOffsetToReveal(oggetto, 0)
        .offset
        .clamp(posizione.minScrollExtent, posizione.maxScrollExtent);
    // più è lontana la fase, più dura lo scorrimento: l'occhio segue il movimento
    final distanza = (arrivo - posizione.pixels).abs();
    final durata = (400 + distanza / 6).clamp(400, 900).round();
    _scorrimentoGuidato = true; // la barra resta sulla destinazione durante lo scorrimento
    _scrollSinistra
        .animateTo(arrivo,
            duration: Duration(milliseconds: durata), curve: Curves.easeInOutCubic)
        .whenComplete(() => _scorrimentoGuidato = false);
  }

  /// Mentre si scorre a mano, la barra e l'atto seguono la fase che si ha sotto gli occhi.
  void _seguiScorrimento() {
    if (_scorrimentoGuidato || !_scrollSinistra.hasClients) return;
    var visibile = 0;
    for (final voce in _chiaviPassi.entries) {
      final oggetto = voce.value.currentContext?.findRenderObject();
      if (oggetto == null) continue;
      final viewport = RenderAbstractViewport.maybeOf(oggetto);
      if (viewport == null) continue;
      final inizio = viewport.getOffsetToReveal(oggetto, 0).offset;
      if (inizio <= _scrollSinistra.offset + 80 && voce.key > visibile) visibile = voce.key;
    }
    final posizione = _scrollSinistra.position;
    if (posizione.pixels >= posizione.maxScrollExtent - 4 && _domandeComplete) {
      visibile = _fasi.length; // in fondo: l'ultima fase, anche se non arriva in cima
    }
    if (visibile != _passo) {
      _passo = visibile;
      _ridisegnaAtto();
    }
  }

  /// Fase in cui si compila un dato: quella corrente se lo chiede, altrimenti la prima.
  int? _faseDelCampo(String nome) {
    bool chiede(Map<String, dynamic> f) =>
        List<Map<String, dynamic>>.from(f['campi'] as List).any((c) => c['nome'] == nome);
    if (_passo >= 1 && _passo <= _fasi.length && chiede(_fasi[_passo - 1])) return _passo;
    for (final f in _fasi) {
      if (chiede(f)) return f['numero'] as int;
    }
    return null;
  }

  /// Dall'atto alla casella: il cursore va nel campo, che scorre in vista da solo. Le caselle
  /// senza cursore (date, elenchi) si portano in vista e il dato si evidenzia nell'atto.
  void _vaiAlCampo(String nome) {
    if (_faseDelCampo(nome) == null) return;
    final nodo = _focusCampi[nome];
    if (nodo != null && nodo.context != null) {
      nodo.requestFocus();
      // nel browser il campo che prende il focus seleziona tutto: cursore in fondo
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final controller = _campi[nome];
        if (controller != null) {
          controller.selection = TextSelection.collapsed(offset: controller.text.length);
        }
      });
      return;
    }
    FocusManager.instance.primaryFocus?.unfocus();
    final contesto = _chiaviCampi[nome]?.currentContext;
    if (contesto != null) {
      Scrollable.ensureVisible(contesto,
          alignment: 0.2, duration: const Duration(milliseconds: 400), curve: Curves.easeInOutCubic);
    }
    _campoAttivo = nome;
    _ridisegnaAtto();
  }

  /// Dalla casella all'atto: scorre fino al primo capoverso in cui compare il dato.
  void _scorriAlDato(String nome) {
    String? trovato;
    for (final f in _fasi) {
      for (final s in List<Map<String, dynamic>>.from(f['sezioni'] as List)) {
        for (final c in List<Map<String, dynamic>>.from(s['capoversi'] as List)) {
          if (c['escluso'] != true && (c['campi'] as List? ?? []).contains(nome)) {
            if (trovato == null || f['numero'] == _passo) trovato ??= c['id'] as String;
            if (f['numero'] == _passo) {
              trovato = c['id'] as String;
              break;
            }
          }
        }
      }
    }
    final contesto = trovato == null ? null : _chiaviCapoversi[trovato]?.currentContext;
    if (contesto != null) {
      Scrollable.ensureVisible(contesto,
          alignment: 0.2, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
    }
  }

  /// Prima di scaricare o verificare: gli errori bloccano, i dati mancanti si segnalano.
  Future<bool> _controllaCompletezza(String azione) async {
    if (!await _salvaOra()) return false;
    if (!mounted) return false;
    final bloccanti = <(String, String?)>[
      for (final b in List<String>.from(_stato['blocchi'] as List)) (b, null),
      for (final f in _fasi)
        for (final c in List<Map<String, dynamic>>.from(f['campi'] as List))
          if (c['errore'] != null) ('${c['etichetta']}: ${c['errore']}', c['nome'] as String),
    ];
    final mancanti = <(String, String?)>[
      for (final q in List<Map<String, dynamic>>.from(_stato['domande'] as List))
        if (q['mancante'] == true) ('Domande iniziali: ${q['testo']}', null),
      for (final f in _fasi)
        for (final c in List<Map<String, dynamic>>.from(f['campi'] as List))
          if (c['mancante'] == true) ('Fase ${f['numero']}: ${c['etichetta']}', c['nome'] as String),
    ];
    if (bloccanti.isEmpty && mancanti.isEmpty) return true;
    setState(() => _mostraMancanti = true);
    final elenco = bloccanti.isNotEmpty ? bloccanti : mancanti;
    final procedi = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(bloccanti.isNotEmpty ? 'Correggi prima questi errori' : 'L\'atto è incompleto'),
        content: SizedBox(
          width: 520,
          child: ListView(shrinkWrap: true, children: [
            for (final (testo, campo) in elenco)
              ListTile(
                dense: true,
                leading: Icon(bloccanti.isNotEmpty ? Icons.error_outline : Icons.edit_note),
                title: Text(testo),
                trailing: campo == null ? null : const Icon(Icons.chevron_right),
                onTap: () {
                  Navigator.pop(c, false);
                  campo == null ? _vaiA(0) : _vaiAlCampo(campo);
                },
              ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          if (bloccanti.isEmpty)
            FilledButton(onPressed: () => Navigator.pop(c, true), child: Text('$azione comunque')),
        ],
      ),
    );
    return procedi == true;
  }

  // --- azioni ---------------------------------------------------------------------------

  Future<void> _espandi(Map<String, dynamic> campo) async {
    final controller = _campo(campo['nome'] as String);
    final appunti = TextEditingController(text: controller.text);
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Riscrivi «${campo['etichetta']}»'),
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
        'sezione': campo['etichetta'],
        'appunti': appunti.text,
        'oggetto': _bozza!['oggetto'] ?? '',
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
      builder: (_) => SceltaRiferimentiDialog(tipologia: _bozza!['tipologia_atto'] as String?),
    );
    if (scelti == null || scelti.isEmpty) return;
    for (final r in scelti) {
      final doppio = _riferimenti.any((x) =>
          x['urn_atto'] == r['urn_atto'] &&
          x['articolo'] == r['articolo'] &&
          x['comma'] == r['comma'] &&
          x['lettera'] == r['lettera']);
      if (!doppio) _riferimenti.add(r);
    }
    await _salva();
  }

  Future<void> _includi(Map<String, dynamic> cap, bool includere) async {
    final id = cap['id'] as String;
    if (cap['incluso_predefinito'] == true) {
      includere ? _esclusi.remove(id) : _esclusi.add(id);
    } else {
      includere ? _inclusi.add(id) : _inclusi.remove(id);
    }
    await _salva();
  }

  /// Fine della modifica diretta di un capoverso: i dati rimasti uguali tornano segnaposto
  /// (restano collegati ai campi), il resto è il testo scritto dall'utente.
  Future<void> _confermaCapoverso(String id) async {
    final cap = _datiCapoversi[id];
    final controller = _capoversi[id];
    if (cap == null || controller == null || controller.text == cap['testo']) return;
    final testo = controller.ricomponi();
    if (testo.trim().isEmpty) {
      _testi.remove(id);
    } else {
      _testi[id] = testo;
    }
    await _salva();
  }

  Future<void> _ripristinaCapoverso(String id) async {
    _testi.remove(id);
    await _salva();
  }

  /// Propone a chi gestisce i modelli di adottare il testo riscritto come testo del modello.
  /// Il testo è proposto con i dati come segnaposto ({{campo}}), modificabile prima dell'invio.
  Future<void> _proponiAlModello(Map<String, dynamic> c) async {
    final modello = _bozza!['modello'] as Map<String, dynamic>;
    final segmenti = List<Map<String, dynamic>>.from(c['segmenti'] as List? ?? const []);
    final attuale = segmenti.isEmpty
        ? c['testo'] as String
        : segmenti.map((s) => s['segnaposto'] ?? s['testo']).join();
    final testo = TextEditingController(text: attuale);
    final motivo = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Proponi una modifica al modello'),
        content: SizedBox(
          width: 640,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Modello: ${modello['titolo']} (v${modello['versione']}) · capoverso ${c['id']}',
                style: Theme.of(d).textTheme.bodySmall),
            const SizedBox(height: 8),
            TextField(
              controller: testo,
              minLines: 3,
              maxLines: 10,
              decoration: const InputDecoration(
                labelText: 'Testo proposto',
                helperText: 'I dati compaiono come {{nome}}: restano collegati alle caselle',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: motivo,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Perché (facoltativo)', border: OutlineInputBorder()),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('Invia la proposta')),
        ],
      ),
    );
    final proposto = testo.text.trim();
    final motivazione = motivo.text.trim();
    testo.dispose();
    motivo.dispose();
    if (ok != true || proposto.isEmpty || !mounted) return;
    try {
      await apiDi(context).post('/api/v1/proposte', {
        'modello': modello['codice'],
        'versione': modello['versione'],
        'capoverso': c['id'],
        'testo_attuale': attuale,
        'testo_proposto': proposto,
        'motivazione': motivazione.isEmpty ? null : motivazione,
      });
      if (mounted) mostraMessaggio(context, 'Proposta inviata a chi gestisce i modelli');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  void _mostraAiuto(String titolo, Map<String, dynamic> dati) {
    final norme = List<String>.from(dati['norme'] as List? ?? []);
    showDialog<void>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(titolo),
        content: SizedBox(
          width: 560,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (dati['aiuto'] != null) Text(dati['aiuto'] as String),
            if (norme.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('Norme citate', style: Theme.of(context).textTheme.labelLarge),
              for (final n in norme) SelectableText(n, style: Theme.of(context).textTheme.bodySmall),
            ],
            if (dati['fonte'] != null) ...[
              const SizedBox(height: 12),
              Text('Fonte del testo: ${dati['fonte']}', style: Theme.of(context).textTheme.bodySmall),
            ],
          ]),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
      ),
    );
  }

  Future<void> _controlloRapido() async {
    setState(() {
      _controlloInCorso = true;
      _controlloLento = false;
    });
    _timerControllo?.cancel();
    _timerControllo = Timer(const Duration(seconds: 10), () {
      if (mounted && _controlloInCorso) setState(() => _controlloLento = true);
    });
    try {
      if (!await _salva()) return;
      if (!mounted) return;
      final r = await apiDi(context).get('$_percorso/controllo-rapido');
      if (!mounted) return;
      setState(() {
        _controllo = r as Map<String, dynamic>;
        _oraControllo = DateTime.now();
        _esitiAperti = true;
      });
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      _timerControllo?.cancel();
      if (mounted) setState(() => _controlloInCorso = false);
    }
  }

  bool get _verificaInCorso =>
      _verificaInAvvio || _verifica?['stato'] == 'IN_CODA' || _verifica?['stato'] == 'IN_CORSO';

  Future<void> _verificaCompleta() async {
    if (!await _controllaCompletezza('Verifica')) return;
    if (!mounted) return;
    setState(() {
      _verificaInAvvio = true;
      _esitiAperti = true;
    });
    try {
      final v = await apiDi(context).post('/api/v1/verifiche', {'bozza_id': widget.bozzaId});
      setState(() => _verifica = v as Map<String, dynamic>);
      _avviaPolling();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _verificaInAvvio = false);
    }
  }

  static Widget _rotellina() =>
      const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2));

  /// Risultato del controllo rapido, o il suo avanzamento mentre è in corso.
  Widget _esitoControlloRapido() {
    final tema = Theme.of(context);
    if (_controlloInCorso) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const LinearProgressIndicator(),
            const SizedBox(height: 8),
            const Text('Verifico i dati obbligatori e i riferimenti normativi su Normattiva…'),
            if (_controlloLento)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'Alcune norme vanno scaricate da Normattiva: può richiedere fino a un minuto '
                  'per norma.',
                  style: tema.textTheme.bodySmall,
                ),
              ),
          ]),
        ),
      );
    }
    if (_controllo == null) return const SizedBox.shrink();
    final blocchi = List<String>.from(_controllo!['blocchi'] as List? ?? []);
    final ora = _oraControllo;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (ora != null)
        Text(
          'Controllo rapido delle ${ora.hour.toString().padLeft(2, '0')}:'
          '${ora.minute.toString().padLeft(2, '0')}',
          style: tema.textTheme.labelMedium,
        ),
      for (final b in blocchi)
        Card(
          color: tema.colorScheme.errorContainer,
          child: ListTile(leading: const Icon(Icons.block), title: Text(b)),
        ),
      PannelloRiferimenti(esito: _controllo!),
    ]);
  }

  void _avviaPolling() {
    _polling?.cancel();
    _polling = Timer.periodic(const Duration(seconds: 3), (_) async {
      if (!mounted || _verifica == null) return;
      try {
        final v = await apiDi(context).get('/api/v1/verifiche/${_verifica!['id']}');
        if (!mounted) return;
        setState(() => _verifica = v as Map<String, dynamic>);
        if (v['stato'] == 'COMPLETATA' || v['stato'] == 'ERRORE') {
          _polling?.cancel();
          setState(() => _esitiAperti = true);
        }
      } catch (_) {
        // nuovo tentativo al prossimo giro
      }
    });
  }

  Future<void> _scarica(String formato, {bool omissis = false}) async {
    if (!await _controllaCompletezza('Scarica')) return;
    if (!mounted) return;
    try {
      await salvaFile(
        apiDi(context),
        '$_percorso/documento',
        'atto${omissis ? '-omissis' : ''}.${formato == 'odt' ? 'odt' : 'pdf'}',
        query: {'formato': formato, 'omissis': omissis.toString()},
      );
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  // --- domande iniziali -------------------------------------------------------------------

  Widget _passoDomande() {
    final domande = List<Map<String, dynamic>>.from(_stato['domande'] as List);
    final blocchi = List<String>.from(_stato['blocchi'] as List);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Text('Le risposte decidono quali capoversi entrano nell\'atto e quali dati ti '
          'verranno chiesti nelle fasi successive. Puoi tornare a modificarle.'),
      const SizedBox(height: 12),
      for (final b in blocchi)
        Card(
          color: Theme.of(context).colorScheme.errorContainer,
          child: ListTile(leading: const Icon(Icons.block), title: Text(b)),
        ),
      for (final q in domande) _domanda(q),
    ]);
  }

  Widget _domanda(Map<String, dynamic> q) {
    final id = q['id'] as String;
    final evidenzia = _mostraMancanti && q['mancante'] == true;
    final Widget risposta;
    switch (q['tipo']) {
      case 'si_no':
        final valore = _risposte[id];
        risposta = SegmentedButton<bool>(
          emptySelectionAllowed: true,
          segments: const [
            ButtonSegment(value: true, label: Text('Sì')),
            ButtonSegment(value: false, label: Text('No')),
          ],
          selected: valore is bool ? {valore} : const {},
          onSelectionChanged: (s) {
            setState(() => _risposte[id] = s.isEmpty ? null : s.first);
            _salva();
          },
        );
      case 'scelta':
        final opzioni = Map<String, dynamic>.from(q['opzioni'] as Map);
        risposta = Wrap(spacing: 8, runSpacing: 8, children: [
          for (final o in opzioni.entries)
            ChoiceChip(
              label: Text(o.value.toString()),
              selected: _risposte[id] == o.key,
              onSelected: (s) {
                setState(() => _risposte[id] = s ? o.key : null);
                _salva();
              },
            ),
        ]);
      case 'scelta_multipla':
        // caratteristiche dell'atto: ognuna attiva un modulo di regole
        final opzioni = Map<String, dynamic>.from(q['opzioni'] as Map? ?? {});
        final descrizioni = Map<String, dynamic>.from(q['descrizioni'] as Map? ?? {});
        final scelte = List<String>.from(_risposte[id] as List? ?? const []);
        risposta = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          for (final o in opzioni.entries)
            CheckboxListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: scelte.contains(o.key),
              title: Text(o.value.toString()),
              subtitle: descrizioni[o.key] == null ? null : Text(descrizioni[o.key].toString()),
              onChanged: (v) {
                setState(() => _risposte[id] = [
                      for (final k in opzioni.keys)
                        if (k == o.key ? v == true : scelte.contains(k)) k,
                    ]);
                _salva();
              },
            ),
        ]);
      default:
        final controller = _risposteTesto.putIfAbsent(
          id,
          () => TextEditingController(text: _risposte[id]?.toString() ?? ''),
        );
        risposta = SizedBox(
          width: 320,
          child: TextField(
            controller: controller,
            keyboardType: q['tipo'] == 'testo'
                ? TextInputType.text
                : const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              prefixText: q['tipo'] == 'importo' ? '€ ' : null,
              hintText: q['tipo'] == 'importo' ? 'es. 35.000,00' : null,
            ),
            onChanged: (v) {
              _risposte[id] = v.trim().isEmpty ? null : v.trim();
              _salvaPiuTardi();
            },
          ),
        );
    }
    return Card(
      shape: evidenzia
          ? RoundedRectangleBorder(
              side: BorderSide(color: Theme.of(context).colorScheme.error),
              borderRadius: BorderRadius.circular(12))
          : null,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(q['testo'] as String, style: Theme.of(context).textTheme.titleSmall)),
            if (q['aiuto'] != null)
              IconButton(
                tooltip: 'Spiegazione',
                icon: const Icon(Icons.info_outline, size: 20),
                onPressed: () => _mostraAiuto(q['testo'] as String, q),
              ),
          ]),
          const SizedBox(height: 8),
          risposta,
          if (q['suggerimento'] != null) _suggerimento(q),
        ]),
      ),
    );
  }

  /// Risposta consigliata da un modulo di regole, con la ragione e il tasto per applicarla.
  Widget _suggerimento(Map<String, dynamic> q) {
    final id = q['id'] as String;
    final s = Map<String, dynamic>.from(q['suggerimento'] as Map);
    final valore = s['valore'];
    final applicato = _risposte[id] == valore;
    final colori = Theme.of(context).colorScheme;
    final etichetta = valore is bool
        ? (valore ? 'Sì' : 'No')
        : (Map<String, dynamic>.from(q['opzioni'] as Map? ?? {})[valore] ?? valore).toString();
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: (applicato ? colori.secondaryContainer : colori.tertiaryContainer).withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(applicato ? Icons.check_circle_outline : Icons.lightbulb_outline, size: 20),
        const SizedBox(width: 8),
        Expanded(
          child: Text.rich(TextSpan(children: [
            TextSpan(
              text: 'Risposta consigliata: $etichetta. ',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            TextSpan(text: s['messaggio'].toString()),
          ])),
        ),
        if (!applicato)
          TextButton(
            onPressed: () {
              setState(() => _risposte[id] = valore);
              _salva();
            },
            child: const Text('Applica'),
          ),
      ]),
    );
  }

  // --- fasi: pannello di sinistra ------------------------------------------------------------

  /// Barra delle fasi: dove si è, cosa è completo, quanti dati mancano. Le fasi si aprono
  /// quando le domande iniziali hanno risposta; la fase da fare dopo è segnalata.
  Widget _barraFasi() {
    final voci = <(int, String)>[
      (0, 'Domande'),
      for (final f in _fasi) (f['numero'] as int, '${f['numero']} ${f['titolo']}'),
    ];
    final colori = Theme.of(context).colorScheme;
    return Wrap(spacing: 6, runSpacing: 6, children: [
      for (final (passo, etichetta) in voci)
        Builder(builder: (context) {
          final completa = _passoCompleto(passo);
          final mancanti = _numeroMancanti(passo);
          final abilitato = passo == 0 || _domandeComplete;
          final suggerita = passo == _passo + 1 && _passoCompleto(_passo) && !completa;
          return ChoiceChip(
            selected: passo == _passo,
            onSelected: abilitato ? (_) => _vaiA(passo) : null,
            showCheckmark: false,
            avatar: completa
                ? Icon(Icons.check_circle, color: Colors.green.shade600, size: 18)
                : suggerita
                    ? Icon(Icons.arrow_forward, color: colori.primary, size: 18)
                    : null,
            side: suggerita ? BorderSide(color: colori.primary, width: 1.5) : null,
            label: Text.rich(TextSpan(children: [
              TextSpan(text: etichetta),
              if (!completa && mancanti > 0 && abilitato)
                TextSpan(
                  text: ' · $mancanti',
                  style: TextStyle(color: colori.error, fontWeight: FontWeight.bold),
                ),
            ])),
            tooltip: !abilitato
                ? 'Rispondi prima alle domande iniziali'
                : completa
                    ? 'Completa'
                    : mancanti > 0
                        ? '$mancanti dati da completare'
                        : null,
          );
        }),
    ]);
  }

  /// Dati della fase, raggruppati per sezione dell'atto, con i capoversi facoltativi.
  Widget _pannelloFase(Map<String, dynamic> fase, Set<String> giaChiesti) {
    final tema = Theme.of(context);
    final campiFase = {
      for (final c in List<Map<String, dynamic>>.from(fase['campi'] as List)) c['nome'] as String: c,
    };
    final chiestiPrima = {...giaChiesti};
    final blocchi = <Widget>[
      if (fase['descrizione'] != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text(fase['descrizione'] as String, style: tema.textTheme.bodySmall),
        ),
    ];
    for (final sezione in List<Map<String, dynamic>>.from(fase['sezioni'] as List)) {
      final capoversi = List<Map<String, dynamic>>.from(sezione['capoversi'] as List);
      // dati usati dai capoversi della sezione: chiesti la prima volta, poi ricordati
      final nomi = <String>{
        for (final c in capoversi)
          if (c['escluso'] != true)
            for (final n in List<String>.from(c['campi'] as List? ?? []))
              if (campiFase.containsKey(n)) n,
      }.toList();
      final nuovi = [for (final n in nomi) if (!giaChiesti.contains(n)) n];
      final ripetuti = [for (final n in nomi) if (giaChiesti.contains(n)) n];
      // dato ricordato nella sezione: compilato in questa fase o in una precedente
      String dove(String n) => chiestiPrima.contains(n) ? 'in una fase precedente' : 'sopra';
      giaChiesti.addAll(nomi);
      final facoltativi = [for (final c in capoversi) if (c['facoltativo'] == true) c];
      final libreria = sezione['riferimenti_libreria'] == true;
      if (nuovi.isEmpty && ripetuti.isEmpty && facoltativi.isEmpty && !libreria) continue;
      blocchi.add(Padding(
        padding: const EdgeInsets.only(top: 16, bottom: 8),
        child: Row(children: [
          Expanded(child: Text(sezione['titolo'] as String, style: tema.textTheme.titleSmall)),
          if (sezione['aiuto'] != null)
            IconButton(
              tooltip: 'Spiegazione',
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.info_outline, size: 18),
              onPressed: () => _mostraAiuto(sezione['titolo'] as String, sezione),
            ),
        ]),
      ));
      for (final c in facoltativi) {
        blocchi.add(_interruttoreFacoltativo(c));
      }
      for (final n in nuovi) {
        blocchi.add(Padding(padding: const EdgeInsets.only(bottom: 12), child: _campoWidget(campiFase[n]!)));
      }
      for (final n in ripetuti) {
        blocchi.add(_promemoria(campiFase[n]!, dove(n)));
      }
      if (libreria) blocchi.add(_riferimentiLibreria());
    }
    // dati della fase non legati a una sezione (non dovrebbe succedere, per sicurezza)
    for (final n in campiFase.keys) {
      if (!giaChiesti.contains(n)) {
        giaChiesti.add(n);
        blocchi.add(Padding(padding: const EdgeInsets.only(bottom: 12), child: _campoWidget(campiFase[n]!)));
      }
    }
    if (blocchi.length <= 1) {
      blocchi.add(const Padding(
        padding: EdgeInsets.only(top: 16),
        child: Text('In questa fase non ci sono dati da compilare: il testo è standard.'),
      ));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: blocchi);
  }

  /// Capoverso facoltativo: si include o si toglie dall'atto.
  Widget _interruttoreFacoltativo(Map<String, dynamic> c) {
    final incluso = c['escluso'] != true;
    final testo = (c['testo'] as String).replaceAll('\n', ' ');
    return SwitchListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      value: incluso,
      onChanged: (v) => _includi(c, v),
      title: Text(incluso ? 'Incluso nell\'atto' : 'Non incluso nell\'atto'),
      subtitle: Text(testo.length > 140 ? '${testo.substring(0, 140)}…' : testo,
          maxLines: 3, overflow: TextOverflow.ellipsis),
      secondary: c['aiuto'] == null
          ? null
          : IconButton(
              tooltip: 'Spiegazione',
              icon: const Icon(Icons.info_outline, size: 18),
              onPressed: () => _mostraAiuto('Capoverso facoltativo', c),
            ),
    );
  }

  Widget _riferimentiLibreria() {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final r in _riferimenti)
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.balance, size: 18),
          title: Text("l'${r['citazione'] ?? r['urn_atto']};"),
          trailing: IconButton(
            tooltip: 'Togli',
            icon: const Icon(Icons.close, size: 18),
            onPressed: () {
              _riferimenti.remove(r);
              _salva();
            },
          ),
        ),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(
          onPressed: _aggiungiRiferimenti,
          icon: const Icon(Icons.add),
          label: const Text('Aggiungi riferimenti dalla libreria normativa'),
        ),
      ),
    ]);
  }

  /// Dato già chiesto in una sezione precedente: si ricorda il valore e si torna al campo.
  Widget _promemoria(Map<String, dynamic> c, String dove) {
    final nome = c['nome'] as String;
    final valore = c['tipo'] == 'elenco' ? '${_elenchi[nome]?.length ?? 0} righe' : _campo(nome).text;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: () => _focusCampo(nome).requestFocus(),
        child: Text(
          '${c['etichetta']}: ${valore.isEmpty ? 'da compilare' : valore} (compilato $dove)',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Theme.of(context).hintColor),
        ),
      ),
    );
  }

  static final _nonCompilato = RegExp(r'\[\[[^\]]+\]\]');

  /// Testo con i dati non ancora compilati evidenziati.
  TextSpan _testoEvidenziato(String testo, TextStyle base) {
    final parti = <TextSpan>[];
    var da = 0;
    for (final m in _nonCompilato.allMatches(testo)) {
      if (m.start > da) parti.add(TextSpan(text: testo.substring(da, m.start)));
      parti.add(TextSpan(
        text: m.group(0),
        style: TextStyle(
          color: Theme.of(context).colorScheme.error,
          backgroundColor: Theme.of(context).colorScheme.errorContainer.withValues(alpha: 0.4),
        ),
      ));
      da = m.end;
    }
    if (da < testo.length) parti.add(TextSpan(text: testo.substring(da)));
    return TextSpan(children: parti, style: base);
  }

  static final _nomeDato = RegExp(r'\{\{\s*([A-Za-z_]\w*)');

  /// Testo di un capoverso non modificabile: i dati si evidenziano come negli altri capoversi
  /// e un clic porta alla loro casella.
  TextSpan _testoConDati(List<Map<String, dynamic>> segmenti, TextStyle base) {
    final colori = Theme.of(context).colorScheme;
    return TextSpan(style: base, children: [
      for (final s in segmenti)
        if (s['segnaposto'] == null)
          TextSpan(text: s['testo'] as String)
        else
          () {
            final testo = s['testo'] as String;
            final nome = _nomeDato.firstMatch(s['segnaposto'] as String)?.group(1);
            final mancante = _nonCompilato.hasMatch(testo);
            return TextSpan(
              text: testo,
              style: mancante
                  ? TextStyle(
                      color: colori.error,
                      backgroundColor: colori.errorContainer.withValues(alpha: 0.4),
                    )
                  : nome == _campoAttivo
                      ? const TextStyle(
                          backgroundColor: Color(0xFFFFD54F),
                          color: Colors.black,
                          fontWeight: FontWeight.bold,
                        )
                      : TextStyle(backgroundColor: colori.secondaryContainer.withValues(alpha: 0.45)),
              mouseCursor: nome == null ? null : SystemMouseCursors.click,
              recognizer: nome == null
                  ? null
                  : _tocchiDati.putIfAbsent(nome, () => TapGestureRecognizer()..onTap = () => _vaiAlCampo(nome)),
            );
          }(),
    ]);
  }

  // --- campi ------------------------------------------------------------------------------

  String? _erroreCampo(Map<String, dynamic> c) {
    if (c['errore'] != null) return c['errore'] as String;
    if (_mostraMancanti && c['mancante'] == true) return 'Dato obbligatorio';
    return null;
  }

  /// Casella di un dato: a ogni tasto si ridisegna solo lei (✕ e provenienza), non la pagina.
  Widget _campoWidget(Map<String, dynamic> c) {
    final nome = c['nome'] as String;
    return KeyedSubtree(
      key: _chiaviCampi.putIfAbsent(nome, GlobalKey.new),
      child: c['tipo'] == 'elenco'
          ? _elencoWidget(c)
          : ValueListenableBuilder<TextEditingValue>(
              valueListenable: _campo(nome),
              builder: (context, _, _) => _casella(c),
            ),
    );
  }

  Widget _casella(Map<String, dynamic> c) {
    final nome = c['nome'] as String;
    final etichetta = '${c['etichetta']}${c['obbligatorio'] == true ? ' *' : ''}';
    final proposto = c['proposto'];
    final controller = _campo(nome);
    final vuotoProposto = proposto == null || proposto.toString().isEmpty;
    final provenienza = !vuotoProposto && controller.text == proposto.toString()
        ? switch (c['origine']) {
            'ente' => 'Dai Dati dell\'ente',
            'profilo' => 'Dal tuo profilo',
            'modello' => 'Proposto dal modello',
            _ => null,
          }
        : null;
    final avviso = vuotoProposto && controller.text.isEmpty
        ? switch (c['origine']) {
            'ente' => 'Dato dell\'ente non impostato: va inserito in Amministrazione → '
                'Modelli e dati dell\'ente.',
            'profilo' => 'Non indicato nel tuo profilo: puoi impostarlo in "Il mio profilo".',
            _ => null,
          }
        : null;
    final aiuto = [
      ?provenienza,
      ?avviso,
      if (c['aiuto'] != null) c['aiuto'],
    ].join('\n');
    switch (c['tipo']) {
      case 'data':
        return InputDecorator(
          decoration: InputDecoration(
            labelText: etichetta,
            helperText: aiuto.isEmpty ? null : aiuto,
            helperMaxLines: 4,
            errorText: _erroreCampo(c),
          ),
          child: Row(children: [
            Expanded(child: Text(controller.text.isEmpty ? '—' : formatData(controller.text))),
            if (controller.text.isNotEmpty)
              IconButton(
                tooltip: 'Svuota',
                icon: const Icon(Icons.close, size: 18),
                onPressed: () => _svuota(nome),
              ),
            TextButton(
              onPressed: () async {
                final d = await scegliData(context, daIso(controller.text));
                if (d != null) {
                  controller.text = isoData(d);
                  _salvaPiuTardi();
                }
              },
              child: const Text('Scegli'),
            ),
          ]),
        );
      default:
        final lungo = c['tipo'] == 'testo_lungo';
        final numerico = c['tipo'] == 'importo' || c['tipo'] == 'numero';
        return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: TextField(
              controller: controller,
              focusNode: _focusCampo(nome),
              onChanged: (v) {
                v.isEmpty ? _svuotati.add(nome) : _svuotati.remove(nome);
                _salvaPiuTardi();
              },
              minLines: lungo ? 3 : 1,
              maxLines: lungo ? 10 : 1,
              textCapitalization: ['cig', 'cup', 'codice_fiscale_piva'].contains(c['tipo'])
                  ? TextCapitalization.characters
                  : TextCapitalization.none,
              keyboardType: numerico ? const TextInputType.numberWithOptions(decimal: true) : null,
              decoration: InputDecoration(
                labelText: etichetta,
                helperText: aiuto.isEmpty ? null : aiuto,
                suffixIcon: controller.text.isEmpty
                    ? null
                    : IconButton(
                        tooltip: 'Svuota',
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () => _svuota(nome),
                      ),
                helperMaxLines: 4,
                prefixText: c['tipo'] == 'importo' ? '€ ' : null,
                errorText: _erroreCampo(c),
                alignLabelWithHint: true,
              ),
            ),
          ),
          if (lungo)
            IconButton(
              tooltip: 'Riscrivi dagli appunti (IA)',
              icon: const Icon(Icons.auto_fix_high),
              onPressed: () => _espandi(c),
            ),
        ]);
    }
  }

  void _svuota(String nome) {
    _campo(nome).clear();
    _svuotati.add(nome);
    _salvaPiuTardi();
  }

  /// Focus di un campo: mentre ci si scrive, il dato è evidenziato nel testo dell'atto.
  FocusNode _focusCampo(String nome) => _focusCampi.putIfAbsent(nome, () {
        final nodo = FocusNode();
        nodo.addListener(() {
          if (!mounted) return;
          if (nodo.hasFocus) {
            _campoAttivo = nome;
            _scorriAlDato(nome);
          } else if (_campoAttivo == nome) {
            _campoAttivo = null;
          }
          _ridisegnaAtto(); // cambia solo l'evidenziazione nell'atto
        });
        return nodo;
      });

  Widget _elencoWidget(Map<String, dynamic> c) {
    final nome = c['nome'] as String;
    final sottocampi = Map<String, dynamic>.from(c['sottocampi'] as Map? ?? {});
    final righe = _elenchi.putIfAbsent(nome, () => []);
    if (righe.isEmpty && (c['minimo'] ?? 0) as int > 0) {
      righe.add({for (final s in sottocampi.keys) s: TextEditingController()});
    }
    final errore = _erroreCampo(c);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('${c['etichetta']}${c['obbligatorio'] == true ? ' *' : ''}',
          style: Theme.of(context).textTheme.labelLarge),
      if (c['aiuto'] != null) Text(c['aiuto'] as String, style: Theme.of(context).textTheme.bodySmall),
      for (var i = 0; i < righe.length; i++)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Column(children: [
              Row(children: [
                Expanded(child: Text('Riga ${i + 1}', style: Theme.of(context).textTheme.labelMedium)),
                IconButton(
                  tooltip: 'Togli la riga',
                  icon: const Icon(Icons.delete_outline, size: 20),
                  onPressed: () => setState(() {
                    for (final ctrl in righe.removeAt(i).values) {
                      ctrl.dispose();
                    }
                    _modificata = true;
                  }),
                ),
              ]),
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final s in sottocampi.entries)
                  SizedBox(
                    width: 200,
                    child: TextField(
                      controller: righe[i].putIfAbsent(s.key, TextEditingController.new),
                      onChanged: (_) => _salvaPiuTardi(),
                      keyboardType: (s.value as Map)['tipo'] == 'importo'
                          ? const TextInputType.numberWithOptions(decimal: true)
                          : null,
                      decoration: InputDecoration(
                        labelText: '${(s.value as Map)['etichetta']}'
                            '${(s.value as Map)['obbligatorio'] == true ? ' *' : ''}',
                        isDense: true,
                      ),
                    ),
                  ),
              ]),
            ]),
          ),
        ),
      if (errore != null)
        Text(errore, style: TextStyle(color: Theme.of(context).colorScheme.error)),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(
          onPressed: () => setState(() {
            righe.add({for (final s in sottocampi.keys) s: TextEditingController()});
            _modificata = true;
          }),
          icon: const Icon(Icons.add),
          label: const Text('Aggiungi riga'),
        ),
      ),
    ]);
  }

  // --- atto: pannello di destra --------------------------------------------------------------

  Widget _barraAzioni() {
    final tema = Theme.of(context);
    return Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
      FilledButton.tonalIcon(
        onPressed: _controlloInCorso ? null : _controlloRapido,
        icon: _controlloInCorso ? _rotellina() : const Icon(Icons.rule),
        label: Text(_controlloInCorso ? 'Controllo in corso…' : 'Controllo rapido'),
      ),
      FilledButton.icon(
        onPressed: _verificaInCorso ? null : _verificaCompleta,
        icon: _verificaInCorso ? _rotellina() : const Icon(Icons.fact_check),
        label: Text(_verificaInCorso ? 'Verifica in corso…' : 'Verifica con checklist'),
      ),
      PopupMenuButton<(String, bool)>(
        tooltip: 'Scarica il documento',
        onSelected: (scelta) => _scarica(scelta.$1, omissis: scelta.$2),
        itemBuilder: (_) => const [
          PopupMenuItem(value: ('odt', false), child: Text('ODT')),
          PopupMenuItem(value: ('pdf', false), child: Text('PDF')),
          PopupMenuItem(value: ('pdfa', false), child: Text('PDF/A')),
          PopupMenuItem(value: ('pdfa', true), child: Text('PDF/A con omissis')),
        ],
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: BoxDecoration(
            border: Border.all(color: tema.colorScheme.outline),
            borderRadius: BorderRadius.circular(20),
          ),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.download, size: 18),
            SizedBox(width: 8),
            Text('Scarica'),
            Icon(Icons.arrow_drop_down, size: 18),
          ]),
        ),
      ),
      ValueListenableBuilder<String>(
        valueListenable: _statoSalvataggio,
        builder: (context, stato, _) => Text(stato, style: tema.textTheme.bodySmall),
      ),
    ]);
  }

  /// Riquadro richiudibile con gli esiti del controllo rapido e della verifica.
  Widget _riquadroEsiti() {
    if (!_controlloInCorso && _controllo == null && _verifica == null) return const SizedBox.shrink();
    final tema = Theme.of(context);
    final esitiChecklist = _verifica?['stato'] == 'COMPLETATA'
        ? List<Map<String, dynamic>>.from(_verifica!['esito_automatico'] as List? ?? [])
        : <Map<String, dynamic>>[];
    final contenuto = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (_verifica != null) StatoVerificaBanner(verifica: _verifica!),
      if (_controlloInCorso)
        _esitoControlloRapido()
      else if (_verifica?['stato'] == 'COMPLETATA') ...[
        PannelloRiferimenti(esito: Map<String, dynamic>.from(_verifica!['esito_riferimenti'] as Map)),
        PannelloChecklist(esiti: esitiChecklist, modello: _verifica!['modello_llm'] as String?),
      ] else
        _esitoControlloRapido(),
    ]);
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        InkWell(
          onTap: () => setState(() => _esitiAperti = !_esitiAperti),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(children: [
              Icon(_esitiAperti ? Icons.expand_less : Icons.expand_more),
              const SizedBox(width: 8),
              Expanded(child: Text('Esiti dei controlli', style: tema.textTheme.titleSmall)),
              if (_controlloInCorso || _verificaInCorso) _rotellina(),
            ]),
          ),
        ),
        if (_esitiAperti)
          ConstrainedBox(
            constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.4),
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: contenuto,
            ),
          ),
      ]),
    );
  }

  /// L'atto impaginato come il documento: intestazione e organo al centro, oggetto in
  /// grassetto, elenchi delle premesse, DETERMINA e punti numerati, luogo, data e firma a
  /// destra. Le sezioni della fase che si sta compilando sono segnate a margine.
  Widget _documento() {
    final tema = Theme.of(context);
    final base = (tema.textTheme.bodyMedium ?? const TextStyle()).copyWith(height: 1.5);
    final grassetto = base.copyWith(fontWeight: FontWeight.bold);
    final fasi = <Widget>[];
    for (final f in _fasi) {
      final numero = f['numero'] as int;
      final allineamento = switch (numero) {
        1 => TextAlign.center,
        4 => TextAlign.right,
        _ => TextAlign.justify,
      };
      final righe = <Widget>[];
      if (f['formula'] != null) {
        righe.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(f['formula'] as String,
              textAlign: TextAlign.center, style: grassetto.copyWith(letterSpacing: 2)),
        ));
      }
      if (f['premessa'] != null) {
        righe.add(Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text(f['premessa'] as String, style: base, textAlign: TextAlign.justify),
        ));
      }
      var progressivo = 0;
      for (final sezione in List<Map<String, dynamic>>.from(f['sezioni'] as List)) {
        final capoversi = [
          for (final c in List<Map<String, dynamic>>.from(sezione['capoversi'] as List))
            if (c['escluso'] != true) c,
        ];
        final riferimenti = sezione['riferimenti_libreria'] == true ? _riferimenti : const [];
        if (capoversi.isEmpty && riferimenti.isEmpty) continue;
        if (sezione['oggetto'] == true) {
          righe.add(Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Oggetto: ', style: grassetto),
              Expanded(
                child: Column(children: [
                  for (final c in capoversi) _testoCapoverso(c, grassetto, TextAlign.justify),
                ]),
              ),
            ]),
          ));
          continue;
        }
        if (sezione['formula'] != null) {
          righe.add(Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('${sezione['formula']}:', style: grassetto),
          ));
        }
        for (final c in capoversi) {
          final prefisso = f['numerazione'] == 'automatica'
              ? '${++progressivo}) '
              : sezione['formula'] != null
                  ? '– '
                  : null;
          final stile = numero == 1 ? grassetto : base;
          righe.add(Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: prefisso == null
                ? _testoCapoverso(c, stile, allineamento)
                : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    SizedBox(width: 28, child: Text(prefisso, style: stile)),
                    Expanded(child: _testoCapoverso(c, stile, allineamento)),
                  ]),
          ));
        }
        for (final r in riferimenti) {
          righe.add(Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: 28, child: Text('– ', style: base)),
              Expanded(child: Text("l'${r['citazione'] ?? r['urn_atto']};", style: base)),
            ]),
          ));
        }
      }
      final corrente = numero == _passo;
      fasi.add(Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.only(left: 12),
        decoration: BoxDecoration(
          border: Border(
            left: BorderSide(
              width: 6,
              color: corrente ? tema.colorScheme.primary.withValues(alpha: 0.5) : Colors.transparent,
            ),
          ),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: righe),
      ));
    }
    return Card(
      color: tema.colorScheme.surface,
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(28, 32, 40, 32),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: fasi),
      ),
    );
  }

  /// Testo di un capoverso nell'atto: modificabile sul posto se il modello lo consente.
  /// Se il cursore è su un dato, sotto compare il collegamento alla sua casella.
  Widget _testoCapoverso(Map<String, dynamic> c, TextStyle stile, TextAlign allineamento) {
    final id = c['id'] as String;
    final chiave = _chiaviCapoversi.putIfAbsent(id, GlobalKey.new);
    final modificabile = c['modificabile'] == true && c['segmenti'] != null;
    Widget testo;
    if (modificabile) {
      final focus = _focusCapoversi.putIfAbsent(id, () {
        final nodo = FocusNode();
        nodo.addListener(() {
          if (!nodo.hasFocus) _confermaCapoverso(id);
          if (mounted) _ridisegnaAtto();
        });
        return nodo;
      });
      final controller = _capoversi[id]!..campoAttivo = _campoAttivo;
      testo = Listener(
        // clic o selezione su un dato: il cursore passa alla sua casella. Si aspetta che il
        // campo di testo abbia finito di gestire il clic (che gli dà il focus)
        onPointerUp: (_) => Future.delayed(const Duration(milliseconds: 80), () {
          final nome = controller.datoSelezionato();
          if (mounted && nome != null) _vaiAlCampo(nome);
        }),
        child: TextField(
          controller: controller,
          focusNode: focus,
          maxLines: null,
          style: stile,
          textAlign: allineamento,
          decoration: const InputDecoration(
            isDense: true,
            border: InputBorder.none,
            contentPadding: EdgeInsets.zero,
          ),
        ),
      );
    } else {
      testo = SelectableText.rich(
        c['segmenti'] == null
            ? _testoEvidenziato(c['testo'] as String, stile)
            : _testoConDati(List<Map<String, dynamic>>.from(c['segmenti'] as List), stile),
        textAlign: allineamento,
      );
    }
    if (c['personalizzato'] == true) {
      // capoverso riscritto: segnato a margine, con il ritorno al testo standard
      testo = Container(
        padding: const EdgeInsets.only(left: 6),
        decoration: BoxDecoration(
          border: Border(left: BorderSide(width: 2, color: Theme.of(context).colorScheme.tertiary)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          testo,
          Wrap(spacing: 12, children: [
            Text('Testo riscritto', style: Theme.of(context).textTheme.bodySmall),
            for (final (etichetta, azione) in [
              ('Ripristina testo standard', () => _ripristinaCapoverso(id)),
              ('Proponi come testo del modello', () => _proponiAlModello(c)),
            ])
              InkWell(
                onTap: azione,
                child: Text(etichetta,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.primary,
                        decoration: TextDecoration.underline)),
              ),
          ]),
        ]),
      );
    }
    // capoverso in lavorazione: contiene il dato della casella attiva o lo si sta scrivendo
    final colori = Theme.of(context).colorScheme;
    final inLavorazione = (_focusCapoversi[id]?.hasFocus ?? false) ||
        (_campoAttivo != null && (c['campi'] as List? ?? []).contains(_campoAttivo));
    return KeyedSubtree(
      key: chiave,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: inLavorazione ? colori.primaryContainer.withValues(alpha: 0.35) : null,
          borderRadius: BorderRadius.circular(4),
          border: Border(
            left: BorderSide(width: 4, color: inLavorazione ? colori.primary : Colors.transparent),
          ),
        ),
        child: testo,
      ),
    );
  }

  Widget _pannelloAtto() {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _barraAzioni(),
          _riquadroEsiti(),
        ]),
      ),
      Expanded(
        child: SingleChildScrollView(
          controller: _scrollAtto,
          padding: const EdgeInsets.all(16),
          child: _cacheDocumento ??= _documento(),
        ),
      ),
    ]);
  }

  /// Colonna di sinistra: domande e fasi una sotto l'altra; la barra in alto scorre alla fase.
  Widget _pannelloCompilazione() {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 8), child: _barraFasi()),
      const Divider(height: 1),
      Expanded(
        child: SingleChildScrollView(
          controller: _scrollSinistra,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 160),
          child: _cacheCompilazione ??= _colonnaCompilazione(),
        ),
      ),
    ]);
  }

  Widget _colonnaCompilazione() {
    final giaChiesti = <String>{}; // ogni dato si chiede una volta sola, nella prima fase
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _intestazionePasso(0, 'Domande iniziali'),
      _passoDomande(),
      for (final f in _fasi) ...[
        _intestazionePasso(f['numero'] as int, 'Fase ${f['numero']} · ${f['titolo']}'),
        if (_domandeComplete)
          _pannelloFase(f, giaChiesti)
        else
          Text('Rispondi prima alle domande iniziali.',
              style: TextStyle(color: Theme.of(context).hintColor)),
      ],
    ]);
  }

  Widget _intestazionePasso(int passo, String titolo) {
    final tema = Theme.of(context);
    return Padding(
      key: _chiaviPassi.putIfAbsent(passo, GlobalKey.new),
      padding: EdgeInsets.only(top: passo == 0 ? 16 : 32, bottom: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(titolo, style: tema.textTheme.titleMedium?.copyWith(color: tema.colorScheme.primary)),
        const SizedBox(height: 4),
        Divider(height: 1, color: tema.colorScheme.primary.withValues(alpha: 0.4)),
      ]),
    );
  }

  /// Divisione tra i due pannelli: si trascina per cambiarne la larghezza, con un doppio clic
  /// torna alla posizione iniziale.
  Widget _divisione(double larghezzaTotale) {
    final colori = Theme.of(context).colorScheme;
    return MouseRegion(
      cursor: SystemMouseCursors.resizeColumn,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onHorizontalDragUpdate: (d) => super.setState(() {
          _rapporto = (_rapporto + d.delta.dx / larghezzaTotale).clamp(0.2, 0.75);
        }),
        onDoubleTap: () => super.setState(() => _rapporto = _rapportoPredefinito),
        child: Tooltip(
          message: 'Trascina per allargare o restringere i pannelli (doppio clic: posizione iniziale)',
          waitDuration: const Duration(seconds: 1),
          child: SizedBox(
            width: 9,
            child: Stack(alignment: Alignment.center, children: [
              const VerticalDivider(width: 1),
              Container(
                width: 5,
                height: 48,
                decoration: BoxDecoration(
                  color: colori.outline,
                  borderRadius: BorderRadius.circular(3),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }

  // --- pagina --------------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (_erroreCaricamento != null) {
      return Scaffold(appBar: AppBar(), body: Center(child: Text(_erroreCaricamento.toString())));
    }
    if (_bozza == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final modello = Map<String, dynamic>.from(_bozza!['modello'] as Map);
    final largo = MediaQuery.sizeOf(context).width >= 1000;
    final corpo = largo
        ? LayoutBuilder(builder: (context, vincoli) {
            final larghezza = vincoli.maxWidth * _rapporto;
            return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              SizedBox(width: larghezza, child: _pannelloCompilazione()),
              _divisione(vincoli.maxWidth),
              Expanded(child: _pannelloAtto()),
            ]);
          })
        : DefaultTabController(
            length: 2,
            child: Column(children: [
              const TabBar(tabs: [Tab(text: 'Compila'), Tab(text: 'Atto')]),
              Expanded(
                child: TabBarView(children: [_pannelloCompilazione(), _pannelloAtto()]),
              ),
            ]),
          );
    return PopScope(
      canPop: !_modificata,
      onPopInvokedWithResult: (fatto, _) async {
        if (fatto) return;
        await _salva();
        if (context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(modello['provvedimento'] as String),
            Text(modello['titolo'] as String, style: Theme.of(context).textTheme.bodySmall),
          ]),
        ),
        body: corpo,
      ),
    );
  }
}

/// Testo di un capoverso nell'app: i dati compilati hanno uno sfondo leggero, quelli del
/// campo su cui si sta scrivendo uno più marcato, quelli mancanti ([[campo]]) sono in rosso.
class _ControllerCapoverso extends TextEditingController {
  _ControllerCapoverso({required this.suModificaRifiutata});

  static final _nonCompilato = RegExp(r'\[\[[^\]]+\]\]');
  static final _nomeCampo = RegExp(r'\{\{\s*([A-Za-z_]\w*)');

  /// Una modifica toccava un dato ed è stata annullata.
  final VoidCallback suModificaRifiutata;

  // posizioni dei dati nel testo, aggiornate mentre si scrive: (inizio, fine, campo, segnaposto)
  List<(int, int, String?, String)> _dati = const [];
  bool _impostando = false;
  String? campoAttivo;

  /// Testo composto dal server, diviso in segmenti di testo fisso e dati.
  void imposta(String testo, List? segmenti) {
    final dati = <(int, int, String?, String)>[];
    var pos = 0;
    for (final s in segmenti ?? const []) {
      final parte = (s as Map)['testo'] as String;
      final segnaposto = s['segnaposto'] as String?;
      if (segnaposto != null && parte.isNotEmpty) {
        dati.add((pos, pos + parte.length, _nomeCampo.firstMatch(segnaposto)?.group(1), segnaposto));
      }
      pos += parte.length;
    }
    _dati = dati;
    _impostando = true;
    try {
      text = testo;
    } finally {
      _impostando = false;
    }
  }

  /// Testo da salvare: i dati tornano segnaposto ({{campo}}) e seguono le caselle; il resto
  /// è il testo fisso, come l'ha scritto l'utente.
  String ricomponi() {
    final risultato = StringBuffer();
    var da = 0;
    for (final (inizio, fine, _, segnaposto) in _dati) {
      if (inizio < da || fine > text.length) continue;
      risultato
        ..write(text.substring(da, inizio))
        ..write(segnaposto);
      da = fine;
    }
    risultato.write(text.substring(da));
    return risultato.toString();
  }

  @override
  set value(TextEditingValue nuovo) {
    final vecchio = value;
    if (_impostando || nuovo.text == vecchio.text) {
      super.value = nuovo;
      return;
    }
    // parte cambiata: quello che resta tolti l'inizio e la fine in comune
    final a = vecchio.text, b = nuovo.text;
    var inizio = 0;
    while (inizio < a.length && inizio < b.length && a[inizio] == b[inizio]) {
      inizio++;
    }
    var fine = 0;
    while (fine < a.length - inizio && fine < b.length - inizio &&
        a[a.length - 1 - fine] == b[b.length - 1 - fine]) {
      fine++;
    }
    final fineVecchio = a.length - fine;
    final tocca = _dati.any((d) => inizio == fineVecchio
        ? inizio > d.$1 && inizio < d.$2 // inserimento dentro un dato
        : inizio < d.$2 && fineVecchio > d.$1); // cancellazione o sostituzione su un dato
    if (tocca) {
      notifyListeners(); // il campo di testo torna al valore di prima
      suModificaRifiutata();
      return;
    }
    final scarto = b.length - a.length;
    _dati = [
      for (final d in _dati)
        d.$1 >= fineVecchio ? (d.$1 + scarto, d.$2 + scarto, d.$3, d.$4) : d,
    ];
    super.value = nuovo;
  }

  /// Dato in cui si trova il cursore o che la selezione tocca (null se testo fisso).
  String? datoSelezionato() {
    if (!selection.isValid) return null;
    final (da, a) = (selection.start, selection.end);
    for (final (inizio, fine, nome, _) in _dati) {
      if (da == a ? da > inizio && da < fine : da < fine && a > inizio) return nome;
    }
    return null;
  }

  @override
  TextSpan buildTextSpan({required BuildContext context, TextStyle? style, required bool withComposing}) {
    final colori = Theme.of(context).colorScheme;
    // intervalli da evidenziare: dati e dati mancanti
    final intervalli = <(int, int, TextStyle)>[];
    for (final (inizio, fine, nome, _) in _dati) {
      if (fine > text.length || _nonCompilato.hasMatch(text.substring(inizio, fine))) continue;
      intervalli.add((
        inizio,
        fine,
        nome == campoAttivo
            ? const TextStyle(
                backgroundColor: Color(0xFFFFD54F), // evidenziatore
                color: Colors.black,
                fontWeight: FontWeight.bold,
              )
            : TextStyle(backgroundColor: colori.secondaryContainer.withValues(alpha: 0.45)),
      ));
    }
    for (final m in _nonCompilato.allMatches(text)) {
      intervalli.add((m.start, m.end, TextStyle(color: colori.error)));
    }
    intervalli.sort((a, b) => a.$1.compareTo(b.$1));
    final parti = <TextSpan>[];
    var da = 0;
    for (final (inizio, fine, stile) in intervalli) {
      if (inizio < da || fine > text.length) continue;
      if (inizio > da) parti.add(TextSpan(text: text.substring(da, inizio)));
      parti.add(TextSpan(text: text.substring(inizio, fine), style: stile));
      da = fine;
    }
    if (da < text.length) parti.add(TextSpan(text: text.substring(da)));
    return TextSpan(style: style, children: parti);
  }
}
