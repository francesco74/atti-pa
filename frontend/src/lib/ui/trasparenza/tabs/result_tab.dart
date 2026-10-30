import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';

import '../../comuni.dart';
import '../browser.dart';
import '../result_manager.dart';
import '../servizio.dart';
import '../utils/html2document.dart';
import '../widgets/editor_documento.dart';

/// Risultati ed editor: mostra l'ultimo risultato di analisi o il documento
/// generato, permette di modificarlo, salvarlo, scaricarlo in PDF o Word e
/// gestire i documenti salvati (anche per comporre il verbale di validazione).
///
/// L'editor è un iframe: ogni elemento Flutter che gli si sovrappone (dialog,
/// menu, elenco a scomparsa) è avvolto in un PointerInterceptor, altrimenti
/// i clic finirebbero all'iframe.
class ResultTab extends StatefulWidget {
  // Ultimo risultato arrivato dalle altre schede.
  final NuovoRisultato? risultato;
  final bool showSidebar;
  // Incrementato quando la schermata principale cambia [showSidebar].
  final int sidebarTrigger;
  // Incrementato a ogni nuovo risultato dalle altre schede.
  final int risultatoTrigger;
  // Porta a un'altra scheda (0 = analisi IA, 1 = generazione documenti).
  final void Function(int scheda)? onApriScheda;

  const ResultTab({
    super.key,
    this.risultato,
    this.showSidebar = true,
    this.sidebarTrigger = 0,
    this.risultatoTrigger = 0,
    this.onApriScheda,
  });

  @override
  State<ResultTab> createState() => _ResultTabState();
}

/// Errore con un messaggio già pronto per l'utente.
class _Errore implements Exception {
  final String messaggio;
  _Errore(this.messaggio);

  @override
  String toString() => messaggio;
}

class _ResultTabState extends State<ResultTab>
    with AutomaticKeepAliveClientMixin {
  final ControlloEditor _editor = ControlloEditor();
  Key _chiaveEditor = UniqueKey();

  // --- Documento aperto ---
  String _html = '';
  // Contenuto dell'editor appena caricato (già normalizzato dall'editor):
  // serve a riconoscere le modifiche.
  String? _riferimento;
  bool _modificato = false;
  String? _docId;
  String _descrizione = '';
  String? _salvatoIl;
  String? _esito;
  bool _verbale = false;
  // Dati del form da cui è stata generata la scheda: con questi il documento
  // si può riaprire nel form di generazione ("Modifica i dati").
  Map<String, dynamic>? _datiSchema;
  // Nome proposto al primo salvataggio (es. nuova versione di un documento).
  String? _nomeProposto;

  bool _toolbarVisibile = true;
  // Un menu a comparsa è aperto: i clic sopra l'editor (un iframe) devono
  // arrivare a Flutter per chiuderlo (vedi build).
  bool _menuAperto = false;
  // null: elenco visibile sugli schermi larghi, nascosto su quelli stretti.
  bool? _elencoVisibile;
  // Operazione in corso (mostrata sotto l'intestazione).
  String? _operazione;

  // --- Documenti salvati ---
  List<Map<String, dynamic>> _documenti = [];
  bool _caricamentoElenco = false;
  String? _erroreElenco;
  final _ricercaController = TextEditingController();
  String? _filtroEsito;
  String _ordinaPer = 'date';
  bool _crescente = false;
  final Set<String> _selezionati = {};

  void Function()? _togliAvvisoUscita;

  // Salvataggio automatico dei documenti già salvati: parte qualche secondo
  // dopo l'ultima modifica. I documenti nuovi si salvano a mano la prima
  // volta, scegliendo il nome.
  static const _attesaSalvataggio = Duration(seconds: 3);
  Timer? _timerSalvataggio;
  bool _salvataggioInCorso = false;
  bool _erroreSalvataggio = false;
  // Cresce a ogni modifica: dice se l'utente ha scritto durante un salvataggio.
  int _versioneModifiche = 0;

  static const _esiti = [
    'Pubblicabile',
    'Pubblicabile provvisoriamente',
    'Non pubblicabile',
  ];

  @override
  bool get wantKeepAlive => true;

  /// Il contenuto è stato modificato nell'editor dopo l'apertura o l'ultimo
  /// salvataggio. Un risultato appena aperto e non toccato non conta: si
  /// rigenera o si riapre da "Analisi avviate".
  bool get _nonSalvato => _html.isNotEmpty && _modificato;

  @override
  void initState() {
    super.initState();
    _elencoVisibile = widget.showSidebar ? null : false;
    final risultato = widget.risultato;
    if (risultato != null && risultato.html.isNotEmpty) {
      _apri(
        risultato.html,
        datiSchema: risultato.datiSchema,
        nomeProposto: risultato.nomeProposto,
      );
    }
    ResultManager.modificheNonSalvate = () => _nonSalvato;
    ResultManager.salvaModifiche = _salvaAutomatico;
    // Chiudendo o ricaricando la pagina il browser chiede conferma (e si
    // prova comunque a salvare le modifiche di un documento già salvato).
    _togliAvvisoUscita = avvisoUscita(() {
      if (_docId != null && _modificato) _salvaAutomatico();
      return _nonSalvato;
    });
    _ricercaController.addListener(() => setState(() {}));
    _caricaElenco();
  }

  @override
  void didUpdateWidget(covariant ResultTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.sidebarTrigger != widget.sidebarTrigger) {
      _elencoVisibile = widget.showSidebar ? null : false;
    }
    if (oldWidget.risultatoTrigger != widget.risultatoTrigger) {
      final nuovo = widget.risultato;
      if (nuovo != null) {
        WidgetsBinding.instance.addPostFrameCallback((_) => _ricevi(nuovo));
      }
    }
  }

  @override
  void dispose() {
    _togliAvvisoUscita?.call();
    _timerSalvataggio?.cancel();
    ResultManager.modificheNonSalvate = null;
    ResultManager.salvaModifiche = null;
    _ricercaController.dispose();
    super.dispose();
  }

  // ---------------------------------------------------------------------------
  // Documento aperto
  // ---------------------------------------------------------------------------

  void _apri(
    String contenuto, {
    String? docId,
    String descrizione = '',
    String? salvatoIl,
    String? esito,
    bool verbale = false,
    Map<String, dynamic>? datiSchema,
    String? nomeProposto,
  }) {
    _timerSalvataggio?.cancel();
    setState(() {
      _erroreSalvataggio = false;
      _datiSchema = datiSchema;
      _nomeProposto = nomeProposto;
      _html = contenuto;
      _docId = docId;
      _descrizione = descrizione;
      _salvatoIl = salvatoIl;
      _esito = esito;
      _verbale = verbale;
      _modificato = false;
      _riferimento = null;
      _chiaveEditor = UniqueKey();
    });
  }

  void _chiudi() => _apri('');

  Future<String> _testoAttuale() async {
    if (_html.isEmpty) return '';
    try {
      return await _editor.testo();
    } catch (_) {
      return _html;
    }
  }

  /// Nuovo risultato dalle altre schede: se il documento aperto non è
  /// salvato si propone di salvarlo prima di sostituirlo.
  Future<void> _ricevi(NuovoRisultato risultato) async {
    if (!mounted) return;
    await _salvaAutomatico();
    if (_nonSalvato) {
      final scelta = await _chiediSalvataggio(
        'È arrivato un nuovo risultato, ma il documento aperto ha modifiche non salvate.',
        annullabile: false,
      );
      if (scelta == _Scelta.salva) await _salva();
    }
    _apri(
      risultato.html,
      datiSchema: risultato.datiSchema,
      nomeProposto: risultato.nomeProposto,
    );
  }

  /// Prima di sostituire il documento aperto: true se si può procedere.
  Future<bool> _puoiSostituire() async {
    // Un documento già salvato si aggiorna da solo; si chiede solo se il
    // salvataggio non riesce o se il documento è nuovo.
    await _salvaAutomatico();
    if (!_nonSalvato) return true;
    final scelta = await _chiediSalvataggio(
      'Il documento aperto ha modifiche non salvate.',
    );
    switch (scelta) {
      case _Scelta.salva:
        return _salva();
      case _Scelta.scarta:
        return true;
      case _Scelta.annulla:
        return false;
    }
  }

  // ---------------------------------------------------------------------------
  // Chiamate al backend
  // ---------------------------------------------------------------------------

  ServizioTrasparenza get _servizio => ServizioTrasparenza(apiDi(context));

  void _menu(bool aperto) {
    if (mounted && _menuAperto != aperto) setState(() => _menuAperto = aperto);
  }

  void _avviso(String messaggio, {bool errore = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(messaggio),
        backgroundColor: errore ? Theme.of(context).colorScheme.error : null,
      ),
    );
  }

  /// Esegue un'operazione mostrando l'avanzamento; gli errori diventano avvisi.
  Future<bool> _esegui(String descrizione, Future<void> Function() fn) async {
    setState(() => _operazione = descrizione);
    try {
      await fn();
      return true;
    } catch (e) {
      _avviso(e.toString(), errore: true);
      return false;
    } finally {
      if (mounted) setState(() => _operazione = null);
    }
  }

  // ---------------------------------------------------------------------------
  // Documenti salvati
  // ---------------------------------------------------------------------------

  Future<void> _caricaElenco() async {
    setState(() {
      _caricamentoElenco = true;
      _erroreElenco = null;
    });
    try {
      final documenti = await _servizio.documenti();
      if (!mounted) return;
      setState(() {
        _documenti = documenti;
        _ordina();
        _selezionati.retainWhere((id) => _documenti.any((d) => d['id'] == id));
      });
    } catch (e) {
      if (mounted) setState(() => _erroreElenco = e.toString());
    } finally {
      if (mounted) setState(() => _caricamentoElenco = false);
    }
  }

  static String _dataDocumento(Map<String, dynamic> d) =>
      (d['updated_at'] ?? d['created_at'] ?? '').toString();

  static DateTime? _leggiData(String testo) {
    if (testo.isEmpty) return null;
    final iso = DateTime.tryParse(testo);
    if (iso != null) return iso.toLocal();
    try {
      // Formato di Flask (es. "Wed, 13 May 2026 14:49:50 GMT"): il server
      // invia già l'ora locale, quindi non si converte.
      return DateFormat(
        "EEE, d MMM yyyy HH:mm:ss 'GMT'",
        'en_US',
      ).parse(testo, true);
    } catch (_) {
      return null;
    }
  }

  static String _formattaData(String? testo) {
    final data = _leggiData(testo ?? '');
    return data == null ? '' : DateFormat('dd/MM/yyyy HH:mm').format(data);
  }

  void _ordina() {
    _documenti.sort((a, b) {
      final int confronto;
      if (_ordinaPer == 'name') {
        confronto = (a['descrizione'] ?? '').toString().toLowerCase().compareTo(
          (b['descrizione'] ?? '').toString().toLowerCase(),
        );
      } else {
        final zero = DateTime.fromMillisecondsSinceEpoch(0);
        confronto = (_leggiData(_dataDocumento(a)) ?? zero).compareTo(
          _leggiData(_dataDocumento(b)) ?? zero,
        );
      }
      return _crescente ? confronto : -confronto;
    });
  }

  List<Map<String, dynamic>> get _documentiVisibili {
    final parole = _ricercaController.text
        .toLowerCase()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty);
    return _documenti.where((d) {
      final descrizione = '${d['descrizione'] ?? ''} ${d['autore'] ?? ''}'.toLowerCase();
      if (!parole.every(descrizione.contains)) return false;
      return _filtroEsito == null || d['esito'] == _filtroEsito;
    }).toList();
  }

  // Sugli schermi stretti l'elenco si sovrappone all'editor: dopo la scelta
  // di un documento si richiude.
  bool get _elencoStretto => MediaQuery.sizeOf(context).width < 900;

  Future<void> _apriDocumento(Map<String, dynamic> documento) async {
    final id = documento['id'] as String?;
    if (id == null) return;
    if (id != _docId || _modificato) {
      if (!await _puoiSostituire()) return;
      await _esegui('Apertura del documento...', () async {
        final r = await _servizio.documento(id);
        final proprio = r['proprio'] == true;
        // Il documento di un altro utente (lo vede l'amministratore) non si modifica:
        // le modifiche si salvano come nuovo documento.
        _apri(
          (r['html'] ?? '').toString(),
          docId: proprio ? id : null,
          descrizione: proprio ? (r['descrizione'] ?? '').toString() : '',
          nomeProposto: proprio ? null : 'Copia di ${r['descrizione']}',
          salvatoIl: _dataDocumento(r),
          esito: r['esito'] as String?,
          verbale: r['tipo'] == 'VERBALE',
          datiSchema: (r['dati_schema'] as Map?)?.cast<String, dynamic>(),
        );
        if (!proprio) _avviso('Documento di ${r['autore']}: le modifiche si salvano come nuovo documento.');
      });
    }
    if (mounted && _elencoStretto) setState(() => _elencoVisibile = false);
  }

  Future<void> _rinomina(Map<String, dynamic> documento) async {
    final attuale = (documento['descrizione'] ?? '').toString();
    final nome = await _chiediNome('Rinomina documento', attuale);
    if (nome == null || nome == attuale) return;
    final id = documento['id'] as String;
    final ok = await _esegui('Rinomina in corso...', () async {
      // Senza i dati del form il backend lascia invariati quelli salvati.
      final salvato = await _servizio.documento(id);
      await _servizio.salva(id: id, descrizione: nome, html: salvato['html'] as String);
      if (id == _docId) setState(() => _descrizione = nome);
    });
    if (ok) _caricaElenco();
  }

  Future<void> _duplica(Map<String, dynamic> documento) async {
    final nome = await _chiediNome(
      'Duplica documento',
      'Copia di ${documento['descrizione'] ?? ''}',
    );
    if (nome == null) return;
    final ok = await _esegui('Duplicazione in corso...', () async {
      final originale = await _servizio.documento(documento['id'] as String);
      await _servizio.salva(
        descrizione: nome,
        html: originale['html'] as String,
        datiSchema: (originale['dati_schema'] as Map?)?.cast<String, dynamic>(),
      );
    });
    if (ok) {
      _avviso('Documento duplicato.');
      _caricaElenco();
    }
  }

  Future<void> _elimina(Map<String, dynamic> documento) async {
    final conferma = await showDialog<bool>(
      context: context,
      builder: (context) => PointerInterceptor(
        child: AlertDialog(
          title: const Text('Elimina documento'),
          content: Text(
            'Vuoi eliminare "${documento['descrizione'] ?? 'Senza titolo'}"?\n'
            'L\'operazione non può essere annullata.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Annulla'),
            ),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: Theme.of(context).colorScheme.error,
              ),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Elimina'),
            ),
          ],
        ),
      ),
    );
    if (conferma != true) return;
    final id = documento['id'] as String;
    final ok = await _esegui('Eliminazione in corso...', () => _servizio.elimina(id));
    if (!ok) return;
    _selezionati.remove(id);
    if (id == _docId) _chiudi();
    _avviso('Documento eliminato.');
    _caricaElenco();
  }

  Future<void> _creaVerbale() async {
    // Nell'ordine in cui compaiono nell'elenco.
    final ids = [
      for (final d in _documenti)
        if (_selezionati.contains(d['id'])) d['id'] as String,
    ];
    if (ids.isEmpty || !await _puoiSostituire()) return;
    await _esegui('Creazione del verbale...', () async {
      _apri(await _servizio.verbale(ids), verbale: true);
      setState(() => _selezionati.clear());
    });
    if (mounted && _elencoStretto) setState(() => _elencoVisibile = false);
  }

  // ---------------------------------------------------------------------------
  // Salvataggio e download
  // ---------------------------------------------------------------------------

  /// Nome proposto per un documento mai salvato: il primo titolo del
  /// contenuto oppure il tipo di documento e la data.
  String _nomeSuggerito() {
    if (_nomeProposto != null && _nomeProposto!.isNotEmpty) {
      return _nomeProposto!;
    }
    final titolo = RegExp(
      r'<h[12][^>]*>(.*?)</h[12]>',
      caseSensitive: false,
      dotAll: true,
    ).firstMatch(_html);
    if (titolo != null) {
      final testo = titolo
          .group(1)!
          .replaceAll(RegExp(r'<[^>]+>'), ' ')
          .replaceAll(RegExp(r'\s+'), ' ')
          .trim();
      if (testo.isNotEmpty) {
        return testo.length > 120 ? testo.substring(0, 120) : testo;
      }
    }
    final oggi = DateFormat('dd/MM/yyyy').format(DateTime.now());
    return _verbale ? 'Verbale di validazione del $oggi' : 'Risultato del $oggi';
  }

  String _nomeFile() {
    final base = (_descrizione.isNotEmpty ? _descrizione : _nomeSuggerito())
        .replaceAll(RegExp(r'[^A-Za-z0-9àèéìòùÀÈÉÌÒÙ _-]'), ' ')
        .trim()
        .replaceAll(RegExp(r'\s+'), '_');
    final corto = base.length > 60 ? base.substring(0, 60) : base;
    final data = DateFormat('dd-MM-yyyy').format(DateTime.now());
    return '${corto.isEmpty ? 'documento' : corto}_$data';
  }

  /// Salva il documento: aggiorna quello aperto oppure, se è nuovo o se si
  /// chiede [comeNuovo], ne crea uno chiedendo il nome. True se salvato.
  void _programmaSalvataggio() {
    _timerSalvataggio?.cancel();
    _timerSalvataggio = Timer(_attesaSalvataggio, _salvaAutomatico);
  }

  /// Salva le modifiche di un documento già salvato, senza chiedere nulla.
  /// Restituisce true se non resta niente da salvare.
  Future<bool> _salvaAutomatico() async {
    _timerSalvataggio?.cancel();
    while (_salvataggioInCorso) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    final id = _docId;
    if (id == null || !_modificato || !mounted) return !_nonSalvato;
    final versione = _versioneModifiche;
    setState(() => _salvataggioInCorso = true);
    try {
      final contenuto = await _testoAttuale();
      final dati = await _servizio.salva(id: id, descrizione: _descrizione, html: contenuto, datiSchema: _datiSchema);
      if (!mounted || _docId != id) return true;
      setState(() {
        _esito = dati['esito'] as String?;
        _salvatoIl = DateTime.now().toIso8601String();
        _riferimento = contenuto;
        _erroreSalvataggio = false;
        // Se l'utente ha scritto durante il salvataggio, resta da salvare.
        if (_versioneModifiche == versione) _modificato = false;
      });
      if (_modificato) _programmaSalvataggio();
      _caricaElenco();
      return !_modificato;
    } catch (e) {
      if (mounted) setState(() => _erroreSalvataggio = true);
      return false;
    } finally {
      if (mounted) setState(() => _salvataggioInCorso = false);
    }
  }

  Future<bool> _salva({bool comeNuovo = false}) async {
    // Con "Salva come nuovo" le modifiche in attesa vanno nella copia: il
    // documento di partenza resta com'era all'ultimo salvataggio.
    _timerSalvataggio?.cancel();
    final contenuto = await _testoAttuale();
    if (contenuto.isEmpty) return false;
    var descrizione = _descrizione;
    if (comeNuovo || _docId == null) {
      final nome = await _chiediNome(
        comeNuovo ? 'Salva come nuovo documento' : 'Salva documento',
        comeNuovo && _descrizione.isNotEmpty
            ? 'Copia di $_descrizione'
            : (_descrizione.isNotEmpty ? _descrizione : _nomeSuggerito()),
      );
      if (nome == null) return false;
      descrizione = nome;
    }
    final aggiorna = !comeNuovo && _docId != null;
    final ok = await _esegui('Salvataggio in corso...', () async {
      final dati = await _servizio.salva(
        id: aggiorna ? _docId : null,
        descrizione: descrizione,
        html: contenuto,
        datiSchema: _datiSchema,
      );
      if (!mounted) return;
      setState(() {
        _docId = dati['id'] as String;
        _descrizione = descrizione;
        _esito = dati['esito'] as String?;
        _salvatoIl = DateTime.now().toIso8601String();
        _html = contenuto;
        _riferimento = contenuto;
        _modificato = false;
        _verbale = false;
        _nomeProposto = null;
      });
    });
    if (ok) {
      _avviso(aggiorna ? 'Modifiche salvate.' : 'Documento salvato.');
      _caricaElenco();
    }
    return ok;
  }

  /// Riapre nel form di generazione i dati da cui è nata la scheda.
  void _modificaDati() {
    final dati = _datiSchema;
    if (dati == null) return;
    ResultManager.modificaDati(
      dati,
      _descrizione.isNotEmpty ? _descrizione : _nomeSuggerito(),
    );
  }

  Future<void> _scarica(String formato) async {
    final contenuto = await _testoAttuale();
    if (contenuto.isEmpty) return;
    final pdf = formato == 'pdf';
    final nome = '${_nomeFile()}.${pdf ? 'pdf' : 'docx'}';
    final ok = await _esegui(
      pdf ? 'Creazione del PDF...' : 'Creazione del documento Word...',
      () async {
        try {
          pdf
              ? await scaricaComePdf(context, contenuto, nome)
              : await scaricaComeDocx(context, contenuto, nome);
        } on Exception catch (e) {
          throw _Errore(
            'Download non riuscito: ${e.toString().replaceFirst('Exception: ', '')}.',
          );
        }
      },
    );
    if (ok) _avviso('Scaricato $nome');
  }

  // ---------------------------------------------------------------------------
  // Dialog
  // ---------------------------------------------------------------------------

  Future<String?> _chiediNome(String titolo, String iniziale) {
    final controller = TextEditingController(text: iniziale);
    String? errore;
    return showDialog<String>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, aggiorna) {
          void conferma() {
            final nome = controller.text.trim();
            if (nome.isEmpty) {
              aggiorna(() => errore = 'Inserisci un nome.');
            } else if (nome.length > 255) {
              aggiorna(() => errore = 'Massimo 255 caratteri.');
            } else {
              Navigator.pop(context, nome);
            }
          }

          return PointerInterceptor(
            child: AlertDialog(
              title: Text(titolo),
              content: SizedBox(
                width: 480,
                child: TextField(
                  controller: controller,
                  autofocus: true,
                  decoration: InputDecoration(
                    labelText: 'Nome del documento',
                    errorText: errore,
                  ),
                  onSubmitted: (_) => conferma(),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Annulla'),
                ),
                FilledButton(onPressed: conferma, child: const Text('Salva')),
              ],
            ),
          );
        },
      ),
    );
  }

  Future<_Scelta> _chiediSalvataggio(
    String messaggio, {
    bool annullabile = true,
  }) async {
    final scelta = await showDialog<_Scelta>(
      context: context,
      barrierDismissible: annullabile,
      builder: (context) => PointerInterceptor(
        child: AlertDialog(
          title: const Text('Modifiche non salvate'),
          content: Text('$messaggio\nVuoi salvarlo?'),
          actions: [
            if (annullabile)
              TextButton(
                onPressed: () => Navigator.pop(context, _Scelta.annulla),
                child: const Text('Annulla'),
              ),
            TextButton(
              onPressed: () => Navigator.pop(context, _Scelta.scarta),
              child: const Text('Non salvare'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, _Scelta.salva),
              child: const Text('Salva'),
            ),
          ],
        ),
      ),
    );
    return scelta ?? (annullabile ? _Scelta.annulla : _Scelta.scarta);
  }

  // ---------------------------------------------------------------------------
  // Impaginazione
  // ---------------------------------------------------------------------------

  static Color _coloreEsito(String esito) => switch (esito) {
    'Pubblicabile' => Colors.green.shade700,
    'Pubblicabile provvisoriamente' => Colors.orange.shade800,
    _ => Colors.red.shade700,
  };

  Widget _etichetta(String testo, Color colore, {bool piccola = false}) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: piccola ? 6 : 8,
        vertical: piccola ? 1 : 3,
      ),
      decoration: BoxDecoration(
        color: colore.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colore.withValues(alpha: 0.5)),
      ),
      child: Text(
        testo,
        style: TextStyle(
          color: colore,
          fontSize: piccola ? 11 : 12,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  /// Voce di menu che copre tutta la riga, così anche sopra l'editor i clic
  /// arrivano al menu.
  PopupMenuItem<String> _voceMenu(
    String valore,
    IconData icona,
    String testo, {
    Color? colore,
  }) {
    return PopupMenuItem<String>(
      value: valore,
      padding: EdgeInsets.zero,
      child: PointerInterceptor(
        child: Container(
          height: 48,
          padding: const EdgeInsets.symmetric(horizontal: 16),
          alignment: Alignment.centerLeft,
          child: Row(
            children: [
              Icon(icona, size: 20, color: colore),
              const SizedBox(width: 12),
              Text(testo, style: TextStyle(color: colore)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _elenco() {
    final colori = Theme.of(context).colorScheme;
    final visibili = _documentiVisibili;
    final idVisibili = visibili.map((d) => d['id'] as String).toSet();
    final selezionatiVisibili = idVisibili.intersection(_selezionati).length;
    final conEsito = _documenti.any((d) => d['esito'] != null);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 4, 0),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'Documenti salvati',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                ),
              ),
              PopupMenuButton<String>(
                tooltip: 'Ordina',
                icon: const Icon(Icons.sort, size: 20),
                onOpened: () => _menu(true),
                onCanceled: () => _menu(false),
                onSelected: (criterio) => setState(() {
                  _menuAperto = false;
                  if (_ordinaPer == criterio) {
                    _crescente = !_crescente;
                  } else {
                    _ordinaPer = criterio;
                    _crescente = criterio == 'name';
                  }
                  _ordina();
                }),
                itemBuilder: (context) => [
                  _voceMenu(
                    'date',
                    Icons.schedule,
                    'Per data${_ordinaPer == 'date' ? (_crescente ? ' ↑' : ' ↓') : ''}',
                  ),
                  _voceMenu(
                    'name',
                    Icons.sort_by_alpha,
                    'Per nome${_ordinaPer == 'name' ? (_crescente ? ' A-Z' : ' Z-A') : ''}',
                  ),
                ],
              ),
              IconButton(
                icon: const Icon(Icons.refresh, size: 20),
                tooltip: 'Aggiorna',
                onPressed: _caricamentoElenco ? null : _caricaElenco,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: TextField(
            controller: _ricercaController,
            decoration: InputDecoration(
              hintText: 'Cerca per nome',
              prefixIcon: const Icon(Icons.search, size: 20),
              isDense: true,
              border: const OutlineInputBorder(),
              suffixIcon: _ricercaController.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear, size: 18),
                      tooltip: 'Cancella ricerca',
                      onPressed: _ricercaController.clear,
                    ),
            ),
          ),
        ),
        if (conEsito)
          SizedBox(
            height: 40,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                for (final esito in [null, ..._esiti])
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                      label: Text(
                        esito == null
                            ? 'Tutti'
                            : esito == 'Pubblicabile provvisoriamente'
                            ? 'Provvisori'
                            : esito,
                        style: const TextStyle(fontSize: 12),
                      ),
                      visualDensity: VisualDensity.compact,
                      selected: _filtroEsito == esito,
                      onSelected: (_) => setState(() => _filtroEsito = esito),
                    ),
                  ),
              ],
            ),
          ),
        if (visibili.isNotEmpty)
          CheckboxListTile(
            dense: true,
            tristate: true,
            controlAffinity: ListTileControlAffinity.leading,
            contentPadding: const EdgeInsets.symmetric(horizontal: 4),
            value: selezionatiVisibili == 0
                ? false
                : selezionatiVisibili == idVisibili.length
                ? true
                : null,
            title: Text(
              _selezionati.isEmpty
                  ? 'Seleziona per il verbale'
                  : '${_selezionati.length} selezionati',
              style: const TextStyle(fontSize: 13),
            ),
            onChanged: (_) => setState(() {
              if (selezionatiVisibili == idVisibili.length) {
                _selezionati.removeAll(idVisibili);
              } else {
                _selezionati.addAll(idVisibili);
              }
            }),
          ),
        const Divider(height: 1),
        Expanded(child: _contenutoElenco(visibili, colori)),
        const Divider(height: 1),
        Padding(
          padding: const EdgeInsets.all(12),
          child: Tooltip(
            message:
                'Unisce i documenti selezionati, nell\'ordine dell\'elenco, al verbale di validazione',
            child: FilledButton.tonalIcon(
              icon: const Icon(Icons.assignment_outlined),
              label: Text(
                _selezionati.isEmpty
                    ? 'Crea verbale'
                    : 'Crea verbale (${_selezionati.length})',
              ),
              onPressed: _selezionati.isEmpty || _operazione != null
                  ? null
                  : _creaVerbale,
            ),
          ),
        ),
      ],
    );
  }

  Widget _contenutoElenco(
    List<Map<String, dynamic>> visibili,
    ColorScheme colori,
  ) {
    if (_caricamentoElenco && _documenti.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_erroreElenco != null) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.cloud_off, color: colori.error),
            const SizedBox(height: 8),
            Text(
              'Impossibile caricare i documenti.\n$_erroreElenco',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: _caricaElenco,
              child: const Text('Riprova'),
            ),
          ],
        ),
      );
    }
    if (visibili.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            _documenti.isEmpty
                ? 'Nessun documento salvato.'
                : 'Nessun documento corrisponde alla ricerca.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey.shade700),
          ),
        ),
      );
    }
    return ListView.separated(
      itemCount: visibili.length,
      separatorBuilder: (_, _) => const Divider(height: 1),
      itemBuilder: (context, index) {
        final documento = visibili[index];
        final id = documento['id'] as String;
        final proprio = documento['proprio'] != false;
        final esito = documento['esito'] as String?;
        final data = _formattaData(_dataDocumento(documento));
        final aperto = id == _docId;
        return ListTile(
          dense: true,
          selected: aperto,
          selectedTileColor: colori.primaryContainer.withValues(alpha: 0.5),
          contentPadding: const EdgeInsets.only(left: 4, right: 0),
          leading: Checkbox(
            value: _selezionati.contains(id),
            onChanged: (v) => setState(
              () => v == true ? _selezionati.add(id) : _selezionati.remove(id),
            ),
          ),
          title: Text(
            (documento['descrizione'] ?? 'Senza titolo').toString(),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 14,
              fontWeight: aperto ? FontWeight.bold : FontWeight.normal,
            ),
          ),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Wrap(
              spacing: 6,
              runSpacing: 2,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                if (data.isNotEmpty)
                  Text(data, style: const TextStyle(fontSize: 12)),
                if (!proprio)
                  Text('di ${documento['autore']}', style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic)),
                if (documento['tipo'] == 'SCHEDA')
                  Tooltip(
                    message: 'Generato da modulo: i dati si possono modificare',
                    child: Icon(
                      Icons.dataset_outlined,
                      size: 14,
                      color: Colors.grey.shade700,
                    ),
                  ),
                if (esito != null)
                  _etichetta(
                    esito == 'Pubblicabile provvisoriamente'
                        ? 'Provvisorio'
                        : esito,
                    _coloreEsito(esito),
                    piccola: true,
                  ),
              ],
            ),
          ),
          onTap: _operazione == null ? () => _apriDocumento(documento) : null,
          trailing: PopupMenuButton<String>(
            tooltip: 'Azioni',
            enabled: _operazione == null,
            onOpened: () => _menu(true),
            onCanceled: () => _menu(false),
            onSelected: (azione) {
              _menu(false);
              switch (azione) {
                case 'rinomina':
                  _rinomina(documento);
                case 'duplica':
                  _duplica(documento);
                default:
                  _elimina(documento);
              }
            },
            itemBuilder: (context) => [
              if (proprio) _voceMenu('rinomina', Icons.edit_outlined, 'Rinomina'),
              _voceMenu('duplica', Icons.copy_outlined, 'Duplica'),
              if (proprio)
                _voceMenu(
                  'elimina',
                  Icons.delete_outline,
                  'Elimina',
                  colore: colori.error,
                ),
            ],
          ),
        );
      },
    );
  }

  Widget _intestazione(bool elencoVisibile) {
    final colori = Theme.of(context).colorScheme;
    final titolo = _descrizione.isNotEmpty
        ? _descrizione
        : (_verbale ? 'Nuovo verbale di validazione' : 'Nuovo risultato');
    final String stato;
    if (_docId == null) {
      stato = 'Non ancora salvato';
    } else if (_salvataggioInCorso) {
      stato = 'Salvataggio in corso...';
    } else if (_erroreSalvataggio) {
      stato = 'Salvataggio automatico non riuscito';
    } else if (_modificato) {
      stato = 'Modifiche in salvataggio automatico...';
    } else {
      stato = 'Salvato il ${_formattaData(_salvatoIl)}';
    }
    return Container(
      color: colori.surfaceContainerLow,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      child: Row(
        children: [
          IconButton(
            icon: Icon(elencoVisibile ? Icons.menu_open : Icons.menu),
            tooltip: elencoVisibile
                ? 'Nascondi documenti salvati'
                : 'Mostra documenti salvati',
            onPressed: () =>
                setState(() => _elencoVisibile = !elencoVisibile),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: _html.isEmpty
                ? const Text(
                    'Nessun documento aperto',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        titolo,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 15,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Wrap(
                        spacing: 8,
                        runSpacing: 4,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Text(
                            stato,
                            style: TextStyle(
                              fontSize: 12,
                              color: Colors.grey.shade700,
                            ),
                          ),
                          if (_docId == null)
                            _etichetta(
                              'Da salvare',
                              Colors.orange.shade800,
                              piccola: true,
                            ),
                          if (_erroreSalvataggio && !_salvataggioInCorso)
                            InkWell(
                              onTap: _salvaAutomatico,
                              child: _etichetta(
                                'Riprova a salvare',
                                Theme.of(context).colorScheme.error,
                                piccola: true,
                              ),
                            ),
                          if (_esito != null)
                            _etichetta(
                              _esito!,
                              _coloreEsito(_esito!),
                              piccola: true,
                            ),
                        ],
                      ),
                    ],
                  ),
          ),
          if (_html.isNotEmpty)
            IconButton(
              icon: Icon(
                _toolbarVisibile ? Icons.format_clear : Icons.text_format,
              ),
              tooltip: _toolbarVisibile
                  ? 'Nascondi la barra di formattazione'
                  : 'Mostra la barra di formattazione',
              onPressed: () =>
                  setState(() => _toolbarVisibile = !_toolbarVisibile),
            ),
        ],
      ),
    );
  }

  Widget _editorDocumento() => EditorDocumento(
        key: _chiaveEditor,
        controllo: _editor,
        contenuto: _html,
        barraVisibile: _toolbarVisibile,
        onCaricato: (contenuto) => _riferimento = contenuto,
        onModifica: (contenuto) {
          if (_riferimento == null || !mounted) return;
          // Confronto sempre con il riferimento: annullando le modifiche il
          // documento torna "salvato".
          final modificato = contenuto != _riferimento;
          _versioneModifiche++;
          if (modificato != _modificato) {
            setState(() => _modificato = modificato);
          }
          if (modificato && _docId != null) _programmaSalvataggio();
        },
      );

  Widget _pulsanti() {
    final libero = _operazione == null;
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerLow,
        border: Border(top: BorderSide(color: Colors.grey.shade300)),
      ),
      child: Wrap(
        alignment: WrapAlignment.end,
        spacing: 8,
        runSpacing: 8,
        children: [
          PopupMenuButton<String>(
            tooltip: 'Azioni sul documento',
            enabled: libero,
            onOpened: () => _menu(true),
            onCanceled: () => _menu(false),
            onSelected: (azione) {
              _menu(false);
              switch (azione) {
                case 'modifica':
                  _modificaDati();
                case 'copia':
                  _salva(comeNuovo: true);
                default:
                  _scarica(azione);
              }
            },
            itemBuilder: (context) => [
              if (_datiSchema != null) ...[
                _voceMenu('modifica', Icons.edit_note, 'Modifica i dati della scheda'),
                const PopupMenuDivider(),
              ],
              _voceMenu('pdf', Icons.picture_as_pdf_outlined, 'Scarica PDF'),
              _voceMenu('docx', Icons.description_outlined, 'Scarica Word (.docx)'),
              if (_docId != null) ...[
                const PopupMenuDivider(),
                _voceMenu('copia', Icons.copy_all_outlined, 'Salva come nuovo documento'),
              ],
            ],
            child: Container(
              height: 40,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              decoration: BoxDecoration(
                border: Border.all(
                  color: libero ? Colors.grey.shade500 : Colors.grey.shade300,
                ),
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.more_horiz, size: 18),
                  SizedBox(width: 8),
                  Text('Azioni'),
                  Icon(Icons.arrow_drop_down),
                ],
              ),
            ),
          ),
          // I documenti già salvati si salvano da soli: il pulsante serve
          // solo la prima volta, per scegliere il nome.
          if (_docId == null)
            FilledButton.icon(
              icon: const Icon(Icons.save_outlined),
              label: const Text('Salva'),
              onPressed: libero ? _salva : null,
            ),
        ],
      ),
    );
  }

  Widget _nessunDocumento() {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.edit_note, size: 64, color: Colors.grey.shade500),
              const SizedBox(height: 16),
              Text(
                'Nessun documento aperto',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              Text(
                'Qui compaiono i risultati delle analisi e i documenti generati, '
                'pronti da correggere, salvare e scaricare. '
                'Puoi anche riaprire un documento salvato.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.grey.shade700),
              ),
              const SizedBox(height: 24),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (widget.onApriScheda != null) ...[
                    FilledButton.tonalIcon(
                      icon: const Icon(Icons.analytics_outlined),
                      label: const Text('Nuova analisi'),
                      onPressed: () => widget.onApriScheda!(0),
                    ),
                    FilledButton.tonalIcon(
                      icon: const Icon(Icons.article_outlined),
                      label: const Text('Genera un documento'),
                      onPressed: () => widget.onApriScheda!(1),
                    ),
                  ],
                  OutlinedButton.icon(
                    icon: const Icon(Icons.folder_open_outlined),
                    label: const Text('Apri un documento salvato'),
                    onPressed: () => setState(() => _elencoVisibile = true),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => ResultManager.daSalvare.value = _nonSalvato,
    );
    return Stack(
      fit: StackFit.expand,
      children: [
        _contenuto(),
        // Con un menu aperto i clic sopra l'editor (iframe) andrebbero
        // all'iframe e il menu non si chiuderebbe: questo strato trasparente
        // li restituisce a Flutter, che chiude il menu.
        if (_menuAperto)
          Positioned.fill(child: PointerInterceptor(child: const SizedBox.expand())),
      ],
    );
  }

  Widget _contenuto() {
    return LayoutBuilder(
      builder: (context, vincoli) {
        final stretta = vincoli.maxWidth < 900;
        final elencoVisibile = _elencoVisibile ?? !stretta;

        final principale = Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _intestazione(elencoVisibile),
            if (_operazione != null) ...[
              const LinearProgressIndicator(),
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text(
                  _operazione!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            ],
            Expanded(
              child: _html.isEmpty
                  ? _nessunDocumento()
                  : _editorDocumento(),
            ),
            if (_html.isNotEmpty) _pulsanti(),
          ],
        );

        if (!stretta) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (elencoVisibile)
                Container(
                  width: 300,
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surface,
                    border: Border(
                      right: BorderSide(color: Colors.grey.shade300),
                    ),
                  ),
                  child: _elenco(),
                ),
              Expanded(child: principale),
            ],
          );
        }

        // Schermi stretti: l'elenco si apre sopra l'editor.
        return Stack(
          children: [
            Positioned.fill(child: principale),
            if (elencoVisibile) ...[
              Positioned.fill(
                child: PointerInterceptor(
                  child: GestureDetector(
                    onTap: () => setState(() => _elencoVisibile = false),
                    child: const ColoredBox(color: Colors.black26),
                  ),
                ),
              ),
              Positioned(
                left: 0,
                top: 0,
                bottom: 0,
                width: math.min(320, vincoli.maxWidth * 0.85),
                child: PointerInterceptor(
                  child: Material(elevation: 8, child: _elenco()),
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}

enum _Scelta { salva, scarta, annulla }
