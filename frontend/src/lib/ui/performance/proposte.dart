import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../anticorruzione/comune.dart' show IconaAzione, RigaVoce;
import '../comuni.dart';
import 'comune.dart';

/// Proposte sugli obiettivi: il responsabile vede quelle delle sue strutture, l'approvatore
/// tutte (partendo da quelle da decidere).
class ProposteTab extends StatefulWidget {
  const ProposteTab({super.key, this.onCambiato});

  final VoidCallback? onCambiato; // dopo una decisione (contatore da decidere)

  @override
  State<ProposteTab> createState() => _ProposteTabState();
}

class _ProposteTabState extends State<ProposteTab> {
  late Future<List<Map<String, dynamic>>> _proposte;
  late String? _stato;

  static const _filtri = {
    'APERTE': 'Non decise',
    'INVIATA': 'In attesa di approvazione',
    'RESTITUITA': 'Restituite',
    'APPROVATA': 'Approvate',
    'RESPINTA': 'Respinte',
    null: 'Tutte',
  };

  @override
  void initState() {
    super.initState();
    _stato = context.read<DatiPerformance>().approvatore ? 'INVIATA' : 'APERTE';
    _carica();
  }

  void _carica() => setState(() {
        _proposte = apiDi(context)
            .get('$apiPerformance/proposte', query: {'stato': ?_stato})
            .then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiPerformance>();
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          for (final f in _filtri.entries)
            ChoiceChip(
              label: Text(f.value),
              selected: _stato == f.key,
              onSelected: (_) {
                _stato = f.key;
                _carica();
              },
            ),
        ]),
      ),
      Expanded(
        child: Caricamento<List<Map<String, dynamic>>>(
          future: _proposte,
          riprova: _carica,
          builder: (context, proposte) => proposte.isEmpty
              ? const Center(
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Text('Nessuna proposta. Si propone dalla scheda Obiettivi: "Nuovo obiettivo", '
                        '"Proponi modifiche" o "Proponi eliminazione".'),
                  ),
                )
              : ListView(padding: const EdgeInsets.all(16), children: [
                  for (final p in proposte)
                    RigaVoce(
                      icona: iconaProposta(p['tipo']),
                      titolo: '${etichettaTipoProposta(p['tipo'])}: ${p['titolo']}',
                      dettagli: [
                        dati.struttura(p['struttura_id']),
                        'anno ${p['anno']}',
                        if (p['autore'] != null) 'di ${p['autore']}',
                        if (p['inviata_il'] != null) 'inviata il ${formatData(p['inviata_il'])}',
                        if (p['decisa_il'] != null) 'decisa il ${formatData(p['decisa_il'])}',
                        if (p['motivazione'] != null) 'motivazione: ${p['motivazione']}',
                      ],
                      finale: [StatoPropostaPf(p['stato'])],
                      onTap: () async {
                        await apriPropostaPf(context, p['id'] as String);
                        _carica();
                        widget.onCambiato?.call();
                      },
                    ),
                ]),
        ),
      ),
    ]);
  }
}

IconData iconaProposta(Object? tipo) => switch (tipo) {
      'CREA' => Icons.add_box_outlined,
      'ELIMINA' => Icons.delete_sweep_outlined,
      _ => Icons.edit_note,
    };

/// Apre una proposta in una pagina a sé; al ritorno chi la apre ricarica.
Future<void> apriPropostaPf(BuildContext context, String id) {
  final dati = context.read<DatiPerformance>();
  return Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => Provider<DatiPerformance>.value(value: dati, child: PropostaPfPage(propostaId: id)),
  ));
}

const _etichetteCampi = {
  'codice': 'Codice',
  'titolo': 'Titolo',
  'descrizione': 'Descrizione',
  'tipo': 'Tipo',
  'impegno': 'Impegno',
  'scadenza': 'Scadenza',
  'misura_codice': 'Misura',
  'indicatori': 'Indicatori',
};

String _valoreCampo(String campo, Object? v) {
  if (v is List) return v.isEmpty ? 'nessuno' : v.join('; ');
  if (v == null || v == '') return '—';
  if (campo == 'impegno') return '$v%';
  if (campo == 'scadenza') return formatData(v);
  if (campo == 'tipo') return etichettaTipoObiettivo(v);
  return '$v';
}

/// Una proposta: l'obiettivo proposto con le azioni e misure e, per una modifica, cosa cambia
/// rispetto a com'era. In bozza (o restituita) la struttura la modifica, la invia o la scarta;
/// inviata la ritira; l'approvatore la approva, la restituisce o la respinge.
class PropostaPfPage extends StatefulWidget {
  const PropostaPfPage({super.key, required this.propostaId});

  final String propostaId;

  @override
  State<PropostaPfPage> createState() => _PropostaPfPageState();
}

class _PropostaPfPageState extends State<PropostaPfPage> {
  Map<String, dynamic>? _p;
  Object? _errore;
  bool _occupata = false;

  String get _base => '$apiPerformance/proposte/${widget.propostaId}';

  @override
  void initState() {
    super.initState();
    _carica();
  }

  Future<void> _carica() async {
    try {
      final p = await apiDi(context).get(_base) as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _p = p;
          _errore = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _errore = e);
    }
  }

  /// Esegue un'operazione; se restituisce la proposta aggiornata la mostra, con [chiudi]
  /// torna indietro.
  Future<void> _esegui(Future<Object?> Function() azione, {String? messaggio, bool chiudi = false}) async {
    setState(() => _occupata = true);
    try {
      final r = await azione();
      if (!mounted) return;
      if (messaggio != null) mostraMessaggio(context, messaggio);
      if (chiudi) {
        Navigator.of(context).pop();
      } else if (r is Map<String, dynamic>) {
        setState(() => _p = r);
      } else {
        await _carica();
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _occupata = false);
    }
  }

  Map<String, dynamic> get _dati => Map<String, dynamic>.from(_p!['dati'] as Map);
  List<Map<String, dynamic>> get _elementi =>
      [for (final x in (_p!['dati'] as Map)['elementi'] as List) Map<String, dynamic>.from(x as Map)];

  Future<void> _salva(Map<String, dynamic> dati) =>
      _esegui(() => apiDi(context).put(_base, {'dati': dati, 'nota': _p!['nota']}));

  Future<void> _modificaObiettivo() async {
    final d = _dati;
    final v = await modificaObiettivo(context, o: d, disponibile: _p!['disponibile'] as int, nota: false);
    if (v != null && mounted) await _salva({...d, ...v});
  }

  Future<void> _nuovoElemento(String tipo) async {
    final elementi = _elementi;
    Map<String, dynamic>? misura;
    if (tipo == 'MISURA') {
      misura = await scegliMisura(context, _p!['struttura_id'] as String, {for (final x in elementi) ?x['misura_id'] as String?});
      if (misura == null || !mounted) return;
    }
    final v = await modificaElemento(context,
        tipo: tipo, misura: misura, disponibile: 100 - (_p!['impegno_elementi'] as int), anno: _p!['anno'] as int, proposta: true);
    if (v == null || !mounted) return;
    await _salva({
      ..._dati,
      'elementi': [...elementi, {...v, 'tipo': tipo, if (misura != null) 'misura_id': misura['id']}],
    });
  }

  Future<void> _modificaElemento(Map<String, dynamic> x) async {
    final v = await modificaElemento(context,
        tipo: x['tipo'] as String,
        x: x,
        disponibile: 100 - (_p!['impegno_elementi'] as int) + (x['impegno'] as int),
        anno: _p!['anno'] as int,
        proposta: true);
    if (v == null || !mounted) return;
    await _salva({
      ..._dati,
      'elementi': [for (final e in _elementi) e['id'] == x['id'] ? {...e, ...v} : e],
    });
  }

  Future<void> _togliElemento(Map<String, dynamic> x) async {
    if (!await conferma(context, x['tipo'] == 'AZIONE' ? 'Togliere l\'azione?' : 'Togliere la misura?',
            'Si toglie dalla proposta.') ||
        !mounted) {
      return;
    }
    await _salva({..._dati, 'elementi': [for (final e in _elementi) if (e['id'] != x['id']) e]});
  }

  Future<void> _invia() async {
    final p = _p!;
    final nota = await chiediTesto(context, p['stato'] == 'RESTITUITA' ? 'Reinvia la proposta corretta' : 'Invia la proposta',
        etichetta: 'Nota per l\'approvatore',
        testo: 'Finché non è decisa la proposta si può ritirare.',
        iniziale: p['nota'] as String?);
    if (nota == null || !mounted) return;
    await _esegui(() => apiDi(context).post('$_base/invia', {'nota': nota}), messaggio: 'Proposta inviata all\'approvatore');
  }

  Future<void> _ritira() async {
    final elimina = _p!['tipo'] == 'ELIMINA';
    if (!await conferma(context, 'Ritirare la proposta?',
            elimina ? 'La proposta di eliminazione si annulla.' : 'La proposta torna in bozza: si può correggere e inviare di nuovo.') ||
        !mounted) {
      return;
    }
    await _esegui(() => apiDi(context).post('$_base/ritira', {}), chiudi: elimina, messaggio: 'Proposta ritirata');
  }

  Future<void> _scarta() async {
    if (!await conferma(context, 'Scartare la proposta?', 'La proposta si elimina; l\'obiettivo resta com\'è.') || !mounted) return;
    await _esegui(() => apiDi(context).delete(_base), chiudi: true, messaggio: 'Proposta scartata');
  }

  Future<void> _approva() async {
    final p = _p!;
    var forza = false;
    if (p['cambiato'] == true) {
      forza = await conferma(context, 'L\'obiettivo è cambiato',
          'Dopo la proposta l\'obiettivo è stato modificato: approvandola le modifiche successive si perdono '
          '(l\'avanzamento resta). Approvare comunque?');
      if (!forza || !mounted) return;
    }
    final motivazione = await chiediTesto(context, 'Approva la proposta', etichetta: 'Motivazione');
    if (motivazione == null || !mounted) return;
    await _esegui(
        () => apiDi(context).post('$_base/approva', {'motivazione': motivazione.isEmpty ? null : motivazione, 'forza': forza}),
        messaggio: 'Proposta approvata: l\'obiettivo è aggiornato');
  }

  Future<void> _decidi(String azione, String titolo, String testo) async {
    final motivazione = await chiediTesto(context, titolo, etichetta: 'Motivazione', testo: testo, obbligatoria: true);
    if (motivazione == null || !mounted) return;
    await _esegui(() => apiDi(context).post('$_base/$azione', {'motivazione': motivazione}));
  }

  Widget _cambiamenti(Map<String, dynamic> campi, TextStyle? stile) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final e in campi.entries)
            Text('${_etichetteCampi[e.key] ?? e.key}: ${_valoreCampo(e.key, (e.value as List)[0])} → '
                '${_valoreCampo(e.key, (e.value as List)[1])}', style: stile),
        ],
      );

  Widget _rigaElemento(Map<String, dynamic> x, Map<String, dynamic>? confronto, bool modificabile) {
    final misura = x['tipo'] == 'MISURA';
    final stato = confronto?['stato'] as String?;
    final eliminato = stato == 'ELIMINATO';
    final tema = Theme.of(context);
    return ListTile(
      leading: Tooltip(
        message: misura ? 'Misura della mappatura dei rischi' : 'Azione',
        child: Icon(misura ? Icons.shield_outlined : Icons.directions_run),
      ),
      title: Text(misura ? '${x['misura_codice']} - ${x['descrizione']}' : '${x['descrizione']}',
          style: eliminato ? const TextStyle(decoration: TextDecoration.lineThrough) : null),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text('Impegno ${x['impegno']}% · entro il ${formatData(x['scadenza'])}'),
          if (stato == 'NUOVO') const Etichetta('Nuova', Colors.green),
          if (stato == 'MODIFICATO') const Etichetta('Modificata', Colors.blue),
          if (eliminato) const Etichetta('Tolta', Colors.red),
        ]),
        ElencoIndicatori([for (final i in (x['indicatori'] as List? ?? const [])) (i as Map).cast<String, dynamic>()]),
        if (stato == 'MODIFICATO') _cambiamenti((confronto!['campi'] as Map).cast<String, dynamic>(), tema.textTheme.bodySmall),
      ]),
      trailing: modificabile && !eliminato
          ? Row(mainAxisSize: MainAxisSize.min, children: [
              IconaAzione(Icons.edit_outlined, 'Modifica', () => _modificaElemento(x)),
              IconaAzione(Icons.delete_outline, 'Togli', () => _togliElemento(x)),
            ])
          : null,
    );
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiPerformance>();
    final p = _p;
    if (p == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Proposta')),
        body: Center(child: _errore != null ? Text('$_errore') : const CircularProgressIndicator()),
      );
    }
    final tema = Theme.of(context);
    final modificabile = p['modificabile'] == true && !_occupata;
    final elimina = p['tipo'] == 'ELIMINA';
    final versione = ((elimina ? p['prima'] : p['dati']) as Map?)?.cast<String, dynamic>() ?? const {};
    final confronto = (p['confronto'] as Map?)?.cast<String, dynamic>();
    final perId = {
      for (final c in (confronto?['elementi'] as List? ?? const [])) (c as Map)['id']: c.cast<String, dynamic>(),
    };
    final elementi = (versione['elementi'] as List? ?? const []).cast<Map>().map((x) => x.cast<String, dynamic>()).toList();
    final tolti = [
      for (final x in ((p['prima'] as Map?)?['elementi'] as List? ?? const []).cast<Map>())
        if (perId[x['id']]?['stato'] == 'ELIMINATO') x.cast<String, dynamic>(),
    ];
    final campiObiettivo = (confronto?['obiettivo'] as Map?)?.cast<String, dynamic>() ?? const {};
    final impegnoElementi = p['impegno_elementi'] as int;
    return Scaffold(
      appBar: AppBar(
        title: Text('${etichettaTipoProposta(p['tipo'])}: ${p['titolo']}', overflow: TextOverflow.ellipsis),
        actions: [
          if (p['inviabile'] == true)
            TextButton.icon(
              onPressed: _occupata ? null : _invia,
              icon: const Icon(Icons.send),
              label: Text(p['stato'] == 'RESTITUITA' ? 'Reinvia' : 'Invia'),
            ),
          if (p['ritirabile'] == true)
            TextButton.icon(onPressed: _occupata ? null : _ritira, icon: const Icon(Icons.undo), label: const Text('Ritira')),
          if (p['scartabile'] == true)
            IconButton(tooltip: 'Scarta la proposta', onPressed: _occupata ? null : _scarta, icon: IconaElimina(attiva: !_occupata)),
          if (p['decidibile'] == true) ...[
            TextButton.icon(onPressed: _occupata ? null : _approva, icon: const Icon(Icons.check), label: const Text('Approva')),
            TextButton.icon(
              onPressed: _occupata
                  ? null
                  : () => _decidi('restituisci', 'Restituisci la proposta', 'La struttura la corregge e la invia di nuovo.'),
              icon: const Icon(Icons.reply),
              label: const Text('Restituisci'),
            ),
            TextButton.icon(
              onPressed: _occupata ? null : () => _decidi('respingi', 'Respingi la proposta', 'L\'obiettivo resta com\'è.'),
              icon: const Icon(Icons.block),
              label: const Text('Respingi'),
            ),
          ],
        ],
      ),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Sezione(
          titolo: 'Proposta',
          azioni: [StatoPropostaPf(p['stato'])],
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${dati.struttura(p['struttura_id'])} · ${(p['piao'] as Map)['titolo']}, anno ${p['anno']}',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            Text([
              if (p['autore'] != null) 'Inviata da ${p['autore']}',
              'creata il ${formatData(p['created_at'])}',
              if (p['inviata_il'] != null) 'inviata il ${formatData(p['inviata_il'])}',
              if (p['decisa_il'] != null) 'decisa il ${formatData(p['decisa_il'])}',
            ].join(', ')),
            if (p['stato'] == 'BOZZA')
              const Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text('In bozza: le modifiche si salvano subito; l\'approvatore la vede quando la invii.'),
              ),
            if (p['nota'] != null) ...[const SizedBox(height: 4), Text('Nota: ${p['nota']}')],
            if (p['motivazione'] != null) ...[
              const SizedBox(height: 4),
              Text('Motivazione dell\'approvatore: ${p['motivazione']}', style: const TextStyle(fontWeight: FontWeight.w600)),
            ],
            if (p['eliminato'] == true)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('L\'obiettivo non esiste più: la proposta si può solo scartare o respingere.',
                    style: TextStyle(color: tema.colorScheme.error)),
              )
            else if (p['cambiato'] == true)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Attenzione: dopo la proposta l\'obiettivo è stato modificato.', style: TextStyle(color: tema.colorScheme.error)),
              ),
            if (elimina)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text('Si propone di eliminare l\'obiettivo qui sotto con le sue azioni e misure.'),
              ),
          ]),
        ),
        Sezione(
          titolo: 'Obiettivo',
          azioni: [
            if (modificabile)
              TextButton.icon(icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('Modifica'), onPressed: _modificaObiettivo),
          ],
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(versione['codice'] == null ? '${versione['titolo']}' : '${versione['codice']} - ${versione['titolo']}',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            Text('${etichettaTipoObiettivo(versione['tipo'])} · impegno ${versione['impegno']}% sugli obiettivi della struttura'
                '${modificabile ? ' (disponibile ${p['disponibile']}%)' : ''}'),
            if (versione['descrizione'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('${versione['descrizione']}')),
            if (campiObiettivo.isNotEmpty) ...[
              const SizedBox(height: 8),
              const Text('Cambia:', style: TextStyle(fontWeight: FontWeight.w600)),
              _cambiamenti(campiObiettivo, null),
            ],
          ]),
        ),
        Sezione(
          titolo: 'Azioni e misure',
          azioni: [
            if (modificabile && impegnoElementi < 100) ...[
              TextButton.icon(icon: const Icon(Icons.add, size: 18), label: const Text('Azione'), onPressed: () => _nuovoElemento('AZIONE')),
              if (dati.misureDisponibili)
                TextButton.icon(
                    icon: const Icon(Icons.add_moderator_outlined, size: 18),
                    label: const Text('Misura'),
                    onPressed: () => _nuovoElemento('MISURA')),
            ],
          ],
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Align(alignment: Alignment.centerLeft, child: TotaleImpegno(impegnoElementi, testo: 'Impegno delle azioni e misure')),
            const SizedBox(height: 8),
            if (elementi.isEmpty && tolti.isEmpty) const Text('Nessuna azione o misura.'),
            for (final x in elementi) _rigaElemento(x, perId[x['id']], modificabile),
            for (final x in tolti) _rigaElemento(x, perId[x['id']], false),
            if (!elimina && p['tipo'] == 'MODIFICA')
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('L\'avanzamento delle azioni e misure (completamento, valori rilevati degli indicatori) non fa parte '
                    'della proposta: si aggiorna dall\'obiettivo.',
                    style: tema.textTheme.bodySmall),
              ),
          ]),
        ),
        if ((p['controlli'] as List? ?? const []).isNotEmpty)
          Sezione(titolo: 'Controlli', child: ElencoControlli((p['controlli'] as List).cast<Map<String, dynamic>>())),
      ]),
    );
  }
}
