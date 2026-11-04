import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';
import 'albero.dart';
import 'comune.dart';

/// Area dei processi senza un'area di rischio.
const _senzaArea = '';

/// Mappatura, un livello alla volta con il percorso in alto: aree di rischio, processi e
/// procedimenti dell'area, attività del processo, rischi e misure dell'attività. La ricerca
/// trova un processo in tutte le aree. Il RPCT modifica direttamente; i referenti propongono
/// con gli stessi pulsanti (aree, e tutto quanto riguarda i processi della loro struttura).
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
  String? _struttura, _livello, _tipo;
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
          'tipo': ?_tipo,
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  void _vaiAree() {
    _processoId = _area = _struttura = _livello = _tipo = null;
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

  /// Proposta del referente: va subito al RPCT.
  Future<void> _proponi(Map<String, dynamic> proposta) async {
    await apiDi(context).post('$apiAnticorruzione/proposte', proposta);
    if (mounted) propostaInviata(context);
  }

  Future<void> _modificaArea(bool rpct, [Map<String, dynamic>? a]) async {
    final v = await modificaArea(context, a);
    if (v == null || !mounted) return;
    try {
      final api = apiDi(context);
      if (!rpct) {
        await _proponi({'tipo': a == null ? 'CREA' : 'MODIFICA', 'oggetto': 'AREA', 'elemento_id': ?a?['id'], 'dati': v});
      } else if (a == null) {
        await api.post('$apiAnticorruzione/aree', v);
      } else {
        await api.put('$apiAnticorruzione/aree/${a['id']}', v);
      }
      if (rpct) widget.onDatiCambiati();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _eliminaArea(bool rpct, Map<String, dynamic> a) async {
    final ok = rpct
        ? await conferma(context, 'Eliminare l\'area ${a['codice']}?', 'Si può eliminare solo un\'area senza processi.')
        : await conferma(context, 'Proporre l\'eliminazione?', 'Si prepara la proposta di eliminare l\'area ${a['codice']} '
            '(solo se non ha processi): decide il RPCT.');
    if (!ok || !mounted) return;
    try {
      if (rpct) {
        await apiDi(context).delete('$apiAnticorruzione/aree/${a['id']}');
        widget.onDatiCambiati();
      } else {
        await _proponi({'tipo': 'ELIMINA', 'oggetto': 'AREA', 'elemento_id': a['id']});
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _nuovoProcesso(DatiAnticorruzione dati, bool rpct) async {
    final v = await modificaProcesso(context, dati, {
      'area_id': _area == _senzaArea ? null : _area,
      // il referente propone per la sua struttura
      if (!rpct) 'struttura_id': context.read<AuthState>().utente?.strutturaId,
    });
    if (v == null || !mounted) return;
    try {
      if (rpct) {
        final p = await apiDi(context).post('$apiAnticorruzione/processi', v) as Map<String, dynamic>;
        if (mounted) setState(() => _processoId = p['id'] as String);
      } else {
        await _proponi({'tipo': 'CREA', 'oggetto': 'PROCESSO', 'dati': {...v, 'attivita': <Object>[]}});
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _elencoProcessi(DatiAnticorruzione dati, List<Map<String, dynamic>> processi) => Column(children: [
        for (final p in processi)
          RigaVoce(
            icona: p['tipo'] == 'PROCEDIMENTO' ? Icons.gavel_outlined : Icons.account_tree_outlined,
            titolo: '${p['codice']} - ${p['denominazione']}',
            dettagli: [
              etichettaTipo(p['tipo']),
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
        if (cerca.isEmpty)
          FilledButton.icon(
            onPressed: () => _modificaArea(rpct),
            icon: const Icon(Icons.add),
            label: Text(rpct ? 'Nuova area' : 'Proponi un\'area'),
          ),
        if (cerca.isEmpty && rpct) const PubblicazioneMappatura(),
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
                IconaAzione(Icons.edit_outlined, rpct ? 'Modifica l\'area' : 'Proponi la modifica dell\'area', () => _modificaArea(rpct, a)),
                IconaAzione(Icons.delete_outline, rpct ? 'Elimina l\'area' : 'Proponi l\'eliminazione dell\'area', () => _eliminaArea(rpct, a)),
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
          width: 180,
          child: DropdownButtonFormField<String?>(
            initialValue: _tipo,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Tipo', isDense: true),
            items: const [
              DropdownMenuItem(value: null, child: Text('Tutti')),
              DropdownMenuItem(value: 'PROCESSO', child: Text('Processi')),
              DropdownMenuItem(value: 'PROCEDIMENTO', child: Text('Procedimenti')),
            ],
            onChanged: (v) {
              _tipo = v;
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
          label: Text(rpct ? 'Nuovo processo o procedimento' : 'Proponi un processo o procedimento'),
        ),
      ]),
      const SizedBox(height: 16),
      if (dellArea.isEmpty) const Center(child: Text('Nessun processo o procedimento.')) else _elencoProcessi(dati, dellArea),
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

/// Terzo e quarto livello: il processo con l'elenco delle attività e, aprendone una, i suoi
/// rischi con le misure. Il RPCT modifica direttamente; il referente, sui processi della sua
/// struttura, con gli stessi pulsanti prepara una proposta per ogni modifica.
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

  void _inviata() {
    if (mounted) propostaInviata(context);
    _carica();
  }

  Future<void> _elimina(OperazioniAlbero ops) async {
    if (!await confermaEliminazione(context, 'il processo', proposta: ops.proposta) || !mounted) return;
    try {
      final api = apiDi(context);
      if (ops.proposta) {
        await api.post('$apiAnticorruzione/proposte', {
          'tipo': 'ELIMINA',
          'oggetto': 'PROCESSO',
          'elemento_id': widget.processoId,
        });
        _inviata();
      } else {
        await api.delete('$apiAnticorruzione/processi/${widget.processoId}');
        widget.onChiuso();
      }
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
          IconaAzione(Icons.edit_outlined, etichettaAzione(ops, 'Modifica l\'attività'), () => eseguiOperazione(context, _carica, () async {
                final v = await modificaAttivita(context, a);
                if (v != null) await ops.modificaAttivita(a, v);
              })),
          IconaAzione(Icons.delete_outline, etichettaAzione(ops, 'Elimina l\'attività'), () => eseguiOperazione(context, _carica, () async {
                if (await confermaEliminazione(context, 'l\'attività', proposta: ops.proposta)) await ops.eliminaAttivita(a);
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
              label: Text(etichettaAzione(ops, 'Modifica')),
              onPressed: () => eseguiOperazione(context, _carica, () async {
                final v = await modificaAttivita(context, a);
                if (v != null) await ops.modificaAttivita(a, v);
              }),
            ),
            TextButton.icon(
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              icon: const Icon(Icons.delete_outline, size: 18),
              label: Text(etichettaAzione(ops, 'Elimina')),
              onPressed: () => eseguiOperazione(context, _carica, () async {
                if (await confermaEliminazione(context, 'l\'attività', proposta: ops.proposta)) {
                  await ops.eliminaAttivita(a);
                  if (!ops.proposta) _attivitaId = null;
                }
              }),
            ),
          ],
        ],
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${a['descrizione']}'),
          if (a['strutture_coinvolte'] != null) Text('Strutture coinvolte: ${a['strutture_coinvolte']}'),
        ]),
      ),
      Sezione(
        titolo: 'Rischi e misure',
        azioni: [
          if (ops != null)
            FilledButton.icon(
              icon: const Icon(Icons.add_alert_outlined, size: 18),
              label: Text(etichettaAzione(ops, 'Aggiungi un rischio')),
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
  List<Widget> _livelloProcesso(DatiAnticorruzione dati, Map<String, dynamic> albero, OperazioniAlbero? ops) {
    final processo = albero['processo'] as Map<String, dynamic>;
    final attivita = (albero['attivita'] as List).cast<Map<String, dynamic>>();
    return [
      IntestazioneProcesso(
        dati: dati,
        processo: processo,
        azioni: [
          if (ops != null) ...[
            TextButton.icon(
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: Text(etichettaAzione(ops, 'Modifica')),
              onPressed: () => eseguiOperazione(context, _carica, () async {
                final v = await modificaProcesso(context, dati, processo);
                if (v != null) await ops.processo(v);
              }),
            ),
            TextButton.icon(
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              icon: const Icon(Icons.delete_outline, size: 18),
              label: Text(etichettaAzione(ops, 'Elimina')),
              onPressed: () => _elimina(ops),
            ),
          ],
        ],
      ),
      Row(children: [
        Expanded(child: Text('Attività', style: Theme.of(context).textTheme.titleMedium)),
        if (ops != null)
          FilledButton.icon(
            icon: const Icon(Icons.add, size: 18),
            label: Text(etichettaAzione(ops, 'Nuova attività')),
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
        final OperazioniAlbero? operazioni = rpct
            ? OperazioniDirette(apiDi(context), widget.processoId)
            : albero['proponibile'] == true
                ? OperazioniProposte(apiDi(context), widget.processoId, _inviata)
                : null;
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
            ..._livelloProcesso(dati, albero, operazioni),
        ]);
      },
    );
  }
}

/// Interruttore del RPCT: la mappatura consultabile dai cittadini su /pubblico/mappatura,
/// con il link da mettere sul sito dell'ente.
class PubblicazioneMappatura extends StatefulWidget {
  const PubblicazioneMappatura({super.key});

  @override
  State<PubblicazioneMappatura> createState() => _PubblicazioneMappaturaState();
}

class _PubblicazioneMappaturaState extends State<PubblicazioneMappatura> {
  bool? _attiva; // null finché non si conosce lo stato
  String _percorso = '/pubblico/mappatura';

  @override
  void initState() {
    super.initState();
    _leggi();
  }

  void _imposta(Object? v) {
    if (v is! Map || !mounted) return;
    setState(() {
      _attiva = v['attiva'] == true;
      _percorso = v['percorso'] as String? ?? _percorso;
    });
  }

  Future<void> _leggi() async {
    try {
      _imposta(await apiDi(context).get('$apiAnticorruzione/pubblicazione'));
    } catch (_) {
      // senza lo stato l'interruttore non compare
    }
  }

  Future<void> _cambia(bool attiva) async {
    if (attiva &&
        !await conferma(context, 'Pubblicare la mappatura?', 'Aree, processi, attività, rischi con il livello e misure '
            'saranno consultabili da chiunque, senza accesso, all\'indirizzo ${_link()}. I valori degli indicatori e '
            'le motivazioni delle correzioni restano riservati.')) {
      return;
    }
    if (!mounted) return;
    try {
      _imposta(await apiDi(context).put('$apiAnticorruzione/pubblicazione', {'attiva': attiva}));
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  String _link() => '${Uri.base.origin}$_percorso';

  @override
  Widget build(BuildContext context) {
    final attiva = _attiva;
    if (attiva == null) return const SizedBox.shrink();
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Switch(value: attiva, onChanged: _cambia),
      const SizedBox(width: 4),
      Text(attiva ? 'Pubblicata per i cittadini' : 'Pubblica per i cittadini'),
      if (attiva)
        IconaAzione(Icons.link, 'Copia il link da mettere sul sito dell\'ente', () async {
          await Clipboard.setData(ClipboardData(text: _link()));
          if (context.mounted) mostraMessaggio(context, 'Link copiato: ${_link()}');
        }),
    ]);
  }
}
