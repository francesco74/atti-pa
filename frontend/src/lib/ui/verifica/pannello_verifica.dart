import 'package:flutter/material.dart';

import '../comuni.dart';

/// Esiti deterministici: riferimenti normativi, segnaposto, dati personali.
class PannelloRiferimenti extends StatelessWidget {
  const PannelloRiferimenti({super.key, required this.esito});

  /// Formato di `esito_riferimenti` o della risposta di controllo-rapido.
  final Map<String, dynamic> esito;

  @override
  Widget build(BuildContext context) {
    final riferimenti = List<Map<String, dynamic>>.from(esito['riferimenti'] as List? ?? []);
    final segnaposto = List<String>.from(esito['segnaposto'] as List? ?? []);
    final dati = List<Map<String, dynamic>>.from(esito['dati_personali'] as List? ?? []);
    // assente nelle verifiche precedenti al rilevamento con il modello
    final statoDati = esito['dati_personali_stato'] as String? ?? 'VALUTATI';
    final mancanti = List<String>.from(esito['campi_obbligatori_mancanti'] as List? ?? []);

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (mancanti.isNotEmpty)
        Sezione(
          titolo: 'Campi obbligatori da compilare (${mancanti.length})',
          child: Wrap(spacing: 6, runSpacing: 6, children: [
            for (final c in mancanti) Chip(label: Text(c), avatar: const Icon(Icons.edit, size: 16)),
          ]),
        ),
      Sezione(
        titolo: 'Riferimenti normativi (${riferimenti.length})',
        child: riferimenti.isEmpty
            ? const Text('Nessun riferimento normativo riconosciuto nel testo.')
            : Column(children: [
                for (final r in riferimenti)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text((r['citazione'] ?? r['testo']).toString()),
                    subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      if (r['fonte'] == 'MANUALE')
                        Text(r['riconosciuto_da'] == 'LLM'
                            ? 'Norma inserita manualmente · citazione riconosciuta dal modello'
                            : 'Norma inserita manualmente'),
                      if (r['nel_complesso'] == true)
                        Text('Citata nel suo complesso'
                            '${r['titolo_atto'] != null ? ': ${r['titolo_atto']}' : ''}'),
                      if (r['vigenza_inizio'] != null)
                        Text('Vigente dal ${formatData(r['vigenza_inizio'])}'
                            '${r['vigenza_fine'] != null ? ' al ${formatData(r['vigenza_fine'])}' : ''}'),
                      for (final a in List<String>.from(r['avvisi'] as List? ?? []))
                        Text('Attenzione: $a', style: const TextStyle(color: Colors.orange)),
                      if (r['coerenza'] is Map)
                        _Coerenza(Map<String, dynamic>.from(r['coerenza'] as Map)),
                    ]),
                    trailing: EsitoChip(r['esito'] as String?),
                  ),
              ]),
      ),
      Sezione(
        titolo: 'Segnaposto non compilati (${segnaposto.length})',
        child: segnaposto.isEmpty
            ? const Text('Nessuno.')
            : Wrap(spacing: 6, runSpacing: 6, children: [
                for (final s in segnaposto) Chip(label: Text(s)),
              ]),
      ),
      Sezione(
        titolo: 'Dati personali da valutare per la pubblicazione'
            '${statoDati == 'VALUTATI' ? ' (${dati.length})' : ''}',
        child: statoDati == 'NON_VALUTATI'
            ? const Text('I dati personali sono rilevati dal modello linguistico nella verifica '
                'completa dell\'atto.')
            : statoDati == 'ERRORE'
            ? Text(
                '${esito['dati_personali_errore'] ?? 'Rilevamento non riuscito'}. '
                'Ripetere la verifica.',
                style: const TextStyle(color: Colors.orange),
              )
            : dati.isEmpty
            ? const Text('Nessun dato personale rilevato dal modello.')
            : Column(children: [
                for (final d in dati)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.privacy_tip,
                        color: d['priorita'] == 'ALTA' ? Colors.red : Colors.orange),
                    title: Text(d['testo'].toString()),
                    subtitle: Text([
                      d['categoria'].toString().replaceAll('_', ' ').toLowerCase(),
                      if (d['motivo'] != null) d['motivo'],
                    ].join(' · ')),
                  ),
              ]),
      ),
    ]);
  }
}

/// Coerenza tra la norma citata e l'uso che ne fa l'atto, proposta dall'LLM.
class _Coerenza extends StatelessWidget {
  const _Coerenza(this.coerenza);

  final Map<String, dynamic> coerenza;

  @override
  Widget build(BuildContext context) {
    final stile = Theme.of(context).textTheme.bodySmall;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Tooltip(
            message: 'Valutazione proposta dal modello linguistico: va confermata da una persona',
            child: Icon(Icons.smart_toy_outlined, size: 16),
          ),
          const SizedBox(width: 4),
          const Text("Coerenza con l'atto: "),
          EsitoChip(coerenza['esito'] as String?),
        ]),
        if (coerenza['motivazione'] != null) Text(coerenza['motivazione'].toString(), style: stile),
        if (coerenza['evidenza'] != null)
          Text('«${coerenza['evidenza']}»', style: stile?.copyWith(fontStyle: FontStyle.italic)),
        if (coerenza['suggerimento'] != null)
          Text('Suggerimento: ${coerenza['suggerimento']}', style: stile),
      ]),
    );
  }
}

/// Esiti della checklist proposti dall'LLM (sola lettura).
class PannelloChecklist extends StatelessWidget {
  const PannelloChecklist({super.key, required this.esiti, this.modello});

  final List<Map<String, dynamic>> esiti;
  final String? modello;

  @override
  Widget build(BuildContext context) {
    return Sezione(
      titolo: 'Checklist di qualità',
      azioni: [
        if (modello != null)
          Tooltip(
            message: 'Valutazione proposta dal modello $modello: va confermata da una persona',
            child: const Icon(Icons.smart_toy_outlined, size: 20),
          ),
      ],
      child: esiti.isEmpty
          ? const Text('Nessuna checklist applicata a questo atto.')
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: perScheda(context, esiti, (e) => SchedaEsito(esito: e)),
            ),
    );
  }
}

/// Esiti raggruppati per scheda di provenienza (generica della tipologia, del modello, delle
/// specificità), con il titolo della scheda prima dei suoi elementi.
List<Widget> perScheda(
  BuildContext context,
  List<Map<String, dynamic>> esiti,
  Widget Function(Map<String, dynamic>) elemento,
) {
  final widget = <Widget>[];
  Object? scheda;
  for (final e in esiti) {
    if (e['scheda_titolo'] != null && e['scheda'] != scheda) {
      scheda = e['scheda'];
      widget.add(Padding(
        padding: EdgeInsets.only(top: widget.isEmpty ? 0 : 12, bottom: 8),
        child: Text(e['scheda_titolo'].toString(), style: Theme.of(context).textTheme.titleSmall),
      ));
    }
    widget.add(elemento(e));
  }
  return widget;
}

class SchedaEsito extends StatelessWidget {
  const SchedaEsito({super.key, required this.esito, this.extra});

  final Map<String, dynamic> esito;
  final Widget? extra;

  @override
  Widget build(BuildContext context) {
    final stile = Theme.of(context).textTheme;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).dividerColor),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(esito['titolo'].toString(), style: stile.titleSmall)),
          if (esito['obbligatorio'] == true)
            const Padding(
              padding: EdgeInsets.only(right: 8),
              child: Text('obbligatorio', style: TextStyle(fontSize: 11)),
            ),
          EsitoChip(esito['esito'] as String?),
        ]),
        if (esito['motivazione'] != null) ...[
          const SizedBox(height: 6),
          Text(esito['motivazione'].toString()),
        ],
        if (esito['evidenza'] != null) ...[
          const SizedBox(height: 6),
          Text('«${esito['evidenza']}»', style: stile.bodySmall?.copyWith(fontStyle: FontStyle.italic)),
        ],
        if (esito['suggerimento'] != null) ...[
          const SizedBox(height: 6),
          Text('Suggerimento: ${esito['suggerimento']}', style: stile.bodySmall),
        ],
        if ((esito['norme_usate'] as List?)?.isNotEmpty ?? false) ...[
          const SizedBox(height: 6),
          Text('Norme considerate: ${(esito['norme_usate'] as List).join('; ')}',
              style: stile.bodySmall),
        ],
        if (extra != null) ...[const SizedBox(height: 8), extra!],
      ]),
    );
  }
}

/// Stato di una verifica in corso.
class StatoVerificaBanner extends StatelessWidget {
  const StatoVerificaBanner({super.key, required this.verifica});

  final Map<String, dynamic> verifica;

  @override
  Widget build(BuildContext context) {
    final stato = verifica['stato'];
    if (stato == 'COMPLETATA') return const SizedBox.shrink();
    final errore = stato == 'ERRORE';
    return Card(
      color: errore ? Colors.red.shade50 : Colors.blue.shade50,
      child: ListTile(
        leading: errore
            ? const Icon(Icons.error, color: Colors.red)
            : const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2)),
        title: Text(errore
            ? 'Verifica non riuscita'
            : stato == 'IN_CORSO'
                ? 'Analisi in corso…'
                : 'Verifica in coda…'),
        subtitle: errore ? Text(verifica['errore']?.toString() ?? '') : null,
      ),
    );
  }
}
