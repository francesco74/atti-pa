import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../anticorruzione/art35.dart';
import '../anticorruzione/comune.dart' show Percorso, RigaVoce;
import '../comuni.dart';
import 'comune.dart';

/// Percorso della pagina pubblica dei procedimenti (da collegare nella sezione Amministrazione
/// trasparente, Attività e procedimenti > Tipologie di procedimento).
const percorsoProcedimentiPubblici = '/pubblico/procedimenti';

/// Procedimenti dell'ente consultabili dai cittadini, senza accesso: strutture, procedimenti
/// della struttura, scheda con tutti i dati dell'art. 35 d.lgs. 33/2013 (allegato 11 alla
/// delibera ANAC 495/2024). La ricerca trova i procedimenti di tutte le strutture. I dati
/// vengono dalla mappatura dell'anticorruzione; la pagina la pubblica il RPCT.
class ProcedimentiPubbliciPage extends StatefulWidget {
  const ProcedimentiPubbliciPage({super.key});

  @override
  State<ProcedimentiPubbliciPage> createState() => _ProcedimentiPubbliciPageState();
}

/// Gruppo dei procedimenti senza struttura responsabile.
const _senzaStruttura = '';

class _ProcedimentiPubbliciPageState extends State<ProcedimentiPubbliciPage> {
  late Future<Map<String, dynamic>> _dati;
  String? _struttura; // struttura aperta
  String? _procedimentoId; // procedimento aperto
  Future<Map<String, dynamic>>? _scheda;
  final _testo = TextEditingController();

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _testo.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
        _dati = _caricaDati();
      });

  Future<Map<String, dynamic>> _caricaDati() async {
    try {
      final d = await apiDi(context).get('$apiPubblico/procedimenti') as Map<String, dynamic>;
      if (mounted) caricaLogoPubblico(context, d['ente'] as Map<String, dynamic>);
      return d;
    } on ApiException catch (e) {
      if (e.status == 404) throw ApiException(404, 'I procedimenti di questo ente non sono pubblicati.');
      rethrow;
    }
  }

  void _vaiStrutture() => setState(() {
        _struttura = _procedimentoId = null;
        _testo.clear();
      });

  void _apri(Map<String, dynamic> p) => setState(() {
        _procedimentoId = p['id'] as String;
        _scheda = apiDi(context).get('$apiPubblico/procedimenti/${p['id']}').then((v) => v as Map<String, dynamic>);
      });

  String _nomeStruttura(Map<String, dynamic> d, String? id) {
    if (id == null || id == _senzaStruttura) return 'Procedimenti comuni a tutte le strutture';
    final s = (d['strutture'] as List).cast<Map<String, dynamic>>().where((s) => s['id'] == id).firstOrNull;
    return s == null ? '—' : '${s['codice']} - ${s['descrizione']}';
  }

  Widget _elenco(Map<String, dynamic> d, List<Map<String, dynamic>> procedimenti) => Column(children: [
        for (final p in procedimenti)
          RigaVoce(
            icona: Icons.gavel_outlined,
            titolo: '${p['denominazione']}',
            dettagli: [?p['tipologia'] as String?, if (_struttura == null) _nomeStruttura(d, p['struttura_id'] as String?)],
            onTap: () => _apri(p),
          ),
      ]);

  List<Widget> _livelloStrutture(Map<String, dynamic> d, List<Map<String, dynamic>> procedimenti) {
    final cerca = _testo.text.trim().toLowerCase();
    final trovati = procedimenti
        .where((p) => '${p['codice']} ${p['denominazione']} ${p['tipologia'] ?? ''}'.toLowerCase().contains(cerca))
        .toList();
    int quanti(String? id) => procedimenti.where((p) => (p['struttura_id'] ?? _senzaStruttura) == (id ?? _senzaStruttura)).length;
    String numero(int n) => n == 1 ? '1 procedimento' : '$n procedimenti';
    final senza = quanti(null);
    return [
      Align(
        alignment: Alignment.centerLeft,
        child: SizedBox(
          width: 360,
          child: TextField(
            controller: _testo,
            decoration: const InputDecoration(labelText: 'Cerca un procedimento', isDense: true, prefixIcon: Icon(Icons.search)),
            onChanged: (_) => setState(() {}),
          ),
        ),
      ),
      const SizedBox(height: 16),
      if (cerca.isNotEmpty)
        trovati.isEmpty ? const Center(child: Text('Nessun procedimento trovato.')) : _elenco(d, trovati)
      else if (procedimenti.isEmpty)
        const Center(child: Text('Nessun procedimento pubblicato.'))
      else
        Column(children: [
          for (final s in (d['strutture'] as List).cast<Map<String, dynamic>>())
            RigaVoce(
              icona: Icons.apartment,
              titolo: '${s['codice']} - ${s['descrizione']}',
              dettagli: [numero(quanti(s['id'] as String))],
              onTap: () => setState(() => _struttura = s['id'] as String),
            ),
          if (senza > 0)
            RigaVoce(
              icona: Icons.apartment,
              titolo: _nomeStruttura(d, null),
              dettagli: [numero(senza)],
              onTap: () => setState(() => _struttura = _senzaStruttura),
            ),
        ]),
    ];
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Caricamento<Map<String, dynamic>>(
            future: _dati,
            riprova: _carica,
            builder: (context, d) {
              final procedimenti = (d['procedimenti'] as List).cast<Map<String, dynamic>>();
              final aperto = procedimenti.where((p) => p['id'] == _procedimentoId).firstOrNull;
              final Widget contenuto;
              if (aperto != null) {
                contenuto = ListView(padding: const EdgeInsets.all(16), children: [
                  Percorso([
                    ('Strutture', _vaiStrutture),
                    if (_struttura != null) (_nomeStruttura(d, _struttura), () => setState(() => _procedimentoId = null)),
                    ('${aperto['denominazione']}', null),
                  ]),
                  const SizedBox(height: 12),
                  Caricamento<Map<String, dynamic>>(
                    future: _scheda!,
                    riprova: () => _apri(aperto),
                    builder: (context, p) => Sezione(
                      titolo: '${aperto['denominazione']}',
                      child: SchedaArt35((p['scheda'] as Map).cast<String, dynamic>()),
                    ),
                  ),
                ]);
              } else if (_struttura != null) {
                contenuto = ListView(padding: const EdgeInsets.all(16), children: [
                  Percorso([('Strutture', _vaiStrutture), (_nomeStruttura(d, _struttura), null)]),
                  const SizedBox(height: 12),
                  _elenco(d, procedimenti.where((p) => (p['struttura_id'] ?? _senzaStruttura) == _struttura).toList()),
                ]);
              } else {
                contenuto = ListView(padding: const EdgeInsets.all(16), children: _livelloStrutture(d, procedimenti));
              }
              return PaginaPubblica(
                ente: (d['ente'] as Map)['nome'] as String,
                titolo: 'Tipologie di procedimento',
                introduzione: 'Procedimenti amministrativi dell\'ente per struttura responsabile: per ciascuno uffici, '
                    'recapiti, modulistica, termini, strumenti di tutela e potere sostitutivo (art. 35 d.lgs. 33/2013).',
                child: contenuto,
              );
            },
          ),
        ),
      );
}
