import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../../api/api_client.dart';
import '../../../util/scelta_file.dart';
import '../../comuni.dart' show SceltaLink, documentiPredefiniti, formatiDocumentiCollegati, linkPredefiniti;
import '../servizio.dart';
import 'selettore_schema.dart' show maiuscola;

/// Precompilazione del form di una scheda a partire dalla fonte originale
/// (pagina web o documenti): il worker la legge con le stesse conversioni
/// dell'analisi e ne estrae i dati con l'IA (POST /api/v1/trasparenza/estrazioni).

class DocumentoFonte {
  final String nome;
  final Uint8List bytes;

  const DocumentoFonte(this.nome, this.bytes);
}

class FontePrecompilazione {
  // Controllo (sezione) da precompilare; null per gli schemi con una sezione.
  final String? idControllo;
  final String url;
  final bool analizzaDocumenti;
  final int maxDocumenti;
  final bool seguiLink;
  final int maxLink;
  final List<DocumentoFonte> documenti;

  const FontePrecompilazione({
    this.idControllo,
    this.url = '',
    this.analizzaDocumenti = false,
    this.maxDocumenti = documentiPredefiniti,
    this.seguiLink = false,
    this.maxLink = linkPredefiniti,
    this.documenti = const [],
  });

  /// Descrizione della fonte, mostrata nel modulo precompilato.
  String get descrizione => url.isNotEmpty
      ? url
      : documenti.map((d) => d.nome).join(', ');
}


bool _urlValido(String testo) {
  final uri = Uri.tryParse(testo);
  return testo.length <= 2048 &&
      uri != null &&
      (uri.scheme == 'http' || uri.scheme == 'https') &&
      uri.host.contains('.');
}

/// Chiede la sezione da precompilare e la fonte (pagina web o documenti).
Future<FontePrecompilazione?> mostraDialogoFonte(
  BuildContext context, {
  required Map<String, dynamic> schema,
  String? idSezioneCorrente,
}) {
  return showDialog<FontePrecompilazione>(
    context: context,
    builder: (_) =>
        _DialogoFonte(schema: schema, idSezioneCorrente: idSezioneCorrente),
  );
}

/// Esegue l'estrazione: restituisce {dati, avvisi} o lancia un'eccezione con
/// un messaggio per l'utente.
Future<Map<String, dynamic>> estraiDaFonte(
  ApiClient api,
  String idSchema,
  FontePrecompilazione fonte,
) async {
  final servizio = ServizioTrasparenza(api);
  final web = fonte.url.isNotEmpty;
  final lavoro = await servizio.avviaEstrazione(
    {
      'schema_id': idSchema,
      'variante': fonte.idControllo,
      if (web) ...{'url': fonte.url, 'analizza_documenti': fonte.analizzaDocumenti, 'max_documenti': fonte.maxDocumenti, 'segui_link': fonte.seguiLink, 'max_link': fonte.maxLink},
    },
    web ? const [] : [for (final d in fonte.documenti) (d.nome, d.bytes)],
  );
  return servizio.attendi(lavoro['id'] as String);
}

enum _Tipo { web, documenti }

class _DialogoFonte extends StatefulWidget {
  final Map<String, dynamic> schema;
  final String? idSezioneCorrente;

  const _DialogoFonte({required this.schema, this.idSezioneCorrente});

  @override
  State<_DialogoFonte> createState() => _DialogoFonteState();
}

class _DialogoFonteState extends State<_DialogoFonte> {
  final _urlController = TextEditingController();
  _Tipo _tipo = _Tipo.web;
  bool _analizzaDocumenti = false;
  int _maxDocumenti = documentiPredefiniti;
  bool _seguiLink = false;
  int _maxLink = linkPredefiniti;
  final List<DocumentoFonte> _documenti = [];
  String? _idControllo;

  // Negli schemi con più sezioni si precompila una sezione alla volta.
  List<Map<String, dynamic>> get _controlli => widget.schema['solo_varianti'] == true
      ? ((widget.schema['audit'] as List?) ?? const [])
            .cast<Map<String, dynamic>>()
      : const [];

  @override
  void initState() {
    super.initState();
    _urlController.addListener(() => setState(() {}));
    final corrente = widget.idSezioneCorrente;
    if (corrente != null) {
      _idControllo = _controlli
          .where((c) => (c['sezioni'] as List).contains(corrente))
          .map((c) => c['id'] as String)
          .firstOrNull;
    }
  }

  @override
  void dispose() {
    _urlController.dispose();
    super.dispose();
  }

  bool get _pronto =>
      (_controlli.isEmpty || _idControllo != null) &&
      (_tipo == _Tipo.web
          ? _urlValido(_urlController.text.trim())
          : _documenti.isNotEmpty);

  Future<void> _scegliDocumenti() async {
    final scelti = await scegliFiles(estensioniAmmesse);
    if (scelti.isEmpty || !mounted) return;
    setState(() {
      final presenti = _documenti.map((d) => d.nome).toSet();
      for (final f in scelti) {
        if (!presenti.contains(f.name)) {
          _documenti.add(DocumentoFonte(f.name, f.bytes));
        }
      }
    });
  }

  void _conferma() {
    Navigator.pop(
      context,
      FontePrecompilazione(
        idControllo: _idControllo,
        url: _tipo == _Tipo.web ? _urlController.text.trim() : '',
        analizzaDocumenti: _tipo == _Tipo.web && _analizzaDocumenti,
        maxDocumenti: _maxDocumenti,
        seguiLink: _tipo == _Tipo.web && _seguiLink,
        maxLink: _maxLink,
        documenti: _tipo == _Tipo.documenti ? List.of(_documenti) : const [],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Precompila da pagina web o documento'),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'L\'IA legge la fonte e compila il modulo con i dati che trova, nel formato '
                'richiesto dallo schema. I dati vanno verificati prima di generare la scheda.',
                style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
              ),
              const SizedBox(height: 16),
              if (_controlli.isNotEmpty) ...[
                DropdownButtonFormField<String>(
                  initialValue: _idControllo,
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: 'Sezione da precompilare *',
                    border: OutlineInputBorder(),
                  ),
                  items: [
                    for (final c in _controlli)
                      DropdownMenuItem(
                        value: c['id'] as String,
                        child: Text(
                          maiuscola(c['titolo'] as String),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: (v) => setState(() => _idControllo = v),
                ),
                const SizedBox(height: 16),
              ],
              SegmentedButton<_Tipo>(
                segments: const [
                  ButtonSegment(
                    value: _Tipo.web,
                    icon: Icon(Icons.language),
                    label: Text('Pagina web'),
                  ),
                  ButtonSegment(
                    value: _Tipo.documenti,
                    icon: Icon(Icons.attach_file),
                    label: Text('Documenti'),
                  ),
                ],
                selected: {_tipo},
                onSelectionChanged: (s) => setState(() => _tipo = s.first),
              ),
              const SizedBox(height: 16),
              if (_tipo == _Tipo.web) ...[
                TextField(
                  controller: _urlController,
                  keyboardType: TextInputType.url,
                  decoration: InputDecoration(
                    labelText: 'Indirizzo della pagina *',
                    hintText:
                        'https://www.ente.it/amministrazione-trasparente/...',
                    prefixIcon: const Icon(Icons.link),
                    border: const OutlineInputBorder(),
                    suffixIcon: _urlController.text.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.clear),
                            tooltip: 'Cancella l\'indirizzo',
                            onPressed: _urlController.clear,
                          ),
                  ),
                ),
                SceltaLink.documenti(
                  titolo: 'Leggi anche i documenti collegati alla pagina ($formatiDocumentiCollegati)',
                  segui: _analizzaDocumenti,
                  numero: _maxDocumenti,
                  onSegui: (v) => setState(() => _analizzaDocumenti = v),
                  onNumero: (v) => setState(() => _maxDocumenti = v),
                  dense: true,
                ),
                SceltaLink(
                  titolo: 'Segui i link presenti nel contenuto principale',
                  segui: _seguiLink,
                  numero: _maxLink,
                  onSegui: (v) => setState(() => _seguiLink = v),
                  onNumero: (v) => setState(() => _maxLink = v),
                  dense: true,
                ),
              ] else ...[
                for (var i = 0; i < _documenti.length; i++)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.description_outlined),
                    title: Text(
                      _documenti[i].nome,
                      overflow: TextOverflow.ellipsis,
                    ),
                    trailing: IconButton(
                      icon: Icon(
                        Icons.delete_outline,
                        color: Colors.red.shade700,
                      ),
                      tooltip: 'Rimuovi',
                      onPressed: () => setState(() => _documenti.removeAt(i)),
                    ),
                  ),
                Align(
                  alignment: Alignment.centerLeft,
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.folder_open),
                    label: Text(
                      _documenti.isEmpty
                          ? 'Seleziona i documenti'
                          : 'Aggiungi altri documenti',
                    ),
                    onPressed: _scegliDocumenti,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'Formati ammessi: PDF, DOC, DOCX, ODT, XLS, XLSX, ODS, CSV, XML, JSON.',
                  style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Annulla'),
        ),
        FilledButton.icon(
          icon: const Icon(Icons.auto_fix_high),
          label: const Text('Estrai i dati'),
          onPressed: _pronto ? _conferma : null,
        ),
      ],
    );
  }
}
