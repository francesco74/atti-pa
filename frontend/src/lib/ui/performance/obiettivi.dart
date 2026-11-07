import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../anticorruzione/comune.dart' show Percorso, IconaAzione;
import '../comuni.dart';
import 'comune.dart';

/// Obiettivi di una struttura in un anno del PIAO, con il totale degli impegni e il
/// completamento; aprendone uno, le sue azioni e misure e lo storico delle modifiche. Il
/// responsabile modifica quelli della sua struttura, l'amministratore tutti.
class ObiettiviTab extends StatefulWidget {
  const ObiettiviTab({super.key});

  @override
  State<ObiettiviTab> createState() => _ObiettiviTabState();
}

class _ObiettiviTabState extends State<ObiettiviTab> with AutomaticKeepAliveClientMixin {
  String? _piaoId;
  int? _anno;
  String? _strutturaId;
  String? _obiettivoId; // obiettivo aperto
  Future<Map<String, dynamic>>? _elenco;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    final dati = context.read<DatiPerformance>();
    final piao = dati.piaoPredefinito;
    _piaoId = piao?['id'] as String?;
    _anno = piao == null ? null : annoPredefinito(piao);
    final visibili = dati.struttureVisibili;
    _strutturaId = visibili.any((s) => s['id'] == dati.strutturaUtente)
        ? dati.strutturaUtente
        : visibili.firstOrNull?['id'] as String?;
    _carica();
  }

  void _carica() {
    if (_piaoId == null || _strutturaId == null) return;
    setState(() {
      _elenco = apiDi(context).get('$apiPerformance/obiettivi', query: {
        'piao_id': _piaoId!,
        'anno': '$_anno',
        'struttura_id': _strutturaId!,
      }).then((v) => v as Map<String, dynamic>);
    });
  }

  Future<void> _nuovo(int disponibile) async {
    final v = await modificaObiettivo(context, disponibile: disponibile);
    if (v == null || !mounted) return;
    try {
      final o = await apiDi(context).post('$apiPerformance/obiettivi', {
        ...v,
        'piao_id': _piaoId,
        'anno': _anno,
        'struttura_id': _strutturaId,
      }) as Map<String, dynamic>;
      if (mounted) setState(() => _obiettivoId = o['id'] as String);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _filtri(DatiPerformance dati) {
    final piao = dati.piaoDi(_piaoId);
    return Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
      SizedBox(
        width: 240,
        child: DropdownButtonFormField<String>(
          initialValue: _piaoId,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'PIAO', isDense: true),
          items: [
            for (final p in dati.piao)
              DropdownMenuItem(
                value: p['id'] as String,
                child: Text('${p['titolo']}${p['stato'] == 'CHIUSO' ? ' (chiuso)' : ''}', overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: (v) {
            _piaoId = v;
            final p = dati.piaoDi(v);
            if (p != null && !(p['anni'] as List).contains(_anno)) _anno = annoPredefinito(p);
            _carica();
          },
        ),
      ),
      if (piao != null)
        SegmentedButton<int>(
          segments: [for (final a in (piao['anni'] as List).cast<int>()) ButtonSegment(value: a, label: Text('$a'))],
          selected: {_anno!},
          onSelectionChanged: (s) {
            _anno = s.first;
            _carica();
          },
        ),
      SizedBox(
        width: 320,
        child: DropdownButtonFormField<String>(
          initialValue: _strutturaId,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Struttura', isDense: true),
          items: [
            for (final s in dati.struttureVisibili)
              DropdownMenuItem(value: s['id'] as String, child: Text('${s['codice']} - ${s['descrizione']}', overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (v) {
            _strutturaId = v;
            _carica();
          },
        ),
      ),
    ]);
  }

  Widget _riga(Map<String, dynamic> o) => Card(
        child: InkWell(
          onTap: () => setState(() => _obiettivoId = o['id'] as String),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              const Icon(Icons.flag_outlined),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(o['codice'] == null ? '${o['titolo']}' : '${o['codice']} - ${o['titolo']}',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    Text('${etichettaTipoObiettivo(o['tipo'])} · impegno ${o['impegno']}% · '
                        '${o['azioni']} azioni, ${o['misure']} misure'),
                    if (o['completo'] != true) Etichetta('Impegni ${o['impegno_elementi']}% su 100%', Colors.red),
                    if ((o['ritardi'] as int) > 0) Etichetta('${o['ritardi']} in ritardo', Colors.orange),
                    if (((o['avvisi'] as int?) ?? 0) > 0)
                      Etichetta(o['avvisi'] == 1 ? '1 avviso' : '${o['avvisi']} avvisi', Colors.deepOrange),
                  ]),
                ]),
              ),
              BarraCompletamento(o['completamento'] as num?),
            ]),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final dati = context.watch<DatiPerformance>();
    if (dati.piao.isEmpty) {
      return Center(
        child: Text(dati.amministratore
            ? 'Nessun PIAO: crealo nella scheda PIAO.'
            : 'Nessun PIAO: lo apre l\'amministratore della performance.'),
      );
    }
    if (dati.struttureVisibili.isEmpty) {
      return const Center(child: Text('Il tuo utente non ha una struttura: sceglila nel profilo.'));
    }
    if (_obiettivoId != null) {
      return VistaObiettivo(
        key: ValueKey(_obiettivoId),
        obiettivoId: _obiettivoId!,
        onChiuso: () {
          setState(() => _obiettivoId = null);
          _carica();
        },
      );
    }
    return Caricamento<Map<String, dynamic>>(
      future: _elenco!,
      riprova: _carica,
      builder: (context, elenco) {
        final obiettivi = (elenco['obiettivi'] as List).cast<Map<String, dynamic>>();
        final totale = elenco['impegno_totale'] as int;
        return ListView(padding: const EdgeInsets.all(16), children: [
          _filtri(dati),
          const SizedBox(height: 16),
          Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            TotaleImpegno(totale),
            Row(mainAxisSize: MainAxisSize.min, children: [
              const Text('Completamento della struttura: '),
              BarraCompletamento(elenco['completamento'] as num?),
            ]),
            if (elenco['modificabile'] == true && totale < 100)
              FilledButton.icon(
                onPressed: () => _nuovo(100 - totale),
                icon: const Icon(Icons.add),
                label: const Text('Nuovo obiettivo'),
              ),
          ]),
          const SizedBox(height: 16),
          if (obiettivi.isEmpty) const Center(child: Text('Nessun obiettivo per la struttura in questo anno.')),
          for (final o in obiettivi) _riga(o),
        ]);
      },
    );
  }
}

/// Obiettivo con le azioni e le misure (impegno, completamento, scadenza) e lo storico.
class VistaObiettivo extends StatefulWidget {
  const VistaObiettivo({super.key, required this.obiettivoId, required this.onChiuso});

  final String obiettivoId;
  final VoidCallback onChiuso; // torna all'elenco (anche dopo l'eliminazione)

  @override
  State<VistaObiettivo> createState() => _VistaObiettivoState();
}

class _VistaObiettivoState extends State<VistaObiettivo> {
  late Future<Map<String, dynamic>> _obiettivo;
  Future<List<Map<String, dynamic>>>? _storico;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _obiettivo = apiDi(context).get('$apiPerformance/obiettivi/${widget.obiettivoId}').then((v) => v as Map<String, dynamic>);
        if (_storico != null) _caricaStorico();
      });

  void _caricaStorico() {
    _storico = apiDi(context)
        .get('$apiPerformance/obiettivi/${widget.obiettivoId}/storico')
        .then((v) => (v as List).cast<Map<String, dynamic>>());
  }

  Future<void> _esegui(Future<void> Function() azione) async {
    try {
      await azione();
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<int> _disponibileObiettivi(Map<String, dynamic> o) async {
    final elenco = await apiDi(context).get('$apiPerformance/obiettivi', query: {
      'piao_id': o['piao_id'] as String,
      'anno': '${o['anno']}',
      'struttura_id': o['struttura_id'] as String,
    }) as Map<String, dynamic>;
    return 100 - (elenco['impegno_totale'] as int) + (o['impegno'] as int);
  }

  Future<void> _modifica(Map<String, dynamic> o) => _esegui(() async {
        final disponibile = await _disponibileObiettivi(o);
        if (!mounted) return;
        final v = await modificaObiettivo(context, o: o, disponibile: disponibile);
        if (v != null && mounted) await apiDi(context).put('$apiPerformance/obiettivi/${o['id']}', v);
      });

  Future<void> _elimina(Map<String, dynamic> o) async {
    final nota = await confermaConNota(context, 'Eliminare l\'obiettivo?', 'Si eliminano anche le sue azioni e misure; '
        'l\'eliminazione resta nello storico del PIAO.');
    if (nota == null || !mounted) return;
    try {
      await apiDi(context).delete('$apiPerformance/obiettivi/${o['id']}', {if (nota.isNotEmpty) 'nota': nota});
      widget.onChiuso();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _nuovoElemento(Map<String, dynamic> o, String tipo) => _esegui(() async {
        final elementi = (o['elementi'] as List).cast<Map<String, dynamic>>();
        Map<String, dynamic>? misura;
        if (tipo == 'MISURA') {
          misura = await scegliMisura(context, o['struttura_id'] as String, {for (final x in elementi) ?x['misura_id'] as String?});
          if (misura == null || !mounted) return;
        }
        final v = await modificaElemento(context,
            tipo: tipo, misura: misura, disponibile: 100 - (o['impegno_elementi'] as int), anno: o['anno'] as int);
        if (v == null || !mounted) return;
        await apiDi(context).post('$apiPerformance/obiettivi/${o['id']}/elementi', {
          ...v,
          'tipo': tipo,
          if (misura != null) 'misura_id': misura['id'],
        });
      });

  Future<void> _modificaElemento(Map<String, dynamic> o, Map<String, dynamic> x) => _esegui(() async {
        final v = await modificaElemento(context,
            tipo: x['tipo'] as String,
            x: x,
            disponibile: 100 - (o['impegno_elementi'] as int) + (x['impegno'] as int),
            anno: o['anno'] as int);
        if (v != null && mounted) await apiDi(context).put('$apiPerformance/elementi/${x['id']}', v);
      });

  Future<void> _eliminaElemento(Map<String, dynamic> x) async {
    final nota = await confermaConNota(context, x['tipo'] == 'AZIONE' ? 'Eliminare l\'azione?' : 'Togliere la misura dall\'obiettivo?',
        'L\'eliminazione resta nello storico dell\'obiettivo.');
    if (nota == null || !mounted) return;
    await _esegui(() => apiDi(context).delete('$apiPerformance/elementi/${x['id']}', {if (nota.isNotEmpty) 'nota': nota}));
  }

  Widget _rigaElemento(Map<String, dynamic> o, Map<String, dynamic> x) {
    final modificabile = o['modificabile'] == true;
    final misura = x['tipo'] == 'MISURA';
    final ritardo = x['in_ritardo'] == true;
    return ListTile(
      leading: Tooltip(
        message: misura ? 'Misura della mappatura dei rischi' : 'Azione',
        child: Icon(misura ? Icons.shield_outlined : Icons.directions_run),
      ),
      title: Text(misura ? '${x['misura_codice']} - ${x['descrizione']}' : '${x['descrizione']}'),
      subtitle: Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        Text('Impegno ${x['impegno']}% · entro il ${formatData(x['scadenza'])}'),
        if (ritardo) const Etichetta('In ritardo', Colors.orange),
        if (misura && x['misura_id'] == null) const Etichetta('Misura non più nella mappatura', Colors.blueGrey),
      ]),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        BarraCompletamento(x['completamento'] as num?, larghezza: 100),
        if (modificabile) ...[
          IconaAzione(Icons.edit_outlined, 'Modifica', () => _modificaElemento(o, x)),
          IconaAzione(Icons.delete_outline, 'Elimina', () => _eliminaElemento(x)),
        ],
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiPerformance>();
    return Caricamento<Map<String, dynamic>>(
      future: _obiettivo,
      riprova: _carica,
      builder: (context, o) {
        final elementi = (o['elementi'] as List).cast<Map<String, dynamic>>();
        final modificabile = o['modificabile'] == true;
        final impegnoElementi = o['impegno_elementi'] as int;
        final titolo = o['codice'] == null ? '${o['titolo']}' : '${o['codice']} - ${o['titolo']}';
        return ListView(padding: const EdgeInsets.all(16), children: [
          Percorso([
            ('Obiettivi ${o['anno']} · ${dati.struttura(o['struttura_id'])}', widget.onChiuso),
            (titolo, null),
          ]),
          const SizedBox(height: 12),
          Sezione(
            titolo: titolo,
            azioni: [
              if (modificabile) ...[
                TextButton.icon(icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('Modifica'), onPressed: () => _modifica(o)),
                TextButton.icon(
                  style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                  icon: const Icon(Icons.delete_outline, size: 18),
                  label: const Text('Elimina'),
                  onPressed: () => _elimina(o),
                ),
              ],
            ],
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${etichettaTipoObiettivo(o['tipo'])} · ${dati.struttura(o['struttura_id'])} · anno ${o['anno']} · '
                  'impegno ${o['impegno']}% sugli obiettivi della struttura'),
              if (o['descrizione'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('${o['descrizione']}')),
              const SizedBox(height: 8),
              Row(children: [const Text('Completamento: '), BarraCompletamento(o['completamento'] as num?, larghezza: 220)]),
              if ((o['piao'] as Map)['stato'] == 'CHIUSO')
                const Padding(padding: EdgeInsets.only(top: 8), child: Etichetta('PIAO chiuso: sola lettura', Colors.blueGrey)),
            ]),
          ),
          Sezione(
            titolo: 'Azioni e misure',
            azioni: [
              if (modificabile && impegnoElementi < 100) ...[
                TextButton.icon(icon: const Icon(Icons.add, size: 18), label: const Text('Azione'), onPressed: () => _nuovoElemento(o, 'AZIONE')),
                if (dati.misureDisponibili)
                  TextButton.icon(icon: const Icon(Icons.add_moderator_outlined, size: 18), label: const Text('Misura'),
                      onPressed: () => _nuovoElemento(o, 'MISURA')),
              ],
            ],
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Align(alignment: Alignment.centerLeft, child: TotaleImpegno(impegnoElementi, testo: 'Impegno delle azioni e misure')),
              const SizedBox(height: 8),
              if (elementi.isEmpty) const Text('Nessuna azione o misura.'),
              for (final x in elementi) _rigaElemento(o, x),
            ]),
          ),
          if (o['controlli'] != null)
            Sezione(titolo: 'Controlli', child: ElencoControlli((o['controlli'] as List).cast<Map<String, dynamic>>())),
          Card(
            child: ExpansionTile(
              title: const Text('Storico delle modifiche'),
              onExpansionChanged: (aperto) {
                if (aperto && _storico == null) setState(_caricaStorico);
              },
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              children: [
                if (_storico != null)
                  Caricamento<List<Map<String, dynamic>>>(
                    future: _storico!,
                    riprova: () => setState(_caricaStorico),
                    builder: (context, voci) => Storico(voci),
                  ),
              ],
            ),
          ),
        ]);
      },
    );
  }
}
