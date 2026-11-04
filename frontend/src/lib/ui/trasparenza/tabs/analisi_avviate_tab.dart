import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../comuni.dart';
import '../coda_analisi.dart';
import '../result_manager.dart';

/// Analisi avviate dall'utente negli ultimi 30 giorni: stato, report da aprire nei
/// risultati, errori; quelle concluse (o ancora in coda) si possono togliere.
class AnalisiAvviateTab extends StatelessWidget {
  const AnalisiAvviateTab({super.key});

  @override
  Widget build(BuildContext context) {
    final coda = context.watch<CodaAnalisi>();
    final Widget contenuto;
    if (!coda.caricata) {
      contenuto = const Center(child: CircularProgressIndicator());
    } else if (coda.lavori.isEmpty) {
      contenuto = Center(
        child: Text(
          coda.errore != null ? 'Elenco non disponibile: ${coda.errore}' : 'Nessuna analisi negli ultimi 30 giorni.',
        ),
      );
    } else {
      contenuto = ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        children: [for (final l in coda.lavori) _VoceAnalisi(l, key: ValueKey(l['id']))],
      );
    }
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 900),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 8, 8),
            child: Row(children: [
              const Expanded(
                child: Text(
                  'Le analisi vengono eseguite una alla volta, nell\'ordine in cui le avvii: intanto '
                  'puoi avviarne altre. Restano qui per 30 giorni: salva i report che vuoi conservare.',
                ),
              ),
              IconButton(tooltip: 'Aggiorna', icon: const Icon(Icons.refresh), onPressed: coda.aggiorna),
            ]),
          ),
          Expanded(child: contenuto),
        ]),
      ),
    );
  }
}

class _VoceAnalisi extends StatefulWidget {
  const _VoceAnalisi(this.lavoro, {super.key});

  final Map<String, dynamic> lavoro;

  @override
  State<_VoceAnalisi> createState() => _VoceAnalisiState();
}

class _VoceAnalisiState extends State<_VoceAnalisi> {
  bool _occupata = false;

  static final _formato = DateFormat('dd/MM/yyyy HH:mm');

  Map<String, dynamic> get _l => widget.lavoro;

  static DateTime? _data(Object? v) => v == null ? null : DateTime.tryParse(v.toString());

  String _tempi() {
    final avvio = _data(_l['created_at']);
    final inizio = _data(_l['avviato_il']);
    final fine = _data(_l['completato_il']);
    final parti = [if (avvio != null) 'Avviata il ${_formato.format(avvio)}'];
    if (inizio != null && fine != null && !fine.isBefore(inizio)) {
      final durata = fine.difference(inizio);
      parti.add(durata.inMinutes > 0
          ? 'durata ${durata.inMinutes} min ${durata.inSeconds % 60} s'
          : 'durata ${durata.inSeconds} s');
    }
    return parti.join(' · ');
  }

  Future<void> _esegui(Future<void> Function() azione) async {
    setState(() => _occupata = true);
    try {
      await azione();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _occupata = false);
    }
  }

  Future<void> _apri() => _esegui(() async {
        final html = await context.read<CodaAnalisi>().report(_l['id'] as String);
        ResultManager.showResultInNewTab(html, nomeProposto: 'Analisi ${_l['titolo']}');
      });

  Future<void> _riprova() {
    final coda = context.read<CodaAnalisi>();
    return _esegui(() => coda.riprova(_l['id'] as String));
  }

  Future<void> _togli() async {
    final inCoda = _l['stato'] == 'IN_CODA';
    if (inCoda &&
        !await conferma(context, 'Annullare l\'analisi?', 'L\'analisi non è ancora partita: verrà annullata.')) {
      return;
    }
    if (!mounted) return;
    final coda = context.read<CodaAnalisi>();
    await _esegui(() => coda.togli(_l['id'] as String));
  }

  @override
  Widget build(BuildContext context) {
    final colori = Theme.of(context).colorScheme;
    final stato = _l['stato'] as String?;
    final (Widget icona, String descrizione) = switch (stato) {
      'IN_CODA' => (Icon(Icons.schedule, color: colori.outline), 'In coda'),
      'IN_CORSO' => (
          const SizedBox.square(dimension: 22, child: CircularProgressIndicator(strokeWidth: 2.5)),
          'In corso'
        ),
      'COMPLETATA' => (Icon(Icons.check_circle, color: Colors.green.shade700), 'Completata'),
      _ => (Icon(Icons.error, color: colori.error), 'Non riuscita'),
    };
    final errore = _l['errore'] as String?;
    final fonte = (_l['fonte'] as String?) ?? '';
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        onTap: stato == 'COMPLETATA' && !_occupata ? _apri : null,
        leading: SizedBox(width: 32, child: Center(child: icona)),
        title: Text((_l['titolo'] as String?) ?? 'Analisi'),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (fonte.isNotEmpty) Text(fonte, maxLines: 2, overflow: TextOverflow.ellipsis),
          Text('$descrizione · ${_tempi()}', style: TextStyle(color: colori.onSurfaceVariant)),
          if (stato == 'ERRORE' && errore != null && errore.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: SelectableText(errore, style: TextStyle(color: colori.error)),
            ),
        ]),
        isThreeLine: true,
        trailing: Wrap(spacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          if (stato == 'COMPLETATA')
            FilledButton.tonalIcon(
              onPressed: _occupata ? null : _apri,
              icon: const Icon(Icons.open_in_new),
              label: const Text('Apri'),
            ),
          if (stato == 'ERRORE')
            FilledButton.tonalIcon(
              onPressed: _occupata ? null : _riprova,
              icon: const Icon(Icons.replay),
              label: const Text('Riprova'),
            ),
          if (stato != 'IN_CORSO')
            IconButton(
              tooltip: stato == 'IN_CODA' ? 'Annulla' : 'Togli dall\'elenco',
              icon: stato == 'IN_CODA' ? const Icon(Icons.cancel_outlined) : IconaElimina(attiva: !_occupata),
              onPressed: _occupata ? null : _togli,
            ),
        ]),
      ),
    );
  }
}
