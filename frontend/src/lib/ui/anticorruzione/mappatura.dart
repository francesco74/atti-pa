import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';
import 'albero.dart';
import 'comune.dart';
import 'proposte.dart';

/// Area dei processi senza un'area di rischio.
const _senzaArea = '';

/// Mappatura, un livello alla volta con il percorso in alto: aree di rischio, processi
/// dell'area, attività del processo, rischi e misure dell'attività. La ricerca trova un
/// processo in tutte le aree. Il RPCT modifica direttamente, i referenti propongono.
class MappaturaTab extends StatefulWidget {
  const MappaturaTab({super.key, required this.onDatiCambiati});

  final VoidCallback onDatiCambiati; // aree modificate: si ricaricano i dati comuni

  @override
  State<MappaturaTab> createState() => _MappaturaTabState();
}

class _MappaturaTabState extends State<MappaturaTab> with AutomaticKeepAliveClientMixin {
  late Future<List<Map<String, dynamic>>> _processi;
  String? _area; // area aperta
  String? _processoId; // processo aperto
  String? _struttura, _livello;
  final _testo = TextEditingController();

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
        _processi = apiDi(context).get('$apiAnticorruzione/processi', query: {
          'struttura': ?_struttura,
          'livello': ?_livello,
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  void _vaiAree() {
    _processoId = _area = _struttura = _livello = null;
    _testo.clear();
    _carica();
  }

  void _vaiArea(String? id) {
    _processoId = null;
    _area = id ?? _senzaArea;
    _carica();
  }

  void _chiudiProcesso() {
    _processoId = null;
    _carica();
  }

  Future<void> _modificaArea([Map<String, dynamic>? a]) async {
    final v = await modificaCampi(context, titolo: a == null ? 'Nuova area di rischio' : 'Area ${a['codice']}', valori: a ?? const {}, campi: const [
      Campo('codice', 'Codice', obbligatorio: true, aiuto: 'es. C'),
      Campo('descrizione', 'Descrizione', righe: 3, obbligatorio: true),
      Campo('descrizione_breve', 'Descrizione breve'),
      Campo('ordine', 'Ordine'),
    ]);
    if (v == null || !mounted) return;
    final corpo = {...v, 'ordine': int.tryParse('${v['ordine'] ?? 0}') ?? 0};
    try {
      final api = apiDi(context);
      if (a == null) {
        await api.post('$apiAnticorruzione/aree', corpo);
      } else {
        await api.put('$apiAnticorruzione/aree/${a['id']}', corpo);
      }
      widget.onDatiCambiati();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _eliminaArea(Map<String, dynamic> a) async {
    if (!await conferma(context, 'Eliminare l\'area ${a['codice']}?', 'Si può eliminare solo un\'area senza processi.')) return;
    if (!mounted) return;
    try {
      await apiDi(context).delete('$apiAnticorruzione/aree/${a['id']}');
      widget.onDatiCambiati();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _nuovoProcesso(DatiAnticorruzione dati, bool rpct) async {
    final v = await modificaProcesso(context, dati, {'area_id': _area == _senzaArea ? null : _area});
    if (v == null || !mounted) return;
    try {
      final api = apiDi(context);
      if (rpct) {
        final p = await api.post('$apiAnticorruzione/processi', v) as Map<String, dynamic>;
        if (mounted) setState(() => _processoId = p['id'] as String);
      } else {
        final pr = await api.post('$apiAnticorruzione/proposte', {
          'tipo': 'CREA',
          'dati': {'processo': v, 'attivita': <Object>[]},
        }) as Map<String, dynamic>;
        if (mounted) await apriProposta(context, pr['id'] as String);
        _carica();
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _elencoProcessi(DatiAnticorruzione dati, List<Map<String, dynamic>> processi) => Column(children: [
        for (final p in processi)
          RigaVoce(
            icona: Icons.account_tree_outlined,
            titolo: '${p['codice']} - ${p['denominazione']}',
            dettagli: [
              p['struttura_id'] == null ? 'Trasversale' : (dati.struttura(p['struttura_id']) ?? ''),
              '${p['attivita']} attività, ${p['rischi']} rischi, ${p['misure']} misure',
            ],
            finale: [LivelloChip(dati, p['livello_massimo'] as String?)],
            onTap: () => setState(() => _processoId = p['id'] as String),
          ),
      ]);

  /// Primo livello: le aree di rischio; mentre si cerca, i processi trovati.
  List<Widget> _livelloAree(DatiAnticorruzione dati, List<Map<String, dynamic>> processi, bool rpct) {
    final cerca = _testo.text.trim().toLowerCase();
    final idAree = dati.aree.map((a) => a['id']).toSet();
    int quanti(Object? id) => processi.where((p) => p['area_id'] == id).length;
    final senzaArea = processi.where((p) => !idAree.contains(p['area_id'])).length;
    final trovati = processi.where((p) => '${p['codice']} ${p['denominazione']}'.toLowerCase().contains(cerca)).toList();
    String numero(int n) => n == 1 ? '1 processo' : '$n processi';
    return [
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(
          width: 320,
          child: TextField(
            controller: _testo,
            decoration: const InputDecoration(labelText: 'Cerca un processo (codice o denominazione)', isDense: true, prefixIcon: Icon(Icons.search)),
            onChanged: (_) => setState(() {}),
          ),
        ),
        if (rpct && cerca.isEmpty)
          FilledButton.icon(onPressed: () => _modificaArea(), icon: const Icon(Icons.add), label: const Text('Nuova area')),
      ]),
      const SizedBox(height: 16),
      if (cerca.isNotEmpty)
        trovati.isEmpty ? const Center(child: Text('Nessun processo trovato.')) : _elencoProcessi(dati, trovati)
      else if (dati.aree.isEmpty && senzaArea == 0)
        const Center(child: Text('Nessuna area di rischio. Il RPCT può crearle o importare i processi standard da Amministrazione → Pacchetti.'))
      else
        Column(children: [
          for (final a in dati.aree)
            RigaVoce(
              icona: Icons.folder_outlined,
              titolo: dati.area(a['id'])!,
              dettagli: [numero(quanti(a['id']))],
              onTap: () => _vaiArea(a['id'] as String),
              finale: [
                if (rpct) ...[
                  IconaAzione(Icons.edit_outlined, 'Modifica l\'area', () => _modificaArea(a)),
                  IconaAzione(Icons.delete_outline, 'Elimina l\'area', () => _eliminaArea(a)),
                ],
              ],
            ),
          if (senzaArea > 0)
            RigaVoce(icona: Icons.folder_off_outlined, titolo: 'Senza area', dettagli: [numero(senzaArea)], onTap: () => _vaiArea(null)),
        ]),
    ];
  }

  /// Secondo livello: i processi dell'area, con i filtri.
  List<Widget> _livelloProcessi(DatiAnticorruzione dati, List<Map<String, dynamic>> processi, bool rpct) {
    final idAree = dati.aree.map((a) => a['id']).toSet();
    final dellArea = processi.where((p) => _area == _senzaArea ? !idAree.contains(p['area_id']) : p['area_id'] == _area).toList();
    return [
      Percorso([('Aree di rischio', _vaiAree), (dati.area(_area) ?? 'Senza area', null)]),
      const SizedBox(height: 12),
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(
          width: 260,
          child: DropdownButtonFormField<String?>(
            initialValue: _struttura,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Struttura', isDense: true),
            items: [
              const DropdownMenuItem(value: null, child: Text('Tutte')),
              for (final s in dati.strutture)
                DropdownMenuItem(value: s['id'] as String, child: Text('${s['codice']} - ${s['descrizione']}', overflow: TextOverflow.ellipsis)),
            ],
            onChanged: (v) {
              _struttura = v;
              _carica();
            },
          ),
        ),
        SizedBox(
          width: 200,
          child: DropdownButtonFormField<String?>(
            initialValue: _livello,
            decoration: const InputDecoration(labelText: 'Livello più alto', isDense: true),
            items: [
              const DropdownMenuItem(value: null, child: Text('Tutti')),
              for (final l in dati.livelli.reversed) DropdownMenuItem(value: l, child: Text(l)),
            ],
            onChanged: (v) {
              _livello = v;
              _carica();
            },
          ),
        ),
        FilledButton.icon(
          onPressed: () => _nuovoProcesso(dati, rpct),
          icon: const Icon(Icons.add),
          label: Text(rpct ? 'Nuovo processo' : 'Proponi un processo'),
        ),
      ]),
      const SizedBox(height: 16),
      if (dellArea.isEmpty) const Center(child: Text('Nessun processo.')) else _elencoProcessi(dati, dellArea),
    ];
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final dati = context.watch<DatiAnticorruzione>();
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    if (_processoId != null) {
      return VistaProcesso(
        key: ValueKey(_processoId),
        processoId: _processoId!,
        onAree: _vaiAree,
        onArea: _vaiArea,
        onChiuso: _chiudiProcesso,
      );
    }
    return Caricamento<List<Map<String, dynamic>>>(
      future: _processi,
      riprova: _carica,
      builder: (context, processi) => ListView(
        padding: const EdgeInsets.all(16),
        children: _area == null ? _livelloAree(dati, processi, rpct) : _livelloProcessi(dati, processi, rpct),
      ),
    );
  }
}

/// Processo aperto da un'altra scheda (es. un obiettivo collegato), a tutta pagina.
Future<void> apriProcesso(BuildContext context, String id) {
  final dati = context.read<DatiAnticorruzione>();
  return Navigator.of(context).push(MaterialPageRoute(
    builder: (c) => Provider.value(
      value: dati,
      child: Scaffold(
        appBar: AppBar(title: const Text('Processo')),
        body: VistaProcesso(
          processoId: id,
          onAree: () => Navigator.of(c).pop(),
          onArea: (_) => Navigator.of(c).pop(),
          onChiuso: () => Navigator.of(c).pop(),
        ),
      ),
    ),
  ));
}

/// Terzo e quarto livello: il processo con l'elenco delle attività e, aprendone una, i suoi
/// rischi con le misure. Il RPCT modifica direttamente, i referenti propongono la modifica
/// o l'eliminazione del processo.
class VistaProcesso extends StatefulWidget {
  const VistaProcesso({
    super.key,
    required this.processoId,
    required this.onAree,
    required this.onArea,
    required this.onChiuso,
  });

  final String processoId;
  final VoidCallback onAree;
  final ValueChanged<String?> onArea;
  final VoidCallback onChiuso; // processo eliminato

  @override
  State<VistaProcesso> createState() => _VistaProcessoState();
}

class _VistaProcessoState extends State<VistaProcesso> {
  late Future<Map<String, dynamic>> _albero;
  String? _attivitaId;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _albero = apiDi(context)
            .get('$apiAnticorruzione/processi/${widget.processoId}')
            .then((v) => daAlbero(v as Map<String, dynamic>));
      });

  Future<void> _proponi(String tipo) async {
    if (tipo == 'ELIMINA' &&
        !await conferma(context, 'Proporre l\'eliminazione?', 'La proposta va al RPCT, che decide se eliminare il processo.')) {
      return;
    }
    if (!mounted) return;
    try {
      final pr = await apiDi(context).post('$apiAnticorruzione/proposte', {'tipo': tipo, 'processo_id': widget.processoId})
          as Map<String, dynamic>;
      if (mounted) await apriProposta(context, pr['id'] as String);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _elimina() async {
    if (!await conferma(context, 'Eliminare il processo?', 'Si eliminano anche attività, rischi, misure e i collegamenti agli obiettivi.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('$apiAnticorruzione/processi/${widget.processoId}');
      widget.onChiuso();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  /// Il livello più alto tra i rischi dell'attività.
  String? _livelloMassimo(DatiAnticorruzione dati, List<Map<String, dynamic>> rischi) {
    String? massimo;
    for (final r in rischi) {
      final l = (r['valutazione'] as Map?)?['livello'] as String?;
      if (l != null && (massimo == null || dati.livelli.indexOf(l) > dati.livelli.indexOf(massimo))) massimo = l;
    }
    return massimo;
  }

  Widget _rigaAttivita(DatiAnticorruzione dati, Map<String, dynamic> a, OperazioniAlbero? ops) {
    final rischi = (a['rischi'] as List).cast<Map<String, dynamic>>();
    final misure = rischi.fold<int>(0, (n, r) => n + (r['misure'] as List).length);
    return RigaVoce(
      icona: Icons.subdirectory_arrow_right,
      titolo: '${a['codice']} - ${a['descrizione']}',
      dettagli: ['${rischi.length} rischi, $misure misure'],
      onTap: () => setState(() => _attivitaId = a['id'] as String),
      finale: [
        LivelloChip(dati, _livelloMassimo(dati, rischi)),
        if (ops != null) ...[
          IconaAzione(Icons.edit_outlined, 'Modifica l\'attività', () => eseguiOperazione(context, _carica, () async {
                final v = await modificaAttivita(context, a);
                if (v != null) await ops.modificaAttivita(a, v);
              })),
          IconaAzione(Icons.delete_outline, 'Elimina l\'attività', () => eseguiOperazione(context, _carica, () async {
                if (await confermaEliminazione(context, 'l\'attività')) await ops.eliminaAttivita(a);
              })),
        ],
      ],
    );
  }

  /// Quarto livello: l'attività con i rischi e le misure.
  List<Widget> _livelloAttivita(DatiAnticorruzione dati, Map<String, dynamic> a, OperazioniAlbero? ops) {
    final rischi = (a['rischi'] as List).cast<Map<String, dynamic>>();
    return [
      Sezione(
        titolo: 'Attività ${a['codice']}',
        azioni: [
          if (ops != null) ...[
            TextButton.icon(
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: const Text('Modifica'),
              onPressed: () => eseguiOperazione(context, _carica, () async {
                final v = await modificaAttivita(context, a);
                if (v != null) await ops.modificaAttivita(a, v);
              }),
            ),
            TextButton.icon(
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              icon: const Icon(Icons.delete_outline, size: 18),
              label: const Text('Elimina'),
              onPressed: () => eseguiOperazione(context, _carica, () async {
                if (await confermaEliminazione(context, 'l\'attività')) {
                  await ops.eliminaAttivita(a);
                  _attivitaId = null;
                }
              }),
            ),
          ],
        ],
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${a['descrizione']}'),
          if (a['strutture_coinvolte'] != null) Text('Strutture coinvolte: ${a['strutture_coinvolte']}'),
          chipObiettivi(a['obiettivi']),
        ]),
      ),
      Sezione(
        titolo: 'Rischi e misure',
        azioni: [
          if (ops != null)
            FilledButton.icon(
              icon: const Icon(Icons.add_alert_outlined, size: 18),
              label: const Text('Aggiungi un rischio'),
              onPressed: () => eseguiOperazione(context, _carica, () async {
                final v = await modificaRischio(context, dati);
                if (v != null) await ops.aggiungiRischio(a, v);
              }),
            ),
        ],
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (rischi.isEmpty) const Text('Nessun rischio individuato.'),
          for (final r in rischi) SchedaRischio(dati: dati, attivita: a, rischio: r, operazioni: ops, onCambiato: _carica),
        ]),
      ),
    ];
  }

  /// Terzo livello: la scheda del processo e le sue attività.
  List<Widget> _livelloProcesso(DatiAnticorruzione dati, Map<String, dynamic> albero, OperazioniAlbero? ops, bool rpct) {
    final processo = albero['processo'] as Map<String, dynamic>;
    final attivita = (albero['attivita'] as List).cast<Map<String, dynamic>>();
    return [
      IntestazioneProcesso(
        dati: dati,
        processo: processo,
        obiettivi: albero['obiettivi'],
        azioni: [
          if (ops != null) ...[
            TextButton.icon(
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: const Text('Modifica'),
              onPressed: () => eseguiOperazione(context, _carica, () async {
                final v = await modificaProcesso(context, dati, processo);
                if (v != null) await ops.processo(v);
              }),
            ),
            TextButton.icon(
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              icon: const Icon(Icons.delete_outline, size: 18),
              label: const Text('Elimina'),
              onPressed: _elimina,
            ),
          ],
          if (!rpct) ...[
            TextButton.icon(onPressed: () => _proponi('MODIFICA'), icon: const Icon(Icons.edit_note), label: const Text('Proponi modifiche')),
            TextButton.icon(onPressed: () => _proponi('ELIMINA'), icon: const Icon(Icons.delete_sweep_outlined), label: const Text('Proponi l\'eliminazione')),
          ],
        ],
      ),
      Row(children: [
        Expanded(child: Text('Attività', style: Theme.of(context).textTheme.titleMedium)),
        if (ops != null)
          FilledButton.icon(
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Nuova attività'),
            onPressed: () => eseguiOperazione(context, _carica, () async {
              final v = await modificaAttivita(context);
              if (v != null) await ops.aggiungiAttivita(v);
            }),
          ),
      ]),
      const SizedBox(height: 12),
      if (attivita.isEmpty) const Text('Nessuna attività.'),
      for (final a in attivita) _rigaAttivita(dati, a, ops),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    return Caricamento<Map<String, dynamic>>(
      future: _albero,
      riprova: _carica,
      builder: (context, albero) {
        final processo = albero['processo'] as Map<String, dynamic>;
        final attivita = (albero['attivita'] as List).cast<Map<String, dynamic>>();
        final aperta = attivita.where((a) => a['id'] == _attivitaId).firstOrNull;
        final operazioni = rpct ? OperazioniDirette(apiDi(context), widget.processoId) : null;
        final nome = '${processo['codice']} ${processo['denominazione']}';
        return ListView(padding: const EdgeInsets.all(16), children: [
          Percorso([
            ('Aree di rischio', widget.onAree),
            (dati.area(processo['area_id']) ?? 'Senza area', () => widget.onArea(processo['area_id'] as String?)),
            (nome, aperta == null ? null : () => setState(() => _attivitaId = null)),
            if (aperta != null) ('${aperta['codice']}', null),
          ]),
          const SizedBox(height: 12),
          if (aperta != null)
            ..._livelloAttivita(dati, aperta, operazioni)
          else
            ..._livelloProcesso(dati, albero, operazioni, rpct),
        ]);
      },
    );
  }
}
