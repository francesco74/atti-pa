import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';
import 'albero.dart';
import 'comune.dart';

const _etichetteStato = {
  'BOZZA': 'Bozza',
  'INVIATA': 'Inviata',
  'APPROVATA': 'Approvata',
  'RESPINTA': 'Respinta',
  'RESTITUITA': 'Restituita',
};
const _coloriStato = {
  'BOZZA': Colors.blueGrey,
  'INVIATA': Colors.blue,
  'APPROVATA': Colors.green,
  'RESPINTA': Colors.red,
  'RESTITUITA': Colors.orange,
};
const _etichetteTipo = {'CREA': 'Nuovo processo', 'MODIFICA': 'Modifica', 'ELIMINA': 'Eliminazione'};

class StatoProposta extends StatelessWidget {
  const StatoProposta(this.stato, {super.key});

  final String? stato;

  @override
  Widget build(BuildContext context) {
    final colore = _coloriStato[stato] ?? Colors.blueGrey;
    return Chip(
      visualDensity: VisualDensity.compact,
      side: BorderSide(color: colore),
      backgroundColor: colore.withValues(alpha: 0.1),
      label: Text(_etichetteStato[stato] ?? '$stato', style: TextStyle(color: colore.shade800)),
    );
  }
}

/// Proposte: il referente vede le sue, il RPCT anche quelle inviate o decise degli altri.
class ProposteTab extends StatefulWidget {
  const ProposteTab({super.key});

  @override
  State<ProposteTab> createState() => _ProposteTabState();
}

class _ProposteTabState extends State<ProposteTab> {
  late Future<List<Map<String, dynamic>>> _proposte;
  String? _stato;

  @override
  void initState() {
    super.initState();
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    _stato = rpct ? 'INVIATA' : null; // il RPCT parte da quelle da decidere
    _carica();
  }

  void _carica() => setState(() {
        _proposte = apiDi(context)
            .get('$apiAnticorruzione/proposte', query: {'stato': ?_stato})
            .then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: Wrap(spacing: 8, children: [
          for (final s in [null, ..._etichetteStato.keys])
            ChoiceChip(
              label: Text(s == null ? 'Tutte' : _etichetteStato[s]!),
              selected: _stato == s,
              onSelected: (_) {
                _stato = s;
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
              ? const Center(child: Text('Nessuna proposta. Si propone dalla mappatura: un processo nuovo, '
                  'le modifiche o l\'eliminazione di uno esistente.'))
              : ListView(padding: const EdgeInsets.all(16), children: [
                  for (final p in proposte)
                    Card(
                      child: ListTile(
                        leading: Icon(switch (p['tipo']) {
                          'CREA' => Icons.add_box_outlined,
                          'ELIMINA' => Icons.delete_sweep_outlined,
                          _ => Icons.edit_note,
                        }),
                        title: Text('${_etichetteTipo[p['tipo']]}: ${p['codice'] ?? ''} ${p['denominazione'] ?? ''}'),
                        subtitle: Text([
                          'di ${p['autore']}',
                          'creata il ${formatData(p['created_at'])}',
                          if (p['inviata_il'] != null) 'inviata il ${formatData(p['inviata_il'])}',
                          if (p['motivazione'] != null) 'motivazione: ${p['motivazione']}',
                        ].join(' · ')),
                        trailing: StatoProposta(p['stato'] as String?),
                        onTap: () async {
                          await apriProposta(context, p['id'] as String);
                          _carica();
                        },
                      ),
                    ),
                ]),
        ),
      ),
    ]);
  }
}

Future<void> apriProposta(BuildContext context, String id) {
  final dati = context.read<DatiAnticorruzione>();
  return Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => Provider.value(value: dati, child: PropostaPage(propostaId: id)),
  ));
}

/// Proposta: l'autore modifica l'albero (bozza o restituita), salva, invia o ritira; il RPCT
/// approva (con conferma se il processo è cambiato), respinge o restituisce con motivazione.
class PropostaPage extends StatefulWidget {
  const PropostaPage({super.key, required this.propostaId});

  final String propostaId;

  @override
  State<PropostaPage> createState() => _PropostaPageState();
}

class _PropostaPageState extends State<PropostaPage> {
  Map<String, dynamic>? _proposta;
  Map<String, dynamic>? _dati; // copia locale dell'albero
  final _nota = TextEditingController();
  bool _modificata = false;
  bool _occupata = false;
  Object? _errore;

  String get _base => '$apiAnticorruzione/proposte/${widget.propostaId}';

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _nota.dispose();
    super.dispose();
  }

  Future<void> _carica() async {
    try {
      final p = await apiDi(context).get(_base) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _proposta = p;
        _dati = jsonDecode(jsonEncode(p['dati'])) as Map<String, dynamic>; // copia profonda
        _nota.text = p['nota'] as String? ?? '';
        _modificata = false;
        _errore = null;
      });
    } catch (e) {
      if (mounted) setState(() => _errore = e);
    }
  }

  bool get _propria => _proposta?['utente_id'] == context.read<AuthState>().utente?.id;
  bool get _modificabile => _propria && const ['BOZZA', 'RESTITUITA'].contains(_proposta?['stato']);

  Future<void> _esegui(Future<void> Function() azione, {String? messaggio, bool chiudi = false}) async {
    setState(() => _occupata = true);
    try {
      await azione();
      if (!mounted) return;
      if (messaggio != null) mostraMessaggio(context, messaggio);
      if (chiudi) {
        Navigator.of(context).pop();
      } else {
        await _carica();
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _occupata = false);
    }
  }

  Future<void> _salva() => apiDi(context).put(_base, {
        if (_proposta!['tipo'] != 'ELIMINA') 'dati': _dati,
        'nota': _nota.text.trim().isEmpty ? null : _nota.text.trim(),
      });

  Future<String?> _motivazione(String titolo, {bool obbligatoria = true}) async {
    final c = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(titolo),
        content: SizedBox(
          width: 480,
          child: TextField(
            controller: c,
            maxLines: 4,
            decoration: InputDecoration(labelText: obbligatoria ? 'Motivazione *' : 'Nota (facoltativa)'),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('Conferma')),
        ],
      ),
    );
    final testo = c.text.trim();
    c.dispose();
    if (ok != true) return null;
    if (obbligatoria && testo.isEmpty) {
      if (mounted) mostraErrore(context, 'Serve la motivazione');
      return null;
    }
    return testo;
  }

  Future<void> _approva() async {
    final p = _proposta!;
    var forza = false;
    if (p['processo_cambiato'] == true) {
      forza = await conferma(context, 'Il processo è cambiato',
          'Dopo la proposta il processo è stato modificato: approvandola le modifiche successive si perdono dove la proposta '
          'tocca gli stessi elementi. Approvare comunque?');
      if (!forza) return;
    }
    final nota = await _motivazione('Approva la proposta', obbligatoria: false);
    if (nota == null) return;
    await _esegui(() => apiDi(context).post('$_base/approva', {'motivazione': nota.isEmpty ? null : nota, 'forza': forza}),
        messaggio: 'Proposta approvata: la mappatura è aggiornata');
  }

  Future<void> _decidi(String azione, String titolo) async {
    final motivazione = await _motivazione(titolo);
    if (motivazione == null) return;
    await _esegui(() => apiDi(context).post('$_base/$azione', {'motivazione': motivazione}));
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    final p = _proposta;
    if (p == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Proposta')),
        body: Center(child: _errore != null ? Text('$_errore') : const CircularProgressIndicator()),
      );
    }
    final albero = _dati!;
    final modificabile = _modificabile && p['tipo'] != 'ELIMINA';
    final operazioni = modificabile ? OperazioniLocali(albero) : null;
    final processo = albero['processo'] as Map<String, dynamic>;
    return PopScope(
      canPop: !_modificata,
      onPopInvokedWithResult: (fatto, _) async {
        if (fatto) return;
        if (await conferma(context, 'Modifiche non salvate', 'Uscire senza salvare la proposta?') && context.mounted) {
          setState(() => _modificata = false);
          Navigator.of(context).pop();
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text('${_etichetteTipo[p['tipo']]}: ${processo['codice'] ?? ''} ${processo['denominazione'] ?? ''}'),
          actions: [
            if (_modificabile) ...[
              TextButton.icon(
                onPressed: _occupata ? null : () => _esegui(_salva, messaggio: 'Proposta salvata'),
                icon: const Icon(Icons.save_outlined),
                label: const Text('Salva'),
              ),
              TextButton.icon(
                onPressed: _occupata
                    ? null
                    : () {
                        final api = apiDi(context);
                        _esegui(() async {
                          await _salva();
                          await api.post('$_base/invia', {});
                        }, messaggio: 'Proposta inviata al RPCT');
                      },
                icon: const Icon(Icons.send),
                label: const Text('Invia'),
              ),
              IconButton(
                tooltip: 'Ritira la proposta',
                icon: IconaElimina(attiva: !_occupata),
                onPressed: _occupata
                    ? null
                    : () async {
                        if (await conferma(context, 'Ritirare la proposta?', 'La proposta si elimina.')) {
                          setState(() => _modificata = false);
                          await _esegui(() => apiDi(context).delete(_base), chiudi: true);
                        }
                      },
              ),
            ],
            if (rpct && p['stato'] == 'INVIATA') ...[
              TextButton.icon(onPressed: _occupata ? null : _approva, icon: const Icon(Icons.check), label: const Text('Approva')),
              TextButton.icon(
                onPressed: _occupata ? null : () => _decidi('restituisci', 'Restituisci al referente'),
                icon: const Icon(Icons.undo),
                label: const Text('Restituisci'),
              ),
              TextButton.icon(
                onPressed: _occupata ? null : () => _decidi('respingi', 'Respingi la proposta'),
                icon: const Icon(Icons.block),
                label: const Text('Respingi'),
              ),
            ],
          ],
        ),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          Sezione(
            titolo: 'Proposta',
            azioni: [StatoProposta(p['stato'] as String?)],
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Di ${p['autore']}, creata il ${formatData(p['created_at'])}'
                  '${p['inviata_il'] != null ? ', inviata il ${formatData(p['inviata_il'])}' : ''}'
                  '${p['decisa_il'] != null ? ', decisa il ${formatData(p['decisa_il'])}' : ''}'),
              if (p['motivazione'] != null) ...[
                const SizedBox(height: 4),
                Text('Motivazione del RPCT: ${p['motivazione']}', style: const TextStyle(fontWeight: FontWeight.w600)),
              ],
              if (p['processo_cambiato'] == true)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text('Attenzione: dopo la proposta il processo è stato modificato.',
                      style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
              const SizedBox(height: 8),
              TextField(
                controller: _nota,
                enabled: _modificabile,
                maxLines: 3,
                decoration: const InputDecoration(labelText: 'Nota per il RPCT'),
                onChanged: (_) => _modificata = true,
              ),
              if (p['tipo'] == 'ELIMINA')
                const Padding(
                  padding: EdgeInsets.only(top: 8),
                  child: Text('Si propone di eliminare il processo qui sotto, con attività, rischi e misure.'),
                ),
            ]),
          ),
          IntestazioneProcesso(
            dati: dati,
            processo: processo,
            azioni: [
              if (operazioni != null)
                IconButton(
                  tooltip: 'Modifica il processo',
                  icon: const Icon(Icons.edit_outlined),
                  onPressed: () async {
                    final v = await modificaProcesso(context, dati, processo);
                    if (v == null) return;
                    await operazioni.processo(v);
                    setState(() => _modificata = true);
                  },
                ),
            ],
          ),
          AlberoProcesso(
            dati: dati,
            albero: albero,
            operazioni: operazioni,
            onCambiato: () => setState(() => _modificata = true),
          ),
        ]),
      ),
    );
  }
}
