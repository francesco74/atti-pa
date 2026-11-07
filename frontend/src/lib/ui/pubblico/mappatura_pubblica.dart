import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../anticorruzione/albero.dart' show IntestazioneProcesso, etichettaTipo;
import '../anticorruzione/comune.dart';
import '../comuni.dart';
import '../ricerca.dart';
import 'comune.dart';

/// Percorso della pagina pubblica nell'app (il link da mettere sul sito dell'ente).
const percorsoMappaturaPubblica = '/pubblico/mappatura';

/// Area dei processi senza un'area di rischio.
const _senzaArea = '';

/// Mappatura dei processi consultabile dai cittadini, senza accesso: aree di rischio,
/// processi e procedimenti dell'area, attività del processo, rischi (con il livello) e misure
/// dell'attività, con la ricerca e i filtri. Sola lettura; la pubblica il RPCT dalla scheda
/// Mappatura. Se l'ente non l'ha pubblicata l'API risponde 404.
class MappaturaPubblicaPage extends StatefulWidget {
  const MappaturaPubblicaPage({super.key});

  @override
  State<MappaturaPubblicaPage> createState() => _MappaturaPubblicaPageState();
}

class _MappaturaPubblicaPageState extends State<MappaturaPubblicaPage> {
  late Future<(String, DatiAnticorruzione)> _dati;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _dati = _caricaDati();
      });

  Future<(String, DatiAnticorruzione)> _caricaDati() async {
    final api = apiDi(context);
    final Map<String, dynamic> d;
    try {
      d = await api.get('$apiPubblico/mappatura') as Map<String, dynamic>;
    } on ApiException catch (e) {
      if (e.status == 404) throw ApiException(404, 'La mappatura dei processi di questo ente non è pubblicata.');
      rethrow;
    }
    final ente = d['ente'] as Map<String, dynamic>;
    if (mounted) caricaLogoPubblico(context, ente);
    List<Map<String, dynamic>> lista(Object? v) => (v as List).cast<Map<String, dynamic>>();
    return (
      ente['nome'] as String,
      DatiAnticorruzione(
        metodologia: {'scala': const <String>[], 'livelli': d['livelli']},
        aree: lista(d['aree']),
        strutture: lista(d['strutture']),
        obblighi: const [],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Caricamento<(String, DatiAnticorruzione)>(
          future: _dati,
          riprova: _carica,
          builder: (context, valore) {
            final (ente, dati) = valore;
            return Provider<DatiAnticorruzione>.value(
              value: dati,
              child: PaginaPubblica(
                ente: ente,
                titolo: 'Mappatura dei processi e valutazione del rischio corruttivo',
                introduzione: 'Processi e procedimenti dell\'ente raggruppati per area di rischio: per ciascuno le attività, '
                    'i possibili eventi rischiosi con il livello di rischio valutato e le misure adottate per '
                    'prevenirli (Piano triennale per la prevenzione della corruzione e la trasparenza).',
                child: const MappaturaPubblica(),
              ),
            );
          },
        ),
      ),
    );
  }
}

/// Navigazione della mappatura pubblica, un livello alla volta con il percorso in alto.
class MappaturaPubblica extends StatefulWidget {
  const MappaturaPubblica({super.key});

  @override
  State<MappaturaPubblica> createState() => _MappaturaPubblicaState();
}

class _MappaturaPubblicaState extends State<MappaturaPubblica> {
  late Future<List<Map<String, dynamic>>> _processi;
  Future<Map<String, dynamic>>? _albero;
  String? _area; // area aperta
  String? _processoId; // processo aperto
  String? _attivitaId; // attività aperta
  String? _struttura, _livello, _tipo;
  final _testo = TextEditingController(); // ricerca in tutte le aree
  final _testoArea = TextEditingController(); // ricerca nei processi dell'area aperta
  late final _registro = RegistroRicerche(apiDi(context).post, '/api/v1/pubblico/ricerche', 'MAPPATURA');
  late final _ricerca = RicercaTesto(_chiamaRicerca, setState, registro: _registro);
  late final _ricercaArea = RicercaTesto(_chiamaRicerca, setState, registro: _registro);

  Future<Object?> _chiamaRicerca(String testo) => apiDi(context).get('$apiPubblico/mappatura/ricerca', query: {'testo': testo});

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _testo.dispose();
    _testoArea.dispose();
    _ricerca.dispose();
    _ricercaArea.dispose();
    super.dispose();
  }

  void _carica() => setState(() {
        _processi = apiDi(context).get('$apiPubblico/mappatura/processi', query: {
          'struttura': ?_struttura,
          'livello': ?_livello,
          'tipo': ?_tipo,
        }).then((v) => (v as List).cast<Map<String, dynamic>>());
      });

  void _vaiAree() => setState(() {
        _processoId = _attivitaId = _area = _struttura = _livello = _tipo = null;
        _testo.clear();
        _testoArea.clear();
        _ricerca.cambia('');
        _ricercaArea.cambia('');
        _carica();
      });

  void _vaiArea(String? id) => setState(() {
        _processoId = _attivitaId = null;
        _area = id ?? _senzaArea;
      });

  void _apriProcesso(String id) => setState(() {
        _processoId = id;
        _attivitaId = null;
        _albero = apiDi(context).get('$apiPubblico/mappatura/processi/$id').then((v) => v as Map<String, dynamic>);
      });

  Widget _elencoProcessi(DatiAnticorruzione dati, List<Map<String, dynamic>> processi, [RicercaTesto? ricerca]) =>
      Column(children: [
        for (final p in processi)
          RigaVoce(
            icona: p['tipo'] == 'PROCEDIMENTO' ? Icons.gavel_outlined : Icons.account_tree_outlined,
            titolo: '${p['codice']} - ${p['denominazione']}',
            dettagli: [
              etichettaTipo(p['tipo']),
              p['struttura_id'] == null ? 'Trasversale' : (dati.struttura(p['struttura_id']) ?? ''),
              '${p['attivita']} attività, ${p['rischi']} rischi, ${p['misure']} misure',
            ],
            finale: [LivelloChip(dati, p['livello_massimo'] as String?)],
            onTap: () {
              ricerca?.aperto(p['id'] as String);
              _apriProcesso(p['id'] as String);
            },
          ),
      ]);

  /// Primo livello: le aree di rischio; mentre si cerca, i processi trovati.
  List<Widget> _livelloAree(DatiAnticorruzione dati, List<Map<String, dynamic>> processi) {
    final cerca = _ricerca.testo;
    final idAree = dati.aree.map((a) => a['id']).toSet();
    int quanti(Object? id) => processi.where((p) => p['area_id'] == id).length;
    final senzaArea = processi.where((p) => !idAree.contains(p['area_id'])).length;
    final trovati = _ricerca.filtra(processi);
    String numero(int n) => n == 1 ? '1 processo' : '$n processi';
    return [
      Align(
        alignment: Alignment.centerLeft,
        child: SizedBox(
          width: 360,
          child: TextField(
            controller: _testo,
            decoration: const InputDecoration(
              labelText: 'Cerca un processo o procedimento',
              hintText: 'Codice, parole o una domanda',
              isDense: true,
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: _ricerca.cambia,
          ),
        ),
      ),
      NotaRicerca(_ricerca),
      const SizedBox(height: 16),
      if (cerca.isNotEmpty)
        trovati.isEmpty
            ? Center(child: Text(_ricerca.inCorso ? '' : 'Nessun processo trovato.'))
            : _elencoProcessi(dati, trovati, _ricerca),
      if (cerca.isNotEmpty) FeedbackRicerca(_ricerca)
      else if (dati.aree.isEmpty && senzaArea == 0)
        const Center(child: Text('Nessun processo pubblicato.'))
      else
        Column(children: [
          for (final a in dati.aree)
            RigaVoce(
              icona: Icons.folder_outlined,
              titolo: dati.area(a['id'])!,
              dettagli: [numero(quanti(a['id']))],
              onTap: () => _vaiArea(a['id'] as String),
            ),
          if (senzaArea > 0)
            RigaVoce(icona: Icons.folder_off_outlined, titolo: 'Senza area', dettagli: [numero(senzaArea)], onTap: () => _vaiArea(null)),
        ]),
    ];
  }

  /// Secondo livello: i processi dell'area, con i filtri.
  List<Widget> _livelloProcessi(DatiAnticorruzione dati, List<Map<String, dynamic>> processi) {
    final idAree = dati.aree.map((a) => a['id']).toSet();
    final cerca = _ricercaArea.testo;
    final tutti = processi.where((p) => _area == _senzaArea ? !idAree.contains(p['area_id']) : p['area_id'] == _area).toList();
    final dellArea = cerca.isEmpty ? tutti : _ricercaArea.filtra(tutti);
    return [
      Percorso([('Aree di rischio', _vaiAree), (dati.area(_area) ?? 'Senza area', null)]),
      const SizedBox(height: 12),
      Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(
          width: 320,
          child: TextField(
            controller: _testoArea,
            decoration: const InputDecoration(
              labelText: 'Cerca nell\'area',
              hintText: 'Codice, parole o una domanda',
              isDense: true,
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: _ricercaArea.cambia,
          ),
        ),
        SizedBox(
          width: 260,
          child: DropdownButtonFormField<String?>(
            initialValue: _struttura,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Struttura', isDense: true),
            items: [
              const DropdownMenuItem(value: null, child: Text('Tutte')),
              for (final s in dati.strutture)
                DropdownMenuItem(value: s['id'] as String, child: Text('${s['codice']} - ${s['descrizione']}', overflow: TextOverflow.ellipsis)),
            ],
            onChanged: (v) {
              _struttura = v;
              _carica();
            },
          ),
        ),
        SizedBox(
          width: 180,
          child: DropdownButtonFormField<String?>(
            initialValue: _tipo,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Tipo', isDense: true),
            items: const [
              DropdownMenuItem(value: null, child: Text('Tutti')),
              DropdownMenuItem(value: 'PROCESSO', child: Text('Processi')),
              DropdownMenuItem(value: 'PROCEDIMENTO', child: Text('Procedimenti')),
            ],
            onChanged: (v) {
              _tipo = v;
              _carica();
            },
          ),
        ),
        SizedBox(
          width: 200,
          child: DropdownButtonFormField<String?>(
            initialValue: _livello,
            decoration: const InputDecoration(labelText: 'Livello più alto', isDense: true),
            items: [
              const DropdownMenuItem(value: null, child: Text('Tutti')),
              for (final l in dati.livelli.reversed) DropdownMenuItem(value: l, child: Text(l)),
            ],
            onChanged: (v) {
              _livello = v;
              _carica();
            },
          ),
        ),
      ]),
      NotaRicerca(_ricercaArea),
      const SizedBox(height: 16),
      if (dellArea.isEmpty)
        Center(child: Text(cerca.isEmpty ? 'Nessun processo o procedimento.' : (_ricercaArea.inCorso ? '' : 'Nessun processo trovato.')))
      else
        _elencoProcessi(dati, dellArea, cerca.isEmpty ? null : _ricercaArea),
      if (cerca.isNotEmpty) FeedbackRicerca(_ricercaArea),
    ];
  }

  /// Il livello più alto tra i rischi dell'attività.
  String? _livelloMassimo(DatiAnticorruzione dati, List<Map<String, dynamic>> rischi) {
    String? massimo;
    for (final r in rischi) {
      final l = r['livello'] as String?;
      if (l != null && (massimo == null || dati.livelli.indexOf(l) > dati.livelli.indexOf(massimo))) massimo = l;
    }
    return massimo;
  }

  /// Terzo livello (il processo con le attività) e quarto (l'attività con rischi e misure).
  Widget _vistaProcesso(DatiAnticorruzione dati, Map<String, dynamic> processo) {
    final attivita = (processo['attivita'] as List).cast<Map<String, dynamic>>();
    final aperta = attivita.where((a) => a['id'] == _attivitaId).firstOrNull;
    final nome = '${processo['codice']} ${processo['denominazione']}';
    List<Map<String, dynamic>> rischi(Map<String, dynamic> a) => (a['rischi'] as List).cast<Map<String, dynamic>>();
    return ListView(padding: const EdgeInsets.all(16), children: [
      Percorso([
        ('Aree di rischio', _vaiAree),
        (dati.area(processo['area_id']) ?? 'Senza area', () => _vaiArea(processo['area_id'] as String?)),
        (nome, aperta == null ? null : () => setState(() => _attivitaId = null)),
        if (aperta != null) ('${aperta['codice']}', null),
      ]),
      const SizedBox(height: 12),
      if (aperta == null) ...[
        IntestazioneProcesso(dati: dati, processo: processo),
        Text('Attività', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        if (attivita.isEmpty) const Text('Nessuna attività.'),
        for (final a in attivita)
          RigaVoce(
            icona: Icons.subdirectory_arrow_right,
            titolo: '${a['codice']} - ${a['descrizione']}',
            dettagli: [
              '${rischi(a).length} rischi, ${rischi(a).fold<int>(0, (n, r) => n + (r['misure'] as List).length)} misure',
            ],
            finale: [LivelloChip(dati, _livelloMassimo(dati, rischi(a)))],
            onTap: () => setState(() => _attivitaId = a['id'] as String),
          ),
        const SizedBox(height: 16),
        FeedbackScheda(registro: _registro, id: processo['id'] as String, titolo: nome),
      ] else ...[
        Sezione(
          titolo: 'Attività ${aperta['codice']}',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${aperta['descrizione']}'),
            if (aperta['strutture_coinvolte'] != null) Text('Strutture coinvolte: ${aperta['strutture_coinvolte']}'),
          ]),
        ),
        Sezione(
          titolo: 'Rischi e misure',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (rischi(aperta).isEmpty) const Text('Nessun rischio individuato.'),
            for (final r in rischi(aperta)) RischioPubblico(dati: dati, rischio: r),
          ]),
        ),
      ],
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final dati = context.watch<DatiAnticorruzione>();
    final albero = _albero;
    if (_processoId != null && albero != null) {
      return Caricamento<Map<String, dynamic>>(
        future: albero,
        riprova: () => _apriProcesso(_processoId!),
        builder: (context, processo) => _vistaProcesso(dati, processo),
      );
    }
    return Caricamento<List<Map<String, dynamic>>>(
      future: _processi,
      riprova: _carica,
      builder: (context, processi) => ListView(
        padding: const EdgeInsets.all(16),
        children: _area == null ? _livelloAree(dati, processi) : _livelloProcessi(dati, processi),
      ),
    );
  }
}

/// Un rischio con il livello e le misure che lo prevengono (senza i valori degli indicatori).
class RischioPubblico extends StatelessWidget {
  const RischioPubblico({super.key, required this.dati, required this.rischio});

  final DatiAnticorruzione dati;
  final Map<String, dynamic> rischio;

  @override
  Widget build(BuildContext context) {
    final r = rischio;
    final colori = Theme.of(context).colorScheme;
    final misure = (r['misure'] as List).cast<Map<String, dynamic>>();
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(border: Border(left: BorderSide(color: dati.colore(r['livello'] as String?), width: 4))),
      padding: const EdgeInsets.only(left: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${r['codice']}', style: const TextStyle(fontWeight: FontWeight.w600)),
        Text(r['evento'] as String? ?? ''),
        const SizedBox(height: 4),
        Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          LivelloChip(dati, r['livello'] as String?),
          if (r['fattore_abilitante'] != null)
            Text('Fattore abilitante: ${r['fattore_abilitante']}', style: TextStyle(color: colori.onSurfaceVariant)),
        ]),
        const SizedBox(height: 4),
        if (misure.isEmpty) Text('Nessuna misura.', style: TextStyle(color: colori.onSurfaceVariant)),
        for (final m in misure)
          ListTile(
            dense: true,
            contentPadding: const EdgeInsets.only(left: 8),
            leading: Icon(m['tipo'] == 'GENERALE' ? Icons.policy_outlined : Icons.task_alt, size: 20),
            title: Text('${m['codice']} - ${m['descrizione']}'),
            subtitle: Text([
              m['tipo'] == 'GENERALE' ? 'Misura generale' : 'Misura specifica',
              ?m['categoria'],
              if (m['obbligo_trasparenza'] != null) 'Pubblicazione ${m['obbligo_trasparenza']}',
              if (m['struttura_id'] != null) 'Responsabile: ${dati.struttura(m['struttura_id']) ?? ''}',
              if (m['fasi'] != null) 'Fasi: ${m['fasi']}',
              if (m['tempi'] != null) 'Tempi: ${m['tempi']}',
              if (m['indicatore'] != null) 'Indicatore: ${m['indicatore']}',
              if (m['target'] != null) 'Target: ${m['target']}',
            ].join(' · ')),
          ),
      ]),
    );
  }
}
