import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../../util/scelta_file.dart';
import '../../comuni.dart';
import '../browser.dart';
import '../coda_analisi.dart';
import '../forms/form_helpers.dart';
import '../servizio.dart';
import '../utils/data_formatter.dart';
import '../widgets/modulo.dart';
import '../widgets/selettore_schema.dart';

class AiAnalysisTab extends StatefulWidget {
  const AiAnalysisTab({super.key});

  @override
  State<AiAnalysisTab> createState() => _AiAnalysisTabState();
}

class SelectedFile {
  final String name;
  final Uint8List bytes;
  final TextEditingController descriptionController;

  SelectedFile({required this.name, required this.bytes})
    : descriptionController = TextEditingController();

  void dispose() {
    descriptionController.dispose();
  }
}

/// Cosa si analizza: una pagina web oppure uno o più documenti caricati.
enum _Sorgente { web, documenti }

class _AiAnalysisTabState extends State<AiAnalysisTab>
    with AutomaticKeepAliveClientMixin {
  // La scheda resta in vita quando si passa alle altre: i dati inseriti
  // non vanno persi.
  @override
  bool get wantKeepAlive => true;

  final TextEditingController _noteController = TextEditingController();
  final TextEditingController _urlController = TextEditingController();
  final TextEditingController _dataPubblicazioneController =
      TextEditingController();
  final TextEditingController _dataAdozioneController = TextEditingController();

  _Sorgente _sorgente = _Sorgente.documenti;
  final List<SelectedFile> _selectedFiles = [];
  bool _analyzePdfInUrl = false;
  bool _followLink = false;
  int _maxLink = linkPredefiniti;

  // Le date partono vuote: con valori predefiniti (es. oggi) l'audit
  // confronterebbe date non reali e giudicherebbe la pubblicazione sempre
  // tempestiva. Se una data non è nota lo si dichiara esplicitamente e
  // l'analisi riporta la tempestività come "Non valutabile".
  bool _pubblicazioneNonNota = false;
  bool _adozioneNonNota = false;

  // Schemi ANAC serviti dall'API (common/trasparenza/schemi): alimentano l'elenco dei
  // tipi di atto (raggruppati per sotto-sezione di Amministrazione trasparente)
  // e la scheda informativa. Ogni schema può avere varianti di audit dedicate.
  List<Map<String, dynamic>> _schemi = [];
  bool _caricamentoSchemi = true;
  String? _erroreSchemi;
  Map<String, dynamic>? _schemaScelto;
  Map<String, dynamic>? _varianteScelta;

  bool _isUploading = false;
  // Esito dell'ultima richiesta (successo o errore), mostrato sotto i pulsanti.
  String? _esito;
  bool _esitoPositivo = false;

  @override
  void initState() {
    super.initState();
    // I campi di testo non passano da setState: si aggiorna il riepilogo di
    // ciò che manca a ogni modifica.
    for (final c in [
      _urlController,
      _dataPubblicazioneController,
      _dataAdozioneController,
    ]) {
      c.addListener(_aggiorna);
    }
    _caricaSchemi();
  }

  void _aggiorna() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _noteController.dispose();
    _urlController.dispose();
    _dataPubblicazioneController.dispose();
    _dataAdozioneController.dispose();
    for (var file in _selectedFiles) {
      file.dispose();
    }
    super.dispose();
  }

  // ---------------------------------------------------------------------------
  // Schemi e tipo di atto
  // ---------------------------------------------------------------------------

  Future<void> _caricaSchemi({bool ricarica = false}) async {
    setState(() {
      _caricamentoSchemi = true;
      _erroreSchemi = null;
    });
    try {
      final schemi = await ServizioTrasparenza(apiDi(context)).schemi(ricarica: ricarica);
      if (!mounted) return;
      setState(() {
        _schemi = schemi;
        _caricamentoSchemi = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _caricamentoSchemi = false;
        _erroreSchemi = 'Impossibile caricare i tipi di atto dal server ($e).';
      });
    }
  }

  String _descrizioneAtto() {
    final schema = _schemaScelto;
    if (schema == null) return 'Scegli il tipo di atto...';
    final base = '${schema['titolo']} (${schema['riferimento']})';
    final variante = _varianteScelta;
    return variante == null
        ? base
        : '$base\n↳ ${maiuscola(variante['titolo'] as String)}';
  }

  void _scegli(Map<String, dynamic> schema, Map<String, dynamic>? variante) {
    setState(() {
      _schemaScelto = schema;
      _varianteScelta = variante;
    });
  }

  Future<void> _scegliAtto() async {
    final scelta = await mostraSelettoreSchema(
      context,
      schemi: _schemi,
      titolo: 'Seleziona il tipo di atto',
      conVarianti: true,
      idSchema: _schemaScelto?['id'] as String?,
      idVariante: _varianteScelta?['id'] as String?,
    );
    if (scelta != null) _scegli(scelta.schema, scelta.variante);
  }

  // ---------------------------------------------------------------------------
  // Documenti
  // ---------------------------------------------------------------------------

  Future<void> _pickFile() async {
    final scelti = await scegliFiles(estensioniAmmesse);
    if (scelti.isEmpty || !mounted) return;
    setState(() {
      // Evita di aggiungere due volte lo stesso file
      final existingNames = _selectedFiles.map((f) => f.name).toSet();
      for (final file in scelti) {
        if (!existingNames.contains(file.name)) {
          _selectedFiles.add(SelectedFile(name: file.name, bytes: file.bytes));
        }
      }
    });
  }

  void _removeFile(int index) {
    setState(() {
      _selectedFiles[index].dispose();
      _selectedFiles.removeAt(index);
    });
  }

  void _previewSelectedFile(int index) {
    if (index < 0 || index >= _selectedFiles.length) return;
    apriAnteprima(_selectedFiles[index].bytes, _selectedFiles[index].name);
  }

  // ---------------------------------------------------------------------------
  // Stato del modulo
  // ---------------------------------------------------------------------------

  DateTime? get _dataPubblicazione =>
      DataFormatter.parseItalianDate(_dataPubblicazioneController.text.trim());
  DateTime? get _dataAdozione =>
      DataFormatter.parseItalianDate(_dataAdozioneController.text.trim());

  // Le pagine di Amministrazione trasparente hanno spesso parametri
  // (?id=...&anno=...): basta un indirizzo http(s) assoluto con dominio.
  // Il backend applica comunque i propri controlli (solo IP pubblici).
  static bool _urlValido(String testo) {
    final uri = Uri.tryParse(testo);
    return testo.length <= 2048 &&
        uri != null &&
        (uri.scheme == 'http' || uri.scheme == 'https') &&
        uri.host.contains('.');
  }

  /// Elenco di ciò che manca per poter avviare l'analisi.
  List<String> get _mancanti {
    final mancanti = <String>[];
    if (_schemaScelto == null) mancanti.add('il tipo di atto');
    if (_sorgente == _Sorgente.web) {
      if (!_urlValido(_urlController.text.trim())) {
        mancanti.add('un indirizzo web valido');
      }
    } else if (_selectedFiles.isEmpty) {
      mancanti.add('almeno un documento');
    }
    if (!_pubblicazioneNonNota && _dataPubblicazione == null) {
      mancanti.add('la data di pubblicazione (o "non nota")');
    }
    if (!_adozioneNonNota && _dataAdozione == null) {
      mancanti.add('la data di adozione (o "non nota")');
    }
    return mancanti;
  }

  bool get _datiPresenti =>
      _schemaScelto != null ||
      _urlController.text.isNotEmpty ||
      _selectedFiles.isNotEmpty ||
      _dataPubblicazioneController.text.isNotEmpty ||
      _dataAdozioneController.text.isNotEmpty ||
      _noteController.text.isNotEmpty;

  Future<void> _nuovaAnalisi() async {
    if (_datiPresenti) {
      final conferma = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Nuova analisi'),
          content: const Text(
            'Tutti i dati inseriti verranno cancellati. Vuoi continuare?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Annulla'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Cancella i dati'),
            ),
          ],
        ),
      );
      if (conferma != true) return;
    }
    setState(() {
      _noteController.clear();
      _urlController.clear();
      _dataPubblicazioneController.clear();
      _dataAdozioneController.clear();
      for (var file in _selectedFiles) {
        file.dispose();
      }
      _selectedFiles.clear();
      _sorgente = _Sorgente.documenti;
      _pubblicazioneNonNota = false;
      _adozioneNonNota = false;
      _schemaScelto = null;
      _varianteScelta = null;
      _analyzePdfInUrl = false;
      _followLink = false;
      _maxLink = linkPredefiniti;
      _esito = null;
    });
  }

  // ---------------------------------------------------------------------------
  // Invio
  // ---------------------------------------------------------------------------

  void _mostraEsito(String messaggio, {required bool positivo}) {
    setState(() {
      _esito = messaggio;
      _esitoPositivo = positivo;
    });
  }

  Future<void> _uploadData() async {
    if (_mancanti.isNotEmpty || _isUploading) return;

    setState(() {
      _isUploading = true;
      _esito = null;
    });

    String data(bool nonNota, DateTime? valore) =>
        nonNota || valore == null ? '' : DateFormat('dd/MM/yyyy').format(valore);

    // Il worker usa il controllo (variante di audit), se scelto, altrimenti lo schema.
    final web = _sorgente == _Sorgente.web;
    final dati = <String, dynamic>{
      'controllo': _varianteScelta?['id'] ?? _schemaScelto!['id'],
      'note': _noteController.text.trim(),
      'data_pubblicazione': data(_pubblicazioneNonNota, _dataPubblicazione),
      'data_adozione': data(_adozioneNonNota, _dataAdozione),
      if (web) ...{
        'url': _urlController.text.trim(),
        'analizza_pdf': _analyzePdfInUrl,
        'segui_link': _followLink,
        'max_link': _maxLink,
      } else
        'descrizioni': {
          for (final f in _selectedFiles) f.name: f.descriptionController.text.trim(),
        },
    };
    final servizio = ServizioTrasparenza(apiDi(context));
    final coda = context.read<CodaAnalisi>();
    try {
      // L'analisi gira in background: si segue nella scheda "Analisi avviate" e intanto
      // se ne possono avviare altre (il form resta compilato).
      final lavoro = await servizio.avviaAnalisi(
        dati,
        web ? const [] : [for (final f in _selectedFiles) (f.name, f.bytes)],
      );
      coda.aggiungi(lavoro);
      _mostraEsito(
        'Analisi avviata: la segui nella scheda "Analisi avviate". Intanto puoi avviarne altre.',
        positivo: true,
      );
    } catch (e) {
      _mostraEsito('Analisi non avviata: $e', positivo: false);
    } finally {
      if (mounted) setState(() => _isUploading = false);
    }
  }

  // ---------------------------------------------------------------------------
  // Impaginazione
  // ---------------------------------------------------------------------------

  Widget _tipoDiAtto() {
    return SezioneNumerata(
      numero: 1,
      titolo: 'Tipo di atto da verificare',
      sottotitolo:
          'Lo schema ANAC rispetto al quale verificare il documento.',
      azione: _schemaScelto == null
          ? null
          : IconButton(
              icon: const Icon(Icons.info_outline),
              tooltip: 'Dettagli normativi dello schema',
              onPressed: () =>
                  mostraInfoSchema(context, _schemaScelto!, _varianteScelta),
            ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: _schemi.isEmpty
                ? null
                : _scegliAtto,
            borderRadius: BorderRadius.circular(8),
            child: InputDecorator(
              decoration: const InputDecoration(
                labelText: 'Tipo di atto *',
                prefixIcon: Icon(Icons.account_tree_outlined),
                suffixIcon: Icon(Icons.arrow_drop_down),
              ),
              child: Text(
                _descrizioneAtto(),
                style: TextStyle(
                  color: _schemaScelto == null
                      ? Colors.black54
                      : Colors.black87,
                  height: 1.4,
                ),
              ),
            ),
          ),
          if (_schemaScelto != null && !schemaAnac(_schemaScelto!))
            AvvisoSchemaNonAnac(schema: _schemaScelto!),
          if (_caricamentoSchemi)
            const Padding(
              padding: EdgeInsets.only(top: 12),
              child: LinearProgressIndicator(),
            ),
          if (_erroreSchemi != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      _erroreSchemi!,
                      style: const TextStyle(color: Colors.red),
                    ),
                  ),
                  TextButton(
                    onPressed: _caricaSchemi,
                    child: const Text('Riprova'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _cosaAnalizzare() {
    return SezioneNumerata(
      numero: 2,
      titolo: 'Cosa analizzare',
      sottotitolo:
          'Una pagina web pubblicata oppure uno o più documenti. Viene inviato solo ciò che è selezionato qui sotto.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SegmentedButton<_Sorgente>(
            segments: const [
              ButtonSegment(
                value: _Sorgente.documenti,
                icon: Icon(Icons.attach_file),
                label: Text('Documenti'),
              ),
              ButtonSegment(
                value: _Sorgente.web,
                icon: Icon(Icons.language),
                label: Text('Pagina web'),
              ),
            ],
            selected: {_sorgente},
            onSelectionChanged: (scelta) =>
                setState(() => _sorgente = scelta.first),
          ),
          const SizedBox(height: 16),
          if (_sorgente == _Sorgente.web) _paginaWeb() else _documenti(),
        ],
      ),
    );
  }

  Widget _paginaWeb() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: _urlController,
          keyboardType: TextInputType.url,
          decoration: InputDecoration(
            labelText: 'Indirizzo della pagina *',
            hintText: 'https://www.ente.it/amministrazione-trasparente/...',
            prefixIcon: const Icon(Icons.link),
            // Visibile solo con del testo: il listener sul controller
            // ricostruisce la scheda a ogni modifica.
            suffixIcon: _urlController.text.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.clear),
                    tooltip: 'Cancella l\'indirizzo',
                    onPressed: _urlController.clear,
                  ),
          ),
        ),
        const SizedBox(height: 8),
        CheckboxListTile(
          title: const Text('Analizza anche i PDF collegati alla pagina (max 5)'),
          value: _analyzePdfInUrl,
          onChanged: (v) => setState(() => _analyzePdfInUrl = v ?? false),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          dense: true,
        ),
        SceltaLink(
          titolo: 'Segui i link presenti nel contenuto principale',
          segui: _followLink,
          numero: _maxLink,
          onSegui: (v) => setState(() => _followLink = v),
          onNumero: (v) => setState(() => _maxLink = v),
          dense: true,
        ),
      ],
    );
  }

  Widget _documenti() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_selectedFiles.isEmpty)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 24),
            decoration: BoxDecoration(
              border: Border.all(color: Colors.grey.shade300),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              'Nessun documento selezionato.\nFormati ammessi: PDF, DOC, DOCX, ODT, XLS, XLSX, ODS, CSV.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey.shade700),
            ),
          )
        else
          for (var index = 0; index < _selectedFiles.length; index++)
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                border: Border.all(color: Colors.grey.shade300),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      const Icon(Icons.description_outlined),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _selectedFiles[index].name,
                          style: const TextStyle(fontWeight: FontWeight.bold),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.visibility_outlined),
                        tooltip: 'Anteprima',
                        onPressed: () => _previewSelectedFile(index),
                      ),
                      IconButton(
                        icon: const IconaElimina(),
                        color: Colors.red.shade700,
                        tooltip: 'Rimuovi',
                        onPressed: () => _removeFile(index),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _selectedFiles[index].descriptionController,
                    decoration: const InputDecoration(
                      labelText: 'Descrizione del documento (facoltativa)',
                      hintText: 'es. Relazione del revisore al rendiconto 2025',
                      isDense: true,
                    ),
                  ),
                ],
              ),
            ),
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            icon: const Icon(Icons.folder_open),
            label: Text(
              _selectedFiles.isEmpty
                  ? 'Seleziona i documenti'
                  : 'Aggiungi altri documenti',
            ),
            onPressed: _pickFile,
          ),
        ),
      ],
    );
  }

  Widget _campoDataConNonNota({
    required TextEditingController controller,
    required String etichetta,
    required String aiuto,
    required bool nonNota,
    required ValueChanged<bool> onNonNota,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (nonNota)
          InputDecorator(
            decoration: InputDecoration(labelText: etichetta, isDense: true),
            child: Text(
              'Non nota: la tempestività risulterà "Non valutabile"',
              style: TextStyle(color: Colors.grey.shade700),
            ),
          )
        else
          campoData(context, controller, '$etichetta *'),
        Padding(
          padding: const EdgeInsets.only(left: 4),
          child: Text(
            aiuto,
            style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
          ),
        ),
        CheckboxListTile(
          title: const Text('Data non nota'),
          value: nonNota,
          onChanged: (v) => onNonNota(v ?? false),
          controlAffinity: ListTileControlAffinity.leading,
          contentPadding: EdgeInsets.zero,
          dense: true,
        ),
      ],
    );
  }

  Widget _date() {
    final pubblicazione = _dataPubblicazione;
    final adozione = _dataAdozione;
    final incoerenti =
        !_pubblicazioneNonNota &&
        !_adozioneNonNota &&
        pubblicazione != null &&
        adozione != null &&
        adozione.isAfter(pubblicazione);

    final campoAdozione = _campoDataConNonNota(
      controller: _dataAdozioneController,
      etichetta: 'Data di adozione dell\'atto',
      aiuto: 'Quando l\'atto è stato adottato o approvato.',
      nonNota: _adozioneNonNota,
      onNonNota: (v) => setState(() => _adozioneNonNota = v),
    );
    final campoPubblicazione = _campoDataConNonNota(
      controller: _dataPubblicazioneController,
      etichetta: 'Data di pubblicazione',
      aiuto: 'Quando è stato (o sarà) pubblicato in Amministrazione trasparente.',
      nonNota: _pubblicazioneNonNota,
      onNonNota: (v) => setState(() => _pubblicazioneNonNota = v),
    );

    return SezioneNumerata(
      numero: 3,
      titolo: 'Date',
      sottotitolo:
          'Servono a valutare la tempestività della pubblicazione rispetto all\'adozione.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          LayoutBuilder(
            builder: (context, vincoli) => vincoli.maxWidth < 560
                ? Column(children: [campoAdozione, campoPubblicazione])
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: campoAdozione),
                      const SizedBox(width: 16),
                      Expanded(child: campoPubblicazione),
                    ],
                  ),
          ),
          if (incoerenti)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
                children: [
                  Icon(Icons.warning_amber, color: Colors.orange.shade800),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'La data di adozione è successiva a quella di pubblicazione: verifica le date.',
                      style: TextStyle(color: Colors.orange.shade900),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _note() {
    return SezioneNumerata(
      numero: 4,
      titolo: 'Note per l\'analisi (facoltative)',
      sottotitolo:
          'Informazioni che il documento non riporta ma che cambiano la verifica.',
      child: TextField(
        controller: _noteController,
        minLines: 3,
        maxLines: 6,
        keyboardType: TextInputType.multiline,
        decoration: const InputDecoration(
          hintText:
              'es. "dirigente di vertice ex art. 19, co. 3 e 4"; "ente presente in Soldi pubblici"; '
              '"incarico a titolo gratuito"; "bilancio riferito all\'anno 2025"',
          alignLabelWithHint: true,
        ),
      ),
    );
  }

  Widget _azioni() {
    final mancanti = _mancanti;
    return BarraAzioni(
      etichetta: 'Avvia analisi',
      icona: Icons.play_arrow,
      onPressed: mancanti.isEmpty ? _uploadData : null,
      etichettaSecondaria: 'Nuova analisi',
      iconaSecondaria: Icons.restart_alt,
      onSecondaria: _nuovaAnalisi,
      inCorso: _isUploading,
      messaggioInCorso: 'Invio della richiesta…',
      avviso: mancanti.isEmpty
          ? null
          : 'Per avviare l\'analisi indica: ${mancanti.join(', ')}.',
      esito: _esito,
      esitoPositivo: _esitoPositivo,
    );
  }


  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Scaffold(
      body: SingleChildScrollView(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 900),
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _tipoDiAtto(),
                  _cosaAnalizzare(),
                  _date(),
                  _note(),
                  const SizedBox(height: 8),
                  _azioni(),
                  const SizedBox(height: 24),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
