import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../../api/api_client.dart';
import '../../util/scelta_file.dart';
import '../comuni.dart';

const _maxAllegati = 5; // per messaggio
const _intervalloStato = Duration(seconds: 2);
const _attesaMassima = Duration(minutes: 20); // una scansione lunga può richiedere minuti

/// Documento allegato al prossimo messaggio: lo converte in testo il RAG dell'ente, con un
/// lavoro di cui si chiede lo stato finché non è concluso.
class AllegatoAssistente {
  AllegatoAssistente(this.nome);

  final String nome;
  String? jobId;
  String stato = 'caricamento'; // poi queued, running, completed, failed
  String? testo;
  String? errore;

  bool get pronto => stato == 'completed';
  bool get fallito => stato == 'failed';
  bool get inCorso => !pronto && !fallito;
}

/// Conversazione con l'assistente: non si salva sul server, quindi l'intera conversazione
/// viene inviata a ogni richiesta. Sta fuori dalla pagina per restare cambiando voce del menu,
/// anche mentre si attende una risposta o la conversione di un allegato.
class ConversazioneAssistente extends ChangeNotifier {
  /// role e content (inviati al modello); per i messaggi dell'utente anche testo e allegati
  /// (nomi separati da a capo), mostrati nella chat al posto del contenuto completo.
  final messaggi = <Map<String, String>>[];
  final allegati = <AllegatoAssistente>[];
  bool inAttesa = false;
  String? errore;

  /// Se il modello è esterno all'ente; null finché non si sa.
  bool? llmEsterno;

  /// Formati che si possono allegare: nessuno se l'ente non è collegato al RAG.
  List<String> formati = const [];
  int maxMbAllegato = 20;

  /// Cambia con una nuova conversazione: la risposta a quella vecchia viene ignorata.
  int _turno = 0;
  bool _chiusa = false;

  bool get allegatiPronti => allegati.every((a) => a.pronto);

  void _aggiorna() {
    if (!_chiusa) notifyListeners();
  }

  Future<void> caricaInformazioni(ApiClient api) async {
    if (llmEsterno != null) return;
    try {
      final info = await api.get('/api/v1/assistente') as Map<String, dynamic>;
      llmEsterno = info['llm_esterno'] == true;
      formati = List<String>.from(info['formati_allegati'] as List? ?? const []);
      maxMbAllegato = (info['max_mb_allegato'] as num?)?.toInt() ?? maxMbAllegato;
    } catch (_) {
      llmEsterno = true; // nel dubbio l'avviso resta
    }
    _aggiorna();
  }

  /// Invia il file al server e segue la conversione; un errore resta sull'allegato.
  Future<void> allega(ApiClient api, FileScelto file) async {
    final a = AllegatoAssistente(file.name);
    allegati.add(a);
    _aggiorna();
    if (file.bytes.length > maxMbAllegato * 1024 * 1024) {
      _fallito(a, 'Il file supera i $maxMbAllegato MB');
      return;
    }
    try {
      final r = await api.postMultipartFiles('/api/v1/assistente/allegati',
          campi: {}, campoFile: 'file', files: [(file.name, file.bytes)]) as Map<String, dynamic>;
      a
        ..jobId = r['job_id'] as String
        ..stato = 'queued';
      _aggiorna();
      final limite = DateTime.now().add(_attesaMassima);
      while (a.inCorso && allegati.contains(a) && !_chiusa) {
        if (DateTime.now().isAfter(limite)) {
          _fallito(a, 'La conversione non è terminata in ${_attesaMassima.inMinutes} minuti');
          return;
        }
        await Future<void>.delayed(_intervalloStato);
        if (!allegati.contains(a) || _chiusa) return;
        final s = await api.get('/api/v1/assistente/allegati/${a.jobId}') as Map<String, dynamic>;
        a
          ..stato = s['stato'] as String
          ..testo = s['testo'] as String?
          ..errore = s['errore'] as String?;
        _aggiorna();
      }
    } catch (e) {
      _fallito(a, e.toString());
    }
  }

  void _fallito(AllegatoAssistente a, String errore) {
    a
      ..stato = 'failed'
      ..errore = errore;
    _aggiorna();
  }

  void togli(AllegatoAssistente a) {
    allegati.remove(a);
    _aggiorna();
  }

  /// Il messaggio porta con sé il testo dei documenti allegati, già convertiti.
  Future<void> invia(ApiClient api, String testo) async {
    final documenti = [
      for (final a in allegati)
        '--- Documento allegato: ${a.nome} ---\n${a.testo}\n--- Fine del documento: ${a.nome} ---',
    ];
    messaggi.add({
      'role': 'user',
      'content': [if (testo.isNotEmpty) testo, ...documenti].join('\n\n'),
      'testo': testo,
      if (allegati.isNotEmpty) 'allegati': allegati.map((a) => a.nome).join('\n'),
    });
    allegati.clear();
    await riprova(api);
  }

  Future<void> riprova(ApiClient api) async {
    final turno = ++_turno;
    inAttesa = true;
    errore = null;
    notifyListeners();
    try {
      final r = await api.post('/api/v1/assistente/messaggi', {
        'messaggi': [for (final m in messaggi) {'role': m['role'], 'content': m['content']}],
      }) as Map<String, dynamic>;
      if (turno != _turno || _chiusa) return;
      messaggi.add({'role': 'assistant', 'content': r['testo'] as String});
    } catch (e) {
      if (turno != _turno || _chiusa) return;
      errore = e.toString();
    }
    inAttesa = false;
    notifyListeners();
  }

  void nuova() {
    _turno++;
    messaggi.clear();
    allegati.clear();
    inAttesa = false;
    errore = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _chiusa = true; // eventuali risposte in arrivo vengono ignorate
    super.dispose();
  }
}

class AssistentePage extends StatefulWidget {
  const AssistentePage({super.key, required this.conversazione});

  final ConversazioneAssistente conversazione;

  @override
  State<AssistentePage> createState() => _AssistentePageState();
}

class _AssistentePageState extends State<AssistentePage> {
  final _testo = TextEditingController();
  final _scorrimento = ScrollController();
  late final _focus = FocusNode(onKeyEvent: _tasto);

  ConversazioneAssistente get _c => widget.conversazione;

  @override
  void initState() {
    super.initState();
    _c.addListener(_aggiornata);
    _c.caricaInformazioni(apiDi(context));
    WidgetsBinding.instance.addPostFrameCallback((_) => _inFondo());
  }

  @override
  void dispose() {
    _c.removeListener(_aggiornata);
    _testo.dispose();
    _scorrimento.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _aggiornata() {
    setState(() {});
    WidgetsBinding.instance.addPostFrameCallback((_) => _inFondo());
  }

  void _inFondo() {
    if (_scorrimento.hasClients) _scorrimento.jumpTo(_scorrimento.position.maxScrollExtent);
  }

  /// Invio manda il messaggio, Maiusc+Invio va a capo.
  KeyEventResult _tasto(FocusNode _, KeyEvent evento) {
    if (evento is! KeyDownEvent ||
        evento.logicalKey != LogicalKeyboardKey.enter ||
        HardwareKeyboard.instance.isShiftPressed) {
      return KeyEventResult.ignored;
    }
    _invia();
    return KeyEventResult.handled;
  }

  void _invia() {
    final testo = _testo.text.trim();
    if ((testo.isEmpty && _c.allegati.isEmpty) || _c.inAttesa) return;
    if (!_c.allegatiPronti) {
      mostraMessaggio(context, 'Attendi la conversione degli allegati, o togli quelli non riusciti');
      return;
    }
    _testo.clear();
    _c.invia(apiDi(context), testo);
    _focus.requestFocus();
  }

  Future<void> _allega() async {
    final scelti = await scegliFiles(_c.formati);
    if (scelti.isEmpty || !mounted) return;
    if (_c.allegati.length + scelti.length > _maxAllegati) {
      mostraErrore(context, 'Al massimo $_maxAllegati documenti per messaggio');
      return;
    }
    final api = apiDi(context);
    for (final f in scelti) {
      _c.allega(api, f);
    }
  }

  Widget _riquadro({required Widget child, required Color colore, bool aDestra = false}) => Align(
        alignment: aDestra ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 720),
          margin: const EdgeInsets.only(bottom: 12),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: colore, borderRadius: BorderRadius.circular(12)),
          child: child,
        ),
      );

  Widget _messaggio(Map<String, String> m, ColorScheme tema) {
    if (m['role'] == 'user') {
      final testo = m['testo'] ?? m['content']!;
      final allegati = m['allegati']?.split('\n') ?? const <String>[];
      return _riquadro(
        aDestra: true,
        colore: tema.primaryContainer,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          for (final nome in allegati)
            Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.description_outlined, size: 18),
              const SizedBox(width: 4),
              Flexible(child: Text(nome, style: const TextStyle(fontWeight: FontWeight.w600))),
            ]),
          if (testo.isNotEmpty) SelectableText(testo),
        ]),
      );
    }
    final testo = m['content']!;
    return _riquadro(
      colore: tema.surfaceContainerHighest,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // le immagini non si caricano: l'indirizzo lo sceglie il modello
        MarkdownBody(data: testo, selectable: true, imageBuilder: (_, _, _) => const SizedBox.shrink()),
        Align(
          alignment: Alignment.centerRight,
          child: IconButton(
            tooltip: 'Copia la risposta',
            icon: const Icon(Icons.copy, size: 18),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: testo));
              if (mounted) mostraMessaggio(context, 'Risposta copiata');
            },
          ),
        ),
      ]),
    );
  }

  Widget _allegato(AllegatoAssistente a, ColorScheme tema) {
    final caratteri = a.testo?.length ?? 0;
    final dettaglio = a.pronto
        ? '${caratteri.toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+$)'), (_) => '.')} caratteri'
        : a.fallito
            ? 'non riuscito'
            : 'in conversione…';
    final chip = InputChip(
      avatar: a.inCorso
          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
          : Icon(a.pronto ? Icons.description_outlined : Icons.error_outline,
              color: a.fallito ? tema.error : null),
      label: Text('${a.nome} · $dettaglio'),
      deleteButtonTooltipMessage: 'Togli',
      onDeleted: () => _c.togli(a),
    );
    return a.errore == null ? chip : Tooltip(message: a.errore!, child: chip);
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context).colorScheme;
    final allegaPossibile = _c.formati.isNotEmpty;
    final errori = [for (final a in _c.allegati) if (a.errore != null) '${a.nome}: ${a.errore}'];
    return Scaffold(
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: Row(children: [
            Expanded(
              child: Text(
                'Scrive e rivede testi, riassume, riformula. Non legge gli atti: verifica sempre ciò che propone.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            TextButton.icon(
              onPressed: _c.messaggi.isEmpty && _c.allegati.isEmpty && !_c.inAttesa ? null : _c.nuova,
              icon: const Icon(Icons.add_comment_outlined),
              label: const Text('Nuova conversazione'),
            ),
          ]),
        ),
        Expanded(
          child: ListView(
            controller: _scorrimento,
            padding: const EdgeInsets.all(16),
            children: [
              if (_c.llmEsterno == true)
                _riquadro(
                  colore: tema.tertiaryContainer,
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Icon(Icons.warning_amber, color: tema.onTertiaryContainer),
                    const SizedBox(width: 8),
                    const Flexible(
                      child: Text('Il testo che scrivi e quello dei documenti che alleghi vengono inviati a '
                          'un fornitore esterno all\'ente: non inserire né allegare dati personali.'),
                    ),
                  ]),
                ),
              for (final m in _c.messaggi) _messaggio(m, tema),
              if (_c.inAttesa)
                const Align(
                  alignment: Alignment.centerLeft,
                  child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()),
                ),
              if (_c.errore != null)
                _riquadro(
                  colore: tema.errorContainer,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(_c.errore!),
                    TextButton(onPressed: () => _c.riprova(apiDi(context)), child: const Text('Riprova')),
                  ]),
                ),
            ],
          ),
        ),
        if (_c.allegati.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Wrap(spacing: 8, runSpacing: 8, children: [for (final a in _c.allegati) _allegato(a, tema)]),
              for (final e in errori)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(e, style: TextStyle(color: tema.error)),
                ),
            ]),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            if (allegaPossibile)
              IconButton(
                tooltip: 'Allega documenti (${_c.formati.join(', ')}; al massimo ${_c.maxMbAllegato} MB)',
                onPressed: _c.inAttesa ? null : _allega,
                icon: const Icon(Icons.attach_file),
              ),
            Expanded(
              child: TextField(
                controller: _testo,
                focusNode: _focus,
                autofocus: true,
                minLines: 1,
                maxLines: 6,
                decoration: const InputDecoration(
                  hintText: 'Scrivi un messaggio o incolla un testo (Maiusc+Invio per andare a capo)',
                  border: OutlineInputBorder(),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              tooltip: 'Invia',
              onPressed: _c.inAttesa || !_c.allegatiPronti ? null : _invia,
              icon: const Icon(Icons.send),
            ),
          ]),
        ),
      ]),
    );
  }
}
