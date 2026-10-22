import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';

/// Copia profonda di una definizione (JSON): l'editor la modifica senza toccare l'originale.
Map<String, dynamic> copia(Map<String, dynamic> d) =>
    Map<String, dynamic>.from(jsonDecode(jsonEncode(d)) as Map);

List<Map<String, dynamic>> listaDi(Object? v) =>
    v == null ? <Map<String, dynamic>>[] : (v as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();

/// Comportamento comune agli editor di modelli, specificità e checklist: la definizione si
/// modifica in memoria, si salva in bozza (invisibile agli atti), si controlla mentre si
/// scrive, si confronta con la versione pubblicata o con lo standard e si pubblica.
mixin EditorConfigurazione<T extends StatefulWidget> on State<T> {
  String get tipo; // modello, modulo, checklist
  String get codice;

  Map<String, dynamic>? dettaglio; // risposta di GET /configurazione/<tipo>/<codice>
  late Map<String, dynamic> definizione;
  Object? erroreCaricamento;
  bool modificata = false; // modifiche non ancora salvate in bozza
  bool salvataggio = false;
  List<String> errori = [];
  List<String> avvisi = [];
  Timer? _controllo;

  String get percorso => '/api/v1/configurazione/$tipo/$codice';
  Map<String, dynamic> get contesto => Map<String, dynamic>.from(dettaglio!['contesto'] as Map);
  Map<String, dynamic>? get standard => dettaglio?['standard'] == null
      ? null
      : Map<String, dynamic>.from((dettaglio!['standard'] as Map)['definizione'] as Map);
  bool get haBozza => dettaglio?['bozza'] != null;
  bool get admin => context.read<AuthState>().utente?.isAdmin ?? false;
  bool get puoPubblicare => admin;

  /// ABILITATO, IN_REDAZIONE (bozza presa in carico da qualcuno), DISATTIVATO.
  String get stato => dettaglio?['stato'] as String? ?? 'ABILITATO';
  Map<String, dynamic>? get redazione => dettaglio?['redazione'] as Map<String, dynamic>?;

  /// La bozza è in carico a questo utente: solo allora si modifica.
  bool get inModifica => haBozza && redazione?['mia'] == true;

  /// Chiamato dopo il caricamento (es. per ricavare le variabili delle condizioni).
  void dopoCaricamento() {}

  /// Chiamato a ogni modifica (es. per aggiornare l'anteprima).
  void dopoModifica() {}

  Future<void> carica() async {
    try {
      final d = await apiDi(context).get(percorso) as Map<String, dynamic>;
      final origine = d['bozza'] != null ? d['bozza']['definizione'] : d['pubblicata']['definizione'];
      setState(() {
        dettaglio = d;
        definizione = copia(Map<String, dynamic>.from(origine as Map));
        modificata = false;
        erroreCaricamento = null;
      });
      dopoCaricamento();
      controllaOra();
    } catch (e) {
      if (mounted) setState(() => erroreCaricamento = e);
    }
  }

  /// Da chiamare dopo ogni modifica della definizione.
  void modifica(VoidCallback cambiamento) {
    if (!inModifica) {
      mostraMessaggio(context, 'Sola lettura: premi "Inizia a modificare" per prendere in carico l\'oggetto');
      return;
    }
    setState(() {
      cambiamento();
      modificata = true;
    });
    _controllo?.cancel();
    _controllo = Timer(const Duration(milliseconds: 900), controllaOra);
    dopoModifica();
  }

  Future<void> controllaOra() async {
    try {
      final r = await apiDi(context).post('$percorso/controlla', {'definizione': definizione})
          as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        errori = List<String>.from(r['errori'] as List);
        avvisi = List<String>.from(r['avvisi'] as List);
      });
    } catch (_) {}
  }

  Future<bool> salvaBozza({bool silenzioso = false}) async {
    setState(() => salvataggio = true);
    try {
      final r = await apiDi(context).put('$percorso/bozza', {'definizione': definizione})
          as Map<String, dynamic>;
      if (!mounted) return false;
      setState(() {
        modificata = false;
        errori = List<String>.from(r['errori'] as List);
        avvisi = List<String>.from(r['avvisi'] as List);
        dettaglio = {...dettaglio!, 'bozza': {'definizione': definizione}};
      });
      if (!silenzioso) mostraMessaggio(context, 'Bozza salvata: gli atti usano ancora la versione pubblicata');
      return true;
    } catch (e) {
      if (mounted) mostraErrore(context, e);
      return false;
    } finally {
      if (mounted) setState(() => salvataggio = false);
    }
  }

  Future<void> scartaBozza() async {
    if (!await conferma(context, 'Scartare la bozza?',
        'Le modifiche non pubblicate vanno perse e si torna alla versione pubblicata.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('$percorso/bozza');
      if (!mounted) return;
      if (dettaglio?['pubblicata'] == null) {
        Navigator.pop(context, true);
      } else {
        await carica();
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> pubblica() async {
    if (modificata && !await salvaBozza(silenzioso: true)) return;
    if (!mounted) return;
    if (errori.isNotEmpty) {
      mostraErrore(context, 'La bozza contiene errori: correggili prima di pubblicare');
      return;
    }
    if (!await conferma(context, 'Pubblicare la nuova versione?',
        'Da ora i nuovi atti useranno la nuova versione; bozze di atto e verifiche già fatte restano '
            'sulla versione con cui sono nate.${tipo == 'modulo' ? ' I modelli che usano questa specificità ricevono una nuova versione.' : ''}')) {
      return;
    }
    if (!mounted) return;
    try {
      final r = await apiDi(context).post('$percorso/pubblica') as Map<String, dynamic>;
      if (!mounted) return;
      mostraMessaggio(context, 'Pubblicata la versione ${r['versione']}');
      await carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  /// Presa in carico: nasce la bozza e l'oggetto è in redazione; gli altri non possono
  /// modificarlo, gli atti continuano a usare la versione pubblicata.
  Future<void> prendiInCarico() async {
    try {
      await apiDi(context).post('$percorso/prendi');
      if (mounted) await carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> sblocca() async {
    if (!await conferma(context, 'Prendere in carico la bozza?',
        'La bozza di ${redazione?['autore'] ?? 'un altro utente'} resta com\'è e passa a te: '
            'chi la stava modificando non potrà più salvarla.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).post('$percorso/sblocca');
      if (mounted) await carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> cambiaAttivazione(bool attiva) async {
    if (!attiva &&
        !await conferma(context, 'Disattivare?', switch (tipo) {
          'modello' => 'Il modello non si potrà più scegliere per gli atti nuovi. Le bozze di atto già '
              'iniziate e le verifiche restano sulla loro versione.',
          'modulo' => 'La specificità sparisce dalle caratteristiche dei modelli, che ricevono una '
              'nuova versione senza i suoi testi.',
          _ => 'La verifica degli atti non applicherà più questa checklist.',
        })) {
      return;
    }
    if (!mounted) return;
    try {
      final r = await apiDi(context).post('$percorso/${attiva ? 'riattiva' : 'disattiva'}') as Map<String, dynamic>;
      if (!mounted) return;
      final avvisi = List<String>.from(r['avvisi'] as List? ?? const []);
      mostraMessaggio(context, attiva ? 'Riattivato' : 'Disattivato');
      if (avvisi.isNotEmpty) {
        await showDialog<void>(
          context: context,
          builder: (c) => AlertDialog(
            title: const Text('Da controllare'),
            content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final a in avvisi) Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('• $a')),
            ]),
            actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
          ),
        );
      }
      if (mounted) await carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> confronta(String con) async {
    try {
      final r = await apiDi(context).post('$percorso/confronta', {'definizione': definizione, 'con': con})
          as Map<String, dynamic>;
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => DifferenzeDialog(
          titolo: con == 'standard' ? 'Differenze rispetto allo standard' : 'Differenze rispetto alla versione pubblicata',
          differenze: listaDi(r['differenze']),
        ),
      );
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> sorgente() async {
    try {
      final r = await apiDi(context).post('/api/v1/configurazione/$tipo/sorgente', {'definizione': definizione})
          as Map<String, dynamic>;
      if (!mounted) return;
      final nuova = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (_) => SorgenteDialog(tipo: tipo, sorgente: r['sorgente'] as String),
      );
      if (nuova != null) {
        nuova['codice'] = codice;
        modifica(() => definizione = nuova);
        dopoCaricamento();
      }
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> storico() async {
    try {
      final r = await apiDi(context).get('$percorso/storico') as List;
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Versioni pubblicate'),
          content: SizedBox(
            width: 480,
            child: ListView(shrinkWrap: true, children: [
              for (final v in r.cast<Map<String, dynamic>>())
                ListTile(
                  leading: Text('v${v['versione']}', style: Theme.of(c).textTheme.titleMedium),
                  title: Text(formatData(v['created_at'])),
                  subtitle: Text([v['autore'], if (v['pacchetto'] != null) v['pacchetto']].whereType<String>().join(' · ')),
                ),
            ]),
          ),
          actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
        ),
      );
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  /// Pulsanti della barra in alto.
  List<Widget> azioniEditor() => [
        if (salvataggio)
          const Padding(
            padding: EdgeInsets.all(14),
            child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
          ),
        if (inModifica)
          TextButton.icon(
            onPressed: salvataggio || !modificata ? null : salvaBozza,
            icon: const Icon(Icons.save_outlined),
            label: Text(modificata ? 'Salva bozza' : 'Bozza salvata'),
          )
        else if (stato == 'ABILITATO')
          FilledButton.tonalIcon(
            onPressed: prendiInCarico,
            icon: const Icon(Icons.edit),
            label: const Text('Inizia a modificare'),
          ),
        PopupMenuButton<String>(
          tooltip: 'Altre azioni',
          onSelected: (a) => switch (a) {
            'pubblicata' => confronta('pubblicata'),
            'standard' => confronta('standard'),
            'sorgente' => sorgente(),
            'storico' => storico(),
            'scarta' => scartaBozza(),
            'sblocca' => sblocca(),
            'disattiva' => cambiaAttivazione(false),
            'riattiva' => cambiaAttivazione(true),
            _ => null,
          },
          itemBuilder: (_) => [
            if (dettaglio?['pubblicata'] != null)
              const PopupMenuItem(value: 'pubblicata', child: Text('Confronta con la versione pubblicata')),
            if (dettaglio?['standard'] != null)
              const PopupMenuItem(value: 'standard', child: Text('Confronta con lo standard')),
            const PopupMenuItem(value: 'sorgente', child: Text('Sorgente (modalità avanzata)')),
            if (dettaglio?['pubblicata'] != null) const PopupMenuItem(value: 'storico', child: Text('Versioni')),
            if (haBozza && (inModifica || admin)) const PopupMenuItem(value: 'scarta', child: Text('Scarta la bozza')),
            if (haBozza && !inModifica && admin)
              const PopupMenuItem(value: 'sblocca', child: Text('Sblocca e prendi in carico')),
            if (admin && stato == 'ABILITATO') const PopupMenuItem(value: 'disattiva', child: Text('Disattiva')),
            if (admin && stato == 'DISATTIVATO') const PopupMenuItem(value: 'riattiva', child: Text('Riattiva')),
          ],
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Tooltip(
            message: puoPubblicare ? '' : 'La pubblicazione spetta a un amministratore',
            child: FilledButton.icon(
              onPressed: puoPubblicare && (haBozza || modificata) ? pubblica : null,
              icon: const Icon(Icons.publish),
              label: const Text('Pubblica'),
            ),
          ),
        ),
      ];

  /// Stato della versione: pubblicata, bozza, provenienza dallo standard.
  Widget statoVersione() {
    final pub = dettaglio?['pubblicata'] as Map?;
    final testo = [
      if (stato == 'DISATTIVATO')
        'Disattivato (ultima versione: v${pub?['versione']})'
      else if (pub != null)
        'Pubblicata: v${pub['versione']}'
      else
        'Nuovo, mai pubblicato',
      if (pub?['pacchetto'] != null)
        pub!['modificato'] == true ? 'standard modificato dall\'ente' : 'standard (${pub['pacchetto']})',
      if (haBozza)
        inModifica
            ? 'in redazione da te${modificata ? ', modifiche non salvate' : ''}'
            : 'in redazione da ${redazione?['autore'] ?? 'un altro utente'}',
    ].join(' · ');
    return Text(testo, style: Theme.of(context).textTheme.bodySmall);
  }

  /// Striscia sopra l'editor quando non si può modificare: perché e cosa fare.
  Widget avvisoStato() {
    if (inModifica) return const SizedBox.shrink();
    final tema = Theme.of(context);
    final (IconData icona, String testo, Widget? azione) = switch (stato) {
      'DISATTIVATO' => (
          Icons.block,
          'Disattivato: non è usato dagli atti nuovi.${admin ? '' : ' Può riattivarlo un amministratore.'}',
          admin ? TextButton(onPressed: () => cambiaAttivazione(true), child: const Text('Riattiva')) : null,
        ),
      'IN_REDAZIONE' => (
          Icons.lock_outline,
          'In redazione da ${redazione?['autore'] ?? 'un altro utente'} dal ${formatData(redazione?['dal'])}: '
              'vedi la sua bozza in sola lettura. Gli atti usano la versione pubblicata.',
          admin ? TextButton(onPressed: sblocca, child: const Text('Sblocca e prendi in carico')) : null,
        ),
      _ => (
          Icons.visibility_outlined,
          'Sola lettura: è la versione usata dagli atti. Per modificarla prendila in carico: '
              'gli altri non potranno modificarla finché la tua bozza non è pubblicata o scartata.',
          TextButton(onPressed: prendiInCarico, child: const Text('Inizia a modificare')),
        ),
    };
    return Material(
      color: tema.colorScheme.secondaryContainer.withValues(alpha: 0.6),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        child: Row(children: [
          Icon(icona, size: 20),
          const SizedBox(width: 12),
          Expanded(child: Text(testo)),
          ?azione,
        ]),
      ),
    );
  }

  /// Errori e avvisi del controllo.
  Widget pannelloControllo() {
    final tema = Theme.of(context);
    if (errori.isEmpty && avvisi.isEmpty) {
      return ListTile(
        dense: true,
        leading: Icon(Icons.check_circle_outline, color: Colors.green.shade600),
        title: const Text('Nessun problema'),
      );
    }
    return ExpansionTile(
      dense: true,
      initiallyExpanded: errori.isNotEmpty,
      leading: Icon(errori.isNotEmpty ? Icons.error_outline : Icons.warning_amber,
          color: errori.isNotEmpty ? tema.colorScheme.error : Colors.orange.shade700),
      title: Text('${errori.length} errori, ${avvisi.length} avvisi'),
      children: [
        for (final e in errori)
          ListTile(dense: true, leading: Icon(Icons.error_outline, size: 18, color: tema.colorScheme.error), title: Text(e)),
        for (final a in avvisi)
          ListTile(dense: true, leading: Icon(Icons.warning_amber, size: 18, color: Colors.orange.shade700), title: Text(a)),
      ],
    );
  }

  /// Uscita con modifiche non salvate: si chiede se salvarle.
  Future<bool> puoUscire() async {
    if (!modificata) return true;
    final scelta = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Modifiche non salvate'),
        content: const Text('Salvare le modifiche nella bozza prima di uscire?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, 'esci'), child: const Text('Esci senza salvare')),
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, 'salva'), child: const Text('Salva bozza')),
        ],
      ),
    );
    if (scelta == 'salva') return salvaBozza(silenzioso: true);
    return scelta == 'esci';
  }

  @override
  void dispose() {
    _controllo?.cancel();
    super.dispose();
  }
}

/// Differenze elemento per elemento (capoversi, domande, dati, controlli).
class DifferenzeDialog extends StatelessWidget {
  const DifferenzeDialog({super.key, required this.titolo, required this.differenze});

  final String titolo;
  final List<Map<String, dynamic>> differenze;

  String _testo(Object? v) {
    if (v == null) return '';
    if (v is Map && v['testo'] != null) return v['testo'].toString();
    if (v is Map && v['regola'] != null) return '${v['titolo']}\n${v['regola']}';
    if (v is String) return v;
    return const JsonEncoder.withIndent('  ').convert(v);
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return AlertDialog(
      title: Text(titolo),
      content: SizedBox(
        width: 900,
        height: 560,
        child: differenze.isEmpty
            ? const Center(child: Text('Nessuna differenza.'))
            : ListView(children: [
                for (final d in differenze)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        Row(children: [
                          Chip(
                            label: Text(d['stato'] as String),
                            backgroundColor: switch (d['stato']) {
                              'aggiunto' => Colors.green.shade100,
                              'tolto' => tema.colorScheme.errorContainer,
                              _ => tema.colorScheme.secondaryContainer,
                            },
                          ),
                          const SizedBox(width: 8),
                          Expanded(child: Text('${d['elemento']} · ${d['dove']}', style: tema.textTheme.titleSmall)),
                        ]),
                        const SizedBox(height: 8),
                        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          if (d['prima'] != null)
                            Expanded(
                              child: Container(
                                padding: const EdgeInsets.all(8),
                                color: tema.colorScheme.errorContainer.withValues(alpha: 0.3),
                                child: SelectableText(_testo(d['prima'])),
                              ),
                            ),
                          if (d['prima'] != null && d['dopo'] != null) const SizedBox(width: 8),
                          if (d['dopo'] != null)
                            Expanded(
                              child: Container(
                                padding: const EdgeInsets.all(8),
                                color: Colors.green.withValues(alpha: 0.12),
                                child: SelectableText(_testo(d['dopo'])),
                              ),
                            ),
                        ]),
                      ]),
                    ),
                  ),
              ]),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Chiudi'))],
    );
  }
}

/// Modalità avanzata: il sorgente YAML (o JSON per le checklist), modificabile e controllato.
class SorgenteDialog extends StatefulWidget {
  const SorgenteDialog({super.key, required this.tipo, required this.sorgente});

  final String tipo;
  final String sorgente;

  @override
  State<SorgenteDialog> createState() => _SorgenteDialogState();
}

class _SorgenteDialogState extends State<SorgenteDialog> {
  late final _testo = TextEditingController(text: widget.sorgente);
  String? _errore;

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  Future<void> _applica() async {
    try {
      final r = await apiDi(context).post('/api/v1/configurazione/sorgente', {
        'tipo': widget.tipo,
        'sorgente': _testo.text,
      }) as Map<String, dynamic>;
      if (mounted) Navigator.pop(context, Map<String, dynamic>.from(r['definizione'] as Map));
    } catch (e) {
      setState(() => _errore = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.tipo == 'checklist' ? 'Sorgente JSON' : 'Sorgente YAML'),
      content: SizedBox(
        width: 900,
        height: 600,
        child: Column(children: [
          Expanded(
            child: TextField(
              controller: _testo,
              expands: true,
              maxLines: null,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
              decoration: const InputDecoration(border: OutlineInputBorder()),
            ),
          ),
          if (_errore != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_errore!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FilledButton(onPressed: _applica, child: const Text('Applica all\'editor')),
      ],
    );
  }
}

/// URN di un articolo in forma breve, es. "art. 50 D.Lgs. 36/2023".
String normaBreve(String urn) {
  final m = RegExp(r'urn:nir:stato:([^:]+):(\d{4})-\d\d-\d\d;([^~]+)~art(.+)$').firstMatch(urn);
  if (m == null) return urn;
  final tipo = switch (m.group(1)) {
    'decreto.legislativo' => 'D.Lgs.',
    'legge' => 'L.',
    'decreto.legge' => 'D.L.',
    'decreto.del.presidente.della.repubblica' => 'D.P.R.',
    _ => m.group(1)!,
  };
  return 'art. ${m.group(4)} $tipo ${m.group(3)}/${m.group(2)}';
}


/// Elenco di URN di norme, con aggiunta dalla libreria normativa o a mano.
class NormeEditor extends StatelessWidget {
  const NormeEditor({super.key, required this.norme, required this.onChanged, required this.aggiungiDaLibreria});

  final List<String> norme;
  final ValueChanged<List<String>> onChanged;
  final Future<List<String>> Function() aggiungiDaLibreria;

  @override
  Widget build(BuildContext context) {
    return InputDecorator(
      decoration: const InputDecoration(labelText: 'Norme citate', border: OutlineInputBorder()),
      child: Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
        for (final n in norme)
          Tooltip(
            message: n,
            child: InputChip(
              label: Text(normaBreve(n)),
              onDeleted: () => onChanged([...norme]..remove(n)),
            ),
          ),
        TextButton.icon(
          onPressed: () async {
            final nuove = await aggiungiDaLibreria();
            if (nuove.isNotEmpty) onChanged([...norme, ...nuove.where((n) => !norme.contains(n))]);
          },
          icon: const Icon(Icons.add, size: 18),
          label: const Text('Aggiungi'),
        ),
      ]),
    );
  }
}

// --- ricerca nella struttura -------------------------------------------------------------------

const _accentate = 'àáâäèéêëìíîïòóôöùúûüÀÁÂÄÈÉÊËÌÍÎÏÒÓÔÖÙÚÛÜ';
const _semplici = 'aaaaeeeeiiiioooouuuuaaaaeeeeiiiioooouuuu';

/// Testo per la ricerca: minuscolo e senza accenti, con la stessa lunghezza dell'originale
/// (le posizioni trovate valgono anche per il testo originale).
String normalizzaRicerca(String testo) {
  final b = StringBuffer();
  for (final c in testo.toLowerCase().split('')) {
    final i = _accentate.indexOf(c);
    b.write(i < 0 ? c : _semplici[i]);
  }
  return b.toString();
}

/// Il testo con le occorrenze della ricerca evidenziate.
Widget testoEvidenziato(BuildContext context, String testo, String ricerca, {TextStyle? stile, int righe = 1}) {
  final q = normalizzaRicerca(ricerca.trim());
  if (q.isEmpty) return Text(testo, style: stile, maxLines: righe, overflow: TextOverflow.ellipsis);
  final n = normalizzaRicerca(testo);
  final colori = Theme.of(context).colorScheme;
  final parti = <TextSpan>[];
  var da = 0;
  for (var i = n.indexOf(q); i >= 0; i = n.indexOf(q, i + q.length)) {
    if (i > da) parti.add(TextSpan(text: testo.substring(da, i)));
    parti.add(TextSpan(
      text: testo.substring(i, i + q.length),
      style: TextStyle(backgroundColor: colori.tertiaryContainer, color: colori.onTertiaryContainer, fontWeight: FontWeight.w600),
    ));
    da = i + q.length;
  }
  if (da < testo.length) parti.add(TextSpan(text: testo.substring(da)));
  return Text.rich(TextSpan(style: stile, children: parti), maxLines: righe, overflow: TextOverflow.ellipsis);
}

/// Il testo cercato compare in uno dei testi dell'elemento?
bool corrisponde(String ricerca, Iterable<Object?> testi) {
  final q = normalizzaRicerca(ricerca.trim());
  return q.isEmpty || testi.any((t) => t != null && normalizzaRicerca(t.toString()).contains(q));
}

/// Casella di ricerca sopra la struttura: numero di risultati, ✕ ed Esc per azzerare,
/// filtri rapidi facoltativi per tipo di elemento.
class CampoRicerca extends StatefulWidget {
  const CampoRicerca({
    super.key,
    required this.onChanged,
    this.valore = '',
    this.risultati,
    this.suggerimento = 'Cerca',
    this.filtri = const {},
    this.filtro,
    this.onFiltro,
  });

  final ValueChanged<String> onChanged;
  final String valore; // testo iniziale (la casella può essere ricreata, es. cambiando scheda)
  final int? risultati; // null: nessuna ricerca in corso
  final String suggerimento;
  final Map<String, String> filtri; // codice → etichetta; vuota: nessun filtro rapido
  final String? filtro;
  final ValueChanged<String>? onFiltro;

  @override
  State<CampoRicerca> createState() => _CampoRicercaState();
}

class _CampoRicercaState extends State<CampoRicerca> {
  late final _testo = TextEditingController(text: widget.valore);

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  void _azzera() {
    _testo.clear();
    widget.onChanged('');
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        CallbackShortcuts(
          bindings: {const SingleActivator(LogicalKeyboardKey.escape): _azzera},
          child: TextField(
            controller: _testo,
            decoration: InputDecoration(
              isDense: true,
              prefixIcon: const Icon(Icons.search, size: 20),
              hintText: widget.suggerimento,
              border: const OutlineInputBorder(),
              suffixIcon: _testo.text.isEmpty
                  ? null
                  : IconButton(tooltip: 'Azzera (Esc)', icon: const Icon(Icons.close, size: 18), onPressed: _azzera),
            ),
            onChanged: (v) {
              setState(() {});
              widget.onChanged(v);
            },
          ),
        ),
        if (widget.filtri.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Wrap(spacing: 4, runSpacing: 4, children: [
              for (final f in widget.filtri.entries)
                ChoiceChip(
                  visualDensity: VisualDensity.compact,
                  label: Text(f.value),
                  selected: widget.filtro == f.key,
                  onSelected: (_) => widget.onFiltro?.call(f.key),
                ),
            ]),
          ),
        if (widget.risultati != null)
          Padding(
            padding: const EdgeInsets.only(top: 4, left: 4),
            child: Text(
              widget.risultati == 0
                  ? 'Nessun risultato'
                  : widget.risultati == 1
                      ? '1 risultato'
                      : '${widget.risultati} risultati',
              style: tema.textTheme.bodySmall,
            ),
          ),
      ]),
    );
  }
}
