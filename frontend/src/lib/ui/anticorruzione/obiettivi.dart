import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../stato/auth_state.dart';
import '../../util/scelta_file.dart';
import '../comuni.dart';
import 'comune.dart';
import 'mappatura.dart';

/// PIAO dell'ente e obiettivi di performance: il RPCT gestisce i PIAO e importa gli
/// obiettivi dal file del Piano; tutti collegano gli obiettivi a processi e attività.
/// Si sceglie il PIAO in alto, sotto compare l'elenco dei suoi obiettivi.
class ObiettiviTab extends StatefulWidget {
  const ObiettiviTab({super.key});

  @override
  State<ObiettiviTab> createState() => _ObiettiviTabState();
}

class _ObiettiviTabState extends State<ObiettiviTab> {
  List<Map<String, dynamic>> _piao = const [];
  String? _piaoId;
  String? _struttura;
  final _testo = TextEditingController();
  Future<List<Map<String, dynamic>>>? _obiettivi;
  String? _obiettivoId; // obiettivo aperto: prende il posto dell'elenco nella scheda
  Object? _errore;

  @override
  void initState() {
    super.initState();
    _caricaPiao();
  }

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  Future<void> _caricaPiao({String? scegli}) async {
    try {
      final v = (await apiDi(context).get('$apiAnticorruzione/piao') as List).cast<Map<String, dynamic>>();
      if (!mounted) return;
      setState(() {
        _piao = v;
        _piaoId = scegli ?? (v.any((p) => p['id'] == _piaoId) ? _piaoId : (v.isEmpty ? null : v.first['id'] as String));
        _errore = null;
      });
      _carica();
    } catch (e) {
      if (mounted) setState(() => _errore = e);
    }
  }

  void _carica() => setState(() {
        _obiettivi = _piaoId == null
            ? null
            : apiDi(context).get('$apiAnticorruzione/piao/$_piaoId/obiettivi', query: {
                'struttura': ?_struttura,
                if (_testo.text.trim().isNotEmpty) 'testo': _testo.text.trim(),
              }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  Future<void> _modificaPiao([Map<String, dynamic>? p]) async {
    final v = await modificaCampi(context, titolo: p == null ? 'Nuovo PIAO' : 'PIAO', valori: p ?? {
      'anno_inizio': DateTime.now().year,
      'anno_fine': DateTime.now().year + 2,
    }, campi: const [
      Campo('anno_inizio', 'Anno iniziale', obbligatorio: true),
      Campo('anno_fine', 'Anno finale', obbligatorio: true),
      Campo('descrizione', 'Descrizione', obbligatorio: true, aiuto: 'es. PIAO 2026-2028'),
      Campo('atto', 'Atto di approvazione', aiuto: 'es. DGC n. 59 del 26/03/2026'),
    ]);
    if (v == null || !mounted) return;
    final corpo = {...v, 'anno_inizio': int.tryParse('${v['anno_inizio']}'), 'anno_fine': int.tryParse('${v['anno_fine']}')};
    try {
      final api = apiDi(context);
      final r = p == null
          ? await api.post('$apiAnticorruzione/piao', corpo) as Map<String, dynamic>
          : await api.put('$apiAnticorruzione/piao/${p['id']}', corpo) as Map<String, dynamic>;
      await _caricaPiao(scegli: r['id'] as String);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _eliminaPiao(Map<String, dynamic> p) async {
    if (!await conferma(context, 'Eliminare ${p['descrizione']}?', 'Si eliminano anche gli obiettivi e i loro collegamenti.')) return;
    if (!mounted) return;
    try {
      await apiDi(context).delete('$apiAnticorruzione/piao/${p['id']}');
      _piaoId = null;
      await _caricaPiao();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _importa() async {
    final file = await scegliFile(['xlsx', 'xls', 'csv']);
    if (file == null || !mounted) return;
    try {
      final r = await apiDi(context).postMultipart('$apiAnticorruzione/piao/$_piaoId/obiettivi/importa',
          campi: {}, campoFile: 'file', bytes: file.bytes, nomeFile: file.name) as Map<String, dynamic>;
      if (!mounted) return;
      final avvisi = [
        if ((r['centri_non_abbinati'] as List).isNotEmpty)
          'Centri del Piano senza struttura corrispondente: ${(r['centri_non_abbinati'] as List).join(', ')} '
              '(assegna la struttura a mano o aggiungila in Amministrazione → Strutture organizzative).',
        if ((r['anni_fuori_dal_piao'] as List).isNotEmpty) 'Anni fuori dal PIAO: ${(r['anni_fuori_dal_piao'] as List).join(', ')}.',
      ];
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Importazione degli obiettivi'),
          content: Text(['Obiettivi nuovi: ${r['creati']}, aggiornati: ${r['aggiornati']}.', ...avvisi].join('\n\n')),
          actions: [FilledButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
        ),
      );
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _modificaObiettivo(DatiAnticorruzione dati, [Map<String, dynamic>? o]) async {
    final v = await modificaCampi(context, titolo: o == null ? 'Nuovo obiettivo' : 'Obiettivo ${o['codice']}',
        valori: o ?? {'anno': DateTime.now().year}, campi: [
      const Campo('codice', 'Codice', obbligatorio: true),
      const Campo('anno', 'Anno', obbligatorio: true),
      const Campo('titolo', 'Titolo', righe: 3),
      const Campo('tipo', 'Tipo', aiuto: 'es. Operativo, Funzionamento, Miglioramento'),
      Campo('struttura_id', 'Struttura assegnataria', scelte: [
        (null, 'Nessuna'),
        for (final s in dati.strutture.where((s) => s['attiva'] == true)) (s['id'] as String, '${s['codice']} - ${s['descrizione']}'),
      ]),
      const Campo('responsabile', 'Responsabile'),
    ]);
    if (v == null || !mounted) return;
    final corpo = {...?o, ...v, 'anno': int.tryParse('${v['anno']}')};
    try {
      final api = apiDi(context);
      if (o == null) {
        await api.post('$apiAnticorruzione/piao/$_piaoId/obiettivi', corpo);
      } else {
        await api.put('$apiAnticorruzione/obiettivi/${o['id']}', corpo);
      }
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  void _scegliPiao(String id) {
    if (id == _piaoId) return;
    _piaoId = id;
    _carica();
  }

  void _chiudiObiettivo() {
    _obiettivoId = null;
    _carica(); // il numero dei collegamenti può essere cambiato
  }

  /// PIAO in lavorazione, in evidenza: selettore, estremi e azioni.
  Widget _selettorePiao(Map<String, dynamic>? piao, bool rpct) {
    final colori = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: piao == null ? null : colori.primaryContainer,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: piao == null ? colori.outlineVariant : colori.primary, width: piao == null ? 1 : 2),
      ),
      child: Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        if (_piao.isNotEmpty)
          SizedBox(
            width: 320,
            child: DropdownButtonFormField<String>(
              key: ValueKey(_piaoId), // dopo una creazione il selettore segue il nuovo PIAO
              initialValue: _piaoId,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'PIAO', isDense: true),
              items: [for (final p in _piao) DropdownMenuItem(value: p['id'] as String, child: Text('${p['descrizione']}'))],
              onChanged: (v) {
                if (v != null) _scegliPiao(v);
              },
            ),
          ),
        if (piao != null) Text('${piao['anno_inizio']}-${piao['anno_fine']}${piao['atto'] != null ? ' · ${piao['atto']}' : ''}'),
        if (rpct) ...[
          if (piao != null) ...[
            IconaAzione(Icons.edit_outlined, 'Modifica il PIAO', () => _modificaPiao(piao)),
            IconaAzione(Icons.delete_outline, 'Elimina il PIAO', () => _eliminaPiao(piao)),
          ],
          OutlinedButton.icon(onPressed: () => _modificaPiao(), icon: const Icon(Icons.add), label: const Text('Nuovo PIAO')),
        ],
      ]),
    );
  }

  Widget _rigaObiettivo(DatiAnticorruzione dati, Map<String, dynamic> o, bool rpct) {
    final collegamenti = o['collegamenti'] as int;
    return RigaVoce(
      icona: Icons.flag_outlined,
      titolo: '${o['codice']} (${o['anno']})${o['titolo'] != null ? ' - ${o['titolo']}' : ''}',
      dettagli: [
        if (o['tipo'] != null) '${o['tipo']}',
        '${o['struttura_id'] != null ? dati.struttura(o['struttura_id']) ?? '' : (o['centro_piano'] ?? 'Senza struttura')}',
        collegamenti == 1 ? '1 collegamento' : '$collegamenti collegamenti',
      ],
      onTap: () => setState(() => _obiettivoId = o['id'] as String),
      finale: [if (rpct) IconaAzione(Icons.edit_outlined, 'Modifica', () => _modificaObiettivo(dati, o))],
    );
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    if (_errore != null) return Center(child: Text('$_errore'));
    if (_obiettivoId != null) {
      return ObiettivoDettaglio(key: ValueKey(_obiettivoId), obiettivoId: _obiettivoId!, onIndietro: _chiudiObiettivo);
    }
    final piao = _piao.where((p) => p['id'] == _piaoId).firstOrNull;
    final testi = Theme.of(context).textTheme;
    return ListView(padding: const EdgeInsets.all(16), children: [
      _selettorePiao(piao, rpct),
      if (_piao.isEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 12),
          child: Text(rpct ? 'Nessun PIAO: crealo e importa gli obiettivi dal file del Piano.' : 'Nessun PIAO registrato.'),
        ),
      if (piao != null) ...[
        const Divider(height: 32),
        Text('Obiettivi di ${piao['descrizione']}', style: testi.titleMedium),
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
            width: 220,
            child: TextField(
              controller: _testo,
              decoration: InputDecoration(
                labelText: 'Cerca',
                isDense: true,
                suffixIcon: IconButton(icon: const Icon(Icons.search), onPressed: _carica),
              ),
              onSubmitted: (_) => _carica(),
            ),
          ),
          if (rpct) ...[
            OutlinedButton.icon(onPressed: _importa, icon: const Icon(Icons.upload_file), label: const Text('Importa obiettivi')),
            TextButton.icon(onPressed: () => _modificaObiettivo(dati), icon: const Icon(Icons.flag_outlined), label: const Text('Nuovo obiettivo')),
          ],
        ]),
        const SizedBox(height: 16),
        if (_obiettivi != null)
          Caricamento<List<Map<String, dynamic>>>(
            future: _obiettivi!,
            riprova: _carica,
            builder: (context, obiettivi) => obiettivi.isEmpty
                ? const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Nessun obiettivo.')))
                : Column(children: [for (final o in obiettivi) _rigaObiettivo(dati, o, rpct)]),
          ),
      ],
    ]);
  }
}

/// Obiettivo con i processi e le attività collegati; si collegano processi interi (con le
/// attività presenti e future) o singole attività.
class ObiettivoDettaglio extends StatefulWidget {
  const ObiettivoDettaglio({super.key, required this.obiettivoId, required this.onIndietro});

  final String obiettivoId;
  final VoidCallback onIndietro;

  @override
  State<ObiettivoDettaglio> createState() => _ObiettivoDettaglioState();
}

class _ObiettivoDettaglioState extends State<ObiettivoDettaglio> {
  late Future<Map<String, dynamic>> _obiettivo;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _obiettivo = apiDi(context).get('$apiAnticorruzione/obiettivi/${widget.obiettivoId}').then((v) => v as Map<String, dynamic>);
      });

  /// Scelta di un processo intero o di una sua attività, nell'albero area → processo → attività.
  Future<void> _collega() async {
    final api = apiDi(context);
    final aree = context.read<DatiAnticorruzione>().aree;
    try {
      final processi = (await api.get('$apiAnticorruzione/processi') as List).cast<Map<String, dynamic>>();
      final collegati = ((await _obiettivo)['collegamenti'] as List).map((c) => c['elemento_id'] as String?).toSet();
      if (!mounted) return;
      final scelta = await showDialog<Map<String, String>>(
        context: context,
        builder: (_) => _SceltaCollegamento(api: api, aree: aree, processi: processi, collegati: collegati),
      );
      if (scelta == null) return;
      await api.post('$apiAnticorruzione/obiettivi/${widget.obiettivoId}/collegamenti', scelta);
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    return Caricamento<Map<String, dynamic>>(
        future: _obiettivo,
        riprova: _carica,
        builder: (context, o) => ListView(padding: const EdgeInsets.all(16), children: [
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(onPressed: widget.onIndietro, icon: const Icon(Icons.arrow_back), label: const Text('Tutti gli obiettivi')),
          ),
          const SizedBox(height: 8),
          Sezione(
            titolo: '${o['codice']} (${o['anno']})',
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (o['titolo'] != null) Text(o['titolo'] as String),
              const SizedBox(height: 4),
              Text([
                if (o['tipo'] != null) 'Tipo: ${o['tipo']}',
                'Struttura: ${o['struttura_id'] != null ? dati.struttura(o['struttura_id']) : '—'}',
                if (o['centro_piano'] != null) 'Centro nel Piano: ${o['centro_piano']}',
                if (o['responsabile'] != null) 'Responsabile: ${o['responsabile']}',
              ].join(' · ')),
            ]),
          ),
          Sezione(
            titolo: 'Processi e attività collegati',
            azioni: [
              FilledButton.icon(onPressed: _collega, icon: const Icon(Icons.link), label: const Text('Collega un processo o un\'attività')),
            ],
            child: Column(children: [
              if ((o['collegamenti'] as List).isEmpty) const Text('Nessun collegamento.'),
              for (final c in (o['collegamenti'] as List).cast<Map<String, dynamic>>())
                ListTile(
                  leading: Icon(c['tipo'] == 'processo' ? Icons.account_tree_outlined : Icons.subdirectory_arrow_right),
                  title: Text('${c['codice']} - ${c['descrizione']}'),
                  subtitle: Text(c['tipo'] == 'processo' ? 'Processo intero, con tutte le attività' : 'Attività del processo ${c['processo']}'),
                  onTap: () => apriProcesso(context, c['processo_id'] as String),
                  trailing: IconButton(
                    tooltip: 'Scollega',
                    icon: const Icon(Icons.link_off),
                    onPressed: () async {
                      try {
                        await apiDi(context).delete('$apiAnticorruzione/collegamenti/${c['id']}');
                        _carica();
                      } catch (e) {
                        if (context.mounted) mostraErrore(context, e);
                      }
                    },
                  ),
                ),
            ]),
          ),
        ]),
    );
  }
}

/// Albero per scegliere cosa collegare: aree di rischio, loro processi e, aprendo un processo,
/// il processo intero o una delle sue attività. Restituisce il corpo del collegamento.
class _SceltaCollegamento extends StatefulWidget {
  const _SceltaCollegamento({required this.api, required this.aree, required this.processi, required this.collegati});

  final ApiClient api;
  final List<Map<String, dynamic>> aree;
  final List<Map<String, dynamic>> processi;
  final Set<String?> collegati; // id di processi e attività già collegati all'obiettivo

  @override
  State<_SceltaCollegamento> createState() => _SceltaCollegamentoState();
}

class _SceltaCollegamentoState extends State<_SceltaCollegamento> {
  final _filtro = TextEditingController();
  final Map<String, Future<List<Map<String, dynamic>>>> _attivita = {}; // lette aprendo il processo

  @override
  void dispose() {
    _filtro.dispose();
    super.dispose();
  }

  Future<List<Map<String, dynamic>>> _attivitaDi(String processoId) => _attivita[processoId] ??= widget.api
      .get('$apiAnticorruzione/processi/$processoId')
      .then((v) => ((v as Map<String, dynamic>)['attivita'] as List).cast<Map<String, dynamic>>());

  Widget _voce({required IconData icona, required String testo, required bool collegata, required Map<String, String> corpo, double rientro = 32}) {
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.only(left: rientro, right: 16),
      leading: Icon(icona, size: 20),
      title: Text(testo),
      subtitle: collegata ? const Text('Già collegato') : null,
      enabled: !collegata,
      onTap: () => Navigator.pop(context, corpo),
    );
  }

  Widget _processo(Map<String, dynamic> p) {
    final id = p['id'] as String;
    return ExpansionTile(
      tilePadding: const EdgeInsets.only(left: 16, right: 12),
      childrenPadding: const EdgeInsets.only(left: 16),
      leading: const Icon(Icons.account_tree_outlined, size: 20),
      title: Text('${p['codice']} - ${p['denominazione']}', style: Theme.of(context).textTheme.bodyMedium),
      children: [
        _voce(
          icona: Icons.link,
          testo: 'Tutto il processo (anche le attività aggiunte in futuro)',
          collegata: widget.collegati.contains(id),
          corpo: {'processo_id': id},
        ),
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _attivitaDi(id),
          builder: (context, stato) {
            if (stato.hasError) return Padding(padding: const EdgeInsets.all(12), child: Text('${stato.error}'));
            if (!stato.hasData) return const Padding(padding: EdgeInsets.all(12), child: LinearProgressIndicator());
            return Column(children: [
              for (final a in stato.data!)
                _voce(
                  icona: Icons.subdirectory_arrow_right,
                  testo: 'Attività ${a['codice']} - ${a['descrizione']}',
                  collegata: widget.collegati.contains(a['id']),
                  corpo: {'attivita_id': a['id'] as String},
                ),
            ]);
          },
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final cerca = _filtro.text.trim().toLowerCase();
    final visibili = widget.processi.where((p) => '${p['codice']} ${p['denominazione']}'.toLowerCase().contains(cerca)).toList();
    final idAree = widget.aree.map((a) => a['id']).toSet();
    final gruppi = [
      for (final a in widget.aree)
        ('${a['codice']}) ${a['descrizione_breve'] ?? a['descrizione']}', visibili.where((p) => p['area_id'] == a['id']).toList()),
      ('Senza area', visibili.where((p) => !idAree.contains(p['area_id'])).toList()),
    ].where((g) => g.$2.isNotEmpty).toList();
    return AlertDialog(
      title: const Text('Collega un processo o un\'attività'),
      content: SizedBox(
        width: 680,
        height: 520,
        child: Column(children: [
          TextField(
            controller: _filtro,
            decoration: const InputDecoration(labelText: 'Cerca un processo', prefixIcon: Icon(Icons.search)),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: gruppi.isEmpty
                ? const Center(child: Text('Nessun processo.'))
                : ListView(children: [
                    for (final (titolo, processi) in gruppi)
                      ExpansionTile(
                        // cercando, le aree con dei risultati si aprono da sole
                        key: ValueKey('$titolo-${cerca.isNotEmpty}'),
                        initiallyExpanded: cerca.isNotEmpty,
                        tilePadding: const EdgeInsets.symmetric(horizontal: 4),
                        title: Text(titolo, style: const TextStyle(fontWeight: FontWeight.w600)),
                        subtitle: Text(processi.length == 1 ? '1 processo' : '${processi.length} processi'),
                        children: [for (final p in processi) _processo(p)],
                      ),
                  ]),
          ),
        ]),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla'))],
    );
  }
}
