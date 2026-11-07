import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../comuni.dart';
import 'comune.dart';

/// Albero di un processo da mostrare: {processo: {...}, attivita: [{..., rischi: [{...,
/// valutazione: {...} | null, misure: [...]}]}]}. Il dettaglio del processo (dall'API) si porta
/// in questo formato con [daAlbero]; le proposte di creazione hanno i figli nella stessa forma.
Map<String, dynamic> daAlbero(Map<String, dynamic> albero) {
  Map<String, dynamic>? valutazione(Map<String, dynamic> r) => r['valori_probabilita'] == null
      ? null
      : {
          for (final k in const [
            'valori_probabilita', 'valori_impatto', 'probabilita', 'impatto', 'motivazione_correzione',
            'probabilita_calcolata', 'impatto_calcolato', 'livello',
          ])
            k: r[k],
        };
  return {
    'processo': {
      for (final k in const [
        'id', 'codice', 'tipo', 'area_id', 'denominazione', 'descrizione', 'tempi', 'attori_esterni',
        'termine_conclusione', 'norma_riferimento', 'art35', 'struttura_id',
      ])
        k: albero[k],
    },
    // procedimento: scheda art. 35 (formato dello schema della trasparenza) e dati mancanti
    'scheda_art35': albero['scheda_art35'],
    'art35_mancanti': albero['art35_mancanti'],
    'proponibile': albero['proponibile'] == true, // processo della struttura del referente
    'attivita': [
      for (final a in (albero['attivita'] as List).cast<Map<String, dynamic>>())
        {
          ...a,
          'rischi': [
            for (final r in (a['rischi'] as List).cast<Map<String, dynamic>>())
              {...r, 'valutazione': valutazione(r), 'misure': (r['misure'] as List).cast<Map<String, dynamic>>()},
          ],
        },
    ],
  };
}

List<Map<String, dynamic>> _lista(Object? v) => (v as List? ?? const []).cast<Map<String, dynamic>>();

/// Modifiche all'albero: dirette (API, RPCT), proposte (referente: ogni operazione è una
/// proposta) o locali (sottoelementi di una proposta di creazione, da salvare).
abstract class OperazioniAlbero {
  bool get proposta; // le azioni si chiamano "Proponi..."
  Future<void> processo(Map<String, dynamic> valori);
  Future<void> aggiungiAttivita(Map<String, dynamic> valori);
  Future<void> modificaAttivita(Map<String, dynamic> attivita, Map<String, dynamic> valori);
  Future<void> eliminaAttivita(Map<String, dynamic> attivita);
  Future<void> aggiungiRischio(Map<String, dynamic> attivita, Map<String, dynamic> valori);
  Future<void> modificaRischio(Map<String, dynamic> rischio, Map<String, dynamic> valori);
  Future<void> eliminaRischio(Map<String, dynamic> attivita, Map<String, dynamic> rischio);
  Future<void> valuta(Map<String, dynamic> rischio, Map<String, dynamic> valutazione);
  Future<void> aggiungiMisura(Map<String, dynamic> rischio, Map<String, dynamic> valori);
  Future<void> modificaMisura(Map<String, dynamic> misura, Map<String, dynamic> valori);
  Future<void> eliminaMisura(Map<String, dynamic> rischio, Map<String, dynamic> misura);
}

/// Modifiche sulla copia locale (proposte): si salvano poi tutte insieme.
class OperazioniLocali implements OperazioniAlbero {
  OperazioniLocali(this.dati);

  final Map<String, dynamic> dati;

  @override
  bool get proposta => false;
  @override
  Future<void> processo(Map<String, dynamic> valori) async => (dati['processo'] as Map).addAll(valori);
  @override
  Future<void> aggiungiAttivita(Map<String, dynamic> valori) async =>
      (dati['attivita'] as List).add({...valori, 'rischi': <Map<String, dynamic>>[]});
  @override
  Future<void> modificaAttivita(Map<String, dynamic> attivita, Map<String, dynamic> valori) async => attivita.addAll(valori);
  @override
  Future<void> eliminaAttivita(Map<String, dynamic> attivita) async => (dati['attivita'] as List).remove(attivita);
  @override
  Future<void> aggiungiRischio(Map<String, dynamic> attivita, Map<String, dynamic> valori) async =>
      (attivita['rischi'] as List).add({...valori, 'valutazione': null, 'misure': <Map<String, dynamic>>[]});
  @override
  Future<void> modificaRischio(Map<String, dynamic> rischio, Map<String, dynamic> valori) async => rischio.addAll(valori);
  @override
  Future<void> eliminaRischio(Map<String, dynamic> attivita, Map<String, dynamic> rischio) async =>
      (attivita['rischi'] as List).remove(rischio);
  @override
  Future<void> valuta(Map<String, dynamic> rischio, Map<String, dynamic> valutazione) async {
    final fattore = valutazione.remove('fattore_abilitante') as String?;
    if (fattore != null) rischio['fattore_abilitante'] = fattore.isEmpty ? null : fattore;
    rischio['valutazione'] = valutazione;
  }

  @override
  Future<void> aggiungiMisura(Map<String, dynamic> rischio, Map<String, dynamic> valori) async =>
      (rischio['misure'] as List).add(valori);
  @override
  Future<void> modificaMisura(Map<String, dynamic> misura, Map<String, dynamic> valori) async => misura.addAll(valori);
  @override
  Future<void> eliminaMisura(Map<String, dynamic> rischio, Map<String, dynamic> misura) async =>
      (rischio['misure'] as List).remove(misura);
}

/// Modifiche dirette sulla mappatura (RPCT): ogni operazione va subito all'API.
class OperazioniDirette implements OperazioniAlbero {
  OperazioniDirette(this.api, this.processoId);

  final ApiClient api;
  final String processoId;

  @override
  bool get proposta => false;
  @override
  Future<void> processo(Map<String, dynamic> valori) => api.put('$apiAnticorruzione/processi/$processoId', valori);
  @override
  Future<void> aggiungiAttivita(Map<String, dynamic> valori) =>
      api.post('$apiAnticorruzione/processi/$processoId/attivita', valori);
  @override
  Future<void> modificaAttivita(Map<String, dynamic> attivita, Map<String, dynamic> valori) =>
      api.put('$apiAnticorruzione/attivita/${attivita['id']}', valori);
  @override
  Future<void> eliminaAttivita(Map<String, dynamic> attivita) => api.delete('$apiAnticorruzione/attivita/${attivita['id']}');
  @override
  Future<void> aggiungiRischio(Map<String, dynamic> attivita, Map<String, dynamic> valori) =>
      api.post('$apiAnticorruzione/attivita/${attivita['id']}/rischi', valori);
  @override
  Future<void> modificaRischio(Map<String, dynamic> rischio, Map<String, dynamic> valori) =>
      api.put('$apiAnticorruzione/rischi/${rischio['id']}', valori);
  @override
  Future<void> eliminaRischio(Map<String, dynamic> attivita, Map<String, dynamic> rischio) =>
      api.delete('$apiAnticorruzione/rischi/${rischio['id']}');
  @override
  Future<void> valuta(Map<String, dynamic> rischio, Map<String, dynamic> valutazione) =>
      api.put('$apiAnticorruzione/rischi/${rischio['id']}/valutazione', valutazione);
  @override
  Future<void> aggiungiMisura(Map<String, dynamic> rischio, Map<String, dynamic> valori) =>
      api.post('$apiAnticorruzione/rischi/${rischio['id']}/misure', valori);
  @override
  Future<void> modificaMisura(Map<String, dynamic> misura, Map<String, dynamic> valori) =>
      api.put('$apiAnticorruzione/misure/${misura['id']}', valori);
  @override
  Future<void> eliminaMisura(Map<String, dynamic> rischio, Map<String, dynamic> misura) =>
      api.delete('$apiAnticorruzione/misure/${misura['id']}');
}

/// Operazioni del referente sui processi della sua struttura: ognuna invia una proposta al
/// RPCT, che il referente può poi completare o ritirare dalla scheda Proposte.
class OperazioniProposte implements OperazioniAlbero {
  OperazioniProposte(this.api, this.processoId, this.inviata);

  final ApiClient api;
  final String processoId;
  final VoidCallback inviata;

  Future<void> _proponi(String tipo, String oggetto, {String? elemento, String? padre, Map<String, dynamic>? dati}) async {
    await api.post('$apiAnticorruzione/proposte', {
      'tipo': tipo,
      'oggetto': oggetto,
      'elemento_id': ?elemento,
      'padre_id': ?padre,
      'dati': ?dati,
    });
    inviata();
  }

  @override
  bool get proposta => true;
  @override
  Future<void> processo(Map<String, dynamic> valori) => _proponi('MODIFICA', 'PROCESSO', elemento: processoId, dati: valori);
  @override
  Future<void> aggiungiAttivita(Map<String, dynamic> valori) => _proponi('CREA', 'ATTIVITA', padre: processoId, dati: valori);
  @override
  Future<void> modificaAttivita(Map<String, dynamic> attivita, Map<String, dynamic> valori) =>
      _proponi('MODIFICA', 'ATTIVITA', elemento: attivita['id'] as String, dati: valori);
  @override
  Future<void> eliminaAttivita(Map<String, dynamic> attivita) => _proponi('ELIMINA', 'ATTIVITA', elemento: attivita['id'] as String);
  @override
  Future<void> aggiungiRischio(Map<String, dynamic> attivita, Map<String, dynamic> valori) =>
      _proponi('CREA', 'RISCHIO', padre: attivita['id'] as String, dati: valori);
  @override
  Future<void> modificaRischio(Map<String, dynamic> rischio, Map<String, dynamic> valori) =>
      _proponi('MODIFICA', 'RISCHIO', elemento: rischio['id'] as String, dati: {...valori, 'valutazione': rischio['valutazione']});
  @override
  Future<void> eliminaRischio(Map<String, dynamic> attivita, Map<String, dynamic> rischio) =>
      _proponi('ELIMINA', 'RISCHIO', elemento: rischio['id'] as String);
  @override
  Future<void> valuta(Map<String, dynamic> rischio, Map<String, dynamic> valutazione) {
    final fattore = valutazione.remove('fattore_abilitante') as String?;
    return _proponi('MODIFICA', 'RISCHIO', elemento: rischio['id'] as String, dati: {
      'evento': rischio['evento'],
      'fattore_abilitante': fattore == null ? rischio['fattore_abilitante'] : (fattore.isEmpty ? null : fattore),
      'valutazione': valutazione,
    });
  }

  @override
  Future<void> aggiungiMisura(Map<String, dynamic> rischio, Map<String, dynamic> valori) =>
      _proponi('CREA', 'MISURA', padre: rischio['id'] as String, dati: valori);
  @override
  Future<void> modificaMisura(Map<String, dynamic> misura, Map<String, dynamic> valori) =>
      _proponi('MODIFICA', 'MISURA', elemento: misura['id'] as String, dati: valori);
  @override
  Future<void> eliminaMisura(Map<String, dynamic> rischio, Map<String, dynamic> misura) =>
      _proponi('ELIMINA', 'MISURA', elemento: misura['id'] as String);
}

/// Etichetta di un'azione: per il referente diventa la proposta corrispondente.
String etichettaAzione(OperazioniAlbero ops, String testo) => !ops.proposta
    ? testo
    : const {
          'Modifica': 'Proponi modifica',
          'Elimina': 'Proponi eliminazione',
          'Valuta': 'Proponi valutazione',
          'Nuova attività': 'Proponi un\'attività',
          'Aggiungi un rischio': 'Proponi un rischio',
          'Aggiungi una misura': 'Proponi una misura',
          'Modifica l\'attività': 'Proponi la modifica dell\'attività',
          'Elimina l\'attività': 'Proponi l\'eliminazione dell\'attività',
          'Modifica la misura': 'Proponi la modifica della misura',
          'Elimina la misura': 'Proponi l\'eliminazione della misura',
        }[testo] ??
        testo;

// --- finestre di modifica ----------------------------------------------------------------

List<(String?, String)> _sceltaStrutture(DatiAnticorruzione d, String vuota) => [
      (null, vuota),
      for (final s in d.strutture.where((s) => s['attiva'] == true)) (s['id'] as String, '${s['codice']} - ${s['descrizione']}'),
    ];

/// Area di rischio (il codice lo assegna il sistema; l'elenco segue la descrizione breve).
Future<Map<String, dynamic>?> modificaArea(BuildContext context, [Map<String, dynamic>? a]) =>
    modificaCampi(context, titolo: a?['codice'] == null ? 'Nuova area di rischio' : 'Area ${a!['codice']}', valori: a ?? const {}, campi: const [
      Campo('descrizione', 'Descrizione', righe: 3, obbligatorio: true),
      Campo('descrizione_breve', 'Descrizione breve', aiuto: 'Le aree si elencano in ordine alfabetico di questa'),
    ]);

/// Processo o procedimento (il codice lo assegna il sistema dall'area, es. C.11). Termine di
/// conclusione e norma di riferimento valgono per i procedimenti.
Future<Map<String, dynamic>?> modificaProcesso(BuildContext context, DatiAnticorruzione d, [Map<String, dynamic>? p]) =>
    modificaCampi(context, titolo: p?['codice'] == null ? 'Nuovo processo o procedimento' : '${etichettaTipo(p!['tipo'])} ${p['codice']}', valori: {'tipo': 'PROCESSO', ...?p}, campi: [
      const Campo('tipo', 'Tipo', scelte: [('PROCESSO', 'Processo'), ('PROCEDIMENTO', 'Procedimento')]),
      Campo('area_id', 'Area di rischio', scelte: [
        (null, 'Nessuna'),
        for (final a in d.aree) (a['id'] as String, '${a['codice']} - ${a['descrizione_breve'] ?? a['descrizione']}'),
      ]),
      const Campo('denominazione', 'Denominazione', righe: 2, obbligatorio: true),
      const Campo('descrizione', 'Descrizione', righe: 4),
      const Campo('tempi', 'Tempi', righe: 2),
      const Campo('attori_esterni', 'Attori esterni', righe: 2),
      const Campo('termine_conclusione', 'Termine di conclusione', aiuto: 'Solo per i procedimenti (es. 30 giorni)'),
      const Campo('norma_riferimento', 'Norma di riferimento', righe: 2, aiuto: 'Solo per i procedimenti'),
      Campo('struttura_id', 'Struttura responsabile', scelte: _sceltaStrutture(d, 'Tutte (processo trasversale)')),
    ]);

String etichettaTipo(Object? tipo) => tipo == 'PROCEDIMENTO' ? 'Procedimento' : 'Processo';

Future<Map<String, dynamic>?> modificaAttivita(BuildContext context, [Map<String, dynamic>? a]) =>
    modificaCampi(context, titolo: a?['codice'] == null ? 'Nuova attività' : 'Attività ${a!['codice']}', valori: a ?? const {}, campi: const [
      Campo('descrizione', 'Descrizione', righe: 4, obbligatorio: true),
      Campo('strutture_coinvolte', 'Strutture coinvolte', righe: 2),
    ]);

Future<Map<String, dynamic>?> modificaRischio(BuildContext context, DatiAnticorruzione d, [Map<String, dynamic>? r]) {
  final attuale = r?['fattore_abilitante'] as String?;
  return modificaCampi(context, titolo: r?['codice'] == null ? 'Nuovo rischio' : 'Rischio ${r!['codice']}', valori: r ?? const {}, campi: [
    const Campo('evento', 'Evento rischioso', righe: 4, obbligatorio: true),
    Campo('fattore_abilitante', 'Fattore abilitante', scelte: [
      (null, 'Nessuno'),
      for (final f in d.fattori) (f, f),
      if (attuale != null && !d.fattori.contains(attuale)) (attuale, attuale),
    ]),
  ]);
}

Future<Map<String, dynamic>?> modificaMisura(BuildContext context, DatiAnticorruzione d, [Map<String, dynamic>? m]) {
  final categoria = m?['categoria'] as String?;
  return modificaCampi(context, titolo: m?['codice'] == null ? 'Nuova misura' : 'Misura ${m!['codice']}', valori: {'tipo': 'SPECIFICA', ...?m}, campi: [
    const Campo('descrizione', 'Descrizione', righe: 5, obbligatorio: true),
    const Campo('tipo', 'Tipo', scelte: [('GENERALE', 'Generale'), ('SPECIFICA', 'Specifica')]),
    Campo('categoria', 'Categoria', scelte: [
      (null, 'Nessuna'),
      for (final c in d.categorie) (c, c),
      if (categoria != null && !d.categorie.contains(categoria)) (categoria, categoria),
    ]),
    Campo('obbligo_trasparenza', 'Obbligo di pubblicazione', aiuto: 'Per le misure di trasparenza: lo schema ANAC', scelte: [
      (null, 'Nessuno'),
      for (final o in d.obblighi) (o['id'] as String, '${o['articolo']} - ${o['titolo']}'),
    ]),
    const Campo('fasi', 'Fasi di attuazione', righe: 3),
    const Campo('tempi', 'Tempi di attuazione', righe: 2),
    Campo('struttura_id', 'Struttura responsabile dell\'attuazione', scelte: _sceltaStrutture(d, 'Quella del processo')),
    const Campo('indicatore', 'Indicatore', righe: 2),
    const Campo('target', 'Target', righe: 2),
  ]);
}

/// Valutazione del rischio: un valore per indicatore, probabilità e impatto calcolati (moda,
/// a parità il più alto) con la correzione facoltativa motivata, livello dalla matrice.
Future<Map<String, dynamic>?> valutaRischio(BuildContext context, DatiAnticorruzione d, Map<String, dynamic> r) async {
  final v = (r['valutazione'] as Map?)?.cast<String, dynamic>() ?? const {};
  final prob = <String, String>{
    for (final i in d.indicatoriProbabilita)
      i['id'] as String: ((v['valori_probabilita'] as Map?)?[i['id']] as String?) ?? d.scala[d.scala.length ~/ 2],
  };
  final imp = <String, String>{
    for (final i in d.indicatoriImpatto)
      i['id'] as String: ((v['valori_impatto'] as Map?)?[i['id']] as String?) ?? d.scala[d.scala.length ~/ 2],
  };
  final pCalc0 = d.moda(prob.values), iCalc0 = d.moda(imp.values);
  String? pCorr = v['probabilita'] != null && v['probabilita'] != pCalc0 ? v['probabilita'] as String : null;
  String? iCorr = v['impatto'] != null && v['impatto'] != iCalc0 ? v['impatto'] as String : null;
  String? fattore = r['fattore_abilitante'] as String?;
  final motivazione = TextEditingController(text: v['motivazione_correzione'] as String? ?? '');
  String? errore;

  Widget indicatori(String titolo, List<Map<String, dynamic>> lista, Map<String, String> valori, void Function(void Function()) aggiorna) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 8, bottom: 4), child: Text(titolo, style: Theme.of(context).textTheme.titleSmall)),
        for (final i in lista)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(children: [
              Expanded(
                child: Tooltip(
                  message: i['descrizione'] as String? ?? '',
                  child: Text('${i['id']}. ${i['nome']}'),
                ),
              ),
              SegmentedButton<String>(
                showSelectedIcon: false,
                segments: [for (final s in d.scala) ButtonSegment(value: s, label: Text(s))],
                selected: {valori[i['id']]!},
                onSelectionChanged: (s) => aggiorna(() => valori[i['id'] as String] = s.first),
              ),
            ]),
          ),
      ]);

  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => StatefulBuilder(builder: (c, aggiorna) {
      final pCalc = d.moda(prob.values), iCalc = d.moda(imp.values);
      final p = pCorr ?? pCalc, i = iCorr ?? iCalc;
      return AlertDialog(
        title: Text('Valutazione del rischio ${r['codice'] ?? ''}'),
        content: SizedBox(
          width: 720,
          child: SingleChildScrollView(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(r['evento'] as String? ?? ''),
              indicatori('Probabilità', d.indicatoriProbabilita, prob, aggiorna),
              indicatori('Impatto', d.indicatoriImpatto, imp, aggiorna),
              const Divider(),
              Wrap(spacing: 16, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                Text('Calcolati: probabilità $pCalc, impatto $iCalc'),
                LivelloChip(d, d.livelloDa(p, i)),
              ]),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(
                  child: DropdownButtonFormField<String?>(
                    initialValue: pCorr,
                    decoration: const InputDecoration(labelText: 'Correzione della probabilità'),
                    items: [const DropdownMenuItem(value: null, child: Text('Nessuna')), for (final s in d.scala) DropdownMenuItem(value: s, child: Text(s))],
                    onChanged: (x) => aggiorna(() => pCorr = x),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: DropdownButtonFormField<String?>(
                    initialValue: iCorr,
                    decoration: const InputDecoration(labelText: 'Correzione dell\'impatto'),
                    items: [const DropdownMenuItem(value: null, child: Text('Nessuna')), for (final s in d.scala) DropdownMenuItem(value: s, child: Text(s))],
                    onChanged: (x) => aggiorna(() => iCorr = x),
                  ),
                ),
              ]),
              if (pCorr != null || iCorr != null)
                TextField(
                  controller: motivazione,
                  maxLines: 3,
                  decoration: const InputDecoration(labelText: 'Motivazione della correzione *'),
                ),
              const SizedBox(height: 8),
              DropdownButtonFormField<String?>(
                initialValue: fattore,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Fattore abilitante'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('Nessuno')),
                  for (final f in {...d.fattori, ?fattore}) DropdownMenuItem(value: f, child: Text(f, overflow: TextOverflow.ellipsis)),
                ],
                onChanged: (x) => aggiorna(() => fattore = x),
              ),
              if (errore != null) Text(errore!, style: TextStyle(color: Theme.of(c).colorScheme.error)),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(
            onPressed: () {
              if ((pCorr != null && pCorr != pCalc || iCorr != null && iCorr != iCalc) && motivazione.text.trim().isEmpty) {
                aggiorna(() => errore = 'Per correggere probabilità o impatto serve la motivazione');
                return;
              }
              Navigator.pop(c, true);
            },
            child: const Text('Salva'),
          ),
        ],
      );
    }),
  );
  final pCalc = d.moda(prob.values), iCalc = d.moda(imp.values);
  final corretta = (pCorr != null && pCorr != pCalc) || (iCorr != null && iCorr != iCalc);
  final risultato = {
    'valori_probabilita': prob,
    'valori_impatto': imp,
    'probabilita': corretta ? (pCorr ?? pCalc) : null,
    'impatto': corretta ? (iCorr ?? iCalc) : null,
    'motivazione_correzione': corretta ? motivazione.text.trim() : null,
    'fattore_abilitante': fattore ?? '',
    // per mostrare subito l'esito nelle proposte (il server lo ricalcola)
    'probabilita_calcolata': pCalc,
    'impatto_calcolato': iCalc,
    'livello': d.livelloDa(corretta ? (pCorr ?? pCalc) : pCalc, corretta ? (iCorr ?? iCalc) : iCalc),
  };
  motivazione.dispose();
  return ok == true ? risultato : null;
}

// --- vista dell'albero -------------------------------------------------------------------

/// Processo con attività, rischi (livello) e misure; con [operazioni] si modifica.
class AlberoProcesso extends StatelessWidget {
  const AlberoProcesso({
    super.key,
    required this.dati,
    required this.albero,
    this.operazioni,
    required this.onCambiato,
    this.aggiungiAttivita = true,
  });

  final DatiAnticorruzione dati;
  final Map<String, dynamic> albero; // formato di daAlbero
  final OperazioniAlbero? operazioni;
  final VoidCallback onCambiato;
  final bool aggiungiAttivita; // no per la proposta di una sola attività

  @override
  Widget build(BuildContext context) {
    final ops = operazioni;
    final attivita = _lista(albero['attivita']);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final a in attivita)
        Card(
          child: ExpansionTile(
            initiallyExpanded: attivita.length <= 3,
            title: Text('${a['codice'] ?? 'Nuova'} - ${a['descrizione']}'),
            subtitle: Text('${_lista(a['rischi']).length} rischi'
                '${a['strutture_coinvolte'] != null ? ' · ${a['strutture_coinvolte']}' : ''}'),
            trailing: ops == null
                ? null
                : Wrap(children: [
                    IconaAzione(Icons.edit_outlined, etichettaAzione(ops, 'Modifica l\'attività'), () => eseguiOperazione(context, onCambiato, () async {
                          final v = await modificaAttivita(context, a);
                          if (v != null) await ops.modificaAttivita(a, v);
                        })),
                    IconaAzione(Icons.add_alert_outlined, etichettaAzione(ops, 'Aggiungi un rischio'), () => eseguiOperazione(context, onCambiato, () async {
                          final v = await modificaRischio(context, dati);
                          if (v != null) await ops.aggiungiRischio(a, v);
                        })),
                    IconaAzione(Icons.delete_outline, etichettaAzione(ops, 'Elimina l\'attività'), () => eseguiOperazione(context, onCambiato, () async {
                          if (await confermaEliminazione(context, 'l\'attività', proposta: ops.proposta)) await ops.eliminaAttivita(a);
                        })),
                  ]),
            childrenPadding: const EdgeInsets.fromLTRB(16, 0, 8, 8),
            children: [
              if (_lista(a['rischi']).isEmpty) const ListTile(dense: true, title: Text('Nessun rischio individuato.')),
              for (final r in _lista(a['rischi']))
                SchedaRischio(dati: dati, attivita: a, rischio: r, operazioni: ops, onCambiato: onCambiato),
            ],
          ),
        ),
      if (ops != null && aggiungiAttivita)
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            icon: const Icon(Icons.add),
            label: const Text('Aggiungi un\'attività'),
            onPressed: () => eseguiOperazione(context, onCambiato, () async {
              final v = await modificaAttivita(context);
              if (v != null) await ops.aggiungiAttivita(v);
            }),
          ),
        ),
    ]);
  }
}

Future<void> eseguiOperazione(BuildContext context, VoidCallback onCambiato, Future<void> Function() azione) async {
  try {
    await azione();
    onCambiato();
  } catch (e) {
    if (context.mounted) mostraErrore(context, e);
  }
}

Future<bool> confermaEliminazione(BuildContext context, String cosa, {bool proposta = false}) => proposta
    ? conferma(context, 'Proporre l\'eliminazione?', 'Si invia al RPCT la proposta di eliminare $cosa, con gli elementi che '
        'contiene: decide il RPCT.')
    : conferma(context, 'Eliminare $cosa?', 'Si eliminano anche gli elementi che contiene.');

/// Un rischio con la valutazione e le misure che lo mitigano.
class SchedaRischio extends StatelessWidget {
  const SchedaRischio({super.key, required this.dati, required this.attivita, required this.rischio, this.operazioni, required this.onCambiato});

  final DatiAnticorruzione dati;
  final Map<String, dynamic> attivita;
  final Map<String, dynamic> rischio;
  final OperazioniAlbero? operazioni;
  final VoidCallback onCambiato;

  @override
  Widget build(BuildContext context) {
    final ops = operazioni;
    final r = rischio;
    final colori = Theme.of(context).colorScheme;
    final valutazione = r['valutazione'] as Map?;
    void esegui(Future<void> Function() azione) => eseguiOperazione(context, onCambiato, azione);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: dati.colore(valutazione?['livello'] as String?), width: 4)),
      ),
      padding: const EdgeInsets.only(left: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${r['codice'] ?? 'Nuovo rischio'}', style: const TextStyle(fontWeight: FontWeight.w600)),
        Text(r['evento'] as String? ?? ''),
        const SizedBox(height: 4),
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          LivelloChip(dati, valutazione?['livello'] as String?),
          if (valutazione != null)
            Text('P ${valutazione['probabilita']} · I ${valutazione['impatto']}'
                '${valutazione['motivazione_correzione'] != null ? ' (corretta)' : ''}',
                style: TextStyle(color: colori.onSurfaceVariant)),
          if (r['fattore_abilitante'] != null)
            Text('Fattore: ${r['fattore_abilitante']}', style: TextStyle(color: colori.onSurfaceVariant)),
        ]),
        if (valutazione != null)
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              dense: true,
              tilePadding: EdgeInsets.zero,
              childrenPadding: const EdgeInsets.only(bottom: 8),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              title: const Text('Valori degli indicatori'),
              children: [ValoriIndicatori(dati: dati, valutazione: valutazione.cast<String, dynamic>())],
            ),
          ),
        if (ops != null)
          Wrap(spacing: 4, children: [
            TextButton.icon(
              icon: const Icon(Icons.speed, size: 18),
              label: Text(etichettaAzione(ops, 'Valuta')),
              onPressed: () => esegui(() async {
                final v = await valutaRischio(context, dati, r);
                if (v != null) await ops.valuta(r, v);
              }),
            ),
            TextButton.icon(
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: Text(etichettaAzione(ops, 'Modifica')),
              onPressed: () => esegui(() async {
                final v = await modificaRischio(context, dati, r);
                if (v != null) await ops.modificaRischio(r, v);
              }),
            ),
            TextButton.icon(
              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
              icon: const Icon(Icons.delete_outline, size: 18),
              label: Text(etichettaAzione(ops, 'Elimina')),
              onPressed: () => esegui(() async {
                if (await confermaEliminazione(context, 'il rischio', proposta: ops.proposta)) await ops.eliminaRischio(attivita, r);
              }),
            ),
            TextButton.icon(
              icon: const Icon(Icons.add_task, size: 18),
              label: Text(etichettaAzione(ops, 'Aggiungi una misura')),
              onPressed: () => esegui(() async {
                final v = await modificaMisura(context, dati);
                if (v != null) await ops.aggiungiMisura(r, v);
              }),
            ),
          ]),
        for (final m in _lista(r['misure']))
          ListTile(
            dense: true,
            contentPadding: const EdgeInsets.only(left: 8),
            leading: Icon(m['tipo'] == 'GENERALE' ? Icons.policy_outlined : Icons.task_alt, size: 20),
            title: Text('${m['codice'] ?? 'Nuova misura'} - ${m['descrizione']}'),
            subtitle: Text([
              m['tipo'] == 'GENERALE' ? 'Generale' : 'Specifica',
              ?m['categoria'],
              if (m['obbligo_trasparenza'] != null) 'Pubblicazione ${m['obbligo_trasparenza']}',
              if (m['struttura_id'] != null) dati.struttura(m['struttura_id']) ?? '',
              if (m['tempi'] != null) 'Tempi: ${m['tempi']}',
            ].join(' · ')),
            trailing: ops == null
                ? null
                : Wrap(children: [
                    IconaAzione(Icons.edit_outlined, etichettaAzione(ops, 'Modifica la misura'), () => esegui(() async {
                          final v = await modificaMisura(context, dati, m);
                          if (v != null) await ops.modificaMisura(m, v);
                        })),
                    IconaAzione(Icons.delete_outline, etichettaAzione(ops, 'Elimina la misura'), () => esegui(() async {
                          if (await confermaEliminazione(context, 'la misura', proposta: ops.proposta)) await ops.eliminaMisura(r, m);
                        })),
                  ]),
          ),
      ]),
    );
  }
}

/// Intestazione del processo o procedimento: area, struttura, tempi, attori esterni e, per
/// il procedimento, termine di conclusione e norma di riferimento.
class IntestazioneProcesso extends StatelessWidget {
  const IntestazioneProcesso({super.key, required this.dati, required this.processo, this.azioni});

  final DatiAnticorruzione dati;
  final Map<String, dynamic> processo;
  final List<Widget>? azioni;

  @override
  Widget build(BuildContext context) {
    final righe = [
      ('Area di rischio', dati.area(processo['area_id'])),
      ('Struttura responsabile', processo['struttura_id'] == null ? 'Tutte (processo trasversale)' : dati.struttura(processo['struttura_id'])),
      ('Descrizione', processo['descrizione']),
      ('Tempi', processo['tempi']),
      ('Attori esterni', processo['attori_esterni']),
      if (processo['tipo'] == 'PROCEDIMENTO') ...[
        ('Termine di conclusione', processo['termine_conclusione']),
        ('Norma di riferimento', processo['norma_riferimento']),
      ],
    ];
    return Sezione(
      titolo: '${etichettaTipo(processo['tipo'])} ${processo['codice'] ?? '(nuovo)'} - ${processo['denominazione'] ?? ''}',
      azioni: azioni,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final (etichetta, valore) in righe)
          if (valore != null && valore.toString().isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text.rich(TextSpan(children: [
                TextSpan(text: '$etichetta: ', style: const TextStyle(fontWeight: FontWeight.w600)),
                TextSpan(text: valore.toString()),
              ])),
            ),
      ]),
    );
  }
}

/// Valori scelti per gli indicatori di probabilità e di impatto, con l'eventuale correzione
/// motivata. Con [prima] (proposta di modifica) gli indicatori cambiati mostrano anche il
/// valore precedente.
class ValoriIndicatori extends StatelessWidget {
  const ValoriIndicatori({super.key, required this.dati, required this.valutazione, this.prima});

  final DatiAnticorruzione dati;
  final Map<String, dynamic> valutazione;
  final Map<String, dynamic>? prima;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    Widget gruppo(String titolo, List<Map<String, dynamic>> indicatori, String chiave) {
      final valori = (valutazione[chiave] as Map?) ?? const {};
      final precedenti = (prima?[chiave] as Map?) ?? const {};
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 4, bottom: 2), child: Text(titolo, style: tema.textTheme.titleSmall)),
        for (final i in indicatori)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 1),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Tooltip(message: i['descrizione'] as String? ?? '', child: Text('${i['id']}. ${i['nome']}')),
              ),
              const SizedBox(width: 12),
              if (prima != null && precedenti[i['id']] != valori[i['id']])
                Text('${precedenti[i['id']] ?? '—'} → ${valori[i['id']] ?? '—'}',
                    style: TextStyle(fontWeight: FontWeight.w600, color: tema.colorScheme.primary))
              else
                Text('${valori[i['id']] ?? '—'}'),
            ]),
          ),
      ]);
    }

    final corretta = valutazione['motivazione_correzione'] != null;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      gruppo('Probabilità (calcolata: ${valutazione['probabilita_calcolata'] ?? '—'})', dati.indicatoriProbabilita, 'valori_probabilita'),
      gruppo('Impatto (calcolato: ${valutazione['impatto_calcolato'] ?? '—'})', dati.indicatoriImpatto, 'valori_impatto'),
      if (corretta)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('Corretta in probabilità ${valutazione['probabilita']}, impatto ${valutazione['impatto']}: '
              '${valutazione['motivazione_correzione']}'),
        ),
    ]);
  }
}
