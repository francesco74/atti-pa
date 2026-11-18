import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../comuni.dart';
import 'catalogo.dart' show scegliVoce;
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
            'motivazione_valutazione', 'probabilita_calcolata', 'impatto_calcolato', 'livello',
          ])
            k: r[k],
        };
  return {
    'processo': {
      for (final k in const [
        'id', 'codice', 'area_id', 'denominazione', 'descrizione', 'tempi', 'attori_esterni', 'struttura_id', 'coinvolte',
      ])
        k: albero[k],
    },
    'proponibile': albero['proponibile'] == true, // processo della struttura del referente
    // obiettivi della performance che usano il processo, una sua attività o una sua misura
    'obiettivi': (albero['obiettivi'] as List? ?? const []).cast<Map<String, dynamic>>(),
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

/// Strutture da scegliere come coinvolte: le attive e quelle già scelte (anche se non più attive).
List<(String?, String)> _scelteCoinvolte(DatiAnticorruzione d, Object? gia) {
  final scelte = {for (final id in (gia as List?) ?? const []) id};
  return [
    for (final s in d.strutture.where((s) => s['attiva'] == true || scelte.contains(s['id'])))
      (s['id'] as String, '${s['codice']} - ${s['descrizione']}'),
  ];
}

/// Area di rischio (l'elenco segue la descrizione breve). Nuova: il codice è precompilato con
/// quello che il sistema propone (la lettera successiva) e si può cambiare; poi non cambia più.
/// Le finestre degli elementi: con [salva] il salvataggio lo fa la finestra, che si chiude solo
/// se riesce (altrimenti l'errore si legge nella finestra e i dati restano).
Future<Map<String, dynamic>?> modificaArea(BuildContext context,
    {Map<String, dynamic>? a, Future<void> Function(Map<String, dynamic>)? salva, bool? nuova}) async {
  nuova ??= a?['id'] == null; // nelle proposte lo dice chi chiama (creazione o modifica)
  var valori = a ?? const <String, dynamic>{};
  if (nuova && valori['codice'] == null) {
    try {
      final r = await apiDi(context).get('$apiAnticorruzione/aree/codice-proposto') as Map;
      valori = {...valori, 'codice': r['codice']};
    } catch (_) {
      // senza proposta il campo resta vuoto: il sistema assegna la lettera successiva
    }
  }
  if (!context.mounted) return null;
  return modificaCampi(context, salva: salva, titolo: nuova ? 'Nuova area di rischio' : 'Area ${a!['codice']}', valori: valori, campi: [
    if (nuova)
      const Campo('codice', 'Codice', aiuto: 'Proposto dal sistema, si può cambiare: breve, senza punti (dà il codice ai processi, es. A.1)'),
    const Campo('descrizione', 'Descrizione', righe: 3, obbligatorio: true),
    const Campo('descrizione_breve', 'Descrizione breve', aiuto: 'Le aree si elencano in ordine alfabetico di questa'),
  ]);
}

/// Processo (il codice lo assegna il sistema dall'area, es. C.11; senza area X.n). I
/// procedimenti non sono processi: un'attività del processo può essere un procedimento.
Future<Map<String, dynamic>?> modificaProcesso(BuildContext context, DatiAnticorruzione d, {Map<String, dynamic>? p, Future<void> Function(Map<String, dynamic>)? salva}) =>
    modificaCampi(context, salva: salva, titolo: p?['codice'] == null ? 'Nuovo processo' : 'Processo ${p!['codice']}', valori: p ?? const {}, campi: [
      Campo('area_id', 'Area di rischio', scelte: [
        (null, 'Nessuna'),
        for (final a in d.aree) (a['id'] as String, '${a['codice']} - ${a['descrizione_breve'] ?? a['descrizione']}'),
      ]),
      const Campo('denominazione', 'Denominazione', righe: 2, obbligatorio: true),
      const Campo('descrizione', 'Descrizione', righe: 4),
      const Campo('tempi', 'Tempi', righe: 2),
      const Campo('attori_esterni', 'Attori esterni', righe: 2),
      Campo('struttura_id', 'Struttura responsabile', scelte: _sceltaStrutture(d, 'Tutte (processo trasversale)')),
      Campo('coinvolte', 'Strutture coinvolte', multipla: true, scelte: _scelteCoinvolte(d, p?['coinvolte']),
          aiuto: 'Oltre alla responsabile: il processo si trova anche tra quelli di queste strutture (che non ne propongono modifiche)'),
    ]);

/// Spiegazione nella finestra dell'elemento: la voce del catalogo da cui viene (o, per
/// un'attività, il procedimento che è).
String? _notaVoce(Map? voce) => voce == null
    ? null
    : voce['procedimento'] == true
        ? 'Procedimento ${voce['codice']}: «${voce['denominazione']}». Il testo si può ritoccare per questo processo; '
            'il procedimento resta lo stesso.'
        : 'Voce del catalogo ${voce['codice']}: «${voce['descrizione']}». Il testo si può ritoccare per questo processo; '
            'la voce resta la stessa.';

/// Elemento nuovo: si sceglie prima la voce dal catalogo (se manca, il RPCT la crea e il
/// referente la propone); null se non si sceglie. Elemento esistente: la sua voce.
Future<Map<String, dynamic>?> _voce(BuildContext context, DatiAnticorruzione d, String tipo, Map? el) async =>
    el == null ? await scegliVoce(context, tipo, dati: d) : (el['voce'] as Map?)?.cast<String, dynamic>();

/// Il procedimento dell'attività ({id, codice, denominazione, procedimento: true}), se lo è.
Map<String, dynamic>? procedimentoDi(Map a) {
  final p = a['procedimento'] as Map?;
  return p == null ? null : {...p.cast<String, dynamic>(), 'procedimento': true};
}

/// Attività: nuova, nasce da una voce del catalogo delle attività oppure è un procedimento del
/// catalogo dei procedimenti (in alternativa); il testo si copia e si ritocca.
/// Dati del procedimento che l'attività può adattare per il suo processo (gli altri restano
/// quelli del catalogo), con l'etichetta; come common/anticorruzione/art35.ADATTABILI.
const campiAdattabili = {
  'struttura_id': 'Unità responsabile dell\'istruttoria',
  'uff_resp_struttura_id': 'Ufficio responsabile del procedimento',
  'uff_finale_struttura_id': 'Ufficio del provvedimento finale',
  'ist_struttura_id': 'Ufficio per informazioni e istanze',
  'sost_struttura_id': 'Ufficio del potere sostitutivo',
  'termine_conclusione': 'Termine di conclusione',
};

/// I dati adattabili come sono nel catalogo: dal procedimento dell'attività ({catalogo}) o da
/// quello appena scelto (elenco del catalogo, con struttura, termine e art35).
Map<String, dynamic> datiCatalogo(Map p) {
  if (p['catalogo'] is Map) return (p['catalogo'] as Map).cast<String, dynamic>();
  final art35 = (p['art35'] as Map?) ?? const {};
  return {
    for (final k in campiAdattabili.keys) k: k == 'struttura_id' || k == 'termine_conclusione' ? p[k] : art35[k],
  };
}

/// L'adattamento di un'attività-procedimento, campo per campo: "Ufficio ...: X (nel catalogo:
/// Y)"; vuoto se non è adattato.
List<String> righeAdattamento(DatiAnticorruzione d, Map a) {
  final adattato = (a['procedimento_adattato'] as Map?) ?? const {};
  final p = a['procedimento'] as Map?;
  final catalogo = p == null ? const <String, dynamic>{} : datiCatalogo(p);
  String testo(String k, Object? v) => v == null ? 'non indicato' : (k.endsWith('struttura_id') ? d.struttura(v) ?? '—' : '$v');
  return [
    for (final MapEntry(key: k, value: etichetta) in campiAdattabili.entries)
      if (adattato[k] != null) '$etichetta: ${testo(k, adattato[k])}${p == null ? '' : ' (nel catalogo: ${testo(k, catalogo[k])})'}',
  ];
}

/// Attività: nuova, nasce da una voce del catalogo delle attività oppure è un procedimento del
/// catalogo dei procedimenti (in alternativa); il testo si copia e si ritocca. Il procedimento si
/// può adattare a questo processo (unità responsabile, uffici, termine): i campi lasciati vuoti
/// valgono come nel catalogo, e l'attività resta tra quelle che usano il procedimento.
Future<Map<String, dynamic>?> modificaAttivita(BuildContext context, DatiAnticorruzione d, {Map<String, dynamic>? a, Future<void> Function(Map<String, dynamic>)? salva}) async {
  final origine = a == null
      ? await scegliVoce(context, 'ATTIVITA', dati: d, procedimenti: true)
      : procedimentoDi(a) ?? (a['voce'] as Map?)?.cast<String, dynamic>();
  if (a == null && origine == null || !context.mounted) return null;
  final procedimento = origine?['procedimento'] == true;
  final catalogo = procedimento ? datiCatalogo(origine!) : const <String, dynamic>{};
  final adattato = (a?['procedimento_adattato'] as Map?) ?? const {};
  String nelCatalogo(String k) {
    final v = catalogo[k];
    if (v == null) return 'non indicato';
    return k.endsWith('struttura_id') ? d.struttura(v) ?? '—' : '$v';
  }

  Map<String, dynamic> conVoce(Map<String, dynamic> v) {
    final adattamento = {
      for (final k in campiAdattabili.keys)
        if (v['adatta_$k'] != null) k: v['adatta_$k'],
    };
    return {
      for (final e in v.entries)
        if (!e.key.startsWith('adatta_')) e.key: e.value,
      if (procedimento) 'procedimento_adattato': adattamento.isEmpty ? null : adattamento,
      if (a == null && procedimento) ...{
        'procedimento_id': origine!['id'],
        'procedimento': {for (final k in const ['id', 'codice', 'denominazione']) k: origine[k], 'catalogo': catalogo},
      },
      if (a == null && !procedimento) ...{'voce_id': origine!['id'], 'voce': origine},
    };
  }

  final v = await modificaCampi(context,
      salva: salva == null ? null : (v) => salva(conVoce(v)),
      titolo: a?['codice'] == null ? (procedimento ? 'Nuova attività: procedimento ${origine!['codice']}' : 'Nuova attività') : 'Attività ${a!['codice']}',
      valori: {
        ...?a,
        if (a == null) 'descrizione': procedimento ? origine!['denominazione'] : origine!['descrizione'],
        for (final e in adattato.entries) 'adatta_${e.key}': e.value,
      },
      nota: procedimento
          ? '${_notaVoce(origine)}\nPer questo processo puoi adattare unità responsabile, uffici e termine: i campi lasciati '
              'come nel catalogo restano quelli del procedimento.'
          : _notaVoce(origine),
      campi: [
        const Campo('descrizione', 'Descrizione', righe: 4, obbligatorio: true),
        Campo('coinvolte', 'Strutture coinvolte', multipla: true, scelte: _scelteCoinvolte(d, a?['coinvolte'])),
        const Campo('strutture_coinvolte', 'Note sulle strutture coinvolte', righe: 2),
        if (procedimento)
          for (final MapEntry(key: k, value: etichetta) in campiAdattabili.entries)
            k.endsWith('struttura_id')
                ? Campo('adatta_$k', '$etichetta (per questo processo)', scelte: [
                    (null, 'Come nel catalogo: ${nelCatalogo(k)}'),
                    for (final s in d.strutture.where((s) => s['attiva'] == true || s['id'] == adattato[k]))
                      (s['id'] as String, '${s['codice']} - ${s['descrizione']}'),
                  ])
                : Campo('adatta_$k', '$etichetta (per questo processo)', aiuto: 'Nel catalogo: ${nelCatalogo(k)}. Vuoto: quello del catalogo'),
      ]);
  return v == null ? null : conVoce(v);
}

Future<Map<String, dynamic>?> modificaRischio(BuildContext context, DatiAnticorruzione d, {Map<String, dynamic>? r, Future<void> Function(Map<String, dynamic>)? salva}) async {
  final voce = await _voce(context, d, 'RISCHIO', r);
  if (r == null && voce == null || !context.mounted) return null;
  Map<String, dynamic> conVoce(Map<String, dynamic> v) => {...v, if (r == null) 'voce_id': voce!['id'], if (r == null) 'voce': voce};
  final attuale = r?['fattore_abilitante'] as String?;
  final v = await modificaCampi(context,
      salva: salva == null ? null : (v) => salva(conVoce(v)),
      titolo: r?['codice'] == null ? 'Nuovo rischio' : 'Rischio ${r!['codice']}',
      valori: r ?? {'evento': voce!['descrizione']},
      nota: _notaVoce(voce),
      campi: [
    const Campo('evento', 'Evento rischioso', righe: 4, obbligatorio: true),
    Campo('fattore_abilitante', 'Fattore abilitante', scelte: [
      (null, 'Nessuno'),
      for (final f in d.fattori) (f, f),
      if (attuale != null && !d.fattori.contains(attuale)) (attuale, attuale),
    ]),
  ]);
  return v == null ? null : conVoce(v);
}

Future<Map<String, dynamic>?> modificaMisura(BuildContext context, DatiAnticorruzione d, {Map<String, dynamic>? m, Future<void> Function(Map<String, dynamic>)? salva}) async {
  final voce = await _voce(context, d, 'MISURA', m);
  if (m == null && voce == null || !context.mounted) return null;
  Map<String, dynamic> conVoce(Map<String, dynamic> v) => {...v, if (m == null) 'voce_id': voce!['id'], if (m == null) 'voce': voce};
  // dalla voce: testo, tipo, categoria, indicatore e target di partenza
  final valori = m ??
      {
        'descrizione': voce!['descrizione'],
        'tipo': voce['tipo_misura'] ?? 'SPECIFICA',
        'categoria': voce['categoria'],
        'indicatore': voce['indicatore'],
        'target': voce['target'],
      };
  final categoria = valori['categoria'] as String?;
  final v = await modificaCampi(context,
      salva: salva == null ? null : (v) => salva(conVoce(v)),
      titolo: m?['codice'] == null ? 'Nuova misura' : 'Misura ${m!['codice']}',
      valori: {'tipo': 'SPECIFICA', ...valori},
      nota: _notaVoce(voce),
      campi: [
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
  return v == null ? null : conVoce(v);
}

/// Valutazione del rischio: un valore per indicatore, probabilità e impatto calcolati (moda,
/// a parità il più alto) con la correzione facoltativa motivata, livello dalla matrice.
Future<Map<String, dynamic>?> valutaRischio(BuildContext context, DatiAnticorruzione d, Map<String, dynamic> r,
    {Future<void> Function(Map<String, dynamic>)? salva}) async {
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
  final giudizio = TextEditingController(text: v['motivazione_valutazione'] as String? ?? '');
  String? errore;
  // parere dell'intelligenza artificiale, chiesto da chi valuta (dopo aver dato i suoi valori)
  Map<String, dynamic>? ia;
  String? erroreIa;
  var attesaIa = false;
  final puoChiedereIa = r['id'] != null || r['attivita_id'] != null;
  final api = apiDi(context);

  Future<void> chiediIa(void Function(void Function()) aggiorna) async {
    aggiorna(() => (attesaIa, erroreIa) = (true, null));
    try {
      final s = await api.post('$apiAnticorruzione/rischi/suggerimento', {
        'evento': r['evento'],
        'fattore_abilitante': fattore,
        'rischio_id': ?r['id'],
        'attivita_id': ?r['attivita_id'],
      }) as Map<String, dynamic>;
      aggiorna(() => (ia, attesaIa) = (s, false));
    } catch (e) {
      aggiorna(() => (erroreIa, attesaIa) = ('$e', false));
    }
  }

  /// Il valore dell'IA per l'indicatore, accanto a quello scelto (evidenziato se diverso).
  Widget valoreIa(BuildContext c, String id, String scelto) {
    final proposto = ((ia?['valori_probabilita'] as Map?)?[id] ?? (ia?['valori_impatto'] as Map?)?[id]) as String?;
    if (proposto == null) return const SizedBox.shrink();
    final diverso = proposto != scelto;
    final tema = Theme.of(c).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(left: 8),
      child: Tooltip(
        message: (ia?['motivazioni'] as Map?)?[id] as String? ?? '',
        child: Chip(
          visualDensity: VisualDensity.compact,
          avatar: Icon(Icons.auto_awesome, size: 14, color: diverso ? tema.onTertiaryContainer : null),
          backgroundColor: diverso ? tema.tertiaryContainer : null,
          label: Text('IA: $proposto'),
        ),
      ),
    );
  }

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
              Builder(builder: (c) => valoreIa(c, i['id'] as String, valori[i['id']]!)),
            ]),
          ),
      ]);

  var salvataggio = false;
  Map<String, dynamic> risultato() {
    final pCalc = d.moda(prob.values), iCalc = d.moda(imp.values);
    final corretta = (pCorr != null && pCorr != pCalc) || (iCorr != null && iCorr != iCalc);
    return {
      'valori_probabilita': prob,
      'valori_impatto': imp,
      'probabilita': corretta ? (pCorr ?? pCalc) : null,
      'impatto': corretta ? (iCorr ?? iCalc) : null,
      'motivazione_correzione': corretta ? motivazione.text.trim() : null,
      'fattore_abilitante': fattore ?? '',
      'motivazione_valutazione': giudizio.text.trim().isEmpty ? null : giudizio.text.trim(),
      // per mostrare subito l'esito nelle proposte (il server lo ricalcola)
      'probabilita_calcolata': pCalc,
      'impatto_calcolato': iCalc,
      'livello': d.livelloDa(corretta ? (pCorr ?? pCalc) : pCalc, corretta ? (iCorr ?? iCalc) : iCalc),
    };
  }

  final ok = await showDialog<bool>(
    context: context,
    // il campo si libera quando la finestra è sparita (l'animazione di chiusura lo usa ancora)
    builder: (c) => LiberaAllaFine([motivazione, giudizio], child: StatefulBuilder(builder: (c, aggiorna) {
      final pCalc = d.moda(prob.values), iCalc = d.moda(imp.values);
      final p = pCorr ?? pCalc, i = iCorr ?? iCalc;
      return AlertDialog(
        title: Text('Valutazione del rischio ${r['codice'] ?? ''}'),
        content: SizedBox(
          width: 720,
          child: SingleChildScrollView(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(r['evento'] as String? ?? ''),
              if (puoChiedereIa) _pannelloIa(c, d, ia, erroreIa, attesaIa,
                  chiedi: () => chiediIa(aggiorna),
                  usaValori: () => aggiorna(() {
                        prob.addAll((ia!['valori_probabilita'] as Map).cast<String, String>());
                        imp.addAll((ia!['valori_impatto'] as Map).cast<String, String>());
                        pCorr = iCorr = null;
                      }),
                  usaGiudizio: () => aggiorna(() => giudizio.text = ia!['motivazione_valutazione'] as String? ?? ''),
                  diversi: [
                    for (final e in [...prob.entries, ...imp.entries])
                      if (((ia?['valori_probabilita'] as Map?)?[e.key] ?? (ia?['valori_impatto'] as Map?)?[e.key]) case final x? when x != e.value) e.key,
                  ].length),
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
              TextField(
                controller: giudizio,
                minLines: 2,
                maxLines: 6,
                decoration: const InputDecoration(
                  labelText: 'Motivazione della valutazione',
                  helperText: 'Giudizio sintetico motivato (facoltativo), riportato nel PTPCT',
                ),
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
          TextButton(onPressed: salvataggio ? null : () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(
            onPressed: salvataggio
                ? null
                : () async {
                    if ((pCorr != null && pCorr != pCalc || iCorr != null && iCorr != iCalc) && motivazione.text.trim().isEmpty) {
                      aggiorna(() => errore = 'Per correggere probabilità o impatto serve la motivazione');
                      return;
                    }
                    if (salva != null) {
                      aggiorna(() => (errore, salvataggio) = (null, true));
                      try {
                        await salva(risultato());
                      } catch (e) {
                        if (c.mounted) aggiorna(() => (errore, salvataggio) = ('$e', false));
                        return;
                      }
                    }
                    if (c.mounted) Navigator.pop(c, true);
                  },
            child: const Text('Salva'),
          ),
        ],
      );
    })),
  );
  return ok == true ? risultato() : null;
}

/// Il parere dell'IA nella finestra di valutazione: prima il pulsante (chi valuta esprime
/// prima i suoi valori), poi il risultato proposto, quanti indicatori sono diversi e i pulsanti
/// per adottare i valori o il giudizio. Nulla si salva senza "Salva".
Widget _pannelloIa(BuildContext c, DatiAnticorruzione d, Map<String, dynamic>? ia, String? errore, bool attesa,
    {required VoidCallback chiedi, required VoidCallback usaValori, required VoidCallback usaGiudizio, required int diversi}) {
  final tema = Theme.of(c);
  return Container(
    margin: const EdgeInsets.only(top: 8),
    padding: const EdgeInsets.all(8),
    decoration: BoxDecoration(color: tema.colorScheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Icon(Icons.auto_awesome, size: 18, color: tema.colorScheme.primary),
        const SizedBox(width: 8),
        Expanded(
          child: Text(ia == null
              ? 'Dai prima i tuoi valori, poi puoi confrontarli con quelli proposti dall\'intelligenza artificiale.'
              : 'Proposta dell\'IA: probabilità ${ia['probabilita']}, impatto ${ia['impatto']}, ${ia['livello']}. '
                  '${diversi == 0 ? 'Gli indicatori coincidono con i tuoi.' : 'Indicatori diversi dai tuoi: $diversi (evidenziati; la motivazione è nel suggerimento).'}'),
        ),
        if (attesa)
          const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
        else if (ia == null)
          TextButton(onPressed: chiedi, child: const Text('Parere dell\'IA')),
      ]),
      if (errore != null) Text(errore, style: TextStyle(color: tema.colorScheme.error)),
      if (ia != null)
        Wrap(spacing: 8, children: [
          if (diversi > 0) TextButton(onPressed: usaValori, child: const Text('Usa i valori dell\'IA')),
          if ((ia['motivazione_valutazione'] as String?)?.isNotEmpty ?? false)
            TextButton(onPressed: usaGiudizio, child: const Text('Usa il giudizio dell\'IA')),
          TextButton(onPressed: chiedi, child: const Text('Chiedi di nuovo')),
        ]),
      if (ia != null)
        Text('È una proposta: controlla i valori e il giudizio prima di salvare.', style: tema.textTheme.bodySmall),
    ]),
  );
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
            subtitle: Text([
              if (a['procedimento'] != null)
                'Procedimento ${(a['procedimento'] as Map)['codice']} - ${(a['procedimento'] as Map)['denominazione']}'
                    '${a['procedimento_adattato'] != null ? ' (adattato)' : ''}',
              ?voceRitoccata(a, a['descrizione'] as String?),
              '${_lista(a['rischi']).length} rischi',
              ?dati.coinvolte(a['coinvolte']),
              ?a['strutture_coinvolte'] as String?,
            ].join(' · ')),
            trailing: ops == null
                ? null
                : Wrap(children: [
                    IconaAzione(Icons.edit_outlined, etichettaAzione(ops, 'Modifica l\'attività'), () => eseguiOperazione(context, onCambiato, () async {
                          await modificaAttivita(context, dati, a: a, salva: (v) => ops.modificaAttivita(a, v));
                        })),
                    IconaAzione(Icons.add_alert_outlined, etichettaAzione(ops, 'Aggiungi un rischio'), () => eseguiOperazione(context, onCambiato, () async {
                          await modificaRischio(context, dati, salva: (v) => ops.aggiungiRischio(a, v));
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
              await modificaAttivita(context, dati, salva: (v) => ops.aggiungiAttivita(v));
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
        if (voceRitoccata(r, r['evento'] as String?) case final voce?)
          Text(voce, style: TextStyle(color: colori.onSurfaceVariant, fontStyle: FontStyle.italic)),
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
                await valutaRischio(context, dati, r, salva: (v) => ops.valuta(r, v));
              }),
            ),
            TextButton.icon(
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: Text(etichettaAzione(ops, 'Modifica')),
              onPressed: () => esegui(() async {
                await modificaRischio(context, dati, r: r, salva: (v) => ops.modificaRischio(r, v));
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
                await modificaMisura(context, dati, salva: (v) => ops.aggiungiMisura(r, v));
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
              ?voceRitoccata(m, m['descrizione'] as String?),
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
                          await modificaMisura(context, dati, m: m, salva: (v) => ops.modificaMisura(m, v));
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

/// Intestazione del processo: area, struttura, strutture coinvolte, descrizione, tempi e
/// attori esterni.
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
      ('Strutture coinvolte', dati.coinvolte(processo['coinvolte'])),
      ('Descrizione', processo['descrizione']),
      ('Tempi', processo['tempi']),
      ('Attori esterni', processo['attori_esterni']),
    ];
    return Sezione(
      titolo: 'Processo ${processo['codice'] ?? '(nuovo)'} - ${processo['denominazione'] ?? ''}',
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
      if (valutazione['motivazione_valutazione'] != null)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('Motivazione: ${valutazione['motivazione_valutazione']}'),
        ),
    ]);
  }
}

/// Obiettivi della performance collegati al processo: hanno come radici le voci delle sue
/// attività o delle sue misure. Sola lettura; niente se non ce ne sono.
class ObiettiviPerformance extends StatelessWidget {
  const ObiettiviPerformance({super.key, required this.dati, required this.obiettivi});

  final DatiAnticorruzione dati;
  final List<Map<String, dynamic>> obiettivi;

  static String _codici(List voci) => [for (final v in voci) (v as Map)['codice'] ?? '?'].join(', ');

  @override
  Widget build(BuildContext context) {
    if (obiettivi.isEmpty) return const SizedBox.shrink();
    final piccolo = Theme.of(context).textTheme.bodySmall;
    return Sezione(
      titolo: 'Obiettivi di performance',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final o in obiettivi)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.flag_outlined),
            title: Text(o['codice'] == null ? '${o['titolo']}' : '${o['codice']} - ${o['titolo']}'),
            subtitle: Text([
              '${o['piao']} · anno ${o['anno']}',
              dati.struttura(o['struttura_id']) ?? '',
              if ((o['azioni'] as List).isNotEmpty) 'azioni: ${_codici(o['azioni'] as List)}',
              if ((o['misure'] as List).isNotEmpty) 'misure: ${_codici(o['misure'] as List)}',
              if (o['completamento'] != null) 'completato al ${(o['completamento'] as num).round()}%',
            ].where((t) => t.isNotEmpty).join(' · ')),
          ),
        Text('Azioni e misure degli obiettivi vengono dalle voci del catalogo: si gestiscono nel modulo Performance.', style: piccolo),
      ]),
    );
  }
}
