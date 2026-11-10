import 'package:flutter/material.dart';
import '../../comuni.dart' show apiDi, mostraErrore, mostraMessaggio;
import '../utils/data_formatter.dart';
import '../widgets/importa_procedimenti.dart';
import '../widgets/modulo.dart';
import '../widgets/selettore_schema.dart' show maiuscola;
import './form_helpers.dart';

typedef Json = Map<String, dynamic>;

/// Dati raccolti dal form, oppure il motivo per cui non si può procedere.
typedef DatiModulo = ({Json? dati, String? errore});

/// Form costruito a partire dalla definizione di uno schema ANAC servita dal
/// API (GET /api/v1/trasparenza/schemi, file common/trasparenza/schemi/*.yaml). Parametri, sezioni,
/// campi, gruppi, condizioni di visibilità, elenchi annidati e opzioni
/// vincolate vengono tutti dallo schema: per modificare il form si modifica
/// il file YAML, non questo codice.
///
/// Il form è diviso in passi numerati a partire da [primoNumero] (i passi
/// precedenti appartengono alla scheda che lo ospita): applicabilità,
/// caratteristiche e sezione, dati da pubblicare, note.
class SchemaForm extends StatefulWidget {
  final Json schema;
  final int primoNumero;
  // Dati di una scheda già generata con cui precompilare il form (stesso
  // formato restituito da [SchemaFormState.raccogli]).
  final Json? datiIniziali;

  const SchemaForm({
    super.key,
    required this.schema,
    this.primoNumero = 2,
    this.datiIniziali,
  });

  @override
  State<SchemaForm> createState() => SchemaFormState();
}

class SchemaFormState extends State<SchemaForm> {
  final _formKey = GlobalKey<FormState>();
  final _chiaveScelte = GlobalKey();
  final _chiaveDati = GlobalKey();
  // Dopo il primo tentativo non riuscito i campi si riconvalidano mentre
  // l'utente li corregge.
  bool _autovalida = false;
  // Fa ricostruire i menu a tendina: serve a riportarli al valore precedente
  // quando l'utente annulla una modifica, e a svuotarli dopo un reset.
  int _revisione = 0;

  String _ambitoSoggettivo = 'TENUTO';
  final Map<String, String?> _parametri = {};
  bool _usaAlternativo = false;
  final _alternativoController = TextEditingController();
  final _noteController = TextEditingController();
  String? _sezioneId;
  List<RigaDati> _righe = [RigaDati()];

  // Campi corti: su schermi larghi stanno due per riga.
  static const _tipiCorti = {
    'importo',
    'percentuale',
    'data',
    'anno',
    'numero',
    'decimale',
    'telefono',
    'email',
    'iban',
  };

  // --- Accesso allo schema ---

  List<Json> _lista(Object? valore) =>
      ((valore as List?) ?? const []).cast<Json>();

  List<Json> get _parametriSchema => _lista(widget.schema['parametri']);
  List<Json> get _tutteLeSezioni => _lista(widget.schema['sezioni']);
  Json? get _alternativo => widget.schema['adempimento_alternativo'] as Json?;

  bool _visibile(Json elemento, Map<String, String?> contesto) {
    final condizione = (elemento['visibile_se'] as Map?) ?? const {};
    return condizione.entries.every(
      (e) => (e.value as List).contains(contesto[e.key] ?? ''),
    );
  }

  List<Json> get _sezioniVisibili =>
      _tutteLeSezioni.where((s) => _visibile(s, _parametri)).toList();

  Json? get _sezione {
    for (final s in _sezioniVisibili) {
      if (s['id'] == _sezioneId) return s;
    }
    return null;
  }

  Map<String, String?> _contesto(RigaDati riga) => {
    ..._parametri,
    ...riga.scelte,
  };

  List<Json> _campiVisibili(List<Json> campi, RigaDati riga) =>
      campi.where((c) => _visibile(c, _contesto(riga))).toList();

  bool get _righeCompilate => _righe.any((r) => !r.isEmpty);

  /// Vero se l'utente ha inserito qualcosa che un reset cancellerebbe.
  /// Sezione attualmente scelta nel form (null se non ancora scelta).
  String? get sezioneCorrente => _sezioneId;

  bool get haDati =>
      _righeCompilate ||
      _alternativoController.text.trim().isNotEmpty ||
      _noteController.text.trim().isNotEmpty;

  // --- Ciclo di vita ---

  @override
  void initState() {
    super.initState();
    final dati = widget.datiIniziali;
    if (dati != null) _carica(dati);
    _selezionaSezioneUnica();
  }

  /// Valori dei dati iniziali che non è stato possibile caricare perché lo
  /// schema nel frattempo è cambiato.
  final Set<String> avvisiCaricamento = {};

  void _carica(Json dati) {
    final avvisi = avvisiCaricamento;
    final ambiti = widget.schema['ambito'] == 'autodichiarazione'
        ? const {'TENUTO', 'PARZIALE', 'NON_TENUTO'}
        : const {'TENUTO', 'NON_TENUTO'};
    final ambito = dati['ambito_soggettivo'];
    if (ambiti.contains(ambito)) _ambitoSoggettivo = ambito as String;
    _noteController.text = (dati['note'] ?? '').toString();

    final alternativo = (dati['alternativo'] ?? '').toString().trim();
    if (alternativo.isNotEmpty) {
      if (_alternativo != null) {
        _usaAlternativo = true;
        _alternativoController.text = alternativo;
        return;
      }
      avvisi.add(
        'L\'adempimento alternativo non è più previsto: il collegamento "$alternativo" non è stato caricato.',
      );
    }

    final parametri = (dati['parametri'] as Map?) ?? const {};
    for (final p in _parametriSchema) {
      final valore = parametri[p['id']];
      if (valore == null) continue;
      if (_lista(p['opzioni']).any((o) => o['valore'] == valore)) {
        _parametri[p['id'] as String] = valore as String;
      } else {
        avvisi.add('${p['etichetta']}: il valore "$valore" non è più previsto.');
      }
    }

    final righe = ((dati['righe'] as List?) ?? const [])
        .whereType<Map>()
        .map((r) => r.cast<String, dynamic>())
        .toList();
    final sezioneId = dati['sezione'];
    if (sezioneId == null) return;
    final sezione = _sezioniVisibili
        .where((s) => s['id'] == sezioneId)
        .firstOrNull;
    if (sezione == null) {
      if (righe.isNotEmpty) {
        avvisi.add(
          'La sezione dei dati salvati non è più prevista per le scelte indicate: le righe non sono state caricate.',
        );
      }
      return;
    }
    _sezioneId = sezioneId as String;
    if (righe.isEmpty) return;
    final campi = _lista(sezione['campi']);
    disponiRighe(_righe);
    _righe = [
      for (final r in sezione['ripetibile'] == true ? righe : righe.take(1))
        _rigaDa(r, campi),
    ];
    // Con molte righe si parte compressi: l'intestazione ne mostra il riassunto.
    if (_righe.length > 3) {
      for (final r in _righe) {
        r.espansa = false;
      }
    }
  }

  /// Scheda art. 35, sezione dei procedimenti: gli elementi si possono importare dal catalogo
  /// dei procedimenti (mappatura dell'anticorruzione o procedimenti della trasparenza), o
  /// inserire da zero.
  bool _importaProcedimenti(Json sezione) => widget.schema['id'] == 'ART_35' && sezione['id'] == 'PROCEDIMENTI';

  Future<void> _importa(List<Json> campi) async {
    try {
      final scelti = await scegliProcedimenti(context, apiDi(context));
      if (scelti == null || scelti.isEmpty || !mounted) return;
      setState(() {
        final vuote = _righe.where((r) => r.isEmpty).toList();
        _righe.removeWhere((r) => r.isEmpty);
        disponiRighe(vuote);
        _righe.addAll([for (final e in scelti) _rigaDa(e, campi)]);
        if (_righe.length > 3) {
          for (final r in _righe) {
            r.espansa = false;
          }
        }
      });
      mostraMessaggio(context, scelti.length == 1 ? 'Importato 1 procedimento' : 'Importati ${scelti.length} procedimenti');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  RigaDati _rigaDa(Json valori, List<Json> campi) {
    final riga = RigaDati();
    final perId = {for (final c in campi) c['id'] as String: c};
    for (final MapEntry(key: id, value: valore) in valori.entries) {
      final campo = perId[id];
      if (campo == null) {
        avvisiCaricamento.add(
          'Il campo "$id" non è più previsto dallo schema: il suo valore non è stato caricato.',
        );
        continue;
      }
      switch (campo['tipo']) {
        case 'scelta':
          if (valore is String && valore.isNotEmpty) riga.scelte[id] = valore;
        case 'elenco':
          final sottoCampi = _lista(campo['campi']);
          final elementi = (valore is List ? valore : const [])
              .whereType<Map>()
              .map((m) => _rigaDa(m.cast<String, dynamic>(), sottoCampi))
              .toList();
          if (elementi.isNotEmpty) riga.impostaElenco(id, elementi);
        default:
          riga[id].text = valore?.toString() ?? '';
      }
    }
    // Una scelta non più ammessa bloccherebbe il menu a tendina: si scarta.
    for (final campo in campi.where((c) => c['tipo'] == 'scelta')) {
      final id = campo['id'] as String;
      final valore = riga.scelte[id];
      if (valore != null && !_opzioni(campo, riga).contains(valore)) {
        riga.scelte[id] = null;
        avvisiCaricamento.add(
          '${campo['etichetta']}: il valore "$valore" non è più previsto.',
        );
      }
    }
    return riga;
  }

  /// Con una sola sezione disponibile non serve sceglierla.
  void _selezionaSezioneUnica() {
    final visibili = _sezioniVisibili;
    if (visibili.length == 1) _sezioneId = visibili.first['id'] as String;
  }

  void _nuoveRighe() {
    disponiRighe(_righe);
    _righe = [RigaDati()];
  }

  @override
  void dispose() {
    _alternativoController.dispose();
    _noteController.dispose();
    disponiRighe(_righe);
    super.dispose();
  }

  void reset() {
    _formKey.currentState?.reset();
    _alternativoController.clear();
    _noteController.clear();
    setState(() {
      _ambitoSoggettivo = 'TENUTO';
      _parametri.clear();
      _usaAlternativo = false;
      _sezioneId = null;
      _nuoveRighe();
      _autovalida = false;
      _revisione++;
      _selezionaSezioneUnica();
    });
  }

  // --- Modifiche che possono cancellare dati ---

  Future<void> _cambiaParametro(String id, String? valore) async {
    if (valore == _parametri[id]) return;
    final sezione = _sezione;
    final resta =
        sezione != null && _visibile(sezione, {..._parametri, id: valore});
    if (sezione != null && !resta && _righeCompilate) {
      final conferma = await confermaPerditaDati(
        context,
        messaggio:
            'Con questa scelta la sezione "${sezione['titolo']}" non è più prevista: '
            'i dati inseriti verranno cancellati.',
      );
      if (!mounted) return;
      if (!conferma) {
        setState(() => _revisione++);
        return;
      }
    }
    setState(() {
      _parametri[id] = valore;
      if (!resta) {
        _sezioneId = null;
        _nuoveRighe();
      }
      _selezionaSezioneUnica();
    });
  }

  Future<void> _scegliSezione(String id) async {
    if (id == _sezioneId) return;
    if (_righeCompilate) {
      final conferma = await confermaPerditaDati(
        context,
        messaggio:
            'Cambiando sezione cambiano i campi da compilare: i dati inseriti verranno cancellati.',
      );
      if (!conferma || !mounted) return;
    }
    setState(() {
      _sezioneId = id;
      _nuoveRighe();
    });
  }

  Future<void> _rimuovi(List<RigaDati> righe, int i, String elemento) async {
    if (!righe[i].isEmpty) {
      final conferma = await confermaPerditaDati(
        context,
        titolo: 'Rimuovere ${elemento.toLowerCase()} ${i + 1}?',
        messaggio: 'I dati inseriti in questo elemento verranno cancellati.',
        conferma: 'Rimuovi',
      );
      if (!conferma || !mounted) return;
    }
    setState(() => righe.removeAt(i).dispose());
  }

  // --- Valori ---

  Object _valore(RigaDati riga, Json campo) {
    final id = campo['id'] as String;
    switch (campo['tipo']) {
      case 'scelta':
        return riga.scelte[id] ?? '';
      case 'elenco':
        final sottoCampi = _lista(campo['campi']);
        return riga
            .elenco(id)
            .where((r) => !r.isEmpty)
            .map((r) => _valoriRiga(r, sottoCampi))
            .toList();
      case 'importo':
        final testo = riga.testo(id);
        return testo.isEmpty ? '' : DataFormatter.formatCurrency(testo);
      case 'percentuale':
        final testo = riga.testo(id);
        return testo.isEmpty ? '' : DataFormatter.formatPercentage(testo);
      default:
        return riga.testo(id);
    }
  }

  /// Solo i campi visibili finiscono nei dati inviati.
  Json _valoriRiga(RigaDati riga, List<Json> campi) => {
    for (final campo in _campiVisibili(campi, riga))
      campo['id'] as String: _valore(riga, campo),
  };

  /// Raccoglie i dati da inviare. Se qualcosa non va porta in vista il primo
  /// punto da correggere e restituisce il motivo.
  Future<DatiModulo> raccogli() async {
    final note = _noteController.text.trim();
    final parametri = {
      for (final e in _parametri.entries)
        if (e.value != null) e.key: e.value,
    };

    // Obbligo non applicabile o soggetto non tenuto: basta la dichiarazione.
    if (_ambitoSoggettivo == 'NON_TENUTO') {
      return (
        dati: <String, dynamic>{
          'ambito_soggettivo': _ambitoSoggettivo,
          'parametri': parametri,
          'sezione': _sezioneId,
          'righe': <Json>[],
          'note': note,
        },
        errore: null,
      );
    }

    if (_usaAlternativo) {
      if (!_validaForm()) {
        await _evidenziaErrori();
        return (dati: null, errore: 'Indica un collegamento valido.');
      }
      return (
        dati: <String, dynamic>{
          'ambito_soggettivo': _ambitoSoggettivo,
          'alternativo': _alternativoController.text.trim(),
          'note': note,
        },
        errore: null,
      );
    }

    if (!_validaForm()) {
      final n = await _evidenziaErrori();
      return (
        dati: null,
        errore: n <= 1
            ? 'C\'è un campo da correggere, evidenziato in rosso.'
            : 'Ci sono $n campi da correggere, evidenziati in rosso.',
      );
    }
    final sezione = _sezione;
    if (sezione == null) {
      await _porta(_chiaveScelte);
      return (dati: null, errore: 'Scegli la sezione da compilare.');
    }
    final compilate = _righe.where((r) => !r.isEmpty).toList();
    if (compilate.isEmpty) {
      await _porta(_chiaveDati);
      return (dati: null, errore: 'Compila i dati da pubblicare.');
    }
    final campi = _lista(sezione['campi']);
    return (
      dati: <String, dynamic>{
        'ambito_soggettivo': _ambitoSoggettivo,
        'parametri': parametri,
        'sezione': _sezioneId,
        'righe': compilate.map((r) => _valoriRiga(r, campi)).toList(),
        'note': note,
      },
      errore: null,
    );
  }

  bool _validaForm() {
    final valido = _formKey.currentState?.validate() ?? false;
    if (!valido && !_autovalida) setState(() => _autovalida = true);
    return valido;
  }

  /// Riapre le righe compresse, conta i campi con errore e scorre al primo.
  Future<int> _evidenziaErrori() async {
    setState(() {
      for (final r in _righe) {
        r.espandiTutto();
      }
    });
    await WidgetsBinding.instance.endOfFrame;
    final errori = <Element>[];
    void visita(Element e) {
      if (e is StatefulElement &&
          e.state is FormFieldState &&
          (e.state as FormFieldState).hasError) {
        errori.add(e);
      }
      e.visitChildren(visita);
    }

    _formKey.currentContext?.visitChildElements(visita);
    if (errori.isNotEmpty && mounted) {
      await Scrollable.ensureVisible(
        errori.first,
        duration: const Duration(milliseconds: 300),
        alignment: 0.2,
      );
    }
    return errori.length;
  }

  Future<void> _porta(GlobalKey chiave) async {
    final contesto = chiave.currentContext;
    if (contesto == null) return;
    await Scrollable.ensureVisible(
      contesto,
      duration: const Duration(milliseconds: 300),
      alignment: 0.1,
    );
  }

  // --- Campi ---

  String? Function(String?) _validatore(Json campo) {
    final obbl = campo['obbligatorio'] == true;
    final maxLunghezza = campo['max_lunghezza'] as int?;

    String? opzionale(String? v, String? Function(String) controllo) {
      if (v == null || v.trim().isEmpty) {
        return obbl ? 'Campo obbligatorio' : null;
      }
      return controllo(v.trim());
    }

    switch (campo['tipo']) {
      case 'data':
        return campo['separatore_data'] == '.'
            ? (v) => DataFormatter.validateDateWithDot(v, isRequired: obbl)
            : (v) => DataFormatter.validateDateWithSlash(v, isRequired: obbl);
      case 'iban':
        final formatoIban = RegExp(r'^IT\d{2}[A-Z]\d{10}[0-9A-Z]{12}$');
        return (v) => opzionale(
          v,
          (t) => formatoIban.hasMatch(t.replaceAll(' ', '').toUpperCase())
              ? null
              : 'IBAN italiano non valido (27 caratteri)',
        );
      case 'anno':
        return (v) => opzionale(v, DataFormatter.validateYear);
      case 'url':
        return (v) => DataFormatter.validateUrl(
          v,
          isRequired: obbl,
          maxLength: maxLunghezza ?? 2048,
        );
      case 'email':
        return (v) => DataFormatter.validateEmailAnac(v, isRequired: obbl);
      case 'telefono':
        return (v) => DataFormatter.validatePhone(v, isRequired: obbl);
      case 'importo':
        return (v) => opzionale(v, DataFormatter.validateCurrencyInput);
      case 'percentuale':
        return (v) => opzionale(v, DataFormatter.validatePercentageInput);
      case 'numero':
        return (v) => opzionale(
          v,
          (t) => int.tryParse(t) == null ? 'Inserisci un numero intero' : null,
        );
      case 'decimale':
        final decimali = campo['decimali'] as int?;
        final cifre = decimali == null ? r'\d+' : '\\d{$decimali}';
        final formato = RegExp(
          '^-?\\d+(,$cifre)${decimali == null ? '?' : ''}\$',
        );
        return (v) => opzionale(
          v,
          (t) => formato.hasMatch(t)
              ? null
              : decimali == null
              ? 'Numero non valido (es. 12,5)'
              : 'Usa esattamente $decimali decimali (es. 18,53)',
        );
      default:
        return (v) => DataFormatter.validateTextLength(
          v,
          maxLength: maxLunghezza ?? 100000,
          isRequired: obbl,
        );
    }
  }

  TextInputType? _tastiera(String tipo) {
    switch (tipo) {
      case 'anno':
      case 'numero':
        return TextInputType.number;
      case 'importo':
      case 'percentuale':
      case 'decimale':
        return const TextInputType.numberWithOptions(
          decimal: true,
          signed: true,
        );
      case 'url':
        return TextInputType.url;
      case 'email':
        return TextInputType.emailAddress;
      case 'telefono':
        return TextInputType.phone;
      case 'testo_lungo':
        return TextInputType.multiline;
      default:
        return null;
    }
  }

  String? _suggerimento(Json campo) {
    switch (campo['tipo']) {
      case 'anno':
        return 'es. 2026';
      case 'url':
        return 'https://...';
      case 'importo':
        return 'es. 1.500,00';
      case 'percentuale':
        return 'es. 45,50';
      default:
        final descrizione = (campo['descrizione'] as String?) ?? '';
        return descrizione.isEmpty ? null : descrizione;
    }
  }

  List<String> _opzioni(Json campo, RigaDati riga) {
    final fisse = campo['opzioni'] as List?;
    if (fisse != null) return fisse.cast<String>();
    final origine = riga.scelte[campo['opzioni_da'] as String];
    final perValore = (campo['opzioni_per'] as Map?) ?? const {};
    return ((perValore[origine] as List?) ?? const []).cast<String>();
  }

  /// Testo breve che identifica una riga compressa: il primo campo compilato.
  String _riassunto(RigaDati riga, List<Json> campi) {
    for (final campo in _campiVisibili(campi, riga)) {
      final tipo = campo['tipo'];
      if (tipo == 'elenco' || tipo == 'url') continue;
      final id = campo['id'] as String;
      final valore = tipo == 'scelta' ? (riga.scelte[id] ?? '') : riga.testo(id);
      if (valore.isNotEmpty) {
        return valore.length > 60 ? '${valore.substring(0, 57)}...' : valore;
      }
    }
    return '';
  }

  Widget _elenco(List<RigaDati> righe, List<Json> campi, String elemento) {
    return elencoRipetibile(
      titoloRiga: elemento,
      righe: righe,
      costruisciRiga: (r) => _campiRiga(r, campi),
      riassunto: (r) => _riassunto(r, campi),
      onAggiungi: () => setState(() => righe.add(RigaDati())),
      onRimuovi: (i) => _rimuovi(righe, i, elemento),
      onDuplica: (i) => setState(() => righe.insert(i + 1, righe[i].copia())),
      onEspandi: (i) => setState(() => righe[i].espansa = !righe[i].espansa),
      etichettaAggiungi: 'Aggiungi ${elemento.toLowerCase()}',
    );
  }

  Widget _campo(RigaDati riga, Json campo, List<Json> fratelli) {
    final id = campo['id'] as String;
    final tipo = campo['tipo'] as String;
    final obbl = campo['obbligatorio'] == true;
    final etichetta = '${campo['etichetta']}${obbl ? ' *' : ''}';

    switch (tipo) {
      case 'scelta':
        return campoScelta(
          value: riga.scelte[id],
          label: etichetta,
          opzioni: _opzioni(campo, riga),
          onChanged: (v) => setState(() {
            riga.scelte[id] = v;
            // Le scelte che dipendono da questa vanno rifatte.
            for (final f in fratelli) {
              if (f['opzioni_da'] == id) riga.scelte[f['id'] as String] = null;
            }
          }),
          validator: seCompilata(
            riga,
            (v) => (obbl && v == null) ? 'Campo obbligatorio' : null,
          ),
        );
      case 'data':
        return campoData(
          context,
          riga[id],
          etichetta,
          validator: seCompilata(riga, _validatore(campo)),
          separatore: campo['separatore_data'] as String? ?? '/',
        );
      case 'elenco':
        return Padding(
          padding: const EdgeInsets.only(top: 4.0, bottom: 12.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              titoloSezione(etichetta),
              if ((campo['descrizione'] as String?)?.isNotEmpty == true)
                notaInformativa(campo['descrizione'] as String),
              _elenco(
                riga.elenco(id),
                _lista(campo['campi']),
                campo['etichetta_elemento'] as String? ?? 'Elemento',
              ),
            ],
          ),
        );
      default:
        return campoTesto(
          riga[id],
          etichetta,
          hint: _suggerimento(campo),
          keyboardType: _tastiera(tipo),
          maxLines: tipo == 'testo_lungo' ? 4 : 1,
          validator: seCompilata(riga, _validatore(campo)),
        );
    }
  }

  /// Campi di una riga: i campi corti affiancati a due a due sugli schermi
  /// larghi, con un sotto-titolo all'inizio di ogni gruppo.
  Widget _campiRiga(RigaDati riga, List<Json> campi) {
    return LayoutBuilder(
      builder: (context, vincoli) {
        final larghezza = vincoli.maxWidth;
        final dueColonne = larghezza >= 600;
        final mezza = (larghezza - 16) / 2;
        final figli = <Widget>[];
        var gruppo = '';
        for (final campo in _campiVisibili(campi, riga)) {
          final g = (campo['gruppo'] as String?) ?? '';
          if (g.isNotEmpty && g != gruppo) {
            figli.add(
              SizedBox(width: larghezza, child: titoloGruppo(context, g)),
            );
          }
          gruppo = g;
          final corto = dueColonne && _tipiCorti.contains(campo['tipo']);
          figli.add(
            SizedBox(
              width: corto ? mezza : larghezza,
              child: _campo(riga, campo, campi),
            ),
          );
        }
        return Wrap(spacing: 16, children: figli);
      },
    );
  }

  // --- Passi ---

  String _etichettaSezione(Json s) {
    final gruppo = (s['gruppo'] as String?) ?? '';
    return gruppo.isEmpty ? s['titolo'] as String : '$gruppo - ${s['titolo']}';
  }

  Widget _riquadroFrase(String testo) {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.grey.shade100,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.grey.shade300),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.format_quote, color: Colors.grey.shade700),
          const SizedBox(width: 8),
          Expanded(child: Text(testo)),
        ],
      ),
    );
  }

  Widget _applicabilita(Json? alternativo) {
    final nonTenuto = _ambitoSoggettivo == 'NON_TENUTO';
    final frase =
        (widget.schema['frasi_ambito'] as Map?)?[_ambitoSoggettivo] as String?;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        KeyedSubtree(
          key: ValueKey('ambito-$_revisione'),
          child: selettoreAmbito(
            value: _ambitoSoggettivo,
            onChanged: (v) => setState(() => _ambitoSoggettivo = v),
            conAutodichiarazione:
                widget.schema['ambito'] == 'autodichiarazione',
            articolo: widget.schema['articolo'] as String? ?? '',
          ),
        ),
        if (frase != null)
          _riquadroFrase(
            'Nel documento sarà riportato: «$frase»'
            '${nonTenuto ? '\nNon servono altri dati.' : ''}',
          ),
        if (alternativo != null && !nonTenuto) ...[
          const SizedBox(height: 8),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: _usaAlternativo,
            title: Text(alternativo['etichetta'] as String),
            subtitle: Text(
              alternativo['descrizione'] as String,
              style: const TextStyle(fontSize: 12),
            ),
            onChanged: (v) => setState(() => _usaAlternativo = v ?? false),
          ),
          if (_usaAlternativo) ...[
            const SizedBox(height: 8),
            campoTesto(
              _alternativoController,
              '${alternativo['etichetta_link']} *',
              hint: 'https://...',
              keyboardType: TextInputType.url,
              validator: (v) => DataFormatter.validateUrl(v, maxLength: 2048),
            ),
          ],
        ],
      ],
    );
  }

  Widget _selettoreParametro(Json parametro) {
    final id = parametro['id'] as String;
    final opzioni = _lista(parametro['opzioni']);
    final scelta = opzioni.where((o) => o['valore'] == _parametri[id]);
    final nota = scelta.isEmpty ? '' : (scelta.first['nota'] as String? ?? '');
    return Padding(
      padding: const EdgeInsets.only(bottom: 16.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DropdownButtonFormField<String>(
            key: ValueKey('$id-$_revisione'),
            initialValue: _parametri[id],
            isExpanded: true,
            decoration: InputDecoration(
              labelText: '${parametro['etichetta']} *',
              helperText:
                  (parametro['descrizione'] as String?)?.isNotEmpty == true
                  ? parametro['descrizione'] as String
                  : null,
              helperMaxLines: 3,
              border: const OutlineInputBorder(),
            ),
            items: opzioni
                .map(
                  (o) => DropdownMenuItem<String>(
                    value: o['valore'] as String,
                    child: Text(o['etichetta'] as String),
                  ),
                )
                .toList(),
            onChanged: (v) => _cambiaParametro(id, v),
            validator: (v) => v == null ? 'Campo obbligatorio' : null,
          ),
          if (nota.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(top: 8.0),
              padding: const EdgeInsets.all(10.0),
              decoration: BoxDecoration(
                color: Colors.orange.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.orange.shade300),
              ),
              child: Text(
                nota,
                style: TextStyle(fontSize: 13, color: Colors.orange.shade900),
              ),
            ),
        ],
      ),
    );
  }

  /// Sezioni disponibili come schede selezionabili, raggruppate per gruppo.
  List<Widget> _schedeSezioni(List<Json> sezioni) {
    final colori = Theme.of(context).colorScheme;
    final schede = <Widget>[];
    String? gruppo;
    for (final s in sezioni) {
      final g = (s['gruppo'] as String?) ?? '';
      if (g.isNotEmpty && g != gruppo) schede.add(titoloGruppo(context, g));
      gruppo = g;
      final scelta = s['id'] == _sezioneId;
      schede.add(
        Card(
          margin: const EdgeInsets.only(bottom: 8),
          elevation: 0,
          color: scelta ? colori.primary.withValues(alpha: 0.06) : null,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
            side: BorderSide(
              color: scelta ? colori.primary : Colors.grey.shade300,
              width: scelta ? 2 : 1,
            ),
          ),
          child: ListTile(
            leading: Icon(
              scelta ? Icons.radio_button_checked : Icons.radio_button_unchecked,
              color: scelta ? colori.primary : Colors.grey.shade600,
            ),
            title: Text(
              s['titolo'] as String,
              style: TextStyle(
                fontSize: 14,
                fontWeight: scelta ? FontWeight.bold : FontWeight.normal,
              ),
            ),
            subtitle: Text(
              'Aggiornamento ${s['aggiornamento']}',
              style: const TextStyle(fontSize: 12),
            ),
            onTap: () => _scegliSezione(s['id'] as String),
          ),
        ),
      );
    }
    return schede;
  }

  Widget _scelte() {
    final sezioni = _sezioniVisibili;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final parametro in _parametriSchema)
          KeyedSubtree(
            key: ValueKey('parametro-${parametro['id']}'),
            child: _selettoreParametro(parametro),
          ),
        if (_tutteLeSezioni.length > 1) ...[
          const Text(
            'Sezione da compilare *',
            style: TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          if (sezioni.isEmpty)
            Text(
              'Completa le scelte qui sopra per vedere le sezioni previste.',
              style: TextStyle(color: Colors.grey.shade700),
            )
          else
            ..._schedeSezioni(sezioni),
        ],
      ],
    );
  }

  Widget _dati() {
    final sezione = _sezione;
    if (sezione == null) {
      return Text(
        'Scegli prima la sezione da compilare.',
        style: TextStyle(color: Colors.grey.shade700),
      );
    }
    final campi = _lista(sezione['campi']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        PannelloInfo(
          voci: [
            ('Sezione', _etichettaSezione(sezione)),
            ('Collocazione', sezione['collocazione'] as String),
            ('Aggiornamento', maiuscola(sezione['aggiornamento'] as String)),
            ('Riferimenti', (sezione['norme'] as List).join('; ')),
          ],
          nota: sezione['nota'] as String?,
        ),
        const SizedBox(height: 16),
        if (_importaProcedimenti(sezione))
          Align(
            alignment: Alignment.centerLeft,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: OutlinedButton.icon(
                icon: const Icon(Icons.download_outlined),
                label: const Text('Importa dalla mappatura dei procedimenti'),
                onPressed: () => _importa(campi),
              ),
            ),
          ),
        if (sezione['ripetibile'] == true)
          _elenco(
            _righe,
            campi,
            sezione['etichetta_elemento'] as String? ?? 'Elemento',
          )
        else
          _campiRiga(_righe.first, campi),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final alternativo = _alternativo;
    final compilaDati = _ambitoSoggettivo != 'NON_TENUTO' && !_usaAlternativo;
    final conScelte =
        compilaDati &&
        (_parametriSchema.isNotEmpty || _tutteLeSezioni.length > 1);
    var numero = widget.primoNumero;

    return Form(
      key: _formKey,
      autovalidateMode: _autovalida
          ? AutovalidateMode.onUserInteraction
          : AutovalidateMode.disabled,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SezioneNumerata(
            numero: numero++,
            titolo: 'Applicabilità',
            sottotitolo: alternativo == null
                ? 'Se l\'obbligo non riguarda l\'ente basta dichiararlo.'
                : 'Se l\'obbligo non riguarda l\'ente, o se è assolto in altro modo, non servono altri dati.',
            child: _applicabilita(alternativo),
          ),
          if (conScelte)
            SezioneNumerata(
              key: _chiaveScelte,
              numero: numero++,
              titolo: 'Caratteristiche e sezione',
              sottotitolo:
                  'Determinano quale tabella dello schema ANAC compilare.',
              child: _scelte(),
            ),
          if (compilaDati)
            SezioneNumerata(
              key: _chiaveDati,
              numero: numero++,
              titolo: 'Dati da pubblicare',
              child: _dati(),
            ),
          SezioneNumerata(
            numero: numero++,
            titolo: 'Note (facoltative)',
            sottotitolo: 'Testo libero riportato nel documento generato.',
            child: campoTesto(
              _noteController,
              'Note',
              maxLines: 3,
              keyboardType: TextInputType.multiline,
            ),
          ),
        ],
      ),
    );
  }
}
