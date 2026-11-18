import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../stato/auth_state.dart';
import '../comuni.dart';
import 'comune.dart';
import 'mappatura.dart' show VistaProcesso;
import 'procedimenti.dart';

const apiCatalogo = '$apiAnticorruzione/catalogo';

const tipiVoce = {'ATTIVITA': 'Attività', 'RISCHIO': 'Rischi', 'MISURA': 'Misure'};
const _singolare = {'ATTIVITA': 'attività', 'RISCHIO': 'rischio', 'MISURA': 'misura', 'PROCEDIMENTO': 'procedimento'};

IconData iconaVoce(String? tipo) => switch (tipo) {
      'ATTIVITA' => Icons.subdirectory_arrow_right,
      'RISCHIO' => Icons.warning_amber_outlined,
      'PROCEDIMENTO' => Icons.gavel_outlined,
      _ => Icons.shield_outlined,
    };

/// Apre il processo (e l'attività) di un elemento del catalogo: {processo: {id, codice,
/// denominazione}, attivita_id | id}.
void apriProcessoDelCatalogo(BuildContext context, Map<String, dynamic> e) {
  final dati = context.read<DatiAnticorruzione>();
  final processo = e['processo'] as Map;
  Navigator.of(context).push(MaterialPageRoute(
    builder: (c) => Provider<DatiAnticorruzione>.value(
      value: dati,
      child: Scaffold(
        appBar: AppBar(title: Text('${processo['codice']} - ${processo['denominazione']}')),
        body: VistaProcesso(
          processoId: processo['id'] as String,
          attivitaIniziale: (e['attivita_id'] ?? e['id']) as String?,
          onAree: () => Navigator.of(c).pop(),
          onArea: (_) => Navigator.of(c).pop(),
          onChiuso: () => Navigator.of(c).pop(),
        ),
      ),
    ),
  ));
}

/// Catalogo della mappatura: le voci (radici) di attività, rischi e misure da cui nascono gli
/// elementi dei processi, con dove sono usate, e i procedimenti (un'attività può essere un
/// procedimento). Il RPCT crea le voci, le modifica (se usate con conferma), le disattiva, le
/// unisce e le elimina se non usate; gestisce i procedimenti, che il referente propone.
class CatalogoTab extends StatefulWidget {
  const CatalogoTab({super.key});

  @override
  State<CatalogoTab> createState() => _CatalogoTabState();
}

class _CatalogoTabState extends State<CatalogoTab> with AutomaticKeepAliveClientMixin {
  String _tipo = 'ATTIVITA';
  final _testo = TextEditingController();
  Timer? _attesa;
  late Future<List<Map<String, dynamic>>> _voci;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _attesa?.cancel();
    _testo.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
        _voci = apiDi(context).get(apiCatalogo, query: {
          'tipo': _tipo,
          if (_testo.text.trim().isNotEmpty) 'testo': _testo.text.trim(),
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  Future<void> _nuova() async {
    final dati = context.read<DatiAnticorruzione>();
    final api = apiDi(context);
    final v = await modificaVoce(context, dati, _tipo, salva: (v) async {
      // prima di crearla: le voci simili già nel catalogo (si torna alla modifica o si crea)
      await controllaSimili(context, _tipo, v['descrizione'] as String, azione: 'Crea');
      await api.post(apiCatalogo, {...v, 'tipo': _tipo});
    });
    if (v != null && mounted) _carica();
  }

  Future<void> _apri(Map<String, dynamic> v) async {
    final dati = context.read<DatiAnticorruzione>();
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => Provider<DatiAnticorruzione>.value(value: dati, child: SchedaVocePage(voceId: v['id'] as String)),
    ));
    if (mounted) _carica();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    final selettore = SegmentedButton<String>(
      segments: [
        for (final e in tipiVoce.entries) ButtonSegment(value: e.key, label: Text(e.value)),
        const ButtonSegment(value: 'PROCEDIMENTO', label: Text('Procedimenti')),
      ],
      selected: {_tipo},
      showSelectedIcon: false,
      onSelectionChanged: (s) {
        _tipo = s.first;
        if (_tipo == 'PROCEDIMENTO') {
          setState(() {});
        } else {
          _carica();
        }
      },
    );
    if (_tipo == 'PROCEDIMENTO') {
      return ListView(padding: const EdgeInsets.all(16), children: [
        Text('I procedimenti amministrativi dell\'ente con i dati dell\'art. 35 d.lgs. 33/2013 (gli stessi della '
            'trasparenza). Nei processi un\'attività può essere un procedimento: si sceglie da qui.',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 12),
        Align(alignment: Alignment.centerLeft, child: selettore),
        const SizedBox(height: 12),
        ElencoProcedimenti(
          gestione: rpct ? GestioneProcedimenti.diretta : GestioneProcedimenti.proposte,
          apriAttivita: apriProcessoDelCatalogo,
        ),
      ]);
    }
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Le voci da cui nascono attività, rischi e misure dei processi. Nel processo il testo si può ritoccare, '
          'ma la voce resta la stessa: così si vede dove una voce è usata.', style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 12),
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        selettore,
        SizedBox(
          width: 320,
          child: TextField(
            controller: _testo,
            decoration: const InputDecoration(labelText: 'Cerca (codice o testo)', prefixIcon: Icon(Icons.search), isDense: true),
            onChanged: (_) {
              _attesa?.cancel();
              _attesa = Timer(const Duration(milliseconds: 400), _carica);
            },
          ),
        ),
        if (rpct)
          FilledButton.icon(
            onPressed: _nuova,
            icon: const Icon(Icons.add, size: 18),
            label: Text('Nuova voce (${_singolare[_tipo]})'),
          ),
      ]),
      const SizedBox(height: 12),
      Caricamento<List<Map<String, dynamic>>>(
        future: _voci,
        riprova: _carica,
        builder: (context, voci) => voci.isEmpty
            ? const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Nessuna voce.')))
            : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text('${voci.length} voci', style: Theme.of(context).textTheme.titleSmall),
                for (final v in voci) _riga(v),
              ]),
      ),
    ]);
  }

  Widget _riga(Map<String, dynamic> v) {
    final usi = v['usi'] as int? ?? 0;
    return RigaVoce(
      icona: iconaVoce(v['tipo'] as String?),
      titolo: '${v['codice']} - ${v['descrizione']}',
      dettagli: [
        usi == 0 ? 'non usata' : (usi == 1 ? 'usata in 1 elemento' : 'usata in $usi elementi'),
        v['standard'] == true ? 'standard' : 'dell\'ente',
        if (v['tipo'] == 'MISURA' && v['categoria'] != null) '${v['categoria']}',
        if (v['per_significato'] == true) 'trovata per significato',
      ],
      finale: [if (v['attiva'] != true) const _Etichetta('Disattivata')],
      onTap: () => _apri(v),
    );
  }
}

class _Etichetta extends StatelessWidget {
  const _Etichetta(this.testo);

  final String testo;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(border: Border.all(color: Colors.blueGrey), borderRadius: BorderRadius.circular(12)),
        child: Text(testo, style: const TextStyle(fontSize: 12)),
      );
}

/// Testo e dati della voce: per le misure anche tipo, categoria, indicatore e target di
/// partenza.
Future<Map<String, dynamic>?> modificaVoce(BuildContext context, DatiAnticorruzione d, String tipo,
    {Map<String, dynamic>? v, Future<void> Function(Map<String, dynamic>)? salva}) {
  final categoria = v?['categoria'] as String?;
  return modificaCampi(context,
      salva: salva,
      titolo: v?['codice'] == null ? 'Nuova voce: ${_singolare[tipo]}' : 'Voce ${v!['codice']}',
      valori: {if (tipo == 'MISURA') 'tipo_misura': 'SPECIFICA', ...?v},
      campi: [
        Campo('descrizione', tipo == 'RISCHIO' ? 'Evento rischioso' : 'Descrizione', righe: 4, obbligatorio: true),
        if (tipo == 'MISURA') ...[
          const Campo('tipo_misura', 'Tipo', scelte: [('GENERALE', 'Generale'), ('SPECIFICA', 'Specifica')]),
          Campo('categoria', 'Categoria', scelte: [
            (null, 'Nessuna'),
            for (final c in d.categorie) (c, c),
            if (categoria != null && !d.categorie.contains(categoria)) (categoria, categoria),
          ]),
          const Campo('indicatore', 'Indicatore', righe: 2),
          const Campo('target', 'Target', righe: 2),
        ],
      ]);
}

/// Le voci del catalogo dello stesso tipo simili a [testo] (per significato, o per parole in
/// comune senza il modello), la più simile prima, con la somiglianza da 0 a 1. Per il tipo
/// PROCEDIMENTO i procedimenti del catalogo, nella stessa forma (testo nella descrizione).
Future<List<Map<String, dynamic>>> vociSimili(ApiClient api, String tipo, String testo, {String? esclusa}) async {
  if (tipo == 'PROCEDIMENTO') {
    final r = await api.get('$apiProcedimentiAc/simili', query: {'testo': testo, 'escluso': ?esclusa}) as List;
    return [for (final p in r.cast<Map<String, dynamic>>()) {...p, 'tipo': 'PROCEDIMENTO', 'descrizione': p['denominazione'], 'attiva': true}];
  }
  return ((await api.get('$apiCatalogo/simili', query: {'tipo': tipo, 'testo': testo, 'esclusa': ?esclusa})) as List)
      .cast<Map<String, dynamic>>();
}

String _usi(Map<String, dynamic> v) {
  final usi = v['usi'] as int? ?? 0;
  if (v['tipo'] == 'PROCEDIMENTO') return usiProcedimento(usi);
  return usi == 0 ? 'non usata' : (usi == 1 ? 'usata in 1 elemento' : 'usata in $usi elementi');
}

/// Prima di creare o proporre una voce nuova ([azione]: "Crea" o "Proponi"): se nel catalogo
/// ce ne sono di simili le mostra. Restituisce null per procedere o, con [scegli], la voce
/// esistente scelta al posto della nuova; lancia [Annullato] per tornare alla modifica. Se le
/// voci simili non si possono cercare si procede (il controllo aiuta, non blocca).
Future<Map<String, dynamic>?> controllaSimili(BuildContext context, String tipo, String testo,
    {required String azione, bool scegli = false}) async {
  List<Map<String, dynamic>> simili;
  try {
    simili = await vociSimili(apiDi(context), tipo, testo);
  } catch (_) {
    return null;
  }
  if (simili.isEmpty || !context.mounted) return null;
  final esito = await showDialog<Object>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(tipo == 'PROCEDIMENTO' ? 'Nel catalogo ci sono procedimenti simili' : 'Nel catalogo ci sono voci simili'),
      content: SizedBox(
        width: 600,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(scegli
              ? 'Prima di ${azione == 'Crea' ? 'creare' : 'proporre'} ${tipo == 'PROCEDIMENTO' ? 'un procedimento nuovo' : 'una voce nuova'}, '
                  'controlla se ${tipo == 'PROCEDIMENTO' ? 'uno di questi' : 'una di queste'} fa già al caso tuo: nel processo il testo si potrà comunque ritoccare.'
              : 'Prima di ${azione == 'Crea' ? 'creare' : 'proporre'} ${tipo == 'PROCEDIMENTO' ? 'un procedimento nuovo' : 'una voce nuova'}, '
                  'controlla che non sia già nel catalogo.'),
          const SizedBox(height: 8),
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (final v in simili)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(iconaVoce(tipo), size: 20),
                  title: Text('${v['codice']} - ${v['descrizione']}'),
                  subtitle: Text([
                    'somiglianza ${((v['somiglianza'] as num) * 100).round()}%',
                    _usi(v),
                    if (v['attiva'] != true) 'disattivata',
                  ].join(' · ')),
                  trailing: scegli && v['attiva'] == true
                      ? TextButton(onPressed: () => Navigator.pop(c, v), child: Text(tipo == 'PROCEDIMENTO' ? 'Scegli questo' : 'Scegli questa'))
                      : null,
                ),
            ]),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c), child: const Text('Torna alla modifica')),
        FilledButton(onPressed: () => Navigator.pop(c, 'procedi'), child: Text('$azione comunque')),
      ],
    ),
  );
  if (esito is Map<String, dynamic>) return esito;
  if (esito == 'procedi') return null;
  throw const Annullato();
}

/// Le voci del catalogo simili a quella proposta, per il RPCT che decide la proposta (niente
/// se non ce ne sono o se non si possono cercare).
class VociSimiliProposta extends StatefulWidget {
  const VociSimiliProposta({super.key, required this.tipo, required this.testo});

  final String tipo, testo;

  @override
  State<VociSimiliProposta> createState() => _VociSimiliPropostaState();
}

class _VociSimiliPropostaState extends State<VociSimiliProposta> {
  late final Future<List<Map<String, dynamic>>> _simili =
      vociSimili(apiDi(context), widget.tipo, widget.testo).catchError((_) => <Map<String, dynamic>>[]);

  @override
  Widget build(BuildContext context) => FutureBuilder<List<Map<String, dynamic>>>(
        future: _simili,
        builder: (context, s) {
          final simili = s.data ?? const [];
          if (simili.isEmpty) return const SizedBox.shrink();
          return Sezione(
            titolo: widget.tipo == 'PROCEDIMENTO' ? 'Procedimenti simili già nel catalogo' : 'Voci simili già nel catalogo',
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(widget.tipo == 'PROCEDIMENTO'
                  ? 'Se il procedimento proposto c\'è già, conviene restituire la proposta indicando quale usare.'
                  : 'Se la voce proposta c\'è già, conviene restituire la proposta indicando quale usare.',
                  style: Theme.of(context).textTheme.bodySmall),
              for (final v in simili)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(iconaVoce(widget.tipo), size: 20),
                  title: Text('${v['codice']} - ${v['descrizione']}'),
                  subtitle: Text([
                    'somiglianza ${((v['somiglianza'] as num) * 100).round()}%',
                    _usi(v),
                    if (v['attiva'] != true) 'disattivata',
                  ].join(' · ')),
                ),
            ]),
          );
        },
      );
}

/// Chiede conferma per un'operazione su una voce usata, elencando dove è usata (mappatura e
/// obiettivi della performance). True: si procede (subito, se la voce non è usata).
Future<bool> confermaVoceUsata(BuildContext context, Map<String, dynamic> voce, String titolo, String conseguenza) async {
  final elementi = (voce['elementi'] as List? ?? const []).cast<Map<String, dynamic>>();
  final obiettivi = (voce['obiettivi'] as List? ?? const []).cast<Map<String, dynamic>>();
  if (elementi.isEmpty && obiettivi.isEmpty) return true;
  final esito = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(titolo),
      content: SizedBox(
        width: 560,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('La voce ${voce['codice']} è usata in:', style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Flexible(
            child: SingleChildScrollView(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (elementi.isNotEmpty) Text(elementi.length == 1 ? '1 elemento della mappatura' : '${elementi.length} elementi della mappatura'),
                for (final e in elementi)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4, left: 8),
                    child: Text('• ${e['codice']} (${(e['processo'] as Map)['codice']} - ${(e['processo'] as Map)['denominazione']})'),
                  ),
                if (obiettivi.isNotEmpty) Text(obiettivi.length == 1 ? '1 obiettivo di performance' : '${obiettivi.length} obiettivi di performance'),
                for (final o in obiettivi)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4, left: 8),
                    child: Text('• ${o['codice'] == null ? '' : '${o['codice']} - '}${o['titolo']} (${o['piao']}, anno ${o['anno']})'),
                  ),
              ]),
            ),
          ),
          const SizedBox(height: 8),
          Text(conseguenza),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Procedi comunque')),
      ],
    ),
  );
  return esito == true;
}

/// Una voce del catalogo: i dati e dove è usata; per il RPCT le operazioni.
class SchedaVocePage extends StatefulWidget {
  const SchedaVocePage({super.key, required this.voceId});

  final String voceId;

  @override
  State<SchedaVocePage> createState() => _SchedaVocePageState();
}

class _SchedaVocePageState extends State<SchedaVocePage> {
  late Future<Map<String, dynamic>> _voce;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _voce = apiDi(context).get('$apiCatalogo/${widget.voceId}').then((v) => v as Map<String, dynamic>);
      });

  Future<void> _esegui(Future<void> Function() azione) async {
    try {
      await azione();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
    if (mounted) _carica();
  }

  static const _restano = 'Gli elementi dei processi e gli obiettivi non cambiano: tengono il loro testo.';

  Future<void> _modifica(Map<String, dynamic> v) => _esegui(() async {
        final dati = context.read<DatiAnticorruzione>();
        final api = apiDi(context);
        // la conferma per la voce usata si chiede prima di salvare, con la finestra ancora aperta
        await modificaVoce(context, dati, v['tipo'] as String, v: v, salva: (nuovi) async {
          if (!await confermaVoceUsata(context, v, 'Modificare una voce usata?', _restano)) throw const Annullato();
          await api.put('$apiCatalogo/${v['id']}', {...nuovi, 'attiva': v['attiva'], 'conferma': true});
        });
      });

  Future<void> _attiva(Map<String, dynamic> v, bool attiva) => _esegui(() async {
        if (!attiva &&
            !await confermaVoceUsata(context, v, 'Disattivare una voce usata?', 'Non si potrà più scegliere. $_restano')) {
          return;
        }
        if (!mounted) return;
        await apiDi(context).put('$apiCatalogo/${v['id']}', {...v, 'attiva': attiva, 'conferma': true});
      });

  Future<void> _unisci(Map<String, dynamic> v) => _esegui(() async {
        final altra = await scegliVoce(context, v['tipo'] as String, escluse: {v['id'] as String},
            titolo: 'Unisci ${v['codice']} a un\'altra voce');
        if (altra == null || !mounted) return;
        final testo = 'I suoi elementi passano a ${altra['codice']} e la voce ${v['codice']} si elimina. $_restano';
        if ((v['elementi'] as List).isEmpty && (v['obiettivi'] as List? ?? const []).isEmpty) {
          if (!await conferma(context, 'Unire le voci?', testo)) return;
        } else if (!await confermaVoceUsata(context, v, 'Unire una voce usata?', testo)) {
          return;
        }
        if (!mounted) return;
        await apiDi(context).post('$apiCatalogo/${v['id']}/unisci', {'in_voce': altra['id'], 'conferma': true});
        if (mounted) Navigator.of(context).pop();
      });

  Future<void> _elimina(Map<String, dynamic> v) => _esegui(() async {
        if (!await conferma(context, 'Eliminare la voce?', 'La voce ${v['codice']} non è usata: si elimina dal catalogo.') || !mounted) {
          return;
        }
        await apiDi(context).delete('$apiCatalogo/${v['id']}');
        if (mounted) Navigator.of(context).pop();
      });

  @override
  Widget build(BuildContext context) {
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    return Scaffold(
      appBar: AppBar(title: const Text('Voce del catalogo')),
      body: Caricamento<Map<String, dynamic>>(
        future: _voce,
        riprova: _carica,
        builder: (context, v) {
          final elementi = (v['elementi'] as List).cast<Map<String, dynamic>>();
          final obiettivi = (v['obiettivi'] as List? ?? const []).cast<Map<String, dynamic>>();
          final righe = [
            ('Tipo', _singolare[v['tipo']]),
            ('Provenienza', v['standard'] == true ? 'voce standard (pacchetto)' : 'voce dell\'ente'),
            if (v['tipo'] == 'MISURA') ...[
              ('Tipo di misura', v['tipo_misura'] == 'GENERALE' ? 'Generale' : 'Specifica'),
              ('Categoria', v['categoria']),
              ('Indicatore', v['indicatore']),
              ('Target', v['target']),
            ],
            if (v['attiva'] != true) ('Stato', 'disattivata: non si sceglie più'),
          ];
          return ListView(padding: const EdgeInsets.all(16), children: [
            Sezione(
              titolo: '${v['codice']} - ${v['descrizione']}',
              azioni: [
                if (rpct) ...[
                  TextButton.icon(icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('Modifica'), onPressed: () => _modifica(v)),
                  TextButton.icon(
                    icon: Icon(v['attiva'] == true ? Icons.block : Icons.check_circle_outline, size: 18),
                    label: Text(v['attiva'] == true ? 'Disattiva' : 'Riattiva'),
                    onPressed: () => _attiva(v, v['attiva'] != true),
                  ),
                  TextButton.icon(icon: const Icon(Icons.merge_type, size: 18), label: const Text('Unisci'), onPressed: () => _unisci(v)),
                  if (elementi.isEmpty && obiettivi.isEmpty)
                    TextButton.icon(
                      style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                      icon: const Icon(Icons.delete_outline, size: 18),
                      label: const Text('Elimina'),
                      onPressed: () => _elimina(v),
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
              ]),
            ),
            Sezione(
              titolo: elementi.isEmpty ? 'Non usata nella mappatura' : 'Usata in ${elementi.length} elementi della mappatura',
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                for (final e in elementi)
                  RigaVoce(
                    icona: iconaVoce(v['tipo'] as String?),
                    titolo: '${e['codice']} - ${e['testo']}',
                    dettagli: [
                      '${(e['processo'] as Map)['codice']} - ${(e['processo'] as Map)['denominazione']}',
                      if (e['diverso'] == true) 'testo ritoccato nel processo',
                    ],
                    onTap: () => apriProcessoDelCatalogo(context, e),
                  ),
              ]),
            ),
            if (obiettivi.isNotEmpty)
              Sezione(
                titolo: 'Radice di ${obiettivi.length == 1 ? '1 obiettivo' : '${obiettivi.length} obiettivi'} di performance',
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  for (final o in obiettivi)
                    ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.flag_outlined),
                      title: Text(o['codice'] == null ? '${o['titolo']}' : '${o['codice']} - ${o['titolo']}'),
                      subtitle: Text([
                        '${o['piao']} · anno ${o['anno']}',
                        ?context.read<DatiAnticorruzione>().struttura(o['struttura_id']),
                        'completato al ${o['completamento']}%',
                      ].join(' · ')),
                    ),
                ]),
              ),
          ]);
        },
      ),
    );
  }
}

/// Scelta di una voce del catalogo (attive, del tipo dato), con la ricerca. Con [dati] (per un
/// elemento nuovo della mappatura) la voce che manca si crea (RPCT) o si propone (referente:
/// approvata, si sceglie). Per un'attività nuova ([procedimenti]) si può scegliere invece un
/// procedimento del catalogo dei procedimenti: il risultato ha allora `procedimento: true`, con
/// id, codice e denominazione.
Future<Map<String, dynamic>?> scegliVoce(BuildContext context, String tipo,
        {Set<String> escluse = const {}, String? titolo, DatiAnticorruzione? dati, bool procedimenti = false}) =>
    showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _SceltaVoce(
          tipo: tipo,
          escluse: escluse,
          titolo: titolo ?? (procedimenti ? 'Nuova attività: dal catalogo o un procedimento' : 'Scegli dal catalogo: ${_singolare[tipo]}'),
          dati: dati,
          procedimenti: procedimenti),
    );

class _SceltaVoce extends StatefulWidget {
  const _SceltaVoce({required this.tipo, required this.escluse, required this.titolo, this.dati, this.procedimenti = false});

  final String tipo;
  final Set<String> escluse;
  final String titolo;
  final DatiAnticorruzione? dati;
  final bool procedimenti; // si può scegliere anche un procedimento

  @override
  State<_SceltaVoce> createState() => _SceltaVoceState();
}

class _SceltaVoceState extends State<_SceltaVoce> {
  final _testo = TextEditingController();
  Timer? _attesa;
  late Future<List<Map<String, dynamic>>> _voci;
  var _procedimento = false; // si sceglie tra i procedimenti

  @override
  void initState() {
    super.initState();
    _cerca();
  }

  @override
  void dispose() {
    _attesa?.cancel();
    _testo.dispose();
    super.dispose();
  }

  void _cerca() => setState(() {
        final testo = _testo.text.trim();
        if (_procedimento) {
          _voci = apiDi(context).get(apiProcedimentiAc, query: {if (testo.isNotEmpty) 'testo': testo}).then((v) => [
                for (final p in (v as List).cast<Map<String, dynamic>>()) {...p, 'procedimento': true},
              ]);
          return;
        }
        _voci = apiDi(context).get(apiCatalogo, query: {
          'tipo': widget.tipo,
          'attive': 'true',
          if (testo.isNotEmpty) 'testo': testo,
        }).then((v) => [for (final x in (v as List).cast<Map<String, dynamic>>()) if (!widget.escluse.contains(x['id'])) x]);
      });

  /// La voce che manca: il RPCT la crea e la sceglie; il referente la propone.
  Future<void> _manca(bool rpct) async {
    if (_procedimento) return _mancaProcedimento(rpct);
    final api = apiDi(context);
    Map<String, dynamic>? nuova;
    var esistente = false;
    // il salvataggio lo fa la finestra della voce: con un errore resta aperta
    final v = await modificaVoce(context, widget.dati!, widget.tipo,
        v: _testo.text.trim().isEmpty ? null : {'descrizione': _testo.text.trim(), if (widget.tipo == 'MISURA') 'tipo_misura': 'SPECIFICA'},
        salva: (v) async {
          // prima le voci simili già nel catalogo: se ne sceglie una, niente voce nuova
          final scelta = await controllaSimili(context, widget.tipo, v['descrizione'] as String,
              azione: rpct ? 'Crea' : 'Proponi', scegli: true);
          if (scelta != null) {
            (nuova, esistente) = (scelta, true);
            return;
          }
          if (rpct) {
            nuova = await api.post(apiCatalogo, {...v, 'tipo': widget.tipo}) as Map<String, dynamic>;
          } else {
            await api.post('$apiAnticorruzione/proposte', {'tipo': 'CREA', 'oggetto': 'VOCE', 'dati': {...v, 'tipo_voce': widget.tipo}});
          }
        });
    if (v == null || !mounted) return;
    if (!rpct && !esistente) {
      mostraMessaggio(context, 'Proposta della voce inviata al RPCT: quando la approva la trovi nel catalogo e la puoi scegliere.');
    }
    Navigator.pop(context, nuova);
  }

  /// Il procedimento che manca: il RPCT lo crea e lo sceglie; il referente lo propone (approvato,
  /// lo sceglie).
  Future<void> _mancaProcedimento(bool rpct) async {
    final strutture = widget.dati?.strutture ?? const <Map<String, dynamic>>[];
    final scelto = await nuovoProcedimento(context, apiProcedimentiAc, rpct ? GestioneProcedimenti.diretta : GestioneProcedimenti.proposte,
        strutture, testo: _testo.text, scegli: true);
    if (scelto != null && mounted) Navigator.pop(context, {...scelto, 'procedimento': true});
  }

  @override
  Widget build(BuildContext context) {
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    final cosa = _procedimento ? 'il procedimento' : 'la voce';
    return AlertDialog(
        title: Text(widget.titolo),
        content: SizedBox(
          width: 640,
          height: 460,
          child: Column(children: [
            if (widget.procedimenti)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(value: false, icon: Icon(Icons.subdirectory_arrow_right), label: Text('Voce del catalogo')),
                    ButtonSegment(value: true, icon: Icon(Icons.gavel_outlined), label: Text('Procedimento')),
                  ],
                  selected: {_procedimento},
                  showSelectedIcon: false,
                  onSelectionChanged: (s) {
                    _procedimento = s.first;
                    _cerca();
                  },
                ),
              ),
            if (widget.dati != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                    (_procedimento ? 'L\'attività è un procedimento amministrativo del catalogo (art. 35). ' : '') +
                        (rpct
                            ? 'Il testo si potrà ritoccare per questo processo. Se $cosa manca, ${_procedimento ? 'crealo' : 'creala'}.'
                            : 'Il testo si potrà ritoccare per questo processo. Se $cosa manca, ${_procedimento ? 'proponilo' : 'proponila'}: '
                                'quando il RPCT ${_procedimento ? 'lo' : 'la'} approva ${_procedimento ? 'lo' : 'la'} potrai scegliere.'),
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            TextField(
              controller: _testo,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Cerca (codice o testo)', prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (_) {
                _attesa?.cancel();
                _attesa = Timer(const Duration(milliseconds: 400), _cerca);
              },
            ),
            const SizedBox(height: 8),
            Expanded(
              child: Caricamento<List<Map<String, dynamic>>>(
                future: _voci,
                riprova: _cerca,
                builder: (context, voci) => voci.isEmpty
                    ? Center(child: Text(_procedimento ? 'Nessun procedimento trovato.' : 'Nessuna voce trovata.'))
                    : ListView(children: [
                        for (final v in voci)
                          if (v['procedimento'] == true)
                            ListTile(
                              dense: true,
                              leading: const Icon(Icons.gavel_outlined, size: 20),
                              title: Text('${v['codice']} - ${v['denominazione']}'),
                              subtitle: Text([
                                usiProcedimento(v['usi'] as int? ?? 0),
                                ?v['termine_conclusione'] as String?,
                                if (v['per_significato'] == true) 'trovato per significato',
                              ].join(' · ')),
                              onTap: () => Navigator.pop(context, v),
                            )
                          else
                            ListTile(
                              dense: true,
                              leading: Icon(iconaVoce(v['tipo'] as String?), size: 20),
                              title: Text('${v['codice']} - ${v['descrizione']}'),
                              subtitle: Text([_usi(v), if (v['per_significato'] == true) 'trovata per significato'].join(' · ')),
                              onTap: () => Navigator.pop(context, v),
                            ),
                      ]),
              ),
            ),
          ]),
        ),
        actions: [
          if (widget.dati != null)
            TextButton.icon(
              icon: Icon(rpct ? Icons.add : Icons.outgoing_mail, size: 18),
              label: Text(_procedimento
                  ? (rpct ? 'Nuovo procedimento' : 'Proponi un procedimento nuovo')
                  : (rpct ? 'Nuova voce' : 'Proponi una voce nuova')),
              onPressed: () => _manca(rpct),
            ),
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        ],
      );
  }
}
