import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../comuni.dart';

const apiPerformance = '/api/v1/performance';

const tipiObiettivo = {'OPERATIVO': 'Operativo', 'FUNZIONAMENTO': 'Funzionamento', 'MIGLIORAMENTO': 'Miglioramento'};

String etichettaTipoObiettivo(Object? tipo) => tipiObiettivo[tipo] ?? '$tipo';

/// Dati usati da tutte le schede del modulo: cosa può fare l'utente, i PIAO e le strutture.
/// Si ricaricano dopo una modifica ai PIAO.
class DatiPerformance {
  DatiPerformance({required this.contesto, required this.piao, required this.strutture});

  final Map<String, dynamic> contesto;
  final List<Map<String, dynamic>> piao; // dal più recente
  final List<Map<String, dynamic>> strutture;

  static Future<DatiPerformance> carica(ApiClient api) async {
    final r = await Future.wait([
      api.get('$apiPerformance/contesto'),
      api.get('$apiPerformance/piao'),
      api.get('/api/v1/ente/strutture'),
    ]);
    List<Map<String, dynamic>> lista(Object? v) => (v as List).cast<Map<String, dynamic>>();
    return DatiPerformance(contesto: r[0] as Map<String, dynamic>, piao: lista(r[1]), strutture: lista(r[2]));
  }

  bool get amministratore => contesto['amministratore'] == true;
  String? get strutturaUtente => contesto['struttura_id'] as String?;
  bool get misureDisponibili => contesto['misure'] == true;

  /// Strutture di cui l'utente vede gli obiettivi (attive, per ordine).
  List<Map<String, dynamic>> get struttureVisibili {
    final visibili = (contesto['visibili'] as List?)?.cast<String>().toSet();
    return [
      for (final s in strutture)
        if ((visibili == null || visibili.contains(s['id'])) && (s['attiva'] != false || s['id'] == strutturaUtente)) s,
    ];
  }

  String struttura(Object? id) {
    for (final s in strutture) {
      if (s['id'] == id) return '${s['codice']} - ${s['descrizione']}';
    }
    return '—';
  }

  Map<String, dynamic>? piaoDi(String? id) => piao.where((p) => p['id'] == id).firstOrNull;

  /// PIAO proposto all'apertura: il più recente aperto, altrimenti il più recente.
  Map<String, dynamic>? get piaoPredefinito => piao.where((p) => p['stato'] == 'APERTO').firstOrNull ?? piao.firstOrNull;
}

/// Anno proposto per un PIAO: quello in corso se è nel triennio, altrimenti il primo.
int annoPredefinito(Map<String, dynamic> piao) {
  final anni = (piao['anni'] as List).cast<int>();
  final adesso = DateTime.now().year;
  return anni.contains(adesso) ? adesso : anni.first;
}

String percentuale(num? valore) {
  if (valore == null) return '—';
  return valore == valore.roundToDouble() ? '${valore.round()}%' : '${valore.toStringAsFixed(1)}%';
}

/// Barra del completamento con la percentuale.
class BarraCompletamento extends StatelessWidget {
  const BarraCompletamento(this.valore, {super.key, this.larghezza = 140});

  final num? valore;
  final double larghezza;

  @override
  Widget build(BuildContext context) {
    final v = (valore ?? 0).clamp(0, 100) / 100;
    final colore = v >= 1 ? Colors.green : v >= 0.5 ? Colors.lightGreen : v > 0 ? Colors.amber : Colors.blueGrey;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      SizedBox(
        width: larghezza,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(value: v.toDouble(), minHeight: 8, color: colore, backgroundColor: colore.withValues(alpha: 0.15)),
        ),
      ),
      const SizedBox(width: 8),
      SizedBox(width: 48, child: Text(percentuale(valore), textAlign: TextAlign.right)),
    ]);
  }
}

/// Etichetta colorata: avvisi (incompleto, in ritardo) e stati.
class Etichetta extends StatelessWidget {
  const Etichetta(this.testo, this.colore, {super.key});

  final String testo;
  final Color colore;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: colore.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: colore.withValues(alpha: 0.6)),
        ),
        child: Text(testo, style: TextStyle(color: colore, fontSize: 12, fontWeight: FontWeight.w600)),
      );
}

/// Totale degli impegni di un insieme: verde a 100, rosso altrimenti.
class TotaleImpegno extends StatelessWidget {
  const TotaleImpegno(this.totale, {super.key, this.testo = 'Impegno assegnato'});

  final int totale;
  final String testo;

  @override
  Widget build(BuildContext context) => Etichetta(
        totale == 100 ? '$testo: 100%' : '$testo: $totale% su 100% (incompleto)',
        totale == 100 ? Colors.green : Colors.red,
      );
}

// --- finestre di modifica ---------------------------------------------------------------------

int? _intero(TextEditingController c) => int.tryParse(c.text.trim());

Widget _campoPercentuale(TextEditingController c, String etichetta, {String? aiuto}) => TextField(
      controller: c,
      keyboardType: TextInputType.number,
      decoration: InputDecoration(labelText: etichetta, suffixText: '%', helperText: aiuto),
    );

const _campoNota = 'Nota sulla modifica (facoltativa, resta nello storico)';

/// Finestra di un obiettivo: codice nel PIAO, titolo, descrizione, tipo, impegno.
Future<Map<String, dynamic>?> modificaObiettivo(BuildContext context, {Map<String, dynamic>? o, required int disponibile}) async {
  final codice = TextEditingController(text: o?['codice'] as String? ?? '');
  final titolo = TextEditingController(text: o?['titolo'] as String? ?? '');
  final descrizione = TextEditingController(text: o?['descrizione'] as String? ?? '');
  final impegno = TextEditingController(text: '${o?['impegno'] ?? disponibile}');
  final nota = TextEditingController();
  var tipo = o?['tipo'] as String? ?? 'OPERATIVO';
  String? errore;
  final risultato = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (c) => StatefulBuilder(
      builder: (c, aggiorna) => AlertDialog(
        title: Text(o == null ? 'Nuovo obiettivo' : 'Modifica l\'obiettivo'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: titolo, maxLines: 2, minLines: 1, decoration: const InputDecoration(labelText: 'Titolo *')),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(
                  child: TextField(
                    controller: codice,
                    decoration: const InputDecoration(labelText: 'Codice nel PIAO', hintText: 'es. P2_OS3_OO1_OG1_26_2'),
                  ),
                ),
                const SizedBox(width: 12),
                SizedBox(
                  width: 200,
                  child: DropdownButtonFormField<String>(
                    initialValue: tipo,
                    decoration: const InputDecoration(labelText: 'Tipo'),
                    items: [for (final e in tipiObiettivo.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
                    onChanged: (v) => tipo = v ?? tipo,
                  ),
                ),
              ]),
              const SizedBox(height: 12),
              TextField(controller: descrizione, maxLines: 4, minLines: 2, decoration: const InputDecoration(labelText: 'Descrizione')),
              const SizedBox(height: 12),
              _campoPercentuale(impegno, 'Impegno',
                  aiuto: 'Rispetto agli altri obiettivi della struttura nell\'anno: disponibile $disponibile%'),
              if (o != null) ...[
                const SizedBox(height: 12),
                TextField(controller: nota, maxLines: 2, minLines: 1, decoration: const InputDecoration(labelText: _campoNota)),
              ],
              if (errore != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(errore!, style: TextStyle(color: Theme.of(c).colorScheme.error)),
                ),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Annulla')),
          FilledButton(
            onPressed: () {
              final i = _intero(impegno);
              if (titolo.text.trim().isEmpty) return aggiorna(() => errore = 'Il titolo è obbligatorio');
              if (i == null || i < 0 || i > disponibile) {
                return aggiorna(() => errore = 'L\'impegno è un numero tra 0 e $disponibile');
              }
              Navigator.pop(c, {
                'codice': codice.text.trim().isEmpty ? null : codice.text.trim(),
                'titolo': titolo.text.trim(),
                'descrizione': descrizione.text.trim().isEmpty ? null : descrizione.text.trim(),
                'tipo': tipo,
                'impegno': i,
                if (nota.text.trim().isNotEmpty) 'nota': nota.text.trim(),
              });
            },
            child: const Text('Salva'),
          ),
        ],
      ),
    ),
  );
  for (final t in [codice, titolo, descrizione, impegno, nota]) {
    t.dispose();
  }
  return risultato;
}

/// Finestra di un'azione o di una misura: descrizione (solo azioni; la misura si sceglie
/// alla creazione), impegno, completamento, scadenza.
Future<Map<String, dynamic>?> modificaElemento(
  BuildContext context, {
  required String tipo,
  Map<String, dynamic>? x,
  Map<String, dynamic>? misura, // misura scelta (nuova misura)
  required int disponibile,
  required int anno,
}) async {
  final descrizione = TextEditingController(text: x?['descrizione'] as String? ?? '');
  final impegno = TextEditingController(text: '${x?['impegno'] ?? disponibile}');
  final completamento = TextEditingController(text: '${x?['completamento'] ?? 0}');
  final nota = TextEditingController();
  var scadenza = daIso(x?['scadenza'] as String?) ?? DateTime(anno, 12, 31);
  String? errore;
  final azione = tipo == 'AZIONE';
  final risultato = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (c) => StatefulBuilder(
      builder: (c, aggiorna) => AlertDialog(
        title: Text('${x == null ? 'Nuova' : 'Modifica'} ${azione ? 'azione' : 'misura'}'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (azione)
                TextField(controller: descrizione, maxLines: 4, minLines: 2, decoration: const InputDecoration(labelText: 'Descrizione *'))
              else
                Text('${x?['misura_codice'] ?? misura?['codice']} - ${x?['descrizione'] ?? misura?['descrizione']}',
                    style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: _campoPercentuale(impegno, 'Impegno', aiuto: 'Disponibile $disponibile%')),
                const SizedBox(width: 12),
                Expanded(child: _campoPercentuale(completamento, 'Completamento')),
              ]),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: Text('Da completare entro il ${formatData(isoData(scadenza))}')),
                TextButton.icon(
                  icon: const Icon(Icons.event, size: 18),
                  label: const Text('Cambia'),
                  onPressed: () async {
                    final d = await scegliData(c, scadenza);
                    if (d != null) aggiorna(() => scadenza = d);
                  },
                ),
              ]),
              if (x != null) ...[
                const SizedBox(height: 12),
                TextField(controller: nota, maxLines: 2, minLines: 1, decoration: const InputDecoration(labelText: _campoNota)),
              ],
              if (errore != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(errore!, style: TextStyle(color: Theme.of(c).colorScheme.error)),
                ),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Annulla')),
          FilledButton(
            onPressed: () {
              final i = _intero(impegno), comp = _intero(completamento);
              if (azione && descrizione.text.trim().isEmpty) return aggiorna(() => errore = 'Descrivi l\'azione');
              if (i == null || i < 0 || i > disponibile) {
                return aggiorna(() => errore = 'L\'impegno è un numero tra 0 e $disponibile');
              }
              if (comp == null || comp < 0 || comp > 100) {
                return aggiorna(() => errore = 'Il completamento è un numero tra 0 e 100');
              }
              Navigator.pop(c, {
                if (azione) 'descrizione': descrizione.text.trim(),
                'impegno': i,
                'completamento': comp,
                'scadenza': isoData(scadenza),
                if (nota.text.trim().isNotEmpty) 'nota': nota.text.trim(),
              });
            },
            child: const Text('Salva'),
          ),
        ],
      ),
    ),
  );
  for (final t in [descrizione, impegno, completamento, nota]) {
    t.dispose();
  }
  return risultato;
}

/// Scelta di una misura della mappatura dei rischi (quelle della struttura per prime).
Future<Map<String, dynamic>?> scegliMisura(BuildContext context, String strutturaId, Set<String> giaPresenti) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (c) => _SceltaMisura(strutturaId: strutturaId, giaPresenti: giaPresenti),
  );
}

class _SceltaMisura extends StatefulWidget {
  const _SceltaMisura({required this.strutturaId, required this.giaPresenti});

  final String strutturaId;
  final Set<String> giaPresenti;

  @override
  State<_SceltaMisura> createState() => _SceltaMisuraState();
}

class _SceltaMisuraState extends State<_SceltaMisura> {
  final _testo = TextEditingController();
  late Future<List<Map<String, dynamic>>> _misure;

  @override
  void initState() {
    super.initState();
    _cerca();
  }

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  void _cerca() => setState(() {
        _misure = apiDi(context).get('$apiPerformance/misure', query: {
          'struttura_id': widget.strutturaId,
          'testo': _testo.text.trim(),
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Scegli una misura della mappatura dei rischi'),
        content: SizedBox(
          width: 640,
          height: 460,
          child: Column(children: [
            TextField(
              controller: _testo,
              decoration: const InputDecoration(labelText: 'Cerca (codice o descrizione)', prefixIcon: Icon(Icons.search), isDense: true),
              onSubmitted: (_) => _cerca(),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: Caricamento<List<Map<String, dynamic>>>(
                future: _misure,
                riprova: _cerca,
                builder: (context, misure) => misure.isEmpty
                    ? const Center(child: Text('Nessuna misura trovata.'))
                    : ListView(children: [
                        for (final m in misure)
                          ListTile(
                            dense: true,
                            enabled: !widget.giaPresenti.contains(m['id']),
                            leading: Icon(m['struttura_id'] == widget.strutturaId ? Icons.star_outline : Icons.task_alt, size: 20),
                            title: Text('${m['codice']} - ${m['descrizione']}'),
                            subtitle: Text([
                              m['tipo'] == 'GENERALE' ? 'Generale' : 'Specifica',
                              ?m['categoria'],
                              if (widget.giaPresenti.contains(m['id'])) 'già nell\'obiettivo',
                            ].join(' · ')),
                            onTap: () => Navigator.pop(context, m),
                          ),
                      ]),
              ),
            ),
          ]),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla'))],
      );
}

/// Nota facoltativa per un'eliminazione (null: annullata).
Future<String?> confermaConNota(BuildContext context, String titolo, String testo) async {
  final nota = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(titolo),
      content: SizedBox(
        width: 480,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(testo),
          const SizedBox(height: 12),
          TextField(controller: nota, maxLines: 2, minLines: 1, decoration: const InputDecoration(labelText: _campoNota)),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Conferma')),
      ],
    ),
  );
  final testoNota = nota.text.trim();
  nota.dispose();
  return ok == true ? testoNota : null;
}

/// Storico delle modifiche: chi, quando, cosa, i campi con il valore prima e dopo, la nota.
class Storico extends StatelessWidget {
  const Storico(this.voci, {super.key});

  final List<Map<String, dynamic>> voci;

  static const _azioni = {'CREATO': 'creazione', 'MODIFICATO': 'modifica', 'ELIMINATO': 'eliminazione'};
  static const _oggetti = {'PIAO': 'PIAO', 'OBIETTIVO': 'Obiettivo', 'AZIONE': 'Azione', 'MISURA': 'Misura'};
  static const _campi = {
    'codice': 'codice', 'titolo': 'titolo', 'descrizione': 'descrizione', 'tipo': 'tipo', 'impegno': 'impegno',
    'completamento': 'completamento', 'scadenza': 'scadenza', 'stato': 'stato', 'atto': 'atto', 'anno': 'anno',
    'struttura': 'struttura',
  };

  static String _valore(String campo, Object? v) {
    if (v == null || v == '') return '—';
    if (campo == 'impegno' || campo == 'completamento') return '$v%';
    if (campo == 'scadenza') return formatData(v);
    if (campo == 'tipo') return tipiObiettivo[v] ?? '$v';
    return '$v';
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    if (voci.isEmpty) return const Text('Nessuna modifica.');
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final v in voci)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${formatData(v['quando'])} ${(v['quando'] as String? ?? '').length >= 16 ? (v['quando'] as String).substring(11, 16) : ''} · '
                '${v['utente']} · ${_oggetti[v['oggetto']] ?? v['oggetto']}, ${_azioni[v['azione']] ?? v['azione']}',
                style: tema.textTheme.labelMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
            Text('${v['descrizione']}'),
            if (v['azione'] == 'MODIFICATO')
              for (final e in (v['campi'] as Map? ?? const {}).entries)
                Text('  ${_campi[e.key] ?? e.key}: ${_valore('${e.key}', (e.value as List)[0])} → ${_valore('${e.key}', (e.value as List)[1])}',
                    style: tema.textTheme.bodySmall),
            if (v['nota'] != null) Text('  Nota: ${v['nota']}', style: tema.textTheme.bodySmall?.copyWith(fontStyle: FontStyle.italic)),
          ]),
        ),
    ]);
  }
}
