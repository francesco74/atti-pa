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
  bool get approvatore => contesto['approvatore'] == true; // decide le proposte, modifica direttamente
  int get daDecidere => (contesto['da_decidere'] as int?) ?? 0;
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

// --- proposte -------------------------------------------------------------------------------

const etichetteStatoProposta = {
  'BOZZA': 'In bozza',
  'INVIATA': 'In attesa di approvazione',
  'RESTITUITA': 'Restituita',
  'APPROVATA': 'Approvata',
  'RESPINTA': 'Respinta',
};
const _coloriStatoProposta = {
  'BOZZA': Colors.blueGrey,
  'INVIATA': Colors.blue,
  'RESTITUITA': Colors.orange,
  'APPROVATA': Colors.green,
  'RESPINTA': Colors.red,
};
const _tipiProposta = {'CREA': 'Nuovo obiettivo', 'MODIFICA': 'Modifica', 'ELIMINA': 'Eliminazione'};

String etichettaTipoProposta(Object? tipo) => _tipiProposta[tipo] ?? '$tipo';

/// Stato di una proposta, colorato.
class StatoPropostaPf extends StatelessWidget {
  const StatoPropostaPf(this.stato, {super.key});

  final Object? stato;

  @override
  Widget build(BuildContext context) =>
      Etichetta(etichetteStatoProposta[stato] ?? '$stato', _coloriStatoProposta[stato] ?? Colors.blueGrey);
}

/// Motivazione o nota per una decisione o un invio (null: annullato). Con [obbligatoria]
/// non si conferma vuota.
Future<String?> chiediTesto(BuildContext context, String titolo,
        {required String etichetta, String? testo, bool obbligatoria = false, String? iniziale}) =>
    showDialog<String>(
      context: context,
      builder: (_) => _DialogoTesto(titolo: titolo, etichetta: etichetta, testo: testo, obbligatoria: obbligatoria, iniziale: iniziale),
    );

class _DialogoTesto extends StatefulWidget {
  const _DialogoTesto({required this.titolo, required this.etichetta, this.testo, required this.obbligatoria, this.iniziale});

  final String titolo, etichetta;
  final String? testo, iniziale;
  final bool obbligatoria;

  @override
  State<_DialogoTesto> createState() => _DialogoTestoState();
}

class _DialogoTestoState extends State<_DialogoTesto> {
  late final _c = TextEditingController(text: widget.iniziale ?? '');
  String? _errore;

  @override
  void dispose() {
    _c.dispose(); // a finestra chiusa (anche dopo l'animazione)
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.titolo),
        content: SizedBox(
          width: 480,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (widget.testo != null) ...[Text(widget.testo!), const SizedBox(height: 12)],
            TextField(
              controller: _c,
              maxLines: 4,
              minLines: 2,
              decoration: InputDecoration(
                labelText: widget.obbligatoria ? '${widget.etichetta} *' : '${widget.etichetta} (facoltativa)',
                errorText: _errore,
              ),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
          FilledButton(
            onPressed: () {
              if (widget.obbligatoria && _c.text.trim().isEmpty) return setState(() => _errore = 'Obbligatoria');
              Navigator.pop(context, _c.text.trim());
            },
            child: const Text('Conferma'),
          ),
        ],
      );
}

/// Contenuto di una finestra che possiede i suoi [controllori] e li libera quando la finestra è
/// smontata, cioè dopo l'animazione di chiusura (liberarli appena showDialog ritorna fa usare
/// alla finestra che si chiude un controller già liberato).
class _ConControllori extends StatefulWidget {
  const _ConControllori(this.controllori, this.builder);

  final List<TextEditingController> controllori;
  final WidgetBuilder builder;

  @override
  State<_ConControllori> createState() => _ConControlloriState();
}

class _ConControlloriState extends State<_ConControllori> {
  @override
  void dispose() {
    for (final c in widget.controllori) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(context);
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

// --- indicatori -------------------------------------------------------------------------------

const tipiIndicatore = {'NUMERO': 'Numero', 'PERCENTUALE': 'Percentuale', 'SI_NO': 'Sì/no', 'DATA': 'Data'};
const _campiIndicatore = ['id', 'descrizione', 'tipo', 'unita', 'partenza', 'target', 'target_data', 'verso', 'fonte'];

/// Numero in forma italiana, senza decimali inutili: 3.0 -> "3", 2.5 -> "2,5".
String numeroIt(num v) =>
    v == v.roundToDouble() ? '${v.round()}' : v.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '').replaceAll('.', ',');

double? _decimale(TextEditingController c) => double.tryParse(c.text.trim().replaceAll(',', '.'));

/// Un valore (partenza, target, rilevato) nella forma dell'indicatore.
String valoreIndicatore(Map ind, Object? v) {
  if (v == null) return '—';
  return switch (ind['tipo']) {
    'DATA' => formatData(v),
    'SI_NO' => v == 1 ? 'sì' : 'no',
    'PERCENTUALE' => '${numeroIt(v as num)}%',
    _ => '${numeroIt(v as num)} ${ind['unita'] ?? ''}'.trim(),
  };
}

/// Sintesi della definizione: "Eventi a cui si partecipa: 3 eventi", "Tempo medio: da 40 giorni
/// a 30 giorni (più basso è meglio)", "Regolamento adottato: sì", "Report: entro il 30/06/2026".
String testoIndicatore(Map ind) {
  final String obiettivo;
  switch (ind['tipo']) {
    case 'SI_NO':
      obiettivo = 'sì';
    case 'DATA':
      obiettivo = 'entro il ${formatData(ind['target_data'])}';
    default:
      var t = valoreIndicatore(ind, ind['target']);
      if (ind['partenza'] != null) t = 'da ${valoreIndicatore(ind, ind['partenza'])} a $t';
      obiettivo = ind['verso'] == 'DECRESCENTE' ? '$t (più basso è meglio)' : t;
  }
  return '${ind['descrizione']}: $obiettivo';
}

/// Il valore rilevato dell'indicatore, o "non rilevato".
String rilevatoIndicatore(Map ind) {
  final v = ind['tipo'] == 'DATA' ? ind['rilevato_data'] : ind['rilevato'];
  return v == null ? 'non rilevato' : 'rilevato ${valoreIndicatore(ind, v)}';
}

/// Solo la definizione (senza rilevato e raggiungimento): quella che si salva con l'obiettivo.
Map<String, dynamic> definizioneIndicatore(Map ind) => {for (final k in _campiIndicatore) if (ind.containsKey(k)) k: ind[k]};

/// Primo indicatore di una misura scelta dalla mappatura, dai suoi campi indicatore e target
/// (testo libero): il primo numero del target diventa il valore da raggiungere (percentuale se
/// c'è "%"); senza numeri è un sì/no. Null se la misura non ha indicatore.
Map<String, dynamic>? indicatoreDaMisura(Map misura) {
  final descrizione = (misura['indicatore'] as String? ?? '').trim();
  if (descrizione.isEmpty) return null;
  final target = misura['target'] as String? ?? '';
  final n = RegExp(r'\d+(?:[.,]\d+)?').firstMatch(target);
  final valore = n == null ? null : double.tryParse(n.group(0)!.replaceAll(',', '.'));
  if (valore == null) return {'descrizione': descrizione, 'tipo': 'SI_NO', 'verso': 'CRESCENTE'};
  final percento = target.contains('%') && valore <= 100;
  return {'descrizione': descrizione, 'tipo': percento ? 'PERCENTUALE' : 'NUMERO', 'target': valore, 'verso': 'CRESCENTE'};
}

/// Indicatori di un'azione o misura, uno per riga; con [rilevati] anche il valore rilevato e il
/// raggiungimento.
class ElencoIndicatori extends StatelessWidget {
  const ElencoIndicatori(this.indicatori, {super.key, this.rilevati = false});

  final List<Map<String, dynamic>> indicatori;
  final bool rilevati;

  @override
  Widget build(BuildContext context) {
    final stile = Theme.of(context).textTheme.bodySmall;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final i in indicatori)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Row(children: [
            const Tooltip(message: 'Indicatore', child: Icon(Icons.straighten, size: 16)),
            const SizedBox(width: 6),
            Expanded(child: Text(rilevati ? '${testoIndicatore(i)} · ${rilevatoIndicatore(i)}' : testoIndicatore(i), style: stile)),
            if (rilevati) ...[
              const SizedBox(width: 8),
              Etichetta('raggiunto ${percentuale(i['raggiungimento'] as num?)}',
                  ((i['raggiungimento'] as num?) ?? 0) >= 100 ? Colors.green : Colors.blueGrey),
            ],
          ]),
        ),
    ]);
  }
}

/// Finestra di un indicatore: cosa si misura, tipo, unità, valore di partenza, target, verso
/// (o la data entro cui raggiungerlo), fonte del dato. Restituisce la definizione (con l'id se
/// c'era).
Future<Map<String, dynamic>?> modificaIndicatore(BuildContext context, {Map<String, dynamic>? i}) async {
  String testo(Object? v) => v == null ? '' : numeroIt(v as num);
  final descrizione = TextEditingController(text: i?['descrizione'] as String? ?? '');
  final unita = TextEditingController(text: i?['unita'] as String? ?? '');
  final partenza = TextEditingController(text: testo(i?['partenza']));
  final target = TextEditingController(text: testo(i?['target']));
  final fonte = TextEditingController(text: i?['fonte'] as String? ?? '');
  var tipo = i?['tipo'] as String? ?? 'NUMERO';
  var verso = i?['verso'] as String? ?? 'CRESCENTE';
  var entro = daIso(i?['target_data'] as String?);
  String? errore;
  final risultato = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _ConControllori([descrizione, unita, partenza, target, fonte], (c) => StatefulBuilder(
      builder: (c, aggiorna) {
        final numerico = tipo == 'NUMERO' || tipo == 'PERCENTUALE';
        return AlertDialog(
          title: Text(i == null ? 'Nuovo indicatore' : 'Modifica l\'indicatore'),
          content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                TextField(
                  controller: descrizione,
                  maxLines: 2,
                  minLines: 1,
                  decoration: const InputDecoration(labelText: 'Cosa si misura *', hintText: 'es. Eventi a cui si partecipa'),
                ),
                const SizedBox(height: 12),
                Row(children: [
                  SizedBox(
                    width: 200,
                    child: DropdownButtonFormField<String>(
                      initialValue: tipo,
                      isExpanded: true,
                      decoration: const InputDecoration(labelText: 'Tipo'),
                      items: [
                        for (final e in tipiIndicatore.entries)
                          DropdownMenuItem(value: e.key, child: Text(e.value, overflow: TextOverflow.ellipsis)),
                      ],
                      onChanged: (v) => aggiorna(() => tipo = v ?? tipo),
                    ),
                  ),
                  if (tipo == 'NUMERO') ...[
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        controller: unita,
                        decoration: const InputDecoration(labelText: 'Unità di misura', hintText: 'es. eventi, giorni'),
                      ),
                    ),
                  ],
                ]),
                if (numerico) ...[
                  const SizedBox(height: 12),
                  Row(children: [
                    Expanded(
                      child: TextField(
                        controller: partenza,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: InputDecoration(
                            labelText: 'Valore di partenza', helperText: 'Facoltativo', suffixText: tipo == 'PERCENTUALE' ? '%' : null),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        controller: target,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: InputDecoration(labelText: 'Target *', helperText: 'Valore da raggiungere',
                            suffixText: tipo == 'PERCENTUALE' ? '%' : null),
                      ),
                    ),
                  ]),
                  const SizedBox(height: 12),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'CRESCENTE', label: Text('Più alto è meglio'), icon: Icon(Icons.trending_up)),
                      ButtonSegment(value: 'DECRESCENTE', label: Text('Più basso è meglio'), icon: Icon(Icons.trending_down)),
                    ],
                    selected: {verso},
                    onSelectionChanged: (v) => aggiorna(() => verso = v.first),
                  ),
                ],
                if (tipo == 'DATA') ...[
                  const SizedBox(height: 12),
                  Row(children: [
                    Expanded(child: Text(entro == null ? 'Da raggiungere entro: —' : 'Da raggiungere entro il ${formatData(isoData(entro!))}')),
                    TextButton.icon(
                      icon: const Icon(Icons.event, size: 18),
                      label: const Text('Scegli'),
                      onPressed: () async {
                        final d = await scegliData(c, entro);
                        if (d != null) aggiorna(() => entro = d);
                      },
                    ),
                  ]),
                ],
                if (tipo == 'SI_NO')
                  const Padding(
                    padding: EdgeInsets.only(top: 12),
                    child: Text('Raggiunto quando si rileva "sì" (es. regolamento adottato).'),
                  ),
                const SizedBox(height: 12),
                TextField(controller: fonte, decoration: const InputDecoration(labelText: 'Fonte del dato', hintText: 'es. protocollo')),
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
                final t = _decimale(target), p = partenza.text.trim().isEmpty ? null : _decimale(partenza);
                if (descrizione.text.trim().isEmpty) return aggiorna(() => errore = 'Indica cosa si misura');
                if (numerico) {
                  if (t == null) return aggiorna(() => errore = 'Indica il target (un numero)');
                  if (partenza.text.trim().isNotEmpty && p == null) return aggiorna(() => errore = 'Il valore di partenza è un numero');
                  if (tipo == 'PERCENTUALE' && (t < 0 || t > 100 || (p != null && (p < 0 || p > 100)))) {
                    return aggiorna(() => errore = 'Le percentuali vanno da 0 a 100');
                  }
                  if (p != null && verso == 'CRESCENTE' && p >= t) {
                    return aggiorna(() => errore = 'La partenza deve essere più bassa del target');
                  }
                  if (p != null && verso == 'DECRESCENTE' && p <= t) {
                    return aggiorna(() => errore = 'Se più basso è meglio, la partenza deve essere più alta del target');
                  }
                }
                if (tipo == 'DATA' && entro == null) return aggiorna(() => errore = 'Scegli la data entro cui raggiungerlo');
                Navigator.pop(c, {
                  if (i?['id'] != null) 'id': i!['id'],
                  'descrizione': descrizione.text.trim(),
                  'tipo': tipo,
                  'unita': tipo == 'NUMERO' && unita.text.trim().isNotEmpty ? unita.text.trim() : null,
                  'partenza': numerico ? p : null,
                  'target': numerico ? t : null,
                  'target_data': tipo == 'DATA' ? isoData(entro!) : null,
                  'verso': numerico ? verso : 'CRESCENTE',
                  'fonte': fonte.text.trim().isEmpty ? null : fonte.text.trim(),
                });
              },
              child: const Text('Salva'),
            ),
          ],
        );
      },
    )),
  );
  return risultato;
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
/// Con [nota] (modifiche dirette) anche la nota per lo storico; nelle proposte la nota è della proposta.
Future<Map<String, dynamic>?> modificaObiettivo(BuildContext context,
    {Map<String, dynamic>? o, required int disponibile, bool nota = true}) async {
  final conNota = nota;
  final codice = TextEditingController(text: o?['codice'] as String? ?? '');
  final titolo = TextEditingController(text: o?['titolo'] as String? ?? '');
  final descrizione = TextEditingController(text: o?['descrizione'] as String? ?? '');
  final impegno = TextEditingController(text: '${o?['impegno'] ?? disponibile}');
  final testoNota = TextEditingController();
  var tipo = o?['tipo'] as String? ?? 'OPERATIVO';
  String? errore;
  final risultato = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _ConControllori([codice, titolo, descrizione, impegno, testoNota], (c) => StatefulBuilder(
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
              if (o != null && conNota) ...[
                const SizedBox(height: 12),
                TextField(controller: testoNota, maxLines: 2, minLines: 1, decoration: const InputDecoration(labelText: _campoNota)),
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
                if (testoNota.text.trim().isNotEmpty) 'nota': testoNota.text.trim(),
              });
            },
            child: const Text('Salva'),
          ),
        ],
      ),
    )),
  );
  return risultato;
}

/// Finestra di un'azione o di una misura: descrizione (solo azioni; la misura si sceglie
/// alla creazione), impegno, scadenza, indicatori e, senza indicatori, completamento. Una
/// misura nuova parte con l'indicatore della mappatura. Nelle proposte niente completamento
/// (si aggiorna a parte) né nota (è della proposta).
Future<Map<String, dynamic>?> modificaElemento(
  BuildContext context, {
  required String tipo,
  Map<String, dynamic>? x,
  Map<String, dynamic>? misura, // misura scelta (nuova misura)
  required int disponibile,
  required int anno,
  bool proposta = false,
}) async {
  final descrizione = TextEditingController(text: x?['descrizione'] as String? ?? '');
  final impegno = TextEditingController(text: '${x?['impegno'] ?? disponibile}');
  final completamento = TextEditingController(text: '${x?['completamento'] ?? 0}');
  final nota = TextEditingController();
  var scadenza = daIso(x?['scadenza'] as String?) ?? DateTime(anno, 12, 31);
  final daMisura = misura == null ? null : indicatoreDaMisura(misura);
  final indicatori = [
    if (x != null)
      for (final i in (x['indicatori'] as List? ?? const [])) definizioneIndicatore(i as Map)
    else
      ?daMisura,
  ];
  String? errore;
  final azione = tipo == 'AZIONE';
  // azione dal catalogo della mappatura: la descrizione è quella della voce e non si scrive
  final copiata = azione && x != null && dallaMappatura(x);
  final risultato = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _ConControllori([descrizione, impegno, completamento, nota], (c) => StatefulBuilder(
      builder: (c, aggiorna) => AlertDialog(
        title: Text('${x == null ? 'Nuova' : 'Modifica'} ${azione ? 'azione' : 'misura'}'),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (copiata) ...[
                Text(titoloElemento(x), style: const TextStyle(fontWeight: FontWeight.w600)),
                Text('Dal catalogo della mappatura dei rischi: la descrizione resta quella della voce.',
                    style: Theme.of(c).textTheme.bodySmall),
              ] else if (azione)
                TextField(controller: descrizione, maxLines: 4, minLines: 2, decoration: const InputDecoration(labelText: 'Descrizione *'))
              else
                Text(x != null ? titoloElemento(x) : '${misura?['codice']} - ${misura?['descrizione']}',
                    style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: _campoPercentuale(impegno, 'Impegno', aiuto: 'Disponibile $disponibile%')),
                if (!proposta && indicatori.isEmpty) ...[
                  const SizedBox(width: 12),
                  Expanded(child: _campoPercentuale(completamento, 'Completamento')),
                ],
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
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: Text('Indicatori', style: Theme.of(c).textTheme.titleSmall)),
                TextButton.icon(
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('Indicatore'),
                  onPressed: () async {
                    final i = await modificaIndicatore(c);
                    if (i != null) aggiorna(() => indicatori.add(i));
                  },
                ),
              ]),
              if (indicatori.isEmpty)
                Text('Nessun indicatore: il completamento si inserisce a mano. Con un indicatore (es. "eventi a cui si '
                    'partecipa: 3") si calcola dal valore rilevato.', style: Theme.of(c).textTheme.bodySmall)
              else ...[
                for (final (n, i) in indicatori.indexed)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.straighten, size: 18),
                    title: Text(testoIndicatore(i)),
                    subtitle: Text([tipiIndicatore[i['tipo']] ?? '${i['tipo']}', if (i['fonte'] != null) 'fonte: ${i['fonte']}'].join(' · ')),
                    trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                      IconButton(
                        tooltip: 'Modifica l\'indicatore',
                        icon: const Icon(Icons.edit_outlined, size: 18),
                        onPressed: () async {
                          final v = await modificaIndicatore(c, i: i);
                          if (v != null) aggiorna(() => indicatori[n] = v);
                        },
                      ),
                      IconButton(
                        tooltip: 'Togli l\'indicatore',
                        icon: const Icon(Icons.delete_outline, size: 18),
                        onPressed: () => aggiorna(() => indicatori.removeAt(n)),
                      ),
                    ]),
                  ),
                if (!proposta)
                  Text('Il completamento si calcola dai valori rilevati degli indicatori.', style: Theme.of(c).textTheme.bodySmall),
              ],
              if (x != null && !proposta) ...[
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
              if (azione && !copiata && descrizione.text.trim().isEmpty) return aggiorna(() => errore = 'Descrivi l\'azione');
              if (i == null || i < 0 || i > disponibile) {
                return aggiorna(() => errore = 'L\'impegno è un numero tra 0 e $disponibile');
              }
              final manuale = !proposta && indicatori.isEmpty;
              if (manuale && (comp == null || comp < 0 || comp > 100)) {
                return aggiorna(() => errore = 'Il completamento è un numero tra 0 e 100');
              }
              Navigator.pop(c, {
                if (azione && !copiata) 'descrizione': descrizione.text.trim(),
                'impegno': i,
                if (!proposta) 'completamento': manuale ? comp : (x?['completamento'] ?? 0),
                'scadenza': isoData(scadenza),
                'indicatori': indicatori,
                if (nota.text.trim().isNotEmpty) 'nota': nota.text.trim(),
              });
            },
            child: const Text('Salva'),
          ),
        ],
      ),
    )),
  );
  return risultato;
}

/// Avanzamento di un'azione o misura: i valori rilevati degli indicatori (il completamento si
/// calcola) o, senza indicatori, il completamento; nota per lo storico.
Future<Map<String, dynamic>?> aggiornaAvanzamento(BuildContext context, Map<String, dynamic> x) async {
  final indicatori = (x['indicatori'] as List? ?? const []).cast<Map<String, dynamic>>();
  final completamento = TextEditingController(text: '${x['completamento'] ?? 0}');
  final nota = TextEditingController();
  final numeri = {
    for (final i in indicatori)
      if (i['tipo'] == 'NUMERO' || i['tipo'] == 'PERCENTUALE')
        i['id']: TextEditingController(text: i['rilevato'] == null ? '' : numeroIt(i['rilevato'] as num)),
  };
  final siNo = {for (final i in indicatori) if (i['tipo'] == 'SI_NO') i['id']: (i['rilevato'] as num?)?.toInt() ?? -1};
  final date = {for (final i in indicatori) if (i['tipo'] == 'DATA') i['id']: daIso(i['rilevato_data'] as String?)};
  String? errore;
  final risultato = await showDialog<Map<String, dynamic>>(
    context: context,
    builder: (_) => _ConControllori([completamento, nota, ...numeri.values], (c) => StatefulBuilder(
      builder: (c, aggiorna) => AlertDialog(
        title: const Text('Aggiorna l\'avanzamento'),
        content: SizedBox(
          width: 520,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(titoloElemento(x), style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              if (indicatori.isEmpty)
                _campoPercentuale(completamento, 'Completamento')
              else ...[
                Text('Valori rilevati: il completamento si calcola dagli indicatori.', style: Theme.of(c).textTheme.bodySmall),
                for (final i in indicatori) ...[
                  const SizedBox(height: 12),
                  Text(testoIndicatore(i)),
                  const SizedBox(height: 4),
                  if (numeri.containsKey(i['id']))
                    TextField(
                      controller: numeri[i['id']],
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(
                        labelText: 'Valore rilevato',
                        isDense: true,
                        suffixText: i['tipo'] == 'PERCENTUALE' ? '%' : i['unita'] as String?,
                      ),
                    )
                  else if (i['tipo'] == 'SI_NO')
                    SegmentedButton<int>(
                      segments: const [
                        ButtonSegment(value: -1, label: Text('Non rilevato')),
                        ButtonSegment(value: 1, label: Text('Sì')),
                        ButtonSegment(value: 0, label: Text('No')),
                      ],
                      selected: {siNo[i['id']]!},
                      onSelectionChanged: (v) => aggiorna(() => siNo[i['id']] = v.first),
                    )
                  else
                    Row(children: [
                      Expanded(
                        child: Text(date[i['id']] == null
                            ? 'Non ancora raggiunto'
                            : 'Raggiunto il ${formatData(isoData(date[i['id']]!))}'),
                      ),
                      TextButton.icon(
                        icon: const Icon(Icons.event, size: 18),
                        label: const Text('Data'),
                        onPressed: () async {
                          final d = await scegliData(c, date[i['id']]);
                          if (d != null) aggiorna(() => date[i['id']] = d);
                        },
                      ),
                      if (date[i['id']] != null)
                        IconButton(
                          tooltip: 'Non ancora raggiunto',
                          icon: const Icon(Icons.clear, size: 18),
                          onPressed: () => aggiorna(() => date[i['id']] = null),
                        ),
                    ]),
                ],
              ],
              const SizedBox(height: 12),
              TextField(controller: nota, maxLines: 2, minLines: 1, decoration: const InputDecoration(labelText: _campoNota)),
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
              final testoNota = {if (nota.text.trim().isNotEmpty) 'nota': nota.text.trim()};
              if (indicatori.isEmpty) {
                final v = _intero(completamento);
                if (v == null || v < 0 || v > 100) return aggiorna(() => errore = 'Il completamento è un numero tra 0 e 100');
                return Navigator.pop(c, {'completamento': v, ...testoNota});
              }
              final rilevazioni = <Map<String, dynamic>>[];
              for (final i in indicatori) {
                final id = i['id'];
                if (numeri.containsKey(id)) {
                  final t = numeri[id]!.text.trim();
                  final v = t.isEmpty ? null : _decimale(numeri[id]!);
                  if (t.isNotEmpty && v == null) return aggiorna(() => errore = '«${i['descrizione']}»: il valore è un numero');
                  if (i['tipo'] == 'PERCENTUALE' && v != null && (v < 0 || v > 100)) {
                    return aggiorna(() => errore = '«${i['descrizione']}»: percentuale da 0 a 100');
                  }
                  rilevazioni.add({'id': id, 'rilevato': v});
                } else if (i['tipo'] == 'SI_NO') {
                  rilevazioni.add({'id': id, 'rilevato': siNo[id]! < 0 ? null : siNo[id]});
                } else {
                  rilevazioni.add({'id': id, 'rilevato_data': date[id] == null ? null : isoData(date[id]!)});
                }
              }
              Navigator.pop(c, {'indicatori': rilevazioni, ...testoNota});
            },
            child: const Text('Salva'),
          ),
        ],
      ),
    )),
  );
  return risultato;
}

/// Titolo di un'azione o misura, con il codice della sua voce del catalogo (radice) o, per le
/// prime copiate, della misura o dell'attività.
String titoloElemento(Map x) {
  final codice = x['voce_codice'] ?? x['misura_codice'] ?? x['mappatura_codice'];
  return codice == null ? '${x['descrizione']}' : '$codice - ${x['descrizione']}';
}

/// Azione dal catalogo della mappatura dei rischi (o copiata da un'attività, prima delle voci).
bool dallaMappatura(Map x) => x['voce_id'] != null || x['voce_codice'] != null || x['mappatura_codice'] != null;

/// Azione copiata da un'attività, senza voce, e poi eliminata dalla mappatura.
bool fuoriMappatura(Map x) => x['voce_codice'] == null && x['mappatura_codice'] != null && x['attivita_id'] == null;

/// Icona di un'azione o misura, con la spiegazione.
Widget iconaElemento(Map x) {
  final (icona, testo) = x['tipo'] == 'MISURA'
      ? (Icons.shield_outlined, 'Misura della mappatura dei rischi')
      : dallaMappatura(x)
          ? (Icons.account_tree_outlined, 'Azione dal catalogo della mappatura dei rischi')
          : (Icons.directions_run, 'Azione');
  return Tooltip(message: testo, child: Icon(icona));
}

/// Le radici di un processo o di una sola attività della mappatura, da spuntare per portarle
/// nell'obiettivo: le voci del catalogo delle attività (diventano azioni) e delle misure, senza
/// i rischi e senza ripetizioni (la misura usata sotto più rischi è una voce). Restituisce gli
/// elementi da aggiungere, con impegno 0% e scadenza a fine anno; le voci già nell'obiettivo non
/// si scelgono.
Future<List<Map<String, dynamic>>?> scegliDaCopiare(BuildContext context, Map<String, dynamic> voce,
    {required int anno, required Set<String> vociPresenti}) {
  return showDialog<List<Map<String, dynamic>>>(
    context: context,
    builder: (c) => _DaCopiare(voce: voce, anno: anno, vociPresenti: vociPresenti),
  );
}

/// Una radice da portare nell'obiettivo: la voce e il primo elemento del processo che la usa.
typedef _Radice = ({Map<String, dynamic> voce, Map<String, dynamic> elemento});

class _DaCopiare extends StatefulWidget {
  const _DaCopiare({required this.voce, required this.anno, required this.vociPresenti});

  final Map<String, dynamic> voce;
  final int anno;
  final Set<String> vociPresenti;

  @override
  State<_DaCopiare> createState() => _DaCopiareState();
}

class _DaCopiareState extends State<_DaCopiare> {
  late Future<Map<String, dynamic>> _albero;
  final _scelte = <String>{}; // voci spuntate
  List<_Radice> _azioni = const [], _misure = const [];
  int _senzaVoce = 0;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        final v = widget.voce;
        _albero = apiDi(context).get('$apiPerformance/mappatura/albero', query: {
          if (v['tipo'] == 'ATTIVITA') 'attivita_id': v['id'] as String else 'processo_id': v['id'] as String,
        }).then((a) {
          final albero = a as Map<String, dynamic>;
          if (mounted) setState(() => _radici(albero));
          return albero;
        });
      });

  /// Le voci delle attività e delle misure, una volta sola, tutte spuntate tranne quelle già
  /// nell'obiettivo e le disattivate.
  void _radici(Map<String, dynamic> albero) {
    final azioni = <String, _Radice>{}, misure = <String, _Radice>{};
    var senza = 0;
    for (final a in (albero['attivita'] as List).cast<Map<String, dynamic>>()) {
      final va = a['voce'] as Map<String, dynamic>?;
      va == null ? senza++ : azioni.putIfAbsent(va['id'] as String, () => (voce: va, elemento: a));
      for (final r in (a['rischi'] as List).cast<Map<String, dynamic>>()) {
        for (final m in (r['misure'] as List).cast<Map<String, dynamic>>()) {
          final vm = m['voce'] as Map<String, dynamic>?;
          vm == null ? senza++ : misure.putIfAbsent(vm['id'] as String, () => (voce: vm, elemento: m));
        }
      }
    }
    _azioni = azioni.values.toList();
    _misure = misure.values.toList();
    _senzaVoce = senza;
    _scelte
      ..clear()
      ..addAll([for (final r in [..._azioni, ..._misure]) if (_sceglibile(r)) r.voce['id'] as String]);
  }

  bool _sceglibile(_Radice r) => !widget.vociPresenti.contains(r.voce['id']) && r.voce['attiva'] != false;

  List<Map<String, dynamic>> _elementi(Map<String, dynamic> albero) {
    final scadenza = '${widget.anno}-12-31';
    return [
      for (final r in _azioni)
        if (_scelte.contains(r.voce['id']))
          {'tipo': 'AZIONE', 'voce_id': r.voce['id'], 'voce_codice': r.voce['codice'], 'descrizione': r.voce['descrizione'],
           'attivita_id': r.elemento['id'], 'processo_id': (albero['processo'] as Map)['id'],
           'impegno': 0, 'scadenza': scadenza, 'indicatori': <Map<String, dynamic>>[]},
      for (final r in _misure)
        if (_scelte.contains(r.voce['id']))
          {'tipo': 'MISURA', 'voce_id': r.voce['id'], 'voce_codice': r.voce['codice'], 'descrizione': r.voce['descrizione'],
           'impegno': 0, 'scadenza': scadenza, 'indicatori': [?indicatoreDaMisura(r.voce)]},
    ];
  }

  @override
  Widget build(BuildContext context) {
    final v = widget.voce;
    final piccolo = Theme.of(context).textTheme.bodySmall;
    Widget casella(_Radice r, String sotto) {
      final id = r.voce['id'] as String;
      final presente = widget.vociPresenti.contains(id);
      final disattivata = r.voce['attiva'] == false;
      return CheckboxListTile(
        dense: true,
        controlAffinity: ListTileControlAffinity.leading,
        value: presente || _scelte.contains(id),
        onChanged: !_sceglibile(r) ? null : (s) => setState(() => s! ? _scelte.add(id) : _scelte.remove(id)),
        title: Text('${r.voce['codice']} - ${r.voce['descrizione']}'),
        subtitle: Text(presente ? 'già nell\'obiettivo' : (disattivata ? 'voce disattivata nel catalogo' : sotto), style: piccolo),
      );
    }

    return AlertDialog(
      title: Text('Dalla mappatura: ${v['codice']} - ${v['descrizione']}'),
      content: SizedBox(
        width: 640,
        height: 480,
        child: Caricamento<Map<String, dynamic>>(
          future: _albero,
          riprova: _carica,
          builder: (context, albero) {
            if (_azioni.isEmpty && _misure.isEmpty) return const Center(child: Text('Nessuna voce del catalogo da portare.'));
            Widget titolo(String t) => Padding(
                padding: const EdgeInsets.only(top: 8, bottom: 4), child: Text(t, style: Theme.of(context).textTheme.titleSmall));
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text('Entrano le radici: le voci del catalogo delle attività (diventano azioni) e delle misure, ognuna una volta '
                  'sola; i rischi no. Impegno 0%: impegno, scadenza e indicatori si impostano poi su ciascuna. '
                  'Se il catalogo o la mappatura cambiano, l\'obiettivo resta com\'è.', style: piccolo),
              if (_senzaVoce > 0)
                Text('$_senzaVoce elementi senza voce del catalogo non si possono portare.', style: piccolo),
              Expanded(
                child: ListView(children: [
                  if (_azioni.isNotEmpty) titolo('Azioni (dalle attività)'),
                  for (final r in _azioni) casella(r, 'Azione'),
                  if (_misure.isNotEmpty) titolo('Misure'),
                  for (final r in _misure)
                    casella(r, ['Misura', if (r.voce['indicatore'] != null) 'indicatore: ${r.voce['indicatore']}'].join(' · ')),
                ]),
              ),
            ]);
          },
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FutureBuilder<Map<String, dynamic>>(
          future: _albero,
          builder: (context, snap) => FilledButton(
            onPressed: !snap.hasData || _scelte.isEmpty ? null : () => Navigator.pop(context, _elementi(snap.data!)),
            child: Text(_scelte.isEmpty ? 'Aggiungi' : 'Aggiungi ${_scelte.length}'),
          ),
        ),
      ],
    );
  }
}

/// Scelta di un processo o di una sola attività della mappatura dei rischi da cui copiare azioni
/// e misure (quelli della struttura per primi).
Future<Map<String, dynamic>?> scegliDallaMappatura(BuildContext context, String strutturaId) {
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (c) => _SceltaMappatura(strutturaId: strutturaId),
  );
}

class _SceltaMappatura extends StatefulWidget {
  const _SceltaMappatura({required this.strutturaId});

  final String strutturaId;

  @override
  State<_SceltaMappatura> createState() => _SceltaMappaturaState();
}

class _SceltaMappaturaState extends State<_SceltaMappatura> {
  final _testo = TextEditingController();
  late Future<List<Map<String, dynamic>>> _voci;

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
        _voci = apiDi(context).get('$apiPerformance/mappatura', query: {
          'struttura_id': widget.strutturaId,
          'testo': _testo.text.trim(),
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Scegli un processo o un\'attività della mappatura'),
        content: SizedBox(
          width: 640,
          height: 460,
          child: Column(children: [
            Text('Dal processo entrano le voci del catalogo delle sue attività (come azioni) e delle sue misure; dall\'attività '
                'solo la sua voce e quelle delle sue misure. Al passo successivo si sceglie cosa portare.',
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 8),
            TextField(
              controller: _testo,
              decoration: const InputDecoration(labelText: 'Cerca (codice o descrizione)', prefixIcon: Icon(Icons.search), isDense: true),
              onSubmitted: (_) => _cerca(),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: Caricamento<List<Map<String, dynamic>>>(
                future: _voci,
                riprova: _cerca,
                builder: (context, voci) => voci.isEmpty
                    ? const Center(child: Text('Nessun processo o attività trovati.'))
                    : ListView(children: [
                        for (final v in voci)
                          ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.only(left: v['tipo'] == 'ATTIVITA' ? 40 : 16, right: 16),
                            leading: Icon(v['tipo'] == 'ATTIVITA' ? Icons.subdirectory_arrow_right : Icons.account_tree_outlined, size: 20),
                            title: Text('${v['codice']} - ${v['descrizione']}'),
                            subtitle: Text([
                              if (v['tipo'] == 'ATTIVITA') 'Attività di ${v['processo']}'
                              else v['processo_tipo'] == 'PROCEDIMENTO' ? 'Procedimento' : 'Processo',
                              if (v['struttura_id'] == null) 'trasversale' else if (v['struttura_id'] == widget.strutturaId) 'della struttura',
                            ].join(' · ')),
                            onTap: () => Navigator.pop(context, v),
                          ),
                      ]),
              ),
            ),
          ]),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla'))],
      );
}

/// Scelta di una misura dal catalogo della mappatura dei rischi (voci attive; [giaPresenti]:
/// voci già nell'obiettivo).
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
        _misure = apiDi(context).get('$apiPerformance/catalogo', query: {
          'tipo': 'MISURA',
          'testo': _testo.text.trim(),
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Scegli una misura dal catalogo della mappatura'),
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
                            leading: const Icon(Icons.shield_outlined, size: 20),
                            title: Text('${m['codice']} - ${m['descrizione']}'),
                            subtitle: Text([
                              m['tipo_misura'] == 'GENERALE' ? 'Generale' : 'Specifica',
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
  var testoNota = '';
  final ok = await showDialog<bool>(
    context: context,
    builder: (_) => _ConControllori([nota], (c) => AlertDialog(
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
        FilledButton(
          onPressed: () {
            testoNota = nota.text.trim();
            Navigator.pop(c, true);
          },
          child: const Text('Conferma'),
        ),
      ],
    )),
  );
  return ok == true ? testoNota : null;
}

/// Storico delle modifiche: chi, quando, cosa, i campi con il valore prima e dopo, la nota.
class Storico extends StatelessWidget {
  const Storico(this.voci, {super.key});

  final List<Map<String, dynamic>> voci;

  static const _azioni = {'CREATO': 'creazione', 'MODIFICATO': 'modifica', 'ELIMINATO': 'eliminazione'};
  static const _oggetti = {
    'PIAO': 'PIAO', 'OBIETTIVO': 'Obiettivo', 'AZIONE': 'Azione', 'MISURA': 'Misura', 'INDICATORE': 'Indicatore',
  };
  static const _campi = {
    'codice': 'codice', 'titolo': 'titolo', 'descrizione': 'descrizione', 'tipo': 'tipo', 'impegno': 'impegno',
    'completamento': 'completamento', 'scadenza': 'scadenza', 'stato': 'stato', 'atto': 'atto', 'anno': 'anno',
    'struttura': 'struttura', 'unita': 'unità di misura', 'partenza': 'valore di partenza', 'target': 'target',
    'target_data': 'da raggiungere entro', 'verso': 'verso', 'fonte': 'fonte del dato', 'rilevato': 'valore rilevato',
  };

  static String _valore(String campo, Object? v) {
    if (v == null || v == '') return '—';
    if (campo == 'impegno' || campo == 'completamento') return '$v%';
    if (campo == 'scadenza' || campo == 'target_data') return formatData(v);
    if (campo == 'tipo') return tipiObiettivo[v] ?? tipiIndicatore[v] ?? '$v';
    if (campo == 'verso') return v == 'DECRESCENTE' ? 'più basso è meglio' : 'più alto è meglio';
    if (v is num) return numeroIt(v);
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
