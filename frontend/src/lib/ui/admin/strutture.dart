import 'package:flutter/material.dart';

import '../../util/scelta_file.dart';
import '../comuni.dart';

/// Strutture in ordine di albero (ogni struttura seguita dalle sottostanti) con la
/// profondità: per l'elenco e per le scelte nei menu a tendina.
List<(Map<String, dynamic>, int)> alberoStrutture(List<Map<String, dynamic>> strutture) {
  final ids = {for (final s in strutture) s['id']};
  final figli = <Object?, List<Map<String, dynamic>>>{};
  for (final s in strutture) {
    // una struttura con il padre mancante si mostra al primo livello
    final padre = ids.contains(s['padre_id']) ? s['padre_id'] : null;
    figli.putIfAbsent(padre, () => []).add(s);
  }
  final risultato = <(Map<String, dynamic>, int)>[];
  final visti = <Object?>{};
  void visita(Object? padre, int livello) {
    for (final s in figli[padre] ?? const <Map<String, dynamic>>[]) {
      if (!visti.add(s['id'])) continue;
      risultato.add((s, livello));
      visita(s['id'], livello + 1);
    }
  }

  visita(null, 0);
  return risultato;
}

/// Etichetta di una struttura: codice e descrizione.
String etichettaStruttura(Map<String, dynamic> s) => '${s['codice']} - ${s['descrizione']}';

/// Menu a tendina delle strutture attive (con quella già scelta, anche se disattivata).
class SceltaStruttura extends StatelessWidget {
  const SceltaStruttura({
    super.key,
    required this.strutture,
    required this.valore,
    required this.onChanged,
    this.etichetta = 'Struttura',
    this.vuota = 'Nessuna',
    this.escluse = const {},
  });

  final List<Map<String, dynamic>> strutture;
  final String? valore;
  final ValueChanged<String?> onChanged;
  final String etichetta;
  final String vuota;
  final Set<Object?> escluse; // es. la struttura stessa e le sue sottostanti, scegliendo il padre

  @override
  Widget build(BuildContext context) {
    final voci = alberoStrutture(strutture)
        .where((e) => !escluse.contains(e.$1['id']) && (e.$1['attiva'] == true || e.$1['id'] == valore));
    return DropdownButtonFormField<String?>(
      initialValue: valore,
      isExpanded: true,
      decoration: InputDecoration(labelText: etichetta),
      items: [
        DropdownMenuItem(value: null, child: Text(vuota)),
        for (final (s, livello) in voci)
          DropdownMenuItem(
            value: s['id'] as String,
            child: Padding(
              padding: EdgeInsets.only(left: 16.0 * livello),
              child: Text(etichettaStruttura(s), overflow: TextOverflow.ellipsis),
            ),
          ),
      ],
      onChanged: onChanged,
    );
  }
}

/// Strutture organizzative dell'ente (staff, settori, U.O.), comuni a tutti i moduli: albero,
/// nuova struttura, modifica, disattivazione, eliminazione (solo se non usata) e importazione
/// da Excel o CSV.
class StrutturePage extends StatefulWidget {
  const StrutturePage({super.key});

  @override
  State<StrutturePage> createState() => _StrutturePageState();
}

class _StrutturePageState extends State<StrutturePage> {
  late Future<List<Map<String, dynamic>>> _strutture;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _strutture = apiDi(context)
            .get('/api/v1/ente/strutture')
            .then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  /// La struttura e tutte le sue sottostanti (non possono diventarne il padre).
  Set<Object?> _discendenti(List<Map<String, dynamic>> tutte, Object? id) {
    final risultato = <Object?>{id};
    var cresciuto = true;
    while (cresciuto) {
      cresciuto = false;
      for (final s in tutte) {
        if (risultato.contains(s['padre_id']) && risultato.add(s['id'])) cresciuto = true;
      }
    }
    return risultato;
  }

  Future<void> _modifica(List<Map<String, dynamic>> tutte, {Map<String, dynamic>? s, String? padre}) async {
    final nuova = s == null;
    final codice = TextEditingController(text: s?['codice'] as String? ?? '');
    final descrizione = TextEditingController(text: s?['descrizione'] as String? ?? '');
    final ordine = TextEditingController(text: '${s?['ordine'] ?? 0}');
    var padreId = nuova ? padre : s['padre_id'] as String?;
    var attiva = s?['attiva'] != false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: Text(nuova ? 'Nuova struttura' : 'Struttura ${s['codice']}'),
          content: SizedBox(
            width: 480,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                  controller: codice,
                  decoration: const InputDecoration(labelText: 'Codice', hintText: 'es. SETTORE 2, U.O. 2.1'),
                ),
                TextField(controller: descrizione, decoration: const InputDecoration(labelText: 'Descrizione')),
                const SizedBox(height: 8),
                SceltaStruttura(
                  strutture: tutte,
                  valore: padreId,
                  etichetta: 'Struttura superiore',
                  vuota: 'Nessuna (primo livello)',
                  escluse: nuova ? const {} : _discendenti(tutte, s['id']),
                  onChanged: (v) => aggiorna(() => padreId = v),
                ),
                TextField(
                  controller: ordine,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Ordine', helperText: 'Posizione tra le strutture dello stesso livello'),
                ),
                if (!nuova)
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Attiva'),
                    subtitle: const Text('Una struttura soppressa si disattiva: resta nello storico ma non si può più scegliere'),
                    value: attiva,
                    onChanged: (v) => aggiorna(() => attiva = v),
                  ),
              ]),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Salva')),
          ],
        ),
      ),
    );
    final corpo = {
      'codice': codice.text.trim(),
      'descrizione': descrizione.text.trim(),
      'padre_id': padreId,
      'ordine': int.tryParse(ordine.text.trim()) ?? 0,
      'attiva': attiva,
    };
    for (final c in [codice, descrizione, ordine]) {
      c.dispose();
    }
    if (ok != true || !mounted) return;
    try {
      final api = apiDi(context);
      if (nuova) {
        await api.post('/api/v1/ente/strutture', corpo);
      } else {
        await api.put('/api/v1/ente/strutture/${s['id']}', corpo);
      }
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _elimina(Map<String, dynamic> s) async {
    if (!await conferma(context, 'Eliminare ${s['codice']}?',
        'Si può eliminare solo una struttura senza strutture sottostanti né utenti assegnati.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('/api/v1/ente/strutture/${s['id']}');
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _importa() async {
    final file = await scegliFile(['xlsx', 'csv']);
    if (file == null || !mounted) return;
    try {
      final r = await apiDi(context).postMultipart(
        '/api/v1/ente/strutture/importa',
        campi: {},
        campoFile: 'file',
        bytes: file.bytes,
        nomeFile: file.name,
      ) as Map<String, dynamic>;
      if (mounted) mostraMessaggio(context, 'Strutture create: ${r['create']}, aggiornate: ${r['aggiornate']}');
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Caricamento<List<Map<String, dynamic>>>(
        future: _strutture,
        riprova: _carica,
        builder: (context, tutte) {
          final colori = Theme.of(context).colorScheme;
          return ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 88), children: [
            Sezione(
              titolo: 'Strutture organizzative',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Staff, settori e unità organizzative dell\'ente, usati da tutti i moduli (per esempio '
                    'per il monitoraggio delle misure anticorruzione). Chi è assegnato a una struttura opera '
                    'anche su quelle sottostanti.'),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  FilledButton.icon(
                    onPressed: () => _modifica(tutte),
                    icon: const Icon(Icons.add),
                    label: const Text('Nuova struttura'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _importa,
                    icon: const Icon(Icons.upload_file),
                    label: const Text('Importa da Excel o CSV'),
                  ),
                ]),
                const SizedBox(height: 4),
                Text('Il file ha le colonne codice, descrizione e padre (codice della struttura superiore). '
                    'Le strutture già presenti con lo stesso codice si aggiornano.',
                    style: TextStyle(color: colori.onSurfaceVariant)),
              ]),
            ),
            if (tutte.isEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('Nessuna struttura.')),
            for (final (s, livello) in alberoStrutture(tutte))
              Card(
                margin: EdgeInsets.only(left: 24.0 * livello, bottom: 4),
                child: ListTile(
                  dense: true,
                  leading: Icon(livello == 0 ? Icons.account_tree_outlined : Icons.subdirectory_arrow_right,
                      color: s['attiva'] == true ? null : Theme.of(context).disabledColor),
                  title: Text(etichettaStruttura(s) + (s['attiva'] == true ? '' : ' (disattivata)'),
                      style: s['attiva'] == true ? null : TextStyle(color: Theme.of(context).disabledColor)),
                  trailing: Wrap(children: [
                    IconButton(
                      tooltip: 'Aggiungi una struttura sottostante',
                      icon: const Icon(Icons.add),
                      onPressed: () => _modifica(tutte, padre: s['id'] as String),
                    ),
                    IconButton(
                      tooltip: 'Elimina',
                      icon: const IconaElimina(),
                      onPressed: () => _elimina(s),
                    ),
                  ]),
                  onTap: () => _modifica(tutte, s: s),
                ),
              ),
          ]);
        },
      ),
    );
  }
}
