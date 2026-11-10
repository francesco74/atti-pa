import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';
import 'albero.dart';
import 'art35.dart';
import 'comune.dart';

const _etichetteStato = {
  'INVIATA': 'In fase di approvazione',
  'APPROVATA': 'Approvata',
  'RESPINTA': 'Respinta',
  'RESTITUITA': 'Restituita',
};
const _coloriStato = {
  'INVIATA': Colors.blue,
  'APPROVATA': Colors.green,
  'RESPINTA': Colors.red,
  'RESTITUITA': Colors.orange,
};

/// (nuovo, modifica, eliminazione) per ogni oggetto.
const _azioni = {
  'AREA': ('Nuova area', 'Modifica dell\'area', 'Eliminazione dell\'area'),
  'PROCESSO': ('Nuovo processo', 'Modifica del processo', 'Eliminazione del processo'),
  'ATTIVITA': ('Nuova attività', 'Modifica dell\'attività', 'Eliminazione dell\'attività'),
  'RISCHIO': ('Nuova analisi del rischio', 'Modifica dell\'analisi del rischio', 'Eliminazione del rischio'),
  'MISURA': ('Nuova misura', 'Modifica della misura', 'Eliminazione della misura'),
};

/// Titolo della proposta: "Nuova attività", "Modifica della misura C.1.1_R.1_M.2"...
String titoloProposta(Map<String, dynamic> p) {
  final azioni = _azioni[p['oggetto']] ?? ('Nuovo elemento', 'Modifica', 'Eliminazione');
  var titolo = switch (p['tipo']) { 'CREA' => azioni.$1, 'MODIFICA' => azioni.$2, _ => azioni.$3 };
  final dati = p['dati'] as Map?;
  if (p['oggetto'] == 'PROCESSO' && p['tipo'] == 'CREA' && dati?['tipo'] == 'PROCEDIMENTO') titolo = 'Nuovo procedimento';
  return p['codice'] == null ? titolo : '$titolo ${p['codice']}';
}

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

/// Proposte: il referente vede le sue (e ritira quelle non ancora decise), il RPCT tutte.
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
              ? const Center(
                  child: Text('Nessuna proposta. Si propone dalla mappatura, con i pulsanti "Proponi..." su aree, '
                      'processi, attività, rischi e misure della propria struttura.'))
              : ListView(padding: const EdgeInsets.all(16), children: [
                  for (final p in proposte)
                    RigaVoce(
                      icona: switch (p['tipo']) {
                        'CREA' => Icons.add_box_outlined,
                        'ELIMINA' => Icons.delete_sweep_outlined,
                        _ => Icons.edit_note,
                      },
                      titolo: '${titoloProposta(p)}${p['titolo'] != null ? ' - ${p['titolo']}' : ''}',
                      dettagli: [
                        if ((p['percorso'] as List? ?? const []).isNotEmpty) (p['percorso'] as List).join(' › '),
                        'di ${p['autore']}',
                        'creata il ${formatData(p['created_at'])}',
                        if (p['inviata_il'] != null) 'inviata il ${formatData(p['inviata_il'])}',
                        if (p['motivazione'] != null) 'motivazione: ${p['motivazione']}',
                      ],
                      finale: [StatoProposta(p['stato'] as String?)],
                      onTap: () async {
                        await apriProposta(context, p['id'] as String);
                        _carica();
                      },
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

/// Una proposta: cosa si propone e dove; per una modifica com'era e come diventa. Finché il
/// RPCT non decide, il referente la corregge o la completa (per una creazione anche con gli
/// elementi sottostanti) oppure la ritira; quella restituita, salvata, torna al RPCT. Il RPCT
/// la approva, la restituisce o la respinge.
class PropostaPage extends StatefulWidget {
  const PropostaPage({super.key, required this.propostaId});

  final String propostaId;

  @override
  State<PropostaPage> createState() => _PropostaPageState();
}

class _PropostaPageState extends State<PropostaPage> {
  Map<String, dynamic>? _proposta;
  Map<String, dynamic>? _dati; // copia locale dei dati proposti
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
  bool get _modificabile => _propria && const ['INVIATA', 'RESTITUITA'].contains(_proposta?['stato']);

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
    if (p['cambiato'] == true) {
      forza = await conferma(context, 'L\'elemento è cambiato',
          'Dopo la proposta l\'elemento è stato modificato: approvandola le modifiche successive si perdono. Approvare comunque?');
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

  /// Cambia i dati proposti con la finestra dell'elemento (creazione semplice o modifica).
  Future<void> _modificaDati(DatiAnticorruzione d) async {
    final dati = _dati!;
    final v = await switch (_proposta!['oggetto']) {
      'AREA' => modificaArea(context, dati),
      'PROCESSO' => modificaProcesso(context, d, dati),
      'ATTIVITA' => modificaAttivita(context, dati),
      'RISCHIO' => modificaRischio(context, d, dati),
      _ => modificaMisura(context, d, dati),
    };
    if (v == null) return;
    setState(() {
      dati.addAll(v);
      _modificata = true;
    });
  }

  Future<void> _valutaDati(DatiAnticorruzione d) async {
    final v = await valutaRischio(context, d, _dati!);
    if (v == null) return;
    setState(() {
      OperazioniLocali(const {}).valuta(_dati!, v);
      _modificata = true;
    });
  }

  /// Creazione di un processo, di un'attività o di un rischio, o loro eliminazione: l'albero
  /// con gli elementi sottostanti (modificabile nella creazione).
  Widget? _albero(DatiAnticorruzione d, Map<String, dynamic> p, bool modificabile) {
    final dati = _dati!;
    final oggetto = p['oggetto'];
    void cambiato() => setState(() => _modificata = true);
    if (oggetto == 'PROCESSO' && p['tipo'] != 'MODIFICA') {
      // i dati del processo sono piatti: per l'albero il processo sta sotto "processo"
      final albero = {'processo': dati, 'attivita': dati['attivita'] ??= <dynamic>[]};
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        IntestazioneProcesso(dati: d, processo: dati, azioni: [
          if (modificabile)
            IconButton(tooltip: 'Modifica', icon: const Icon(Icons.edit_outlined), onPressed: () => _modificaDati(d)),
        ]),
        AlberoProcesso(dati: d, albero: albero, operazioni: modificabile ? OperazioniLocali(albero) : null, onCambiato: cambiato),
      ]);
    }
    if (oggetto == 'ATTIVITA' && p['tipo'] != 'MODIFICA') {
      dati['rischi'] ??= <dynamic>[];
      final albero = {'attivita': [dati]};
      return AlberoProcesso(
        dati: d,
        albero: albero,
        operazioni: modificabile ? OperazioniLocali(albero) : null,
        onCambiato: cambiato,
        aggiungiAttivita: false,
      );
    }
    if (oggetto == 'RISCHIO' && p['tipo'] != 'MODIFICA') {
      dati['misure'] ??= <dynamic>[];
      return SchedaRischio(
        dati: d,
        attivita: {'rischi': [dati]},
        rischio: dati,
        operazioni: modificabile ? OperazioniLocali(const {}) : null,
        onCambiato: cambiato,
      );
    }
    return null;
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
    final modificabile = _modificabile && p['tipo'] != 'ELIMINA';
    final percorso = (p['percorso'] as List? ?? const []).cast<String>();
    final albero = _albero(dati, p, modificabile);
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
          title: Text(titoloProposta(p)),
          actions: [
            if (_modificabile) ...[
              TextButton.icon(
                onPressed: _occupata
                    ? null
                    : () => _esegui(_salva,
                        messaggio: p['stato'] == 'RESTITUITA' ? 'Proposta corretta e inviata di nuovo al RPCT' : 'Proposta aggiornata'),
                icon: Icon(p['stato'] == 'RESTITUITA' ? Icons.send : Icons.save_outlined),
                label: Text(p['stato'] == 'RESTITUITA' ? 'Salva e reinvia' : 'Salva'),
              ),
              IconButton(
                tooltip: 'Ritira la proposta',
                icon: IconaElimina(attiva: !_occupata),
                onPressed: _occupata
                    ? null
                    : () async {
                        if (await conferma(context, 'Ritirare la proposta?', 'La proposta si elimina e il RPCT non la vede più.')) {
                          setState(() => _modificata = false);
                          await _esegui(() => apiDi(context).delete(_base), chiudi: true);
                        }
                      },
              ),
            ],
            if (rpct && !_propria && p['stato'] == 'INVIATA') ...[
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
              if (percorso.isNotEmpty) ...[
                Text('In: ${percorso.join(' › ')}', style: const TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
              ],
              Text('Di ${p['autore']}, creata il ${formatData(p['created_at'])}'
                  '${p['inviata_il'] != null ? ', inviata il ${formatData(p['inviata_il'])}' : ''}'
                  '${p['decisa_il'] != null ? ', decisa il ${formatData(p['decisa_il'])}' : ''}'),
              if (p['tipo'] == 'CREA' && p['codice'] == null)
                const Text('Il codice lo assegna il sistema all\'approvazione.'),
              if (p['motivazione'] != null) ...[
                const SizedBox(height: 4),
                Text('Motivazione del RPCT: ${p['motivazione']}', style: const TextStyle(fontWeight: FontWeight.w600)),
              ],
              if (p['cambiato'] == true)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text('Attenzione: dopo la proposta l\'elemento è stato modificato o eliminato.',
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
                  child: Text('Si propone di eliminare l\'elemento qui sotto, con gli elementi che contiene.'),
                ),
            ]),
          ),
          if (p['controlli'] != null)
            Sezione(
              titolo: 'Controlli',
              child: ElencoControlli((p['controlli'] as List).cast<Map<String, dynamic>>()),
            ),
          if (albero != null)
            albero
          else
            Sezione(
              titolo: p['tipo'] == 'MODIFICA' ? 'Modifiche proposte' : 'Elemento proposto',
              azioni: [
                if (modificabile) ...[
                  if (p['oggetto'] == 'RISCHIO')
                    TextButton.icon(icon: const Icon(Icons.speed, size: 18), label: const Text('Valuta'), onPressed: () => _valutaDati(dati)),
                  TextButton.icon(
                    icon: const Icon(Icons.edit_outlined, size: 18),
                    label: const Text('Modifica'),
                    onPressed: () => _modificaDati(dati),
                  ),
                ],
              ],
              child: TabellaCampi(
                dati: dati,
                valori: _dati!,
                prima: p['tipo'] == 'MODIFICA' ? (p['prima'] as Map?)?.cast<String, dynamic>() : null,
              ),
            ),
        ]),
      ),
    );
  }
}

const _etichetteCampi = {
  'tipo': 'Tipo',
  'area_id': 'Area di rischio',
  'denominazione': 'Denominazione',
  'descrizione': 'Descrizione',
  'descrizione_breve': 'Descrizione breve',
  'tempi': 'Tempi',
  'attori_esterni': 'Attori esterni',
  'termine_conclusione': 'Termine di conclusione',
  'norma_riferimento': 'Norma di riferimento',
  'struttura_id': 'Struttura',
  'strutture_coinvolte': 'Strutture coinvolte',
  'evento': 'Evento rischioso',
  'fattore_abilitante': 'Fattore abilitante',
  'valutazione': 'Valutazione',
  'categoria': 'Categoria',
  'obbligo_trasparenza': 'Obbligo di pubblicazione',
  'fasi': 'Fasi di attuazione',
  'indicatore': 'Indicatore',
  'target': 'Target',
};

/// I campi dell'elemento proposto; con [prima] (modifica) solo quelli che cambiano, con il
/// valore attuale e quello proposto.
class TabellaCampi extends StatelessWidget {
  const TabellaCampi({super.key, required this.dati, required this.valori, this.prima});

  final DatiAnticorruzione dati;
  final Map<String, dynamic> valori;
  final Map<String, dynamic>? prima;

  /// I dati art. 35 del procedimento si mostrano campo per campo ("art35.tipologia"...).
  static Map<String, dynamic> _piatti(Map<String, dynamic> valori) => {
        for (final e in valori.entries)
          if (e.key == 'art35')
            for (final k in etichetteArt35.keys) 'art35.$k': (e.value as Map?)?[k]
          else
            e.key: e.value,
      };

  static String? _etichetta(String campo) =>
      campo.startsWith('art35.') ? 'Art. 35 - ${etichetteArt35[campo.substring(6)]}' : _etichetteCampi[campo];

  String _testo(String campo, Object? v) {
    if (v == null || v == '') return '—';
    if (campo.startsWith('art35.')) {
      if (campo.endsWith('_struttura_id')) return dati.struttura(v) ?? '—';
      if (v is List) return v.map((o) => '${(o as Map)['giorni']} dalle ${o['ora_inizio']} alle ${o['ora_fine']}').join('; ');
      return const {'SI': 'Sì', 'NO': 'No'}[v] ?? '$v';
    }
    return switch (campo) {
      'area_id' => dati.area(v) ?? '—',
      'struttura_id' => dati.struttura(v) ?? '—',
      'tipo' => const {'PROCESSO': 'Processo', 'PROCEDIMENTO': 'Procedimento', 'GENERALE': 'Generale', 'SPECIFICA': 'Specifica'}[v] ?? '$v',
      'valutazione' => '${(v as Map)['livello'] ?? 'Non valutato'} (P ${v['probabilita'] ?? v['probabilita_calcolata']} · '
          'I ${v['impatto'] ?? v['impatto_calcolato']})${v['motivazione_correzione'] != null ? ', corretta: ${v['motivazione_correzione']}' : ''}',
      _ => '$v',
    };
  }

  /// Per il confronto: la valutazione conta anche con i valori degli indicatori, che possono
  /// cambiare senza cambiare il livello.
  String _confronto(String campo, Object? v) => campo == 'valutazione' && v is Map
      ? jsonEncode([v['valori_probabilita'], v['valori_impatto'], v['probabilita'], v['impatto'], v['motivazione_correzione']])
      : _testo(campo, v);

  @override
  Widget build(BuildContext context) {
    final valori = _piatti(this.valori);
    final prima = this.prima == null ? null : _piatti(this.prima!);
    final campi = [..._etichetteCampi.keys, for (final k in etichetteArt35.keys) 'art35.$k']
        .where((c) => valori.containsKey(c) || (prima?.containsKey(c) ?? false));
    final righe = [
      for (final c in campi)
        if (prima == null ? valori[c] != null || !c.startsWith('art35.') : _confronto(c, prima[c]) != _confronto(c, valori[c])) c,
    ];
    if (righe.isEmpty) return const Text('Nessuna differenza rispetto all\'elemento attuale.');
    final grassetto = const TextStyle(fontWeight: FontWeight.w600);
    final barrato = TextStyle(decoration: TextDecoration.lineThrough, color: Theme.of(context).colorScheme.onSurfaceVariant);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final c in righe)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(_etichetta(c)!, style: grassetto),
            if (prima != null) Text(_testo(c, prima[c]), style: barrato),
            Text(_testo(c, valori[c])),
            if (c == 'valutazione' && valori[c] is Map)
              Padding(
                padding: const EdgeInsets.only(top: 4, left: 8),
                child: ValoriIndicatori(
                  dati: dati,
                  valutazione: (valori[c] as Map).cast<String, dynamic>(),
                  prima: (prima?[c] as Map?)?.cast<String, dynamic>(),
                ),
              ),
          ]),
        ),
    ]);
  }
}
