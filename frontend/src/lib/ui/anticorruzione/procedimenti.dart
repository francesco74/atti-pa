import 'dart:async';

import 'package:flutter/material.dart';

import '../comuni.dart';
import 'art35.dart';
import 'catalogo.dart' show controllaSimili;
import 'comune.dart';
import 'importa_procedimenti.dart';

const apiProcedimentiAc = '$apiAnticorruzione/procedimenti';

/// Come si gestisce il catalogo dei procedimenti da una vista: direttamente (RPCT, o operatore
/// della trasparenza senza l'anticorruzione), con le proposte (referente) o in sola lettura.
enum GestioneProcedimenti { diretta, proposte, lettura }

/// Denominazione, descrizione, termine, riferimenti normativi e struttura responsabile del
/// procedimento (i dati dell'art. 35 hanno la loro finestra).
Future<Map<String, dynamic>?> modificaProcedimento(BuildContext context, List<Map<String, dynamic>> strutture,
        {Map<String, dynamic>? p, Future<void> Function(Map<String, dynamic>)? salva, String? titolo}) =>
    modificaCampi(
      context,
      salva: salva,
      titolo: titolo ?? (p?['codice'] == null ? 'Nuovo procedimento' : 'Procedimento ${p!['codice']}'),
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

const _campiBase = ['denominazione', 'descrizione', 'termine_conclusione', 'norma_riferimento', 'struttura_id'];

/// I dati del procedimento da inviare (salvataggio o proposta), con le [modifiche].
Map<String, dynamic> datiProcedimento(Map<String, dynamic> p, [Map<String, dynamic> modifiche = const {}]) => {
      for (final k in _campiBase) k: p[k],
      if (p['art35'] != null) 'art35': p['art35'],
      ...modifiche,
    };

Future<void> _proponi(BuildContext context, String tipo, {String? elemento, Map<String, dynamic>? dati}) async {
  await apiDi(context).post('$apiAnticorruzione/proposte', {
    'tipo': tipo,
    'oggetto': 'PROCEDIMENTO',
    'elemento_id': ?elemento,
    'dati': ?dati,
  });
  if (context.mounted) propostaInviata(context);
}

/// Nuovo procedimento: il RPCT (o l'operatore della trasparenza) lo crea, il referente lo
/// propone; prima, con le API dell'anticorruzione, si mostrano quelli simili già nel catalogo.
/// Restituisce il procedimento creato o scelto tra i simili (null per una proposta).
Future<Map<String, dynamic>?> nuovoProcedimento(BuildContext context, String api, GestioneProcedimenti gestione,
    List<Map<String, dynamic>> strutture, {String? testo, bool scegli = false}) async {
  final client = apiDi(context);
  Map<String, dynamic>? risultato;
  final proposta = gestione == GestioneProcedimenti.proposte;
  final v = await modificaProcedimento(context, strutture,
      titolo: proposta ? 'Proponi un procedimento' : null,
      p: testo == null || testo.trim().isEmpty ? null : {'denominazione': testo.trim()},
      salva: (v) async {
        if (api == apiProcedimentiAc) {
          final scelto = await controllaSimili(context, 'PROCEDIMENTO', v['denominazione'] as String,
              azione: proposta ? 'Proponi' : 'Crea', scegli: scegli);
          if (scelto != null) {
            risultato = scelto;
            return;
          }
        }
        if (proposta) {
          await client.post('$apiAnticorruzione/proposte', {'tipo': 'CREA', 'oggetto': 'PROCEDIMENTO', 'dati': v});
        } else {
          risultato = await client.post(api, v) as Map<String, dynamic>;
        }
      });
  if (v != null && proposta && risultato == null && context.mounted) {
    mostraMessaggio(context, 'Proposta del procedimento inviata al RPCT: quando la approva lo trovi nel catalogo.');
  }
  return risultato;
}

/// Catalogo dei procedimenti dell'ente (art. 35 d.lgs. 33/2013), condiviso tra anticorruzione e
/// trasparenza: elenco con la ricerca (anche per significato), i dati art. 35 mancanti e, nella
/// mappatura, in quante attività è usato. Si incorpora in una vista che scorre (non scorre da sé).
class ElencoProcedimenti extends StatefulWidget {
  const ElencoProcedimenti({
    super.key,
    this.api = apiProcedimentiAc,
    required this.gestione,
    this.azioni = const [],
    this.apriAttivita,
  });

  final String api;
  final GestioneProcedimenti gestione;
  final List<Widget> azioni; // es. l'interruttore della pagina pubblica
  final void Function(BuildContext context, Map<String, dynamic> attivita)? apriAttivita;

  @override
  State<ElencoProcedimenti> createState() => _ElencoProcedimentiState();
}

class _ElencoProcedimentiState extends State<ElencoProcedimenti> {
  late Future<(List<Map<String, dynamic>>, List<Map<String, dynamic>>)> _dati;
  final _cerca = TextEditingController();
  Timer? _attesa;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _attesa?.cancel();
    _cerca.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
        final api = apiDi(context);
        final testo = _cerca.text.trim();
        _dati = Future.wait([
          api.get(widget.api, query: {if (testo.isNotEmpty) 'testo': testo}),
          api.get('/api/v1/ente/strutture'),
        ]).then((r) => ((r[0] as List).cast<Map<String, dynamic>>(), (r[1] as List).cast<Map<String, dynamic>>()));
      });

  String _struttura(List<Map<String, dynamic>> strutture, Object? id) {
    final s = strutture.where((s) => s['id'] == id).firstOrNull;
    return s == null ? 'senza unità responsabile' : '${s['codice']} - ${s['descrizione']}';
  }

  Future<void> _nuovo(List<Map<String, dynamic>> strutture) async {
    final creato = await nuovoProcedimento(context, widget.api, widget.gestione, strutture);
    if (!mounted) return;
    if (creato != null) {
      await _apri(creato['id'] as String);
    } else {
      _carica();
    }
  }

  Future<void> _importa(List<Map<String, dynamic>> strutture) async {
    final fatto = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => ImportaProcedimentiPage(strutture: strutture, api: widget.api, apiImportazioni: '${widget.api}/importazioni'),
    ));
    if (fatto == true) _carica();
  }

  Future<void> _apri(String id) async {
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => ProcedimentoPage(
          api: widget.api, procedimentoId: id, gestione: widget.gestione, apriAttivita: widget.apriAttivita),
    ));
    if (mounted) _carica();
  }

  @override
  Widget build(BuildContext context) {
    final diretta = widget.gestione == GestioneProcedimenti.diretta;
    return Caricamento<(List<Map<String, dynamic>>, List<Map<String, dynamic>>)>(
      future: _dati,
      riprova: _carica,
      builder: (context, d) {
        final (procedimenti, strutture) = d;
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SizedBox(
              width: 320,
              child: TextField(
                controller: _cerca,
                decoration: const InputDecoration(labelText: 'Cerca (codice o testo)', prefixIcon: Icon(Icons.search), isDense: true),
                onChanged: (_) {
                  _attesa?.cancel();
                  _attesa = Timer(const Duration(milliseconds: 400), _carica);
                },
              ),
            ),
            if (diretta) ...[
              FilledButton.icon(onPressed: () => _nuovo(strutture), icon: const Icon(Icons.add, size: 18), label: const Text('Nuovo procedimento')),
              OutlinedButton.icon(
                onPressed: () => _importa(strutture),
                icon: const Icon(Icons.download_outlined, size: 18),
                label: const Text('Importa dal sito o da documenti'),
              ),
            ],
            if (widget.gestione == GestioneProcedimenti.proposte)
              OutlinedButton.icon(
                onPressed: () => _nuovo(strutture),
                icon: const Icon(Icons.outgoing_mail, size: 18),
                label: const Text('Proponi un procedimento'),
              ),
            ...widget.azioni,
          ]),
          const SizedBox(height: 12),
          if (procedimenti.isEmpty)
            Padding(
              padding: const EdgeInsets.all(24),
              child: Center(child: Text(_cerca.text.trim().isEmpty ? 'Nessun procedimento.' : 'Nessun procedimento trovato.')),
            )
          else ...[
            Text(procedimenti.length == 1 ? '1 procedimento' : '${procedimenti.length} procedimenti',
                style: Theme.of(context).textTheme.titleSmall),
            for (final p in procedimenti)
              RigaVoce(
                icona: Icons.gavel_outlined,
                titolo: '${p['codice']} - ${p['denominazione']}',
                dettagli: [
                  _struttura(strutture, p['struttura_id']),
                  if (p['termine_conclusione'] != null) 'termine: ${p['termine_conclusione']}',
                  if (p['usi'] != null && widget.api == apiProcedimentiAc) usiProcedimento(p['usi'] as int),
                  if (p['per_significato'] == true) 'trovato per significato',
                ],
                finale: [CompletezzaArt35((p['art35_mancanti'] as List? ?? const []).length)],
                onTap: () => _apri(p['id'] as String),
              ),
          ],
        ]);
      },
    );
  }
}

/// "non usato", "in 1 attività", "in 3 attività" della mappatura.
String usiProcedimento(int usi) => usi == 0 ? 'non usato nella mappatura' : (usi == 1 ? 'in 1 attività' : 'in $usi attività');

/// Un procedimento del catalogo: dati generali, scheda art. 35 e (nell'anticorruzione) le
/// attività della mappatura che lo sono. Modifica ed eliminazione dirette o proposte.
class ProcedimentoPage extends StatefulWidget {
  const ProcedimentoPage({
    super.key,
    this.api = apiProcedimentiAc,
    required this.procedimentoId,
    required this.gestione,
    this.apriAttivita,
  });

  final String api;
  final String procedimentoId;
  final GestioneProcedimenti gestione;
  final void Function(BuildContext context, Map<String, dynamic> attivita)? apriAttivita;

  @override
  State<ProcedimentoPage> createState() => _ProcedimentoPageState();
}

class _ProcedimentoPageState extends State<ProcedimentoPage> {
  late Future<(Map<String, dynamic>, List<Map<String, dynamic>>)> _dati;

  String get _url => '${widget.api}/${widget.procedimentoId}';

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        final api = apiDi(context);
        _dati = Future.wait([api.get(_url), api.get('/api/v1/ente/strutture')])
            .then((r) => (r[0] as Map<String, dynamic>, (r[1] as List).cast<Map<String, dynamic>>()));
      });

  bool _proposte(Map<String, dynamic> p) => widget.gestione == GestioneProcedimenti.proposte && p['proponibile'] == true;

  /// Salva o propone i dati generali o quelli dell'art. 35 (gli altri restano); l'errore passa
  /// a chi chiama (la finestra lo mostra).
  Future<void> _scrivi(Map<String, dynamic> p, Map<String, dynamic> modifiche) async {
    final dati = datiProcedimento(p, modifiche);
    if (_proposte(p)) {
      await _proponi(context, 'MODIFICA', elemento: p['id'] as String, dati: dati);
    } else {
      await apiDi(context).put(_url, dati);
    }
  }

  Future<void> _modifica(Map<String, dynamic> p, List<Map<String, dynamic>> strutture) async {
    final v = await modificaProcedimento(context, strutture,
        p: p, titolo: _proposte(p) ? 'Proponi la modifica di ${p['codice']}' : null, salva: (v) => _scrivi(p, v));
    if (v != null && mounted) _carica();
  }

  Future<void> _elimina(Map<String, dynamic> p) async {
    final proposta = _proposte(p);
    final ok = proposta
        ? await conferma(context, 'Proporre l\'eliminazione?', 'Si invia al RPCT la proposta di eliminare ${p['codice']} - ${p['denominazione']}.')
        : await conferma(context, 'Eliminare il procedimento?', '${p['codice']} - ${p['denominazione']}');
    if (!ok || !mounted) return;
    try {
      if (proposta) {
        await _proponi(context, 'ELIMINA', elemento: p['id'] as String);
      } else {
        await apiDi(context).delete(_url);
        if (mounted) Navigator.of(context).pop();
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Procedimento')),
        body: Caricamento<(Map<String, dynamic>, List<Map<String, dynamic>>)>(
          future: _dati,
          riprova: _carica,
          builder: (context, r) {
            final (p, strutture) = r;
            final diretta = widget.gestione == GestioneProcedimenti.diretta;
            final modificabile = diretta || _proposte(p);
            final attivita = (p['attivita'] as List? ?? const []).cast<Map<String, dynamic>>();
            final struttura = strutture.where((s) => s['id'] == p['struttura_id']).firstOrNull;
            final righe = [
              ('Unità responsabile dell\'istruttoria', struttura == null ? null : '${struttura['codice']} - ${struttura['descrizione']}'),
              ('Termine di conclusione', p['termine_conclusione']),
              ('Riferimenti normativi', p['norma_riferimento']),
              ('Descrizione', p['descrizione']),
            ];
            return ListView(padding: const EdgeInsets.all(16), children: [
              Sezione(
                titolo: '${p['codice']} - ${p['denominazione']}',
                azioni: [
                  if (modificabile) ...[
                    TextButton.icon(
                      icon: const Icon(Icons.edit_outlined, size: 18),
                      label: Text(diretta ? 'Modifica' : 'Proponi modifica'),
                      onPressed: () => _modifica(p, strutture),
                    ),
                    if (attivita.isEmpty)
                      TextButton.icon(
                        style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                        icon: const Icon(Icons.delete_outline, size: 18),
                        label: Text(diretta ? 'Elimina' : 'Proponi eliminazione'),
                        onPressed: () => _elimina(p),
                      ),
                  ],
                ],
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final (etichetta, valore) in righe)
                    if (valore != null && valore.toString().isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Text.rich(TextSpan(children: [
                          TextSpan(text: '$etichetta: ', style: const TextStyle(fontWeight: FontWeight.w600)),
                          TextSpan(text: '$valore'),
                        ])),
                      ),
                  if (widget.gestione == GestioneProcedimenti.lettura)
                    const Padding(
                      padding: EdgeInsets.only(top: 8),
                      child: Text('Si modifica nel catalogo dell\'anticorruzione.', style: TextStyle(fontStyle: FontStyle.italic)),
                    ),
                ]),
              ),
              SezioneArt35(
                scheda: (p['scheda_art35'] as Map).cast<String, dynamic>(),
                mancanti: List<String>.from(p['art35_mancanti'] as List? ?? const []),
                onModifica: modificabile
                    ? () async {
                        // il salvataggio (o la proposta) lo fa la finestra: con un errore resta aperta
                        final v = await modificaArt35(context, strutture, (p['art35'] as Map?)?.cast<String, dynamic>(),
                            procedimento: p, salva: (v) => _scrivi(p, {'art35': v}));
                        if (v != null && mounted) _carica();
                      }
                    : null,
              ),
              if (widget.api == apiProcedimentiAc)
                Sezione(
                  titolo: attivita.isEmpty ? 'Non è un\'attività della mappatura' : 'Attività della mappatura (${attivita.length})',
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    if (attivita.isEmpty)
                      Text('Nei processi un\'attività può essere questo procedimento: si sceglie aggiungendo l\'attività.',
                          style: Theme.of(context).textTheme.bodySmall),
                    for (final a in attivita)
                      RigaVoce(
                        icona: Icons.subdirectory_arrow_right,
                        titolo: '${a['codice']} - ${a['descrizione']}',
                        dettagli: ['${(a['processo'] as Map)['codice']} - ${(a['processo'] as Map)['denominazione']}'],
                        onTap: widget.apriAttivita == null ? null : () => widget.apriAttivita!(context, a),
                      ),
                  ]),
                ),
            ]);
          },
        ),
      );
}
