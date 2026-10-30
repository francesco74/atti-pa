import 'dart:convert';

import 'package:flutter/material.dart';

import '../comuni.dart';
import 'comune.dart';

/// Editor della metodologia di valutazione del rischio adottata dall'ente nel PIAO: scala dei
/// valori, livelli di rischio (dal più basso), matrice probabilità × impatto, indicatori,
/// fattori abilitanti e categorie delle misure. Salvando, le valutazioni esistenti si
/// ricalcolano; quelle con indicatori tolti restano da rivalutare.
class MetodologiaPage extends StatefulWidget {
  const MetodologiaPage({super.key, required this.metodologia});

  final Map<String, dynamic> metodologia;

  @override
  State<MetodologiaPage> createState() => _MetodologiaPageState();
}

class _MetodologiaPageState extends State<MetodologiaPage> {
  late Map<String, dynamic> _m;
  bool _modificata = false;
  bool _salvataggio = false;

  @override
  void initState() {
    super.initState();
    _m = jsonDecode(jsonEncode(widget.metodologia)) as Map<String, dynamic>..remove('standard');
  }

  List<String> _testi(String chiave) => (_m[chiave] as List).cast<String>();
  List<Map<String, dynamic>> _indicatori(String chiave) => (_m[chiave] as List).cast<Map<String, dynamic>>();
  Map<String, dynamic> get _matrice => (_m['matrice'] as Map).cast<String, dynamic>();

  void _cambia(VoidCallback f) => setState(() {
        f();
        _modificata = true;
      });

  Future<String?> _chiediTesto(String titolo, [String iniziale = '']) async {
    final v = await modificaCampi(context, titolo: titolo, valori: {'testo': iniziale}, campi: const [Campo('testo', 'Testo', righe: 3, obbligatorio: true)]);
    return v?['testo'] as String?;
  }

  /// Rinomina un valore della scala o un livello anche nella matrice.
  void _rinomina(String chiave, int i, String nuovo) {
    final vecchio = _testi(chiave)[i];
    _cambia(() {
      _testi(chiave)[i] = nuovo;
      if (chiave == 'scala') {
        final matrice = {
          for (final e in _matrice.entries)
            (e.key == vecchio ? nuovo : e.key): {
              for (final c in (e.value as Map).entries) (c.key == vecchio ? nuovo : c.key as String): c.value,
            },
        };
        _m['matrice'] = matrice;
      } else {
        for (final riga in _matrice.values) {
          final r = riga as Map;
          for (final k in r.keys.toList()) {
            if (r[k] == vecchio) r[k] = nuovo;
          }
        }
      }
    });
  }

  Widget _listaTesti(String chiave, String titolo, String aiuto, {bool ordinata = false, bool rinominaInMatrice = false}) {
    final lista = _testi(chiave);
    return Sezione(
      titolo: titolo,
      azioni: [
        IconButton(
          tooltip: 'Aggiungi',
          icon: const Icon(Icons.add),
          onPressed: () async {
            final v = await _chiediTesto('Nuovo valore');
            if (v != null) _cambia(() => lista.add(v));
          },
        ),
      ],
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(aiuto, style: Theme.of(context).textTheme.bodySmall),
        for (var i = 0; i < lista.length; i++)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: ordinata ? Text('${i + 1}') : null,
            title: Text(lista[i]),
            trailing: Wrap(children: [
              if (ordinata) ...[
                IconButton(
                  tooltip: 'Più in basso nell\'ordine',
                  icon: const Icon(Icons.arrow_upward, size: 18),
                  onPressed: i == 0 ? null : () => _cambia(() => lista.insert(i - 1, lista.removeAt(i))),
                ),
                IconButton(
                  tooltip: 'Più in alto nell\'ordine',
                  icon: const Icon(Icons.arrow_downward, size: 18),
                  onPressed: i == lista.length - 1 ? null : () => _cambia(() => lista.insert(i + 1, lista.removeAt(i))),
                ),
              ],
              IconButton(
                tooltip: 'Modifica',
                icon: const Icon(Icons.edit_outlined, size: 18),
                onPressed: () async {
                  final v = await _chiediTesto('Modifica', lista[i]);
                  if (v == null) return;
                  if (rinominaInMatrice) {
                    _rinomina(chiave, i, v);
                  } else {
                    _cambia(() => lista[i] = v);
                  }
                },
              ),
              IconButton(
                tooltip: 'Togli',
                icon: const IconaElimina(size: 18),
                onPressed: () => _cambia(() => lista.removeAt(i)),
              ),
            ]),
          ),
      ]),
    );
  }

  Widget _indicatoriSezione(String chiave, String titolo) {
    final lista = _indicatori(chiave);
    Future<Map<String, dynamic>?> modifica([Map<String, dynamic>? i]) => modificaCampi(context,
        titolo: i == null ? 'Nuovo indicatore' : 'Indicatore ${i['id']}', valori: i ?? const {}, campi: const [
      Campo('nome', 'Nome', obbligatorio: true),
      Campo('descrizione', 'Descrizione', righe: 4),
    ]);
    return Sezione(
      titolo: titolo,
      azioni: [
        IconButton(
          tooltip: 'Aggiungi un indicatore',
          icon: const Icon(Icons.add),
          onPressed: () async {
            final v = await modifica();
            if (v == null) return;
            final numeri = lista.map((x) => int.tryParse('${x['id']}') ?? 0);
            final id = '${numeri.fold(0, (a, b) => a > b ? a : b) + 1}';
            _cambia(() => lista.add({'id': id, 'nome': v['nome'], 'descrizione': v['descrizione'] ?? ''}));
          },
        ),
      ],
      child: Column(children: [
        for (final i in lista)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Text('${i['id']}'),
            title: Text('${i['nome']}'),
            subtitle: (i['descrizione'] as String?)?.isNotEmpty == true ? Text(i['descrizione'] as String) : null,
            trailing: Wrap(children: [
              IconButton(
                icon: const Icon(Icons.edit_outlined, size: 18),
                onPressed: () async {
                  final v = await modifica(i);
                  if (v != null) _cambia(() => i..['nome'] = v['nome']..['descrizione'] = v['descrizione'] ?? '');
                },
              ),
              IconButton(
                tooltip: 'Togli (le valutazioni che lo usano restano da rivalutare)',
                icon: const IconaElimina(size: 18),
                onPressed: () => _cambia(() => lista.remove(i)),
              ),
            ]),
          ),
      ]),
    );
  }

  Widget _matriceSezione() {
    final scala = _testi('scala');
    final livelli = _testi('livelli');
    return Sezione(
      titolo: 'Matrice probabilità × impatto',
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(columns: [
          const DataColumn(label: Text('Probabilità \\ Impatto')),
          for (final i in scala) DataColumn(label: Text(i)),
        ], rows: [
          for (final p in scala.reversed)
            DataRow(cells: [
              DataCell(Text(p, style: const TextStyle(fontWeight: FontWeight.w600))),
              for (final i in scala)
                DataCell(DropdownButton<String>(
                  value: livelli.contains((_matrice[p] as Map?)?[i]) ? (_matrice[p] as Map)[i] as String : null,
                  hint: const Text('—'),
                  underline: const SizedBox.shrink(),
                  items: [for (final l in livelli) DropdownMenuItem(value: l, child: Text(l))],
                  onChanged: (v) => _cambia(() => (_m['matrice'] as Map).putIfAbsent(p, () => <String, dynamic>{})[i] = v),
                )),
            ]),
        ]),
      ),
    );
  }

  Future<void> _salva() async {
    setState(() => _salvataggio = true);
    try {
      final r = await apiDi(context).put('$apiAnticorruzione/metodologia', _m) as Map<String, dynamic>;
      if (!mounted) return;
      _modificata = false;
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Metodologia salvata'),
          content: Text('Valutazioni ricalcolate: ${r['ricalcolati']}.'
              '${(r['da_rivalutare'] as int) > 0 ? '\nDa rivalutare (indicatori cambiati): ${r['da_rivalutare']}.' : ''}'),
          actions: [FilledButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
        ),
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _salvataggio = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !_modificata,
      onPopInvokedWithResult: (fatto, _) async {
        if (fatto) return;
        if (await conferma(context, 'Modifiche non salvate', 'Uscire senza salvare la metodologia?') && context.mounted) {
          setState(() => _modificata = false);
          Navigator.of(context).pop();
        }
      },
      child: Scaffold(
        appBar: AppBar(title: const Text('Metodologia di valutazione del rischio'), actions: [
          TextButton.icon(
            onPressed: _salvataggio || !_modificata ? null : _salva,
            icon: const Icon(Icons.save_outlined),
            label: const Text('Salva'),
          ),
        ]),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          const Text('La metodologia è quella adottata dall\'ente nel PIAO. Probabilità e impatto sono la moda dei valori '
              'degli indicatori (a parità vale il più alto); il livello viene dalla matrice. Salvando, le valutazioni '
              'esistenti si ricalcolano.'),
          const SizedBox(height: 12),
          _listaTesti('scala', 'Scala dei valori', 'Dal più basso al più alto (es. Basso, Medio, Alto).',
              ordinata: true, rinominaInMatrice: true),
          _listaTesti('livelli', 'Livelli di rischio', 'Dal meno grave al più grave: serve per ordinare, filtrare e colorare.',
              ordinata: true, rinominaInMatrice: true),
          _matriceSezione(),
          _indicatoriSezione('indicatori_probabilita', 'Indicatori di probabilità'),
          _indicatoriSezione('indicatori_impatto', 'Indicatori di impatto'),
          _listaTesti('fattori_abilitanti', 'Fattori abilitanti', 'Proposti nella valutazione del rischio.'),
          _listaTesti('categorie_misure', 'Categorie delle misure', 'Proposte nella scheda della misura.'),
        ]),
      ),
    );
  }
}
