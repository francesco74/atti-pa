import 'package:flutter/material.dart';

import '../../anticorruzione/art35.dart';
import '../../anticorruzione/comune.dart' show Campo, IconaAzione, RigaVoce, modificaCampi;
import '../../anticorruzione/importa_procedimenti.dart';
import '../../anticorruzione/mappatura.dart' show PubblicazioneMappatura;
import '../../comuni.dart';

const apiProcedimenti = '/api/v1/trasparenza/procedimenti';

/// Procedimenti dell'ente (art. 35 d.lgs. 33/2013): catalogo condiviso con l'anticorruzione.
/// Con il solo modulo trasparenza l'operatore li crea, modifica, importa ed elimina qui,
/// direttamente; con l'anticorruzione attiva si gestiscono nella mappatura (iter di
/// approvazione del RPCT) e qui si consultano. In entrambi i casi c'è l'interruttore della
/// pagina pubblica dei procedimenti.
class ProcedimentiTab extends StatefulWidget {
  const ProcedimentiTab({super.key});

  @override
  State<ProcedimentiTab> createState() => _ProcedimentiTabState();
}

class _Dati {
  _Dati(this.conIter, this.procedimenti, this.strutture);

  final bool conIter;
  final List<Map<String, dynamic>> procedimenti;
  final List<Map<String, dynamic>> strutture;

  String struttura(Object? id) {
    final s = strutture.where((s) => s['id'] == id).firstOrNull;
    return s == null ? '—' : '${s['codice']} - ${s['descrizione']}';
  }
}

class _ProcedimentiTabState extends State<ProcedimentiTab> with AutomaticKeepAliveClientMixin {
  late Future<_Dati> _dati;
  final _cerca = TextEditingController();

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _cerca.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
    final api = apiDi(context);
    _dati = Future.wait([api.get('$apiProcedimenti/pubblicazione'), api.get(apiProcedimenti), api.get('/api/v1/ente/strutture')]).then(
      (r) => _Dati(
        (r[0] as Map)['con_iter'] == true,
        (r[1] as List).cast<Map<String, dynamic>>(),
        (r[2] as List).cast<Map<String, dynamic>>(),
      ),
    );
  });

  Future<void> _nuovo(_Dati d) async {
    final v = await modificaProcedimento(context, d.strutture);
    if (v == null || !mounted) return;
    try {
      final p = await apiDi(context).post(apiProcedimenti, v) as Map<String, dynamic>;
      if (!mounted) return;
      await _apri(p['id'] as String);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _importa(_Dati d) async {
    final fatto = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ImportaProcedimentiPage(
          strutture: d.strutture,
          api: apiProcedimenti,
          apiImportazioni: '$apiProcedimenti/importazioni',
          nomeCatalogo: 'elenco dei procedimenti',
        ),
      ),
    );
    if (fatto == true) _carica();
  }

  Future<void> _apri(String id) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProcedimentoPage(procedimentoId: id)));
    if (mounted) _carica();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Caricamento<_Dati>(
      future: _dati,
      riprova: _carica,
      builder: (context, d) {
        final cerca = _cerca.text.trim().toLowerCase();
        final elenco = [
          for (final p in d.procedimenti)
            if (cerca.isEmpty || '${p['codice']} ${p['denominazione']} ${d.struttura(p['struttura_id'])}'.toLowerCase().contains(cerca)) p,
        ];
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              d.conIter
                  ? 'I procedimenti fanno parte della mappatura dell\'anticorruzione: si modificano lì, con l\'iter di '
                        'approvazione del RPCT. Qui si consultano e si importano nella scheda art. 35.'
                  : 'Tipologie di procedimento dell\'ente con i dati dell\'art. 35 d.lgs. 33/2013: si importano nella scheda '
                        'art. 35 e si possono pubblicare in una pagina consultabile dai cittadini.',
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SizedBox(
                  width: 320,
                  child: TextField(
                    controller: _cerca,
                    decoration: const InputDecoration(labelText: 'Cerca', prefixIcon: Icon(Icons.search), isDense: true),
                    onChanged: (_) => setState(() {}),
                  ),
                ),
                if (!d.conIter) ...[
                  FilledButton.icon(onPressed: () => _nuovo(d), icon: const Icon(Icons.add), label: const Text('Nuovo procedimento')),
                  OutlinedButton.icon(
                    onPressed: () => _importa(d),
                    icon: const Icon(Icons.download_outlined),
                    label: const Text('Importa dal sito o da documenti'),
                  ),
                ],
                const PubblicazioneMappatura(api: '$apiProcedimenti/pubblicazione', soloProcedimenti: true),
              ],
            ),
            const SizedBox(height: 16),
            if (elenco.isEmpty)
              Text(d.procedimenti.isEmpty ? 'Nessun procedimento.' : 'Nessun procedimento trovato.')
            else
              Card(
                child: Column(
                  children: [
                    for (final p in elenco)
                      RigaVoce(
                        icona: Icons.assignment_outlined,
                        titolo: '${p['codice']} - ${p['denominazione']}',
                        dettagli: [
                          d.struttura(p['struttura_id']),
                          if (p['termine_conclusione'] != null) 'termine: ${p['termine_conclusione']}',
                        ],
                        finale: [CompletezzaArt35((p['art35_mancanti'] as List? ?? const []).length)],
                        onTap: () => _apri(p['id'] as String),
                      ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }
}

/// Denominazione, descrizione, termine, norma e struttura responsabile del procedimento (i
/// dati dell'art. 35 hanno la loro finestra).
Future<Map<String, dynamic>?> modificaProcedimento(BuildContext context, List<Map<String, dynamic>> strutture, [Map<String, dynamic>? p]) =>
    modificaCampi(
      context,
      titolo: p == null ? 'Nuovo procedimento' : 'Procedimento ${p['codice']}',
      valori: p ?? const {},
      campi: [
        const Campo('denominazione', 'Denominazione', righe: 2, obbligatorio: true),
        const Campo('descrizione', 'Descrizione', righe: 4),
        const Campo('termine_conclusione', 'Termine di conclusione', aiuto: 'es. 30 giorni'),
        const Campo('norma_riferimento', 'Riferimenti normativi', righe: 2),
        Campo(
          'struttura_id',
          'Unità responsabile dell\'istruttoria',
          scelte: [
            (null, '—'),
            for (final s in strutture)
              if (s['attiva'] != false || s['id'] == p?['struttura_id']) (s['id'] as String, '${s['codice']} - ${s['descrizione']}'),
          ],
        ),
      ],
    );

/// Un procedimento: dati generali e scheda art. 35; modificabile solo senza l'anticorruzione.
class ProcedimentoPage extends StatefulWidget {
  const ProcedimentoPage({super.key, required this.procedimentoId});

  final String procedimentoId;

  @override
  State<ProcedimentoPage> createState() => _ProcedimentoPageState();
}

class _ProcedimentoPageState extends State<ProcedimentoPage> {
  late Future<(_Dati, Map<String, dynamic>)> _dati;

  String get _url => '$apiProcedimenti/${widget.procedimentoId}';

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
    final api = apiDi(context);
    _dati = Future.wait([api.get('$apiProcedimenti/pubblicazione'), api.get(_url), api.get('/api/v1/ente/strutture')]).then(
      (r) =>
          (_Dati((r[0] as Map)['con_iter'] == true, const [], (r[2] as List).cast<Map<String, dynamic>>()), r[1] as Map<String, dynamic>),
    );
  });

  /// Salva i dati generali e quelli dell'art. 35 (quelli non indicati restano).
  Future<void> _salva(Map<String, dynamic> p, Map<String, dynamic> modifiche) async {
    try {
      await apiDi(context).put(_url, {
        for (final k in const ['denominazione', 'descrizione', 'termine_conclusione', 'norma_riferimento', 'struttura_id']) k: p[k],
        ...modifiche,
      });
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _elimina(Map<String, dynamic> p) async {
    if (!await conferma(context, 'Eliminare il procedimento?', '${p['codice']} - ${p['denominazione']}') || !mounted) return;
    try {
      await apiDi(context).delete(_url);
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Caricamento<(_Dati, Map<String, dynamic>)>(
      future: _dati,
      riprova: _carica,
      builder: (context, r) {
        final (d, p) = r;
        final modificabile = !d.conIter;
        return Scaffold(
          appBar: AppBar(
            title: Text('${p['codice']} - ${p['denominazione']}', overflow: TextOverflow.ellipsis),
            actions: [
              if (modificabile) ...[
                IconaAzione(Icons.edit_outlined, 'Modifica', () async {
                  final v = await modificaProcedimento(context, d.strutture, p);
                  if (v != null && context.mounted) await _salva(p, v);
                }),
                IconaAzione(Icons.delete_outline, 'Elimina', () => _elimina(p)),
              ],
            ],
          ),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Sezione(
                titolo: 'Procedimento',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${p['codice']} - ${p['denominazione']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    Text('Unità responsabile: ${d.struttura(p['struttura_id'])}'),
                    if (p['termine_conclusione'] != null) Text('Termine di conclusione: ${p['termine_conclusione']}'),
                    if (p['norma_riferimento'] != null) Text('Riferimenti normativi: ${p['norma_riferimento']}'),
                    if (p['descrizione'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('${p['descrizione']}')),
                    if (!modificabile)
                      const Padding(
                        padding: EdgeInsets.only(top: 8),
                        child: Text('Si modifica nella mappatura dell\'anticorruzione.', style: TextStyle(fontStyle: FontStyle.italic)),
                      ),
                  ],
                ),
              ),
              SezioneArt35(
                scheda: (p['scheda_art35'] as Map).cast<String, dynamic>(),
                mancanti: List<String>.from(p['art35_mancanti'] as List? ?? const []),
                onModifica: modificabile
                    ? () async {
                        final v = await modificaArt35(context, d.strutture, (p['art35'] as Map?)?.cast<String, dynamic>(), procedimento: p);
                        if (v != null && context.mounted) await _salva(p, {'art35': v});
                      }
                    : null,
              ),
            ],
          ),
        );
      },
    ),
  );
}
