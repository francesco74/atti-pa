import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../api/api_client.dart';
import '../../comuni.dart';
import '../result_manager.dart';
import '../servizio.dart';
import '../forms/schema_form.dart';
import '../widgets/modulo.dart';
import '../widgets/precompila_da_fonte.dart';
import '../widgets/selettore_schema.dart';
import '../utils/error_dialog.dart';

/// Generazione dei documenti conformi agli schemi ANAC: un form per ogni
/// schema servito dall'API (common/trasparenza/schemi/*.yaml).
class PdfGeneratorTab extends StatefulWidget {
  const PdfGeneratorTab({super.key});

  @override
  State<PdfGeneratorTab> createState() => _PdfGeneratorTabState();
}

class _PdfGeneratorTabState extends State<PdfGeneratorTab>
    with AutomaticKeepAliveClientMixin {
  // La scheda resta in vita quando si passa alle altre: i dati inseriti
  // non vanno persi.
  @override
  bool get wantKeepAlive => true;

  List<Map<String, dynamic>> _schemi = [];
  bool _caricamentoSchemi = true;
  String? _erroreSchemi;
  Map<String, dynamic>? _schema;
  // Una nuova chiave per ogni schema scelto: il form riparte da zero.
  GlobalKey<SchemaFormState> _chiaveForm = GlobalKey();

  // Dati di un documento salvato riaperti dalla scheda dei risultati
  // ("Modifica i dati"): precompilano il form e il documento rigenerato
  // diventa una nuova versione di [_origine].
  Map<String, dynamic>? _datiIniziali;
  String? _origine;
  // Dati estratti con l'IA dal testo di un documento: da verificare.
  bool _estratti = false;
  List<String> _avvisiCaricamento = [];

  bool _isGenerating = false;
  // Estrazione dei dati da una pagina web o da documenti in corso.
  bool _estrazioneInCorso = false;
  String? _esito;
  bool _esitoPositivo = false;

  @override
  void initState() {
    super.initState();
    ResultManager.registraGeneratore(_riceviDati);
    _caricaSchemi();
  }

  @override
  void dispose() {
    ResultManager.registraGeneratore(null);
    super.dispose();
  }

  void _dimenticaOrigine() {
    _datiIniziali = null;
    _origine = null;
    _estratti = false;
    _avvisiCaricamento = [];
  }

  /// Carica nel form i dati in attesa (vedi ResultManager.modificaDati).
  /// Senza gli schemi viene richiamata al termine del loro caricamento.
  Future<void> _riceviDati() async {
    if (_schemi.isEmpty || !mounted) return;
    final richiesta = ResultManager.prendiDatiInAttesa();
    if (richiesta == null) return;
    final schema = _schemi
        .where((s) => s['id'] == richiesta.dati['pdf_type'])
        .firstOrNull;
    if (schema == null) {
      _mostraEsito(
        'Lo schema di "${richiesta.origine}" non è più disponibile: i dati non possono essere caricati.',
        positivo: false,
      );
      return;
    }
    await _caricaDati(richiesta, schema);
  }

  /// Ricrea il form con i dati indicati (dati salvati o estratti con l'IA).
  Future<void> _caricaDati(
    DatiDaModificare richiesta,
    Map<String, dynamic> schema,
  ) async {
    if (_chiaveForm.currentState?.haDati ?? false) {
      final conferma = await confermaPerditaDati(
        context,
        messaggio:
            'Per caricare i dati di "${richiesta.origine}" quelli inseriti nel modulo verranno cancellati.',
      );
      if (!conferma || !mounted) return;
    }
    setState(() {
      _schema = schema;
      _datiIniziali = richiesta.dati;
      _origine = richiesta.origine;
      _estratti = richiesta.estratti;
      _avvisiCaricamento = [...richiesta.avvisi];
      _chiaveForm = GlobalKey();
      _esito = null;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final avvisi = _chiaveForm.currentState?.avvisiCaricamento;
      if (mounted && avvisi != null && avvisi.isNotEmpty) {
        setState(() => _avvisiCaricamento.addAll(avvisi));
      }
    });
  }

  /// Estrae con l'IA i dati da una pagina web o da documenti e precompila
  /// il form dello schema scelto.
  Future<void> _precompila() async {
    final schema = _schema;
    if (schema == null) return;
    final fonte = await mostraDialogoFonte(
      context,
      schema: schema,
      idSezioneCorrente: _chiaveForm.currentState?.sezioneCorrente,
    );
    if (fonte == null || !mounted) return;
    setState(() {
      _estrazioneInCorso = true;
      _esito = null;
    });
    try {
      final risultato = await estraiDaFonte(apiDi(context), schema['id'] as String, fonte);
      if (!mounted) return;
      await _caricaDati(
        DatiDaModificare(
          (risultato['dati'] as Map).cast<String, dynamic>(),
          fonte.descrizione,
          estratti: true,
          avvisi: ((risultato['avvisi'] as List?) ?? const []).cast<String>(),
        ),
        schema,
      );
    } catch (e) {
      _mostraEsito(
        'Estrazione non riuscita: ${e.toString().replaceFirst('Exception: ', '')}.',
        positivo: false,
      );
    } finally {
      if (mounted) setState(() => _estrazioneInCorso = false);
    }
  }

  /// Nome proposto per la nuova versione di un documento salvato.
  String? get _nomeNuovaVersione {
    final origine = _origine;
    // Una scheda nata da dati estratti non è una versione dell'origine
    // (es. il report di un'analisi): il nome viene dal documento generato.
    if (origine == null || _estratti) return null;
    final base = origine.replaceFirst(
      RegExp(r' - aggiornato al \d{2}/\d{2}/\d{4}$'),
      '',
    );
    return '$base - aggiornato al ${DateFormat('dd/MM/yyyy').format(DateTime.now())}';
  }

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
      _riceviDati();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _caricamentoSchemi = false;
        _erroreSchemi =
            'Impossibile caricare i tipi di documento dal server ($e).';
      });
    }
  }

  Future<void> _scegliSchema() async {
    final scelta = await mostraSelettoreSchema(
      context,
      schemi: _schemi,
      titolo: 'Seleziona il documento da generare',
      idSchema: _schema?['id'] as String?,
    );
    if (scelta == null || !mounted || scelta.schema['id'] == _schema?['id']) {
      return;
    }
    if (_chiaveForm.currentState?.haDati ?? false) {
      final conferma = await confermaPerditaDati(
        context,
        messaggio:
            'Cambiando tipo di documento i dati inseriti verranno cancellati.',
      );
      if (!conferma || !mounted) return;
    }
    setState(() {
      _schema = scelta.schema;
      _dimenticaOrigine();
      _chiaveForm = GlobalKey();
      _esito = null;
    });
  }

  Future<void> _svuota() async {
    final form = _chiaveForm.currentState;
    if (form == null) return;
    if (form.haDati) {
      final conferma = await confermaPerditaDati(
        context,
        titolo: 'Svuota modulo',
        messaggio: 'Tutti i dati inseriti verranno cancellati.',
        conferma: 'Svuota',
      );
      if (!conferma || !mounted) return;
    }
    form.reset();
    setState(() {
      _dimenticaOrigine();
      _esito = null;
    });
  }

  void _mostraEsito(String messaggio, {required bool positivo}) {
    if (!mounted) return;
    setState(() {
      _esito = messaggio;
      _esitoPositivo = positivo;
    });
  }

  Future<void> _genera() async {
    final form = _chiaveForm.currentState;
    final schema = _schema;
    if (form == null || schema == null || _isGenerating) return;

    setState(() => _esito = null);
    final raccolti = await form.raccogli();
    if (!mounted) return;
    final dati = raccolti.dati;
    if (dati == null) {
      _mostraEsito(
        raccolti.errore ?? 'Controlla i dati inseriti.',
        positivo: false,
      );
      return;
    }

    setState(() => _isGenerating = true);
    try {
      final datiSchema = {'pdf_type': schema['id'], ...dati};
      final html = await ServizioTrasparenza(apiDi(context)).generaScheda(datiSchema);
      _mostraEsito(
        'Documento generato: è stato aperto nella scheda Risultati.',
        positivo: true,
      );
      // I dati accompagnano il documento: salvandolo si potranno
      // ricaricare nel form per modificarlo.
      ResultManager.showResultInNewTab(
        html,
        datiSchema: datiSchema,
        nomeProposto: _nomeNuovaVersione,
      );
    } on ApiException catch (e) {
      _mostraEsito('Il documento non è stato generato.', positivo: false);
      if (mounted) showErrorDialog(context, content: e.messaggio);
    } catch (e) {
      _mostraEsito(
        'Errore di connessione: verifica che il server sia raggiungibile ($e).',
        positivo: false,
      );
    } finally {
      if (mounted) setState(() => _isGenerating = false);
    }
  }

  Widget _tipoDiDocumento() {
    final schema = _schema;
    return SezioneNumerata(
      numero: 1,
      titolo: 'Tipo di documento',
      sottotitolo: 'Lo schema ANAC secondo cui generare il documento.',
      azione: schema == null
          ? null
          : IconButton(
              icon: const Icon(Icons.info_outline),
              tooltip: 'Dettagli normativi dello schema',
              onPressed: () => mostraInfoSchema(context, schema),
            ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: _schemi.isEmpty ? null : _scegliSchema,
            borderRadius: BorderRadius.circular(8),
            child: InputDecorator(
              decoration: const InputDecoration(
                labelText: 'Tipo di documento *',
                prefixIcon: Icon(Icons.article_outlined),
                suffixIcon: Icon(Icons.arrow_drop_down),
              ),
              child: Text(
                schema == null
                    ? 'Scegli il tipo di documento...'
                    : '${schema['titolo']} (${schema['riferimento']})',
                style: TextStyle(
                  color: schema == null ? Colors.black54 : Colors.black87,
                  height: 1.4,
                ),
              ),
            ),
          ),
          if (schema != null && !schemaAnac(schema))
            AvvisoSchemaNonAnac(schema: schema),
          if (schema != null) ...[
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                icon: const Icon(Icons.auto_fix_high),
                label: const Text('Precompila da pagina web o documento'),
                onPressed: _estrazioneInCorso || _isGenerating
                    ? null
                    : _precompila,
              ),
            ),
            if (_estrazioneInCorso) ...[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
              const SizedBox(height: 6),
              const Text(
                'Estrazione dei dati con l\'IA in corso: può richiedere qualche minuto...',
                style: TextStyle(fontSize: 13),
              ),
            ],
          ],
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
                    onPressed: () => _caricaSchemi(ricarica: true),
                    child: const Text('Riprova'),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _avvisoOrigine() {
    final colori = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colori.primaryContainer.withValues(alpha: 0.35),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colori.primaryContainer),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.edit_note, color: colori.primary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _estratti
                      ? 'Dati estratti automaticamente con l\'IA da «$_origine». Verificali tutti '
                            'prima di generare: i campi vuoti non sono stati trovati nel documento e '
                            'vanno completati a mano.'
                      : 'Stai modificando i dati di «$_origine». Generando, nella scheda Risultati '
                            'si aprirà una nuova versione del documento: quella salvata resta invariata.',
                ),
              ),
            ],
          ),
          for (final avviso in _avvisiCaricamento)
            Padding(
              padding: const EdgeInsets.only(top: 6, left: 32),
              child: Text(
                '• $avviso',
                style: TextStyle(fontSize: 13, color: Colors.orange.shade900),
              ),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final schema = _schema;
    return SingleChildScrollView(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _tipoDiDocumento(),
                if (_origine != null) _avvisoOrigine(),
                if (schema != null)
                  SchemaForm(
                    key: _chiaveForm,
                    schema: schema,
                    primoNumero: 2,
                    datiIniziali: _datiIniziali,
                  ),
                const SizedBox(height: 8),
                BarraAzioni(
                  etichetta: 'Genera documento',
                  icona: Icons.picture_as_pdf_outlined,
                  onPressed: schema == null || _estrazioneInCorso
                      ? null
                      : _genera,
                  etichettaSecondaria: 'Svuota modulo',
                  iconaSecondaria: Icons.restart_alt,
                  onSecondaria: schema == null ? null : _svuota,
                  inCorso: _isGenerating,
                  messaggioInCorso: 'Generazione del documento in corso...',
                  avviso: schema == null
                      ? 'Per iniziare scegli il tipo di documento.'
                      : null,
                  esito: _esito,
                  esitoPositivo: _esitoPositivo,
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
