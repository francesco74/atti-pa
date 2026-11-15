import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../../api/api_client.dart';
import '../../util/scelta_file.dart';
import '../comuni.dart';

const _intervalloStato = Duration(seconds: 2);
const _attesaMassima = Duration(minutes: 20); // una scansione lunga può richiedere minuti
const _intestazioneSessione = 'X-Assistente-Sessione';
const _larghezzaPannello = 340.0;

String _migliaia(int n) => n.toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+$)'), (_) => '.');

/// Documento della conversazione: sta nella sessione del RAG dell'ente, che lo converte, lo
/// indicizza e ne cerca i passaggi a ogni domanda. Lo stato si segue finché non è pronto.
class DocumentoSessione {
  DocumentoSessione(this.nome);

  final String nome;
  String? id;
  String stato = 'caricamento'; // poi in_coda, conversione, indicizzazione, pronto, errore
  int? token;
  int? parti;
  String? errore;
  bool selezionato = true;

  bool get pronto => stato == 'pronto';
  bool get fallito => stato == 'errore';
  bool get inCorso => !pronto && !fallito;

  String get descrizioneStato => switch (stato) {
        'caricamento' => 'invio…',
        'in_coda' => 'in coda…',
        'conversione' => 'in conversione…',
        'indicizzazione' => 'in indicizzazione…',
        'pronto' => [
            if (parti != null) parti == 1 ? '1 parte' : '$parti parti',
            if (token != null) '${_migliaia(token!)} token',
          ].join(' · '),
        _ => 'non riuscito',
      };

  void aggiorna(Map<String, dynamic> d) {
    id = d['id'] as String? ?? id;
    stato = d['stato'] as String? ?? stato;
    token = (d['token'] as num?)?.toInt() ?? token;
    parti = (d['parti'] as num?)?.toInt() ?? parti;
    errore = d['errore'] as String?;
  }
}

/// Conversazione con l'assistente: non si salva sul server, quindi l'intera conversazione
/// viene inviata a ogni richiesta. Sta fuori dalla pagina per restare cambiando voce del menu,
/// anche mentre si attende una risposta o l'elaborazione di un documento. I documenti stanno
/// in una sessione del RAG, identificata da un token che l'API firma per questo utente: si
/// perdono ricaricando la pagina o con "Nuova conversazione".
class ConversazioneAssistente extends ChangeNotifier {
  /// role e content (inviati al modello). Per i messaggi dell'utente anche `documenti` (nomi
  /// dei documenti su cui si chiede, separati da a capo) e `ids` (i loro id, separati da
  /// virgola), e per le azioni `azione` (riassunto, confronto, estrazione) e `istruzioni`;
  /// per le risposte `fonti` (righe "documento|parte").
  final messaggi = <Map<String, String>>[];
  final documenti = <DocumentoSessione>[];
  bool inAttesa = false;
  String? errore;

  /// Azione in corso (Riassumi, Confronta, Estrai): id e avanzamento (chiamate all'LLM).
  String? azioneId;
  int azioneFatti = 0;
  int azioneTotale = 0;

  /// Se il modello è esterno all'ente; null finché non si sa.
  bool? llmEsterno;

  /// Formati dei documenti: nessuno se l'ente non è collegato al RAG.
  List<String> formati = const [];
  int maxMbDocumento = 20;
  int? maxDocumenti;
  int? maxToken;

  String? _sessione;
  Future<String>? _creazione;

  /// Cambia con una nuova conversazione: le risposte e gli stati di quella vecchia si ignorano.
  int _turno = 0;
  bool _chiusa = false;

  List<DocumentoSessione> get selezionati => [for (final d in documenti) if (d.pronto && d.selezionato) d];
  int get tokenUsati => documenti.where((d) => !d.fallito).fold(0, (n, d) => n + (d.token ?? 0));
  int get documentiAttivi => documenti.where((d) => !d.fallito).length;
  bool get documentiInCorso => documenti.any((d) => d.inCorso);

  Map<String, String> get _intestazioni => {_intestazioneSessione: ?_sessione};

  void _aggiorna() {
    if (!_chiusa) notifyListeners();
  }

  Future<void> caricaInformazioni(ApiClient api) async {
    if (llmEsterno != null) return;
    try {
      final info = await api.get('/api/v1/assistente') as Map<String, dynamic>;
      llmEsterno = info['llm_esterno'] == true;
      formati = List<String>.from(info['formati_documenti'] as List? ?? const []);
      maxMbDocumento = (info['max_mb_documento'] as num?)?.toInt() ?? maxMbDocumento;
    } catch (_) {
      llmEsterno = true; // nel dubbio l'avviso resta
    }
    _aggiorna();
  }

  /// Token della sessione, creata al primo documento.
  Future<String> _token(ApiClient api) {
    if (_sessione != null) return Future.value(_sessione);
    return _creazione ??= () async {
      try {
        final r = await api.post('/api/v1/assistente/sessione') as Map<String, dynamic>;
        final limiti = r['limiti'] as Map<String, dynamic>? ?? const {};
        maxDocumenti = (limiti['max_documenti'] as num?)?.toInt();
        maxToken = (limiti['max_token'] as num?)?.toInt();
        return _sessione = r['sessione'] as String;
      } finally {
        _creazione = null;
      }
    }();
  }

  /// La sessione non c'è più nel RAG (scaduta): i documenti sono persi.
  void _sessioneScaduta() {
    _sessione = null;
    for (final d in documenti) {
      if (!d.fallito) {
        d
          ..stato = 'errore'
          ..errore = 'Sessione scaduta: carica di nuovo il documento';
      }
    }
  }

  /// Invia il file al RAG (tramite l'API) e ne segue l'elaborazione; un errore resta sul documento.
  Future<void> carica(ApiClient api, FileScelto file) async {
    final turno = _turno;
    final d = DocumentoSessione(file.name);
    documenti.add(d);
    _aggiorna();
    if (file.bytes.length > maxMbDocumento * 1024 * 1024) {
      _fallito(d, 'Il file supera i $maxMbDocumento MB');
      return;
    }
    bool attivo() => turno == _turno && documenti.contains(d) && !_chiusa;
    try {
      await _token(api);
      if (!attivo()) return;
      final r = await api.postMultipart('/api/v1/assistente/sessione/documenti',
          campi: {}, campoFile: 'file', bytes: file.bytes, nomeFile: file.name, intestazioni: _intestazioni);
      d.aggiorna(r as Map<String, dynamic>);
      _aggiorna();
      final limite = DateTime.now().add(_attesaMassima);
      while (d.inCorso && attivo()) {
        if (DateTime.now().isAfter(limite)) {
          _fallito(d, 'L\'elaborazione non è terminata in ${_attesaMassima.inMinutes} minuti');
          return;
        }
        await Future<void>.delayed(_intervalloStato);
        if (!attivo()) return;
        final s = await api.get('/api/v1/assistente/sessione/documenti/${d.id}', intestazioni: _intestazioni);
        d.aggiorna(s as Map<String, dynamic>);
        _aggiorna();
      }
    } on ApiException catch (e) {
      if (!attivo()) return;
      if (e.status == 404 && d.id != null) {
        _sessioneScaduta();
        _aggiorna();
      } else {
        _fallito(d, e.messaggio);
      }
    } catch (e) {
      if (attivo()) _fallito(d, e.toString());
    }
  }

  void _fallito(DocumentoSessione d, String errore) {
    d
      ..stato = 'errore'
      ..errore = errore;
    _aggiorna();
  }

  /// Toglie il documento dalla conversazione e dal RAG.
  void togli(ApiClient api, DocumentoSessione d) {
    documenti.remove(d);
    _aggiorna();
    if (d.id != null && _sessione != null && !d.fallito) {
      api.delete('/api/v1/assistente/sessione/documenti/${d.id}', null, _intestazioni).catchError((_) {});
    }
  }

  void seleziona(DocumentoSessione d, bool valore) {
    d.selezionato = valore;
    _aggiorna();
  }

  /// Con documenti selezionati la domanda riguarda quelli: risponde dai loro passaggi.
  Future<void> invia(ApiClient api, String testo) async {
    final scelti = selezionati;
    messaggi.add({
      'role': 'user',
      'content': testo,
      if (scelti.isNotEmpty) 'documenti': scelti.map((d) => d.nome).join('\n'),
      if (scelti.isNotEmpty) 'ids': scelti.map((d) => d.id!).join(','),
    });
    await riprova(api);
  }

  Future<void> riprova(ApiClient api) async {
    if (messaggi.last['azione'] != null) return _eseguiAzione(api);
    final turno = ++_turno;
    inAttesa = true;
    errore = null;
    notifyListeners();
    final ids = messaggi.last['ids']?.split(',') ?? const <String>[];
    try {
      final r = await api.post(
        '/api/v1/assistente/messaggi',
        {
          'messaggi': [for (final m in messaggi) {'role': m['role'], 'content': m['content']}],
          if (ids.isNotEmpty) 'documenti': ids,
        },
        ids.isNotEmpty ? _intestazioni : null,
      ) as Map<String, dynamic>;
      if (turno != _turno || _chiusa) return;
      final fonti = [
        for (final f in (r['fonti'] as List? ?? const []).cast<Map<String, dynamic>>()) '${f['documento']}|${f['parte']}',
      ];
      messaggi.add({'role': 'assistant', 'content': r['testo'] as String, if (fonti.isNotEmpty) 'fonti': fonti.join('\n')});
    } on ApiException catch (e) {
      if (turno != _turno || _chiusa) return;
      if (e.status == 404 && ids.isNotEmpty) _sessioneScaduta();
      errore = e.messaggio;
    } catch (e) {
      if (turno != _turno || _chiusa) return;
      errore = e.toString();
    }
    inAttesa = false;
    _aggiorna();
  }

  static const nomiAzioni = {'riassunto': 'Riassumi', 'confronto': 'Confronta', 'estrazione': 'Estrai'};

  /// Riassumi, Confronta o Estrai sui documenti selezionati: lavoro del worker, che legge i
  /// documenti per intero a blocchi; il risultato diventa una risposta dell'assistente.
  Future<void> azione(ApiClient api, String tipo, {String istruzioni = ''}) async {
    final scelti = selezionati;
    if (scelti.isEmpty || inAttesa) return;
    final nomi = scelti.map((d) => d.nome).join(', ');
    messaggi.add({
      'role': 'user',
      'content': '${nomiAzioni[tipo]}: $nomi${istruzioni.isNotEmpty ? ' — $istruzioni' : ''}',
      'documenti': scelti.map((d) => d.nome).join('\n'),
      'ids': scelti.map((d) => d.id!).join(','),
      'azione': tipo,
      'istruzioni': istruzioni,
    });
    await _eseguiAzione(api);
  }

  Future<void> _eseguiAzione(ApiClient api) async {
    final m = messaggi.last;
    final turno = ++_turno;
    inAttesa = true;
    errore = null;
    azioneFatti = azioneTotale = 0;
    notifyListeners();
    bool attivo() => turno == _turno && !_chiusa;
    try {
      final r = await api.post('/api/v1/assistente/azioni', {
        'tipo': m['azione'],
        'documenti': m['ids']!.split(','),
        'istruzioni': m['istruzioni'] ?? '',
      }, _intestazioni) as Map<String, dynamic>;
      if (!attivo()) return;
      azioneId = r['id'] as String;
      final limite = DateTime.now().add(const Duration(hours: 2));
      while (attivo()) {
        await Future<void>.delayed(_intervalloStato);
        if (!attivo() || azioneId == null) return;
        final s = await api.get('/api/v1/assistente/azioni/$azioneId') as Map<String, dynamic>;
        if (!attivo()) return;
        final avanzamento = s['avanzamento'] as Map<String, dynamic>? ?? const {};
        azioneFatti = (avanzamento['fatti'] as num?)?.toInt() ?? 0;
        azioneTotale = (avanzamento['totale'] as num?)?.toInt() ?? 0;
        if (s['stato'] == 'completata') {
          messaggi.add({'role': 'assistant', 'content': s['testo'] as String? ?? ''});
          break;
        }
        if (s['stato'] == 'errore') {
          errore = s['errore'] as String? ?? 'Azione non riuscita';
          break;
        }
        if (DateTime.now().isAfter(limite)) {
          errore = 'L\'azione non è terminata in due ore';
          break;
        }
        _aggiorna();
      }
    } on ApiException catch (e) {
      if (!attivo()) return;
      if (e.status == 404 && azioneId == null) _sessioneScaduta();
      errore = e.messaggio;
    } catch (e) {
      if (!attivo()) return;
      errore = e.toString();
    }
    azioneId = null;
    inAttesa = false;
    _aggiorna();
  }

  /// Ferma l'azione in corso: il worker si ferma al passo successivo.
  void annullaAzione(ApiClient api) {
    final id = azioneId;
    if (id == null) return;
    azioneId = null;
    api.delete('/api/v1/assistente/azioni/$id').catchError((_) {});
    if (messaggi.isNotEmpty && messaggi.last['azione'] != null) messaggi.removeLast();
    _turno++;
    inAttesa = false;
    _aggiorna();
  }

  /// Nuova conversazione: la sessione dei documenti si chiude e il RAG li cancella subito.
  void nuova(ApiClient api) {
    _turno++;
    annullaAzione(api);
    if (_sessione != null) {
      api.delete('/api/v1/assistente/sessione', null, _intestazioni).catchError((_) {});
    }
    _sessione = null;
    messaggi.clear();
    documenti.clear();
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
    if (testo.isEmpty || _c.inAttesa) return;
    _testo.clear();
    _c.invia(apiDi(context), testo);
    _focus.requestFocus();
  }

  Future<void> _carica() async {
    final scelti = await scegliFiles(_c.formati);
    if (scelti.isEmpty || !mounted) return;
    final massimo = _c.maxDocumenti;
    if (massimo != null && _c.documentiAttivi + scelti.length > massimo) {
      mostraErrore(context, 'Al massimo $massimo documenti per conversazione');
      return;
    }
    final api = apiDi(context);
    for (final f in scelti) {
      _c.carica(api, f);
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

  /// Fonti di una risposta raggruppate per documento: "Delibera.pdf (parti 3, 1)".
  Widget _fonti(String righe, ColorScheme tema) {
    final perDocumento = <String, List<String>>{};
    for (final r in righe.split('\n')) {
      final i = r.lastIndexOf('|');
      perDocumento.putIfAbsent(r.substring(0, i), () => []).add(r.substring(i + 1));
    }
    final testo = [
      for (final MapEntry(key: nome, value: parti) in perDocumento.entries)
        '$nome (${parti.length == 1 ? 'parte' : 'parti'} ${parti.join(', ')})',
    ].join('; ');
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Text('Passaggi consultati: $testo',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: tema.onSurfaceVariant)),
    );
  }

  Widget _messaggio(Map<String, String> m, ColorScheme tema) {
    if (m['role'] == 'user') {
      // nelle azioni i nomi dei documenti sono già nel testo del messaggio
      final documenti = m['azione'] != null ? const <String>[] : m['documenti']?.split('\n') ?? const <String>[];
      return _riquadro(
        aDestra: true,
        colore: tema.primaryContainer,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          if (documenti.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.description_outlined, size: 16),
                const SizedBox(width: 4),
                Flexible(
                  child: Text(documenti.join(', '),
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600)),
                ),
              ]),
            ),
          SelectableText(m['content']!),
        ]),
      );
    }
    final testo = m['content']!;
    return _riquadro(
      colore: tema.surfaceContainerHighest,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // le immagini non si caricano: l'indirizzo lo sceglie il modello
        MarkdownBody(data: testo, selectable: true, imageBuilder: (_, _, _) => const SizedBox.shrink()),
        if (m['fonti'] != null) _fonti(m['fonti']!, tema),
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

  /// Pannello dei documenti: a lato su schermo largo, dal basso sul telefono.
  Widget _pannello(ColorScheme tema) {
    final testi = Theme.of(context).textTheme;
    final maxToken = _c.maxToken;
    final maxDocumenti = _c.maxDocumenti;
    return ListenableBuilder(
      listenable: _c,
      builder: (context, _) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
          child: Row(children: [
            Expanded(child: Text('Documenti', style: testi.titleMedium)),
            FilledButton.tonalIcon(
              onPressed: _c.inAttesa ? null : _carica,
              icon: const Icon(Icons.upload_file),
              label: const Text('Carica'),
            ),
          ]),
        ),
        if (maxToken != null && _c.documenti.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              LinearProgressIndicator(value: (_c.tokenUsati / maxToken).clamp(0.0, 1.0)),
              const SizedBox(height: 4),
              Text(
                '${_migliaia(_c.tokenUsati)} di ${_migliaia(maxToken)} token'
                '${maxDocumenti != null ? ' · ${_c.documentiAttivi} di $maxDocumenti documenti' : ''}',
                style: testi.bodySmall,
              ),
            ]),
          ),
        Expanded(
          child: _c.documenti.isEmpty
              ? Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(
                    'Carica delibere, determine, leggi o altri documenti (${_c.formati.join(', ')}; al massimo '
                    '${_c.maxMbDocumento} MB l\'uno) e fai domande su quelli selezionati: le risposte citano '
                    'le parti dei documenti da cui vengono.',
                    style: testi.bodySmall,
                  ),
                )
              : ListView(children: [
                  for (final d in _c.documenti)
                    ListTile(
                      dense: true,
                      leading: d.inCorso
                          ? const SizedBox(
                              width: 24, height: 24, child: Padding(padding: EdgeInsets.all(3), child: CircularProgressIndicator(strokeWidth: 2)))
                          : d.fallito
                              ? Icon(Icons.error_outline, color: tema.error)
                              : Checkbox(
                                  value: d.selezionato,
                                  onChanged: (v) => _c.seleziona(d, v ?? false),
                                ),
                      title: Text(d.nome, maxLines: 2, overflow: TextOverflow.ellipsis),
                      subtitle: Text(d.fallito ? (d.errore ?? 'non riuscito') : d.descrizioneStato,
                          style: d.fallito ? TextStyle(color: tema.error) : null),
                      trailing: IconButton(
                        tooltip: 'Togli',
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () => _c.togli(apiDi(context), d),
                      ),
                      onTap: d.pronto ? () => _c.seleziona(d, !d.selezionato) : null,
                    ),
                ]),
        ),
        if (_c.documenti.any((d) => d.pronto))
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              OutlinedButton.icon(
                onPressed: _c.inAttesa || _c.selezionati.isEmpty ? null : () => _c.azione(apiDi(context), 'riassunto'),
                icon: const Icon(Icons.short_text),
                label: const Text('Riassumi'),
              ),
              Tooltip(
                message: 'Seleziona almeno due documenti',
                child: OutlinedButton.icon(
                  onPressed:
                      _c.inAttesa || _c.selezionati.length < 2 ? null : () => _c.azione(apiDi(context), 'confronto'),
                  icon: const Icon(Icons.compare_arrows),
                  label: const Text('Confronta'),
                ),
              ),
              OutlinedButton.icon(
                onPressed: _c.inAttesa || _c.selezionati.isEmpty ? null : _estrai,
                icon: const Icon(Icons.table_rows_outlined),
                label: const Text('Estrai…'),
              ),
            ]),
          ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            'Le domande usano solo i documenti selezionati. I documenti restano fino a "Nuova '
            'conversazione", al ricaricamento della pagina o dopo due ore senza uso.',
            style: testi.bodySmall?.copyWith(color: tema.onSurfaceVariant),
          ),
        ),
      ]),
    );
  }

  /// Cosa estrarre: scelte rapide o testo libero.
  Future<void> _estrai() async {
    const scelte = ['le scadenze e i termini', 'gli importi', 'gli obblighi e gli adempimenti', 'i soggetti coinvolti'];
    final campo = TextEditingController();
    final istruzioni = await showDialog<String>(
      context: context,
      builder: (contesto) => AlertDialog(
        title: const Text('Cosa estrarre dai documenti selezionati?'),
        content: SizedBox(
          width: 480,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final s in scelte) ActionChip(label: Text(s), onPressed: () => Navigator.pop(contesto, s)),
            ]),
            const SizedBox(height: 16),
            TextField(
              controller: campo,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Altro (es. le norme citate)', border: OutlineInputBorder()),
              onSubmitted: (v) => Navigator.pop(contesto, v.trim()),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(contesto), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(contesto, campo.text.trim()), child: const Text('Estrai')),
        ],
      ),
    );
    campo.dispose();
    if (istruzioni == null || istruzioni.isEmpty || !mounted) return;
    _c.azione(apiDi(context), 'estrazione', istruzioni: istruzioni);
  }

  /// Avanzamento di un'azione: chiamate all'LLM fatte su quelle previste.
  Widget _avanzamentoAzione(ColorScheme tema) {
    final totale = _c.azioneTotale;
    final tipo = _c.messaggi.isNotEmpty ? _c.messaggi.last['azione'] : null;
    final nome = switch (tipo) { 'riassunto' => 'Riassunto', 'confronto' => 'Confronto', _ => 'Estrazione' };
    return _riquadro(
      colore: tema.surfaceContainerHighest,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(totale == 0
            ? '$nome: lettura dei documenti…'
            : '$nome in corso: passo ${_c.azioneFatti} di $totale'),
        const SizedBox(height: 8),
        LinearProgressIndicator(value: totale == 0 ? null : (_c.azioneFatti / totale).clamp(0.0, 1.0)),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(onPressed: () => _c.annullaAzione(apiDi(context)), child: const Text('Annulla')),
        ),
      ]),
    );
  }

  void _apriPannello(ColorScheme tema) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => SizedBox(height: MediaQuery.of(context).size.height * 0.7, child: _pannello(tema)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context).colorScheme;
    final conDocumenti = _c.formati.isNotEmpty;
    final largo = MediaQuery.of(context).size.width >= 1000;
    final scelti = _c.selezionati.length;
    // telefono: la descrizione su una riga a sé, i pulsanti sotto con le etichette corte
    final stretto = spazioStretto(context, MediaQuery.sizeOf(context).width);
    final descrizione = Text(
      'Scrive e rivede testi, riassume, risponde sui documenti che carichi. Non legge gli '
      'atti dell\'ente: verifica sempre ciò che propone.',
      style: Theme.of(context).textTheme.bodySmall,
    );
    final pulsanti = [
      if (conDocumenti && !largo)
        TextButton.icon(
          onPressed: () => _apriPannello(tema),
          icon: const Icon(Icons.folder_open_outlined),
          label: Text('Documenti (${_c.documenti.length})'),
        ),
      TextButton.icon(
        onPressed: _c.messaggi.isEmpty && _c.documenti.isEmpty && !_c.inAttesa ? null : () => _c.nuova(apiDi(context)),
        icon: const Icon(Icons.add_comment_outlined),
        label: Text(stretto ? 'Nuova' : 'Nuova conversazione'),
      ),
    ];
    final chat = Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: stretto
            ? Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                descrizione,
                Wrap(alignment: WrapAlignment.end, children: pulsanti),
              ])
            : Row(children: [Expanded(child: descrizione), ...pulsanti]),
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
                    child: Text('Il testo che scrivi e i passaggi dei documenti che carichi vengono inviati a '
                        'un fornitore esterno all\'ente: non inserire né caricare dati personali.'),
                  ),
                ]),
              ),
            for (final m in _c.messaggi) _messaggio(m, tema),
            if (_c.inAttesa && _c.messaggi.isNotEmpty && _c.messaggi.last['azione'] != null)
              _avanzamentoAzione(tema)
            else if (_c.inAttesa)
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
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(
            child: TextField(
              controller: _testo,
              focusNode: _focus,
              autofocus: true,
              minLines: 1,
              maxLines: 6,
              decoration: InputDecoration(
                // sul telefono non c'è Maiusc+Invio: il suggerimento resta su una riga
                hintText: (scelti > 0
                        ? 'Domanda su ${scelti == 1 ? 'il documento selezionato' : 'i $scelti documenti selezionati'}'
                        : 'Scrivi un messaggio o incolla un testo') +
                    (stretto ? '' : ' (Maiusc+Invio per andare a capo)'),
                border: const OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            tooltip: 'Invia',
            onPressed: _c.inAttesa ? null : _invia,
            icon: const Icon(Icons.send),
          ),
        ]),
      ),
    ]);
    return Scaffold(
      body: conDocumenti && largo
          ? Row(children: [
              Expanded(child: chat),
              const VerticalDivider(width: 1),
              SizedBox(width: _larghezzaPannello, child: _pannello(tema)),
            ])
          : chat,
    );
  }
}
