import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';
import 'comune.dart';
import 'mappatura.dart' show VistaProcesso;

const apiCatalogo = '$apiAnticorruzione/catalogo';

const tipiVoce = {'ATTIVITA': 'Attività', 'RISCHIO': 'Rischi', 'MISURA': 'Misure'};
const _singolare = {'ATTIVITA': 'attività', 'RISCHIO': 'rischio', 'MISURA': 'misura'};

IconData iconaVoce(String? tipo) => switch (tipo) {
      'ATTIVITA' => Icons.subdirectory_arrow_right,
      'RISCHIO' => Icons.warning_amber_outlined,
      _ => Icons.shield_outlined,
    };

/// Catalogo della mappatura: le voci (radici) di attività, rischi e misure da cui nascono gli
/// elementi dei processi, con dove sono usate. Il RPCT le crea, le modifica (se usate con
/// conferma), le disattiva, le unisce e le elimina se non usate.
class CatalogoTab extends StatefulWidget {
  const CatalogoTab({super.key});

  @override
  State<CatalogoTab> createState() => _CatalogoTabState();
}

class _CatalogoTabState extends State<CatalogoTab> with AutomaticKeepAliveClientMixin {
  String _tipo = 'ATTIVITA';
  final _testo = TextEditingController();
  Timer? _attesa;
  late Future<List<Map<String, dynamic>>> _voci;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _attesa?.cancel();
    _testo.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
        _voci = apiDi(context).get(apiCatalogo, query: {
          'tipo': _tipo,
          if (_testo.text.trim().isNotEmpty) 'testo': _testo.text.trim(),
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  Future<void> _nuova() async {
    final dati = context.read<DatiAnticorruzione>();
    final v = await modificaVoce(context, dati, _tipo);
    if (v == null || !mounted) return;
    try {
      await apiDi(context).post(apiCatalogo, {...v, 'tipo': _tipo});
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _apri(Map<String, dynamic> v) async {
    final dati = context.read<DatiAnticorruzione>();
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => Provider<DatiAnticorruzione>.value(value: dati, child: SchedaVocePage(voceId: v['id'] as String)),
    ));
    if (mounted) _carica();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Le voci da cui nascono attività, rischi e misure dei processi. Nel processo il testo si può ritoccare, '
          'ma la voce resta la stessa: così si vede dove una voce è usata.', style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 12),
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SegmentedButton<String>(
          segments: [for (final e in tipiVoce.entries) ButtonSegment(value: e.key, label: Text(e.value))],
          selected: {_tipo},
          showSelectedIcon: false,
          onSelectionChanged: (s) {
            _tipo = s.first;
            _carica();
          },
        ),
        SizedBox(
          width: 320,
          child: TextField(
            controller: _testo,
            decoration: const InputDecoration(labelText: 'Cerca (codice o testo)', prefixIcon: Icon(Icons.search), isDense: true),
            onChanged: (_) {
              _attesa?.cancel();
              _attesa = Timer(const Duration(milliseconds: 400), _carica);
            },
          ),
        ),
        if (rpct)
          FilledButton.icon(
            onPressed: _nuova,
            icon: const Icon(Icons.add, size: 18),
            label: Text('Nuova voce (${_singolare[_tipo]})'),
          ),
      ]),
      const SizedBox(height: 12),
      Caricamento<List<Map<String, dynamic>>>(
        future: _voci,
        riprova: _carica,
        builder: (context, voci) => voci.isEmpty
            ? const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Nessuna voce.')))
            : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text('${voci.length} voci', style: Theme.of(context).textTheme.titleSmall),
                for (final v in voci) _riga(v),
              ]),
      ),
    ]);
  }

  Widget _riga(Map<String, dynamic> v) {
    final usi = v['usi'] as int? ?? 0;
    return RigaVoce(
      icona: iconaVoce(v['tipo'] as String?),
      titolo: '${v['codice']} - ${v['descrizione']}',
      dettagli: [
        usi == 0 ? 'non usata' : (usi == 1 ? 'usata in 1 elemento' : 'usata in $usi elementi'),
        v['standard'] == true ? 'standard' : 'dell\'ente',
        if (v['tipo'] == 'MISURA' && v['categoria'] != null) '${v['categoria']}',
      ],
      finale: [if (v['attiva'] != true) const _Etichetta('Disattivata')],
      onTap: () => _apri(v),
    );
  }
}

class _Etichetta extends StatelessWidget {
  const _Etichetta(this.testo);

  final String testo;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(border: Border.all(color: Colors.blueGrey), borderRadius: BorderRadius.circular(12)),
        child: Text(testo, style: const TextStyle(fontSize: 12)),
      );
}

/// Testo e dati della voce: per le misure anche tipo, categoria, indicatore e target di
/// partenza.
Future<Map<String, dynamic>?> modificaVoce(BuildContext context, DatiAnticorruzione d, String tipo, [Map<String, dynamic>? v]) {
  final categoria = v?['categoria'] as String?;
  return modificaCampi(context,
      titolo: v?['codice'] == null ? 'Nuova voce: ${_singolare[tipo]}' : 'Voce ${v!['codice']}',
      valori: {if (tipo == 'MISURA') 'tipo_misura': 'SPECIFICA', ...?v},
      campi: [
        Campo('descrizione', tipo == 'RISCHIO' ? 'Evento rischioso' : 'Descrizione', righe: 4, obbligatorio: true),
        if (tipo == 'MISURA') ...[
          const Campo('tipo_misura', 'Tipo', scelte: [('GENERALE', 'Generale'), ('SPECIFICA', 'Specifica')]),
          Campo('categoria', 'Categoria', scelte: [
            (null, 'Nessuna'),
            for (final c in d.categorie) (c, c),
            if (categoria != null && !d.categorie.contains(categoria)) (categoria, categoria),
          ]),
          const Campo('indicatore', 'Indicatore', righe: 2),
          const Campo('target', 'Target', righe: 2),
        ],
      ]);
}

/// Chiede conferma per un'operazione su una voce usata, elencando dove è usata. True: si
/// procede (subito, se la voce non è usata).
Future<bool> confermaVoceUsata(BuildContext context, Map<String, dynamic> voce, String titolo, String conseguenza) async {
  final elementi = (voce['elementi'] as List? ?? const []).cast<Map<String, dynamic>>();
  if (elementi.isEmpty) return true;
  final esito = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(titolo),
      content: SizedBox(
        width: 560,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('La voce ${voce['codice']} è usata in ${elementi.length == 1 ? '1 elemento' : '${elementi.length} elementi'} della mappatura:',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Flexible(
            child: SingleChildScrollView(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final e in elementi)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('• ${e['codice']} (${(e['processo'] as Map)['codice']} - ${(e['processo'] as Map)['denominazione']})'),
                  ),
              ]),
            ),
          ),
          const SizedBox(height: 8),
          Text(conseguenza),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Procedi comunque')),
      ],
    ),
  );
  return esito == true;
}

/// Una voce del catalogo: i dati e dove è usata; per il RPCT le operazioni.
class SchedaVocePage extends StatefulWidget {
  const SchedaVocePage({super.key, required this.voceId});

  final String voceId;

  @override
  State<SchedaVocePage> createState() => _SchedaVocePageState();
}

class _SchedaVocePageState extends State<SchedaVocePage> {
  late Future<Map<String, dynamic>> _voce;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _voce = apiDi(context).get('$apiCatalogo/${widget.voceId}').then((v) => v as Map<String, dynamic>);
      });

  Future<void> _esegui(Future<void> Function() azione) async {
    try {
      await azione();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
    if (mounted) _carica();
  }

  static const _restano = 'Gli elementi dei processi non cambiano: tengono il loro testo.';

  Future<void> _modifica(Map<String, dynamic> v) => _esegui(() async {
        final dati = context.read<DatiAnticorruzione>();
        final nuovi = await modificaVoce(context, dati, v['tipo'] as String, v);
        if (nuovi == null || !mounted) return;
        if (!await confermaVoceUsata(context, v, 'Modificare una voce usata?', _restano) || !mounted) return;
        await apiDi(context).put('$apiCatalogo/${v['id']}', {...nuovi, 'attiva': v['attiva'], 'conferma': true});
      });

  Future<void> _attiva(Map<String, dynamic> v, bool attiva) => _esegui(() async {
        if (!attiva &&
            !await confermaVoceUsata(context, v, 'Disattivare una voce usata?', 'Non si potrà più scegliere. $_restano')) {
          return;
        }
        if (!mounted) return;
        await apiDi(context).put('$apiCatalogo/${v['id']}', {...v, 'attiva': attiva, 'conferma': true});
      });

  Future<void> _unisci(Map<String, dynamic> v) => _esegui(() async {
        final altra = await scegliVoce(context, v['tipo'] as String, escluse: {v['id'] as String},
            titolo: 'Unisci ${v['codice']} a un\'altra voce');
        if (altra == null || !mounted) return;
        final testo = 'I suoi elementi passano a ${altra['codice']} e la voce ${v['codice']} si elimina. $_restano';
        if ((v['elementi'] as List).isEmpty) {
          if (!await conferma(context, 'Unire le voci?', testo)) return;
        } else if (!await confermaVoceUsata(context, v, 'Unire una voce usata?', testo)) {
          return;
        }
        if (!mounted) return;
        await apiDi(context).post('$apiCatalogo/${v['id']}/unisci', {'in_voce': altra['id'], 'conferma': true});
        if (mounted) Navigator.of(context).pop();
      });

  Future<void> _elimina(Map<String, dynamic> v) => _esegui(() async {
        if (!await conferma(context, 'Eliminare la voce?', 'La voce ${v['codice']} non è usata: si elimina dal catalogo.') || !mounted) {
          return;
        }
        await apiDi(context).delete('$apiCatalogo/${v['id']}');
        if (mounted) Navigator.of(context).pop();
      });

  /// Apre il processo (e l'attività) dove la voce è usata.
  void _apriProcesso(Map<String, dynamic> e) {
    final dati = context.read<DatiAnticorruzione>();
    final processo = e['processo'] as Map;
    Navigator.of(context).push(MaterialPageRoute(
      builder: (c) => Provider<DatiAnticorruzione>.value(
        value: dati,
        child: Scaffold(
          appBar: AppBar(title: Text('${processo['codice']} - ${processo['denominazione']}')),
          body: VistaProcesso(
            processoId: processo['id'] as String,
            attivitaIniziale: e['attivita_id'] as String?,
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
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    return Scaffold(
      appBar: AppBar(title: const Text('Voce del catalogo')),
      body: Caricamento<Map<String, dynamic>>(
        future: _voce,
        riprova: _carica,
        builder: (context, v) {
          final elementi = (v['elementi'] as List).cast<Map<String, dynamic>>();
          final righe = [
            ('Tipo', _singolare[v['tipo']]),
            ('Provenienza', v['standard'] == true ? 'voce standard (pacchetto)' : 'voce dell\'ente'),
            if (v['tipo'] == 'MISURA') ...[
              ('Tipo di misura', v['tipo_misura'] == 'GENERALE' ? 'Generale' : 'Specifica'),
              ('Categoria', v['categoria']),
              ('Indicatore', v['indicatore']),
              ('Target', v['target']),
            ],
            if (v['attiva'] != true) ('Stato', 'disattivata: non si sceglie più'),
          ];
          return ListView(padding: const EdgeInsets.all(16), children: [
            Sezione(
              titolo: '${v['codice']} - ${v['descrizione']}',
              azioni: [
                if (rpct) ...[
                  TextButton.icon(icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('Modifica'), onPressed: () => _modifica(v)),
                  TextButton.icon(
                    icon: Icon(v['attiva'] == true ? Icons.block : Icons.check_circle_outline, size: 18),
                    label: Text(v['attiva'] == true ? 'Disattiva' : 'Riattiva'),
                    onPressed: () => _attiva(v, v['attiva'] != true),
                  ),
                  TextButton.icon(icon: const Icon(Icons.merge_type, size: 18), label: const Text('Unisci'), onPressed: () => _unisci(v)),
                  if (elementi.isEmpty)
                    TextButton.icon(
                      style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                      icon: const Icon(Icons.delete_outline, size: 18),
                      label: const Text('Elimina'),
                      onPressed: () => _elimina(v),
                    ),
                ],
              ],
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final (etichetta, valore) in righe)
                  if (valore != null && valore.toString().isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text.rich(TextSpan(children: [
                        TextSpan(text: '$etichetta: ', style: const TextStyle(fontWeight: FontWeight.w600)),
                        TextSpan(text: '$valore'),
                      ])),
                    ),
              ]),
            ),
            Sezione(
              titolo: elementi.isEmpty ? 'Non usata nella mappatura' : 'Usata in ${elementi.length} elementi della mappatura',
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                for (final e in elementi)
                  RigaVoce(
                    icona: iconaVoce(v['tipo'] as String?),
                    titolo: '${e['codice']} - ${e['testo']}',
                    dettagli: [
                      '${(e['processo'] as Map)['codice']} - ${(e['processo'] as Map)['denominazione']}',
                      if (e['diverso'] == true) 'testo ritoccato nel processo',
                    ],
                    onTap: () => _apriProcesso(e),
                  ),
              ]),
            ),
          ]);
        },
      ),
    );
  }
}

/// Scelta di una voce del catalogo (attive, del tipo dato), con la ricerca. Con [dati] (per un
/// elemento nuovo della mappatura) la voce che manca si crea (RPCT) o si propone (referente:
/// approvata, si sceglie).
Future<Map<String, dynamic>?> scegliVoce(BuildContext context, String tipo,
        {Set<String> escluse = const {}, String? titolo, DatiAnticorruzione? dati}) =>
    showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _SceltaVoce(
          tipo: tipo, escluse: escluse, titolo: titolo ?? 'Scegli dal catalogo: ${_singolare[tipo]}', dati: dati),
    );

class _SceltaVoce extends StatefulWidget {
  const _SceltaVoce({required this.tipo, required this.escluse, required this.titolo, this.dati});

  final String tipo;
  final Set<String> escluse;
  final String titolo;
  final DatiAnticorruzione? dati;

  @override
  State<_SceltaVoce> createState() => _SceltaVoceState();
}

class _SceltaVoceState extends State<_SceltaVoce> {
  final _testo = TextEditingController();
  Timer? _attesa;
  late Future<List<Map<String, dynamic>>> _voci;

  @override
  void initState() {
    super.initState();
    _cerca();
  }

  @override
  void dispose() {
    _attesa?.cancel();
    _testo.dispose();
    super.dispose();
  }

  void _cerca() => setState(() {
        _voci = apiDi(context).get(apiCatalogo, query: {
          'tipo': widget.tipo,
          'attive': 'true',
          if (_testo.text.trim().isNotEmpty) 'testo': _testo.text.trim(),
        }).then((v) => [for (final x in (v as List).cast<Map<String, dynamic>>()) if (!widget.escluse.contains(x['id'])) x]);
      });

  /// La voce che manca: il RPCT la crea e la sceglie; il referente la propone.
  Future<void> _manca(bool rpct) async {
    final v = await modificaVoce(context, widget.dati!, widget.tipo,
        _testo.text.trim().isEmpty ? null : {'descrizione': _testo.text.trim(), if (widget.tipo == 'MISURA') 'tipo_misura': 'SPECIFICA'});
    if (v == null || !mounted) return;
    try {
      final api = apiDi(context);
      if (rpct) {
        final nuova = await api.post(apiCatalogo, {...v, 'tipo': widget.tipo}) as Map<String, dynamic>;
        if (mounted) Navigator.pop(context, nuova);
        return;
      }
      await api.post('$apiAnticorruzione/proposte', {'tipo': 'CREA', 'oggetto': 'VOCE', 'dati': {...v, 'tipo_voce': widget.tipo}});
      if (!mounted) return;
      mostraMessaggio(context, 'Proposta della voce inviata al RPCT: quando la approva la trovi nel catalogo e la puoi scegliere.');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    return AlertDialog(
        title: Text(widget.titolo),
        content: SizedBox(
          width: 640,
          height: 460,
          child: Column(children: [
            if (widget.dati != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                    rpct
                        ? 'Il testo della voce si potrà ritoccare per questo processo. Se la voce manca, creala.'
                        : 'Il testo della voce si potrà ritoccare per questo processo. Se la voce manca, proponila: '
                            'quando il RPCT la approva la potrai scegliere.',
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            TextField(
              controller: _testo,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Cerca (codice o testo)', prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (_) {
                _attesa?.cancel();
                _attesa = Timer(const Duration(milliseconds: 400), _cerca);
              },
            ),
            const SizedBox(height: 8),
            Expanded(
              child: Caricamento<List<Map<String, dynamic>>>(
                future: _voci,
                riprova: _cerca,
                builder: (context, voci) => voci.isEmpty
                    ? const Center(child: Text('Nessuna voce trovata.'))
                    : ListView(children: [
                        for (final v in voci)
                          ListTile(
                            dense: true,
                            leading: Icon(iconaVoce(v['tipo'] as String?), size: 20),
                            title: Text('${v['codice']} - ${v['descrizione']}'),
                            subtitle: Text((v['usi'] as int? ?? 0) == 0 ? 'non usata' : 'usata in ${v['usi']} elementi'),
                            onTap: () => Navigator.pop(context, v),
                          ),
                      ]),
              ),
            ),
          ]),
        ),
        actions: [
          if (widget.dati != null)
            TextButton.icon(
              icon: Icon(rpct ? Icons.add : Icons.outgoing_mail, size: 18),
              label: Text(rpct ? 'Nuova voce' : 'Proponi una voce nuova'),
              onPressed: () => _manca(rpct),
            ),
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        ],
      );
  }
}
