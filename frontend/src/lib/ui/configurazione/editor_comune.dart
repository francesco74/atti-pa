import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
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
  bool get puoPubblicare => context.read<AuthState>().utente?.isAdmin ?? false;

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
        TextButton.icon(
          onPressed: salvataggio || !modificata ? null : salvaBozza,
          icon: const Icon(Icons.save_outlined),
          label: Text(modificata ? 'Salva bozza' : 'Bozza salvata'),
        ),
        PopupMenuButton<String>(
          tooltip: 'Altre azioni',
          onSelected: (a) => switch (a) {
            'pubblicata' => confronta('pubblicata'),
            'standard' => confronta('standard'),
            'sorgente' => sorgente(),
            'storico' => storico(),
            'scarta' => scartaBozza(),
            _ => null,
          },
          itemBuilder: (_) => [
            if (dettaglio?['pubblicata'] != null)
              const PopupMenuItem(value: 'pubblicata', child: Text('Confronta con la versione pubblicata')),
            if (dettaglio?['standard'] != null)
              const PopupMenuItem(value: 'standard', child: Text('Confronta con lo standard')),
            const PopupMenuItem(value: 'sorgente', child: Text('Sorgente (modalità avanzata)')),
            if (dettaglio?['pubblicata'] != null) const PopupMenuItem(value: 'storico', child: Text('Versioni')),
            if (haBozza) const PopupMenuItem(value: 'scarta', child: Text('Scarta la bozza')),
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
      if (pub != null) 'Pubblicata: v${pub['versione']}' else 'Nuovo, mai pubblicato',
      if (pub?['pacchetto'] != null)
        pub!['modificato'] == true ? 'standard modificato dall\'ente' : 'standard (${pub['pacchetto']})',
      if (haBozza || modificata) 'bozza in corso${modificata ? ', modifiche non salvate' : ''}',
    ].join(' · ');
    return Text(testo, style: Theme.of(context).textTheme.bodySmall);
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

/// Elenco di URN di norme, con aggiunta dalla libreria normativa o a mano.
class NormeEditor extends StatelessWidget {
  const NormeEditor({super.key, required this.norme, required this.onChanged, required this.aggiungiDaLibreria});

  final List<String> norme;
  final ValueChanged<List<String>> onChanged;
  final Future<List<String>> Function() aggiungiDaLibreria;

  String _breve(String urn) {
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

  @override
  Widget build(BuildContext context) {
    return InputDecorator(
      decoration: const InputDecoration(labelText: 'Norme citate', border: OutlineInputBorder()),
      child: Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
        for (final n in norme)
          Tooltip(
            message: n,
            child: InputChip(
              label: Text(_breve(n)),
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
