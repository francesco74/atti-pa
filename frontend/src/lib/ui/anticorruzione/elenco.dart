import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../admin/strutture.dart' show alberoStrutture, etichettaStruttura;
import '../comuni.dart';
import '../ricerca.dart';
import '../trasparenza/browser.dart' show scaricaBytes;
import 'albero.dart' show etichettaTipo;
import 'art35.dart' show CompletezzaArt35, SezioneArt35;
import 'comune.dart';
import 'mappatura.dart' show VistaProcesso;

/// Livelli della mappatura che l'elenco mostra, uno alla volta.
const livelliElenco = {
  'AREA': 'Aree',
  'PROCESSO': 'Processi e procedimenti',
  'ATTIVITA': 'Attività',
  'RISCHIO': 'Rischi',
  'MISURA': 'Misure',
};

/// Filtri sulle lacune della mappatura, per livello.
const _lacune = {
  'AREA': {'SENZA_PROCESSI': 'Senza processi'},
  'PROCESSO': {
    'SENZA_ATTIVITA': 'Senza attività',
    'SENZA_RISCHI': 'Senza rischi',
    'SENZA_MISURE': 'Senza misure',
    'ART35_INCOMPLETI': 'Procedimenti con dati art. 35 mancanti',
  },
  'ATTIVITA': {'SENZA_RISCHI': 'Senza rischi', 'SENZA_MISURE': 'Senza misure'},
  'RISCHIO': {'SENZA_MISURE': 'Senza misure', 'NON_VALUTATI': 'Non valutati'},
  'MISURA': {'SENZA_STRUTTURA': 'Senza struttura responsabile', 'SENZA_INDICATORE': 'Senza indicatore'},
};

/// Area dei processi senza un'area di rischio, nel filtro.
const _senzaArea = '';

/// Confronto "naturale" dei codici: A.2 prima di A.10.
int confrontaCodici(String a, String b) {
  final re = RegExp(r'(\d+)|(\D+)');
  final pa = re.allMatches(a).map((m) => m.group(0)!).toList();
  final pb = re.allMatches(b).map((m) => m.group(0)!).toList();
  for (var i = 0; i < pa.length && i < pb.length; i++) {
    final na = int.tryParse(pa[i]), nb = int.tryParse(pb[i]);
    final c = na != null && nb != null ? na.compareTo(nb) : pa[i].toLowerCase().compareTo(pb[i].toLowerCase());
    if (c != 0) return c;
  }
  return pa.length.compareTo(pb.length);
}

/// Tutta la mappatura dell'ente (GET /anticorruzione/elenco) con i collegamenti tra i livelli.
class MappaturaPiatta {
  MappaturaPiatta(Map<String, dynamic> json)
      : aree = _lista(json['aree']),
        processi = _lista(json['processi']),
        attivita = _lista(json['attivita']),
        rischi = _lista(json['rischi']),
        misure = _lista(json['misure']) {
    for (final (livello, elenco) in [
      ('AREA', aree), ('PROCESSO', processi), ('ATTIVITA', attivita), ('RISCHIO', rischi), ('MISURA', misure),
    ]) {
      for (final x in elenco) {
        perId[x['id'] as String] = x;
        livelloDi[x['id'] as String] = livello;
      }
    }
    for (final p in processi) {
      processiDi.putIfAbsent(p['area_id'] as String? ?? _senzaArea, () => []).add(p);
    }
    for (final a in attivita) {
      figli.putIfAbsent(a['processo_id'] as String, () => []).add(a);
    }
    for (final r in rischi) {
      figli.putIfAbsent(r['attivita_id'] as String, () => []).add(r);
    }
    for (final m in misure) {
      figli.putIfAbsent(m['rischio_id'] as String, () => []).add(m);
    }
  }

  static List<Map<String, dynamic>> _lista(Object? v) => (v as List? ?? const []).cast<Map<String, dynamic>>();

  final List<Map<String, dynamic>> aree, processi, attivita, rischi, misure;
  final perId = <String, Map<String, dynamic>>{};
  final livelloDi = <String, String>{};
  final processiDi = <String, List<Map<String, dynamic>>>{}; // per area ('' senza area)
  final figli = <String, List<Map<String, dynamic>>>{}; // processo -> attività -> rischi -> misure

  List<Map<String, dynamic>> figliDi(Object? id) => figli[id] ?? const [];

  List<Map<String, dynamic>> elenco(String livello) => switch (livello) {
        'AREA' => aree,
        'PROCESSO' => processi,
        'ATTIVITA' => attivita,
        'RISCHIO' => rischi,
        _ => misure,
      };

  /// Percorso dell'elemento: area, processo, attività, rischio (quelli che ci sono sopra).
  ({Map<String, dynamic>? area, Map<String, dynamic>? processo, Map<String, dynamic>? attivita, Map<String, dynamic>? rischio})
      percorso(String livello, Map<String, dynamic> x) {
    final rischio = livello == 'MISURA' ? perId[x['rischio_id']] : (livello == 'RISCHIO' ? x : null);
    final attivita = livello == 'ATTIVITA' ? x : (rischio == null ? null : perId[rischio['attivita_id']]);
    final processo = livello == 'PROCESSO' ? x : (attivita == null ? null : perId[attivita['processo_id']]);
    final area = livello == 'AREA' ? x : (processo == null ? null : perId[processo['area_id']]);
    return (
      area: area,
      processo: livello == 'PROCESSO' ? null : processo,
      attivita: livello == 'ATTIVITA' ? null : attivita,
      rischio: livello == 'RISCHIO' ? null : rischio,
    );
  }

  Map<String, dynamic>? processoDi(String livello, Map<String, dynamic> x) =>
      livello == 'PROCESSO' ? x : percorso(livello, x).processo;

  /// Rischi sotto l'elemento (per il livello più alto e i conteggi).
  List<Map<String, dynamic>> rischiSotto(String livello, Map<String, dynamic> x) => switch (livello) {
        'AREA' => [for (final p in processiDi[x['id']] ?? const <Map<String, dynamic>>[]) ...rischiSotto('PROCESSO', p)],
        'PROCESSO' => [for (final a in figliDi(x['id'])) ...figliDi(a['id'])],
        'ATTIVITA' => figliDi(x['id']),
        'RISCHIO' => [x],
        _ => [?perId[x['rischio_id']]],
      };

  List<Map<String, dynamic>> misureSotto(String livello, Map<String, dynamic> x) =>
      livello == 'MISURA' ? [x] : [for (final r in rischiSotto(livello, x)) ...figliDi(r['id'])];

  /// Struttura responsabile dell'elemento: quella del processo (attività e rischi la prendono
  /// dal processo); per la misura la sua o, se manca, quella del processo. null: trasversale.
  ({String? id, bool ereditata}) struttura(String livello, Map<String, dynamic> x) {
    final processo = processoDi(livello, x);
    if (livello == 'MISURA' && x['struttura_id'] != null) return (id: x['struttura_id'] as String, ereditata: false);
    return (id: processo?['struttura_id'] as String?, ereditata: livello != 'PROCESSO' && processo?['struttura_id'] != null);
  }
}

/// Elenco piatto della mappatura: un livello alla volta (aree, processi e procedimenti,
/// attività, rischi, misure) con il percorso nelle prime colonne, la ricerca in linguaggio
/// naturale e i filtri (area, struttura con le sottostrutture, tipo, livello di rischio,
/// misure, lacune). Si ordina per colonna, si esporta in Excel; una riga apre la scheda
/// dell'elemento.
class ElencoTab extends StatefulWidget {
  const ElencoTab({super.key});

  @override
  State<ElencoTab> createState() => _ElencoTabState();
}

class _ElencoTabState extends State<ElencoTab> with AutomaticKeepAliveClientMixin {
  late Future<MappaturaPiatta> _mappatura;
  String _livello = 'PROCESSO';
  String? _area, _struttura, _tipo, _rischio, _tipoMisura, _categoria, _lacuna;
  bool _sottostrutture = true, _trasversali = false;
  int? _colonna; // ordinamento scelto (null: per codice, o per pertinenza mentre si cerca)
  bool _crescente = true;
  int _righePerPagina = 25;
  final _testo = TextEditingController();
  late final _registro = RegistroRicerche(apiDi(context).post, '/api/v1/ricerche', 'ELENCO');
  late final _ricerca = RicercaTesto(
    (t) => apiDi(context).get('$apiAnticorruzione/elenco/ricerca', query: {'testo': t, 'livello': _livello}),
    setState,
    registro: _registro,
  );

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _testo.dispose();
    _ricerca.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
        _mappatura = apiDi(context).get('$apiAnticorruzione/elenco').then((v) => MappaturaPiatta(v as Map<String, dynamic>));
      });

  void _cambiaLivello(String livello) {
    setState(() {
      _livello = livello;
      _colonna = null;
      if (!(_lacune[livello]?.containsKey(_lacuna) ?? false)) _lacuna = null;
    });
    _ricerca.rilancia();
  }

  void _azzera() {
    _testo.clear();
    _ricerca.cambia('');
    setState(() {
      _area = _struttura = _tipo = _rischio = _tipoMisura = _categoria = _lacuna = null;
      _sottostrutture = true;
      _trasversali = false;
      _colonna = null;
    });
  }

  bool get _filtriAttivi =>
      _testo.text.isNotEmpty ||
      [_area, _struttura, _tipo, _rischio, _tipoMisura, _categoria, _lacuna].any((v) => v != null) ||
      _trasversali;

  /// Strutture che soddisfano il filtro: la scelta e, se richiesto, le sottostanti.
  Set<String>? _struttureScelte(DatiAnticorruzione dati) {
    final scelta = _struttura;
    if (scelta == null) return null;
    final risultato = {scelta};
    if (_sottostrutture) {
      var cresciuto = true;
      while (cresciuto) {
        cresciuto = false;
        for (final s in dati.strutture) {
          if (risultato.contains(s['padre_id']) && risultato.add(s['id'] as String)) cresciuto = true;
        }
      }
    }
    return risultato;
  }

  /// Livello di rischio dell'elemento: il suo (rischio), quello del rischio (misura), il più
  /// alto tra quelli sotto (area, processo, attività).
  String? _livelloRischio(DatiAnticorruzione dati, MappaturaPiatta m, Map<String, dynamic> x) {
    String? massimo;
    for (final r in m.rischiSotto(_livello, x)) {
      final l = r['livello'] as String?;
      if (l != null && (massimo == null || dati.livelli.indexOf(l) > dati.livelli.indexOf(massimo))) massimo = l;
    }
    return massimo;
  }

  bool _passaFiltri(DatiAnticorruzione dati, MappaturaPiatta m, Map<String, dynamic> x, Set<String>? strutture) {
    final processo = m.processoDi(_livello, x);
    if (_area != null) {
      final area = _livello == 'AREA' ? x['id'] : (processo?['area_id'] ?? _senzaArea);
      if (area != _area) return false;
    }
    if (_tipo != null && _livello != 'AREA' && processo?['tipo'] != _tipo) return false;
    if (strutture != null) {
      bool ok(String? id) => id == null ? _trasversali : strutture.contains(id);
      if (_livello == 'AREA') {
        if (!(m.processiDi[x['id']] ?? const []).any((p) => ok(p['struttura_id'] as String?))) return false;
      } else if (!ok(m.struttura(_livello, x).id)) {
        return false;
      }
    }
    if (_rischio != null && _livelloRischio(dati, m, x) != _rischio) return false;
    if (_livello == 'MISURA') {
      if (_tipoMisura != null && x['tipo'] != _tipoMisura) return false;
      if (_categoria != null && x['categoria'] != _categoria) return false;
    }
    return switch (_lacuna) {
      'SENZA_PROCESSI' => (m.processiDi[x['id']] ?? const []).isEmpty,
      'SENZA_ATTIVITA' => m.figliDi(x['id']).isEmpty,
      'SENZA_RISCHI' => m.rischiSotto(_livello, x).isEmpty,
      'SENZA_MISURE' => m.misureSotto(_livello, x).isEmpty,
      'NON_VALUTATI' => x['livello'] == null,
      'SENZA_STRUTTURA' => m.struttura(_livello, x).id == null,
      'SENZA_INDICATORE' => (x['indicatore'] as String? ?? '').trim().isEmpty,
      'ART35_INCOMPLETI' => x['tipo'] == 'PROCEDIMENTO' && (x['art35_mancanti'] as List? ?? const []).isNotEmpty,
      _ => true,
    };
  }

  /// Testo per il filtro locale mentre la ricerca del server non ha risposto: codice e
  /// descrizione dell'elemento e del suo percorso.
  String _testoLocale(MappaturaPiatta m, Map<String, dynamic> x) {
    final p = m.percorso(_livello, x);
    return [x, p.area, p.processo, p.attivita, p.rischio]
        .whereType<Map<String, dynamic>>()
        .map((e) => '${e['codice']} ${_titolo(e)}')
        .join(' ');
  }

  List<_Colonna> _colonne(DatiAnticorruzione dati, MappaturaPiatta m) {
    String codice(Map<String, dynamic>? e) => e == null ? '' : '${e['codice']}';
    String testo(Map<String, dynamic>? e) => e == null ? '' : _titolo(e);
    String struttura(Map<String, dynamic> x) {
      final s = m.struttura(_livello, x);
      if (s.id == null) return 'Trasversale';
      final nome = dati.struttura(s.id) ?? '—';
      return s.ereditata && _livello == 'MISURA' ? '$nome (dal processo)' : nome;
    }

    final livello = _Colonna('Livello', (x) => _livelloRischio(dati, m, x) ?? '',
        ordine: (x) => dati.livelli.indexOf(_livelloRischio(dati, m, x) ?? ''),
        cella: (x) => LivelloChip(dati, _livelloRischio(dati, m, x)));
    final area = _Colonna('Area', (x) => codice(m.percorso(_livello, x).area), ordine: (x) => codice(m.percorso(_livello, x).area));
    final processo = _Colonna('Processo', (x) {
      final p = m.percorso(_livello, x).processo;
      return p == null ? '' : '${p['codice']} - ${p['denominazione']}';
    }, largo: true, ordine: (x) => codice(m.percorso(_livello, x).processo));
    final attivita = _Colonna('Attività', (x) {
      final a = m.percorso(_livello, x).attivita;
      return a == null ? '' : '${a['codice']} - ${a['descrizione']}';
    }, largo: true, ordine: (x) => codice(m.percorso(_livello, x).attivita));
    int quanti(List l) => l.length;
    return switch (_livello) {
      'AREA' => [
          _Colonna('Codice', codice, ordine: codice),
          _Colonna('Area di rischio', testo, largo: true),
          _Colonna('Processi', (x) => quanti(m.processiDi[x['id']] ?? const []), numerica: true),
          _Colonna('Rischi', (x) => quanti(m.rischiSotto('AREA', x)), numerica: true),
          _Colonna('Misure', (x) => quanti(m.misureSotto('AREA', x)), numerica: true),
          livello,
        ],
      'PROCESSO' => [
          area,
          _Colonna('Codice', codice, ordine: codice),
          _Colonna('Processo o procedimento', testo, largo: true),
          _Colonna('Tipo', (x) => etichettaTipo(x['tipo'])),
          _Colonna('Struttura', struttura),
          _Colonna('Attività', (x) => quanti(m.figliDi(x['id'])), numerica: true),
          _Colonna('Rischi', (x) => quanti(m.rischiSotto('PROCESSO', x)), numerica: true),
          _Colonna('Misure', (x) => quanti(m.misureSotto('PROCESSO', x)), numerica: true),
          livello,
          _Colonna('Art. 35', (x) {
            final mancanti = x['art35_mancanti'] as List?;
            if (x['tipo'] != 'PROCEDIMENTO' || mancanti == null) return '';
            return mancanti.isEmpty ? 'Completo' : 'Mancano ${mancanti.length}';
          }, ordine: (x) => (x['art35_mancanti'] as List?)?.length ?? -1, cella: (x) {
            final mancanti = x['art35_mancanti'] as List?;
            return x['tipo'] != 'PROCEDIMENTO' || mancanti == null ? const SizedBox.shrink() : CompletezzaArt35(mancanti.length);
          }),
        ],
      'ATTIVITA' => [
          area,
          processo,
          _Colonna('Codice', codice, ordine: codice),
          _Colonna('Attività', testo, largo: true),
          _Colonna('Struttura', struttura),
          _Colonna('Rischi', (x) => quanti(m.figliDi(x['id'])), numerica: true),
          _Colonna('Misure', (x) => quanti(m.misureSotto('ATTIVITA', x)), numerica: true),
          livello,
        ],
      'RISCHIO' => [
          area,
          processo,
          attivita,
          _Colonna('Codice', codice, ordine: codice),
          _Colonna('Evento rischioso', testo, largo: true),
          livello,
          _Colonna('Misure', (x) => quanti(m.figliDi(x['id'])), numerica: true),
        ],
      _ => [
          processo,
          _Colonna('Rischio', (x) {
            final r = m.percorso(_livello, x).rischio;
            return r == null ? '' : '${r['codice']} - ${r['evento']}';
          }, largo: true, ordine: (x) => codice(m.percorso(_livello, x).rischio)),
          livello,
          _Colonna('Codice', codice, ordine: codice),
          _Colonna('Misura', testo, largo: true),
          _Colonna('Tipo', (x) => x['tipo'] == 'GENERALE' ? 'Generale' : 'Specifica'),
          _Colonna('Categoria', (x) => '${x['categoria'] ?? ''}'),
          _Colonna('Struttura', struttura),
        ],
    };
  }

  Future<void> _esporta(List<_Colonna> colonne, List<Map<String, dynamic>> righe) async {
    try {
      final bytes = await apiDi(context).postBytes('$apiAnticorruzione/elenco/esporta', {
        'titolo': livelliElenco[_livello],
        'intestazioni': [for (final c in colonne) c.titolo],
        'righe': [
          for (final x in righe) [for (final c in colonne) c.valore(x)],
        ],
      });
      scaricaBytes(bytes, 'elenco_${livelliElenco[_livello]!.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '_')}.xlsx');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _apri(MappaturaPiatta m, Map<String, dynamic> x) async {
    _ricerca.aperto(x['id'] as String);
    await apriSchedaElemento(context, m, x);
    if (mounted) _carica(); // dalla scheda si può andare nella mappatura e modificare
  }

  Widget _menu<T>(String etichetta, T? valore, Map<T, String> voci, ValueChanged<T?> onChanged, {double larghezza = 200}) => SizedBox(
        width: larghezza,
        child: DropdownButtonFormField<T?>(
          key: ValueKey('$etichetta-$_livello-$valore'),
          initialValue: valore,
          isExpanded: true,
          decoration: InputDecoration(labelText: etichetta, isDense: true),
          items: [
            DropdownMenuItem<T?>(value: null, child: const Text('Tutti')),
            for (final e in voci.entries) DropdownMenuItem<T?>(value: e.key, child: Text(e.value, overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (v) => setState(() => onChanged(v)),
        ),
      );

  Widget _filtri(DatiAnticorruzione dati, MappaturaPiatta m) {
    final strutture = alberoStrutture(dati.strutture);
    final categorie = {for (final x in m.misure) if (x['categoria'] != null) x['categoria'] as String: x['categoria'] as String};
    return Wrap(spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
      SizedBox(
        width: 360,
        child: TextField(
          controller: _testo,
          decoration: InputDecoration(
            labelText: 'Cerca in ${livelliElenco[_livello]!.toLowerCase()}',
            hintText: 'Codice, parole o una domanda',
            isDense: true,
            prefixIcon: const Icon(Icons.search),
          ),
          onChanged: (t) {
            _colonna = null; // si ordina per pertinenza
            _ricerca.cambia(t);
          },
        ),
      ),
      _menu<String>('Area', _area, {for (final a in dati.aree) a['id'] as String: dati.area(a['id'])!, _senzaArea: 'Senza area'},
          (v) => _area = v, larghezza: 260),
      SizedBox(
        width: 300,
        child: DropdownButtonFormField<String?>(
          key: ValueKey('struttura-$_struttura'),
          initialValue: _struttura,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Struttura organizzativa', isDense: true),
          items: [
            const DropdownMenuItem(value: null, child: Text('Tutte')),
            for (final (s, profondita) in strutture)
              DropdownMenuItem(
                value: s['id'] as String,
                child: Padding(
                  padding: EdgeInsets.only(left: 16.0 * profondita),
                  child: Text(etichettaStruttura(s), overflow: TextOverflow.ellipsis),
                ),
              ),
          ],
          onChanged: (v) => setState(() => _struttura = v),
        ),
      ),
      if (_struttura != null) ...[
        FilterChip(
          label: const Text('Comprese le sottostrutture'),
          selected: _sottostrutture,
          onSelected: (v) => setState(() => _sottostrutture = v),
        ),
        FilterChip(
          label: const Text('Comprese le trasversali'),
          tooltip: 'Processi e misure senza struttura responsabile, che riguardano tutte le strutture',
          selected: _trasversali,
          onSelected: (v) => setState(() => _trasversali = v),
        ),
      ],
      if (_livello != 'AREA')
        _menu<String>('Tipo', _tipo, const {'PROCESSO': 'Processi', 'PROCEDIMENTO': 'Procedimenti'}, (v) => _tipo = v, larghezza: 170),
      _menu<String>(_livello == 'RISCHIO' || _livello == 'MISURA' ? 'Livello di rischio' : 'Livello più alto', _rischio,
          {for (final l in dati.livelli.reversed) l: l}, (v) => _rischio = v),
      if (_livello == 'MISURA') ...[
        _menu<String>('Tipo di misura', _tipoMisura, const {'GENERALE': 'Generale', 'SPECIFICA': 'Specifica'}, (v) => _tipoMisura = v,
            larghezza: 170),
        _menu<String>('Categoria', _categoria, categorie, (v) => _categoria = v, larghezza: 260),
      ],
      _menu<String>('Mostra solo', _lacuna, _lacune[_livello]!, (v) => _lacuna = v, larghezza: 240),
      if (_filtriAttivi) TextButton.icon(onPressed: _azzera, icon: const Icon(Icons.filter_alt_off_outlined), label: const Text('Azzera i filtri')),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final dati = context.watch<DatiAnticorruzione>();
    return Caricamento<MappaturaPiatta>(
      future: _mappatura,
      riprova: _carica,
      builder: (context, m) {
        final tutti = m.elenco(_livello);
        final strutture = _struttureScelte(dati);
        var righe = [for (final x in tutti) if (_passaFiltri(dati, m, x, strutture)) x];
        final colonne = _colonne(dati, m);
        if (_ricerca.testo.isNotEmpty) righe = _ricerca.filtra(righe, testoLocale: (x) => _testoLocale(m, x));
        if (_colonna != null) {
          final c = colonne[_colonna!];
          righe.sort((a, b) {
            final va = c.chiave(a), vb = c.chiave(b);
            final r = va is num && vb is num ? va.compareTo(vb) : confrontaCodici('$va', '$vb');
            return _crescente ? r : -r;
          });
        }
        final nome = livelliElenco[_livello]!.toLowerCase();
        return ListView(padding: const EdgeInsets.all(16), children: [
          SegmentedButton<String>(
            segments: [for (final e in livelliElenco.entries) ButtonSegment(value: e.key, label: Text(e.value))],
            selected: {_livello},
            showSelectedIcon: false,
            onSelectionChanged: (s) => _cambiaLivello(s.first),
          ),
          const SizedBox(height: 16),
          _filtri(dati, m),
          NotaRicerca(_ricerca, risultati: righe.length),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: Semantics(
                liveRegion: true,
                child: Text(righe.length == tutti.length ? '${tutti.length} $nome' : '${righe.length} $nome su ${tutti.length}',
                    style: Theme.of(context).textTheme.titleSmall),
              ),
            ),
            OutlinedButton.icon(
              onPressed: righe.isEmpty ? null : () => _esporta(colonne, righe),
              icon: const Icon(Icons.table_view_outlined),
              label: const Text('Esporta in Excel'),
            ),
          ]),
          const SizedBox(height: 8),
          if (righe.isEmpty)
            Padding(
              padding: const EdgeInsets.all(24),
              child: Center(child: Text(_ricerca.inCorso ? '' : (tutti.isEmpty ? 'La mappatura è vuota.' : 'Nessun elemento con questi filtri.'))),
            )
          else
            PaginatedDataTable(
              key: ValueKey('$_livello-${righe.length}-$_righePerPagina'),
              columns: [
                for (final (i, c) in colonne.indexed)
                  DataColumn(
                    label: Text(c.titolo),
                    numeric: c.numerica,
                    onSort: (_, _) => setState(() {
                      _crescente = _colonna == i ? !_crescente : true;
                      _colonna = i;
                    }),
                  ),
              ],
              sortColumnIndex: _colonna,
              sortAscending: _crescente,
              source: _Righe(righe, colonne, (x) => _apri(m, x)),
              // se le righe stanno in una pagina la tabella è alta quanto loro (niente righe
              // vuote in fondo) e la scelta delle righe per pagina non serve
              rowsPerPage: righe.length < _righePerPagina ? righe.length : _righePerPagina,
              availableRowsPerPage: const [25, 50, 100],
              onRowsPerPageChanged: righe.length < _righePerPagina
                  ? null
                  : (n) => setState(() => _righePerPagina = n ?? _righePerPagina),
              showCheckboxColumn: false,
              dataRowMinHeight: 48,
              dataRowMaxHeight: 72,
              columnSpacing: 24,
              showFirstLastButtons: true,
            ),
          FeedbackRicerca(_ricerca),
        ]);
      },
    );
  }
}

String _titolo(Map<String, dynamic> e) => '${e['denominazione'] ?? e['evento'] ?? e['descrizione'] ?? ''}';

/// Colonna dell'elenco: valore (anche per l'Excel), chiave di ordinamento, cella.
class _Colonna {
  _Colonna(this.titolo, this.valore, {this.numerica = false, this.largo = false, Object? Function(Map<String, dynamic>)? ordine, this.cella})
      : _ordine = ordine;

  final String titolo;
  final Object? Function(Map<String, dynamic>) valore;
  final bool numerica, largo;
  final Object? Function(Map<String, dynamic>)? _ordine;
  final Widget Function(Map<String, dynamic>)? cella;

  Object? chiave(Map<String, dynamic> x) => (_ordine ?? valore)(x);
}

class _Righe extends DataTableSource {
  _Righe(this.righe, this.colonne, this.apri);

  final List<Map<String, dynamic>> righe;
  final List<_Colonna> colonne;
  final ValueChanged<Map<String, dynamic>> apri;

  @override
  DataRow? getRow(int index) {
    if (index >= righe.length) return null;
    final x = righe[index];
    return DataRow.byIndex(
      index: index,
      onSelectChanged: (_) => apri(x),
      cells: [
        for (final c in colonne)
          DataCell(c.cella?.call(x) ??
              ConstrainedBox(
                constraints: BoxConstraints(maxWidth: c.largo ? 360 : 220),
                child: Text('${c.valore(x) ?? ''}', maxLines: 3, overflow: TextOverflow.ellipsis),
              )),
      ],
    );
  }

  @override
  bool get isRowCountApproximate => false;

  @override
  int get rowCount => righe.length;

  @override
  int get selectedRowCount => 0;
}

// --- scheda di un elemento ---------------------------------------------------------------------

const _nomiLivello = {'AREA': 'Area', 'PROCESSO': 'Processo', 'ATTIVITA': 'Attività', 'RISCHIO': 'Rischio', 'MISURA': 'Misura'};

IconData _icona(String livello, Map<String, dynamic> x) => switch (livello) {
      'AREA' => Icons.folder_outlined,
      'PROCESSO' => x['tipo'] == 'PROCEDIMENTO' ? Icons.gavel_outlined : Icons.account_tree_outlined,
      'ATTIVITA' => Icons.subdirectory_arrow_right,
      'RISCHIO' => Icons.warning_amber_outlined,
      _ => Icons.shield_outlined,
    };

/// Apre la scheda di un elemento della mappatura (dall'elenco o da un'altra scheda).
Future<void> apriSchedaElemento(BuildContext context, MappaturaPiatta m, Map<String, dynamic> x) {
  final dati = context.read<DatiAnticorruzione>();
  return Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => Provider<DatiAnticorruzione>.value(value: dati, child: SchedaElementoPage(mappatura: m, elemento: x)),
  ));
}

/// I dati di un elemento della mappatura in sola lettura: il percorso (cliccabile), tutti i
/// suoi campi e gli elementi sotto. "Apri nella mappatura" porta al processo (e all'attività)
/// per modificarlo o proporre modifiche.
class SchedaElementoPage extends StatelessWidget {
  const SchedaElementoPage({super.key, required this.mappatura, required this.elemento});

  final MappaturaPiatta mappatura;
  final Map<String, dynamic> elemento;

  List<(String, Object?)> _campi(DatiAnticorruzione dati, String livello) {
    final x = elemento, m = mappatura;
    String struttura() {
      final s = m.struttura(livello, x);
      if (s.id == null) return 'Tutte (trasversale)';
      final nome = dati.struttura(s.id) ?? '—';
      return s.ereditata ? '$nome (dal processo)' : nome;
    }

    String? obbligo(Object? id) {
      final o = dati.obblighi.where((o) => o['id'] == id).firstOrNull;
      return o == null ? id as String? : '${o['articolo']} - ${o['titolo']}';
    }

    return switch (livello) {
      'AREA' => [('Descrizione', x['descrizione']), ('Descrizione breve', x['descrizione_breve'])],
      'PROCESSO' => [
          ('Tipo', etichettaTipo(x['tipo'])),
          ('Denominazione', x['denominazione']),
          ('Struttura responsabile', struttura()),
          ('Descrizione', x['descrizione']),
          ('Tempi', x['tempi']),
          ('Attori esterni', x['attori_esterni']),
          if (x['tipo'] == 'PROCEDIMENTO') ...[
            ('Termine di conclusione', x['termine_conclusione']),
            ('Norma di riferimento', x['norma_riferimento']),
          ],
        ],
      'ATTIVITA' => [
          ('Descrizione', x['descrizione']),
          ('Strutture coinvolte', x['strutture_coinvolte']),
          ('Struttura responsabile', struttura()),
        ],
      'RISCHIO' => [
          ('Evento rischioso', x['evento']),
          ('Fattore abilitante', x['fattore_abilitante']),
          ('Probabilità', x['probabilita'] == null
              ? null
              : x['probabilita_calcolata'] != null && x['probabilita_calcolata'] != x['probabilita']
                  ? '${x['probabilita']} (calcolata ${x['probabilita_calcolata']})'
                  : x['probabilita']),
          ('Impatto', x['impatto'] == null
              ? null
              : x['impatto_calcolato'] != null && x['impatto_calcolato'] != x['impatto']
                  ? '${x['impatto']} (calcolato ${x['impatto_calcolato']})'
                  : x['impatto']),
          ('Motivazione della correzione', x['motivazione_correzione']),
          ('Valutato il', x['valutato_il'] == null ? null : formatData(x['valutato_il'])),
        ],
      _ => [
          ('Descrizione', x['descrizione']),
          ('Tipo', x['tipo'] == 'GENERALE' ? 'Generale' : 'Specifica'),
          ('Categoria', x['categoria']),
          ('Struttura responsabile', struttura()),
          ('Obbligo di trasparenza', obbligo(x['obbligo_trasparenza'])),
          ('Fasi di attuazione', x['fasi']),
          ('Tempi', x['tempi']),
          ('Indicatore', x['indicatore']),
          ('Target', x['target']),
        ],
    };
  }

  /// Elementi del livello sotto (con il titolo della sezione).
  (String, String, List<Map<String, dynamic>>)? _sotto(String livello) => switch (livello) {
        'AREA' => ('Processi e procedimenti', 'PROCESSO', mappatura.processiDi[elemento['id']] ?? const []),
        'PROCESSO' => ('Attività', 'ATTIVITA', mappatura.figliDi(elemento['id'])),
        'ATTIVITA' => ('Rischi', 'RISCHIO', mappatura.figliDi(elemento['id'])),
        'RISCHIO' => ('Misure', 'MISURA', mappatura.figliDi(elemento['id'])),
        _ => null,
      };

  Future<void> _apriMappatura(BuildContext context, String livello) async {
    final p = mappatura.percorso(livello, elemento);
    final processo = livello == 'PROCESSO' ? elemento : p.processo;
    if (processo == null) return;
    final attivita = livello == 'ATTIVITA' ? elemento : p.attivita;
    final dati = context.read<DatiAnticorruzione>();
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (c) => Provider<DatiAnticorruzione>.value(
        value: dati,
        child: Scaffold(
          appBar: AppBar(title: const Text('Mappatura')),
          body: VistaProcesso(
            processoId: processo['id'] as String,
            attivitaIniziale: attivita?['id'] as String?,
            onAree: () => Navigator.of(c).pop(),
            onArea: (_) => Navigator.of(c).pop(),
            onChiuso: () => Navigator.of(c).pop(),
          ),
        ),
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    final livello = mappatura.livelloDi[elemento['id']] ?? 'PROCESSO';
    final p = mappatura.percorso(livello, elemento);
    final sotto = _sotto(livello);
    final rischio = livello == 'RISCHIO' ? elemento['livello'] as String? : null;
    final titolo = '${_nomiLivello[livello]} ${elemento['codice']}';
    void apri(Map<String, dynamic> e) => apriSchedaElemento(context, mappatura, e);
    return Scaffold(
      appBar: AppBar(title: Text(titolo, overflow: TextOverflow.ellipsis)),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Percorso([
          for (final e in [p.area, p.processo, p.attivita, p.rischio].whereType<Map<String, dynamic>>())
            ('${e['codice']} - ${_titolo(e)}', () => apri(e)),
          ('${elemento['codice']} - ${_titolo(elemento)}', null),
        ]),
        const SizedBox(height: 12),
        Sezione(
          titolo: '$titolo - ${_titolo(elemento)}',
          azioni: [
            if (livello != 'AREA')
              TextButton.icon(
                icon: const Icon(Icons.open_in_new, size: 18),
                label: const Text('Apri nella mappatura'),
                onPressed: () => _apriMappatura(context, livello),
              ),
          ],
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (rischio != null || livello == 'RISCHIO')
              Padding(padding: const EdgeInsets.only(bottom: 8), child: LivelloChip(dati, rischio)),
            for (final (etichetta, valore) in _campi(dati, livello))
              if (valore != null && '$valore'.trim().isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text.rich(TextSpan(children: [
                    TextSpan(text: '$etichetta: ', style: const TextStyle(fontWeight: FontWeight.w600)),
                    TextSpan(text: '$valore'),
                  ])),
                ),
          ]),
        ),
        if (livello == 'PROCESSO' && elemento['tipo'] == 'PROCEDIMENTO' && elemento['scheda_art35'] != null)
          SezioneArt35(
            scheda: (elemento['scheda_art35'] as Map).cast<String, dynamic>(),
            mancanti: List<String>.from(elemento['art35_mancanti'] as List? ?? const []),
          ),
        if (sotto != null)
          Sezione(
            titolo: '${sotto.$1} (${sotto.$3.length})',
            child: sotto.$3.isEmpty
                ? Text('Nessun elemento.', style: Theme.of(context).textTheme.bodyMedium)
                : Column(children: [
                    for (final e in sotto.$3)
                      RigaVoce(
                        icona: _icona(sotto.$2, e),
                        titolo: '${e['codice']} - ${_titolo(e)}',
                        dettagli: [
                          if (sotto.$2 == 'PROCESSO') etichettaTipo(e['tipo']),
                          if (sotto.$2 == 'MISURA') e['tipo'] == 'GENERALE' ? 'Generale' : 'Specifica',
                        ],
                        finale: [if (sotto.$2 == 'RISCHIO') LivelloChip(dati, e['livello'] as String?)],
                        onTap: () => apri(e),
                      ),
                  ]),
          ),
      ]),
    );
  }
}
