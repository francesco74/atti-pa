import 'package:flutter/material.dart';

import '../comuni.dart';
import '../admin/strutture.dart' show alberoStrutture;

/// Dati del procedimento per l'art. 35 d.lgs. 33/2013 (allegato 11 alla delibera ANAC
/// 495/2024): la scheda arriva dall'API nel formato dello schema ART_35 della trasparenza,
/// con i recapiti degli uffici presi dalle strutture organizzative.

/// Etichette dei dati propri del procedimento (`art35` del processo), anche per le proposte.
const etichetteArt35 = {
  'tipologia': 'Tipologia di procedimento',
  'uff_resp_struttura_id': 'Ufficio responsabile del procedimento',
  'uff_finale_struttura_id': 'Ufficio competente per il provvedimento finale',
  'istanza_di_parte': 'A istanza di parte',
  'ist_struttura_id': 'Ufficio per informazioni e istanze',
  'ist_modulistica': 'Atti e modulistica (link)',
  'modalita_info': 'Come avere informazioni sui procedimenti in corso',
  'dichiarazione_sostitutiva': 'Sostituibile da dichiarazione dell\'interessato',
  'silenzio_assenso': 'Silenzio assenso',
  'strumenti_tutela': 'Strumenti di tutela',
  'servizio_online_link': 'Servizio online (link)',
  'servizio_online_tempi': 'Tempi di attivazione del servizio online',
  'link_pagamenti': 'Pagamenti (link)',
  'sost_struttura_id': 'Ufficio del titolare del potere sostitutivo',
  'sost_attivazione': 'Come attivare il potere sostitutivo',
  ...etichetteRecapitiArt35,
};

/// Recapiti che si possono scrivere nel procedimento al posto di quelli della struttura
/// dell'ufficio: campo -> etichetta (anche per le proposte).
const etichetteRecapitiArt35 = {
  'uff_resp_tel': 'Ufficio responsabile - telefono',
  'uff_resp_peo': 'Ufficio responsabile - PEO',
  'uff_resp_pec': 'Ufficio responsabile - PEC',
  'uff_finale_resp': 'Responsabile dell\'ufficio competente',
  'uff_finale_tel': 'Ufficio competente - telefono',
  'uff_finale_peo': 'Ufficio competente - PEO',
  'uff_finale_pec': 'Ufficio competente - PEC',
  'ist_indirizzo': 'Ufficio istanze - indirizzo',
  'ist_telefono': 'Ufficio istanze - telefono',
  'ist_peo': 'Ufficio istanze - PEO',
  'ist_pec': 'Ufficio istanze - PEC',
  'orari': 'Orari di apertura al pubblico',
  'sost_nominativo': 'Titolare del potere sostitutivo',
  'sost_qualifica': 'Qualifica del titolare del potere sostitutivo',
  'sost_tel': 'Potere sostitutivo - telefono',
  'sost_peo': 'Potere sostitutivo - PEO',
  'sost_pec': 'Potere sostitutivo - PEC',
};

/// Finestra dei dati art. 35 del procedimento, con le sezioni e le domande dell'allegato 11
/// come nella trasparenza: le parti che dipendono da una risposta (ufficio finale diverso, a
/// istanza di parte) compaiono solo quando servono. Gli uffici si scelgono dall'organigramma e
/// se ne vedono i recapiti; un recapito scritto qui vale solo per questo procedimento, al posto
/// di quello della struttura. Restituisce la mappa `art35` da salvare. [procedimento]: i dati
/// che vengono dal procedimento (denominazione, struttura responsabile...). Usata dalla
/// mappatura e dai procedimenti della trasparenza.
Future<Map<String, dynamic>?> modificaArt35(
  BuildContext context,
  List<Map<String, dynamic>> strutture,
  Map<String, dynamic>? art35, {
  Map<String, dynamic>? procedimento,
}) =>
    showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _FinestraArt35(strutture: strutture, art35: art35 ?? const {}, procedimento: procedimento ?? const {}),
    );

final _reUrl = RegExp(r'^https?://\S+$', caseSensitive: false);

class _FinestraArt35 extends StatefulWidget {
  const _FinestraArt35({required this.strutture, required this.art35, required this.procedimento});

  final List<Map<String, dynamic>> strutture;
  final Map<String, dynamic> art35;
  final Map<String, dynamic> procedimento;

  @override
  State<_FinestraArt35> createState() => _FinestraArt35State();
}

class _FinestraArt35State extends State<_FinestraArt35> {
  static const _testi = [
    'tipologia', 'ist_modulistica', 'modalita_info', 'strumenti_tutela', 'servizio_online_link', 'servizio_online_tempi',
    'link_pagamenti', 'sost_attivazione',
  ];
  static const _scelte = [
    'uff_resp_struttura_id', 'uff_finale_struttura_id', 'ist_struttura_id', 'sost_struttura_id', 'istanza_di_parte',
    'dichiarazione_sostitutiva', 'silenzio_assenso',
  ];

  late final Map<String, TextEditingController> _c = {
    for (final k in [..._testi, ...etichetteRecapitiArt35.keys.where((k) => k != 'orari')])
      k: TextEditingController(text: widget.art35[k] as String? ?? ''),
  };
  late final Map<String, String?> _v = {for (final k in _scelte) k: widget.art35[k] as String?};
  late bool _finaleDiverso = widget.art35['uff_finale_struttura_id'] != null;
  late final List<List<TextEditingController>> _orari = [
    for (final o in (widget.art35['orari'] as List? ?? const []).cast<Map>())
      [for (final k in const ['giorni', 'ora_inizio', 'ora_fine']) TextEditingController(text: '${o[k] ?? ''}')],
  ];
  String? _errore;

  @override
  void dispose() {
    for (final c in [..._c.values, for (final r in _orari) ...r]) {
      c.dispose();
    }
    super.dispose();
  }

  Map<String, dynamic>? _struttura(Object? id) => widget.strutture.where((s) => s['id'] == id).firstOrNull;

  String _orariTesto(Object? orari) => (orari as List? ?? const [])
      .cast<Map>()
      .map((o) => '${o['giorni']} dalle ${o['ora_inizio']} alle ${o['ora_fine']}')
      .join('; ');

  // --- pezzi della finestra ---

  Widget _titolo(String testo) => Padding(
        padding: const EdgeInsets.only(top: 16, bottom: 8),
        child: Semantics(header: true, child: Text(testo, style: Theme.of(context).textTheme.titleSmall)),
      );

  Widget _testo(String k, String etichetta, {int righe = 1, String? aiuto}) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: TextField(
          controller: _c[k],
          minLines: righe == 1 ? 1 : 2,
          maxLines: righe,
          decoration: InputDecoration(labelText: etichetta, helperText: aiuto, helperMaxLines: 3),
        ),
      );

  Widget _siNo(String k, String etichetta, {ValueChanged<String?>? cambiato}) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: DropdownButtonFormField<String?>(
          initialValue: _v[k],
          decoration: InputDecoration(labelText: etichetta),
          items: const [
            DropdownMenuItem(value: null, child: Text('—')),
            DropdownMenuItem(value: 'SI', child: Text('Sì')),
            DropdownMenuItem(value: 'NO', child: Text('No')),
          ],
          onChanged: (v) => setState(() {
            _v[k] = v;
            cambiato?.call(v);
          }),
        ),
      );

  /// Scelta dell'ufficio dall'organigramma (ad albero, strutture attive e quella già scelta)
  /// e, sotto, i suoi recapiti: ognuno si può scrivere per questo procedimento.
  Widget _ufficio(String k, String etichetta, {required String vuota, Object? predefinita, required List<(String, String)> recapiti}) {
    final voci = alberoStrutture(widget.strutture).where((e) => e.$1['attiva'] != false || e.$1['id'] == _v[k]);
    final struttura = _struttura(_v[k] ?? predefinita);
    final tema = Theme.of(context);
    String? dallaStruttura(String attributo) {
      if (struttura == null) return null;
      final v = attributo == 'orari' ? _orariTesto(struttura['orari']) : (struttura[attributo] as String? ?? '');
      return v.trim().isEmpty ? null : v;
    }

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      DropdownButtonFormField<String?>(
        initialValue: _v[k],
        isExpanded: true,
        decoration: InputDecoration(labelText: etichetta, helperText: 'Scegli l\'ufficio dall\'organigramma'),
        items: [
          DropdownMenuItem(value: null, child: Text(vuota, overflow: TextOverflow.ellipsis)),
          for (final (s, livello) in voci)
            DropdownMenuItem(
              value: s['id'] as String,
              child: Padding(
                padding: EdgeInsets.only(left: 16.0 * livello),
                child: Text('${s['codice']} - ${s['descrizione']}', overflow: TextOverflow.ellipsis),
              ),
            ),
        ],
        onChanged: (v) => setState(() => _v[k] = v),
      ),
      if (struttura != null)
        Padding(
          padding: const EdgeInsets.only(left: 12, top: 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Dati dalla struttura; scrivi qui solo quelli diversi per questo procedimento.', style: tema.textTheme.bodySmall),
            const SizedBox(height: 8),
            for (final (campo, attributo) in recapiti)
              if (campo == 'orari')
                _orariProcedimento(dallaStruttura('orari'))
              else
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: TextField(
                    controller: _c[campo],
                    decoration: InputDecoration(
                      labelText: etichetteRecapitiArt35[campo]!.split(' - ').last.replaceFirstMapped(
                          RegExp(r'^.'), (m) => m.group(0)!.toUpperCase()),
                      isDense: true,
                      floatingLabelBehavior: FloatingLabelBehavior.always,
                      hintText: dallaStruttura(attributo),
                      helperText: dallaStruttura(attributo) == null
                          ? 'Manca nella struttura: scrivilo qui o completalo in Amministrazione → Strutture'
                          : 'Vuoto: quello della struttura',
                      helperStyle: dallaStruttura(attributo) == null ? TextStyle(color: tema.colorScheme.error) : null,
                    ),
                  ),
                ),
          ]),
        ),
      const SizedBox(height: 8),
    ]);
  }

  Widget _orariProcedimento(String? dallaStruttura) {
    final tema = Theme.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('Orari di apertura al pubblico', style: tema.textTheme.labelLarge),
      Text(
        _orari.isNotEmpty
            ? 'Orari propri di questo procedimento.'
            : dallaStruttura == null
                ? 'La struttura non ha orari: aggiungili qui o in Amministrazione → Strutture.'
                : 'Dalla struttura: $dallaStruttura',
        style: tema.textTheme.bodySmall?.copyWith(color: _orari.isEmpty && dallaStruttura == null ? tema.colorScheme.error : null),
      ),
      for (final (n, riga) in _orari.indexed)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(children: [
            Expanded(
              flex: 3,
              child: TextField(controller: riga[0], decoration: const InputDecoration(labelText: 'Giorni', isDense: true)),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: TextField(controller: riga[1], decoration: const InputDecoration(labelText: 'Dalle', hintText: '09:00', isDense: true)),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: TextField(controller: riga[2], decoration: const InputDecoration(labelText: 'Alle', hintText: '12:30', isDense: true)),
            ),
            IconButton(
              tooltip: 'Togli la fascia oraria',
              icon: const Icon(Icons.delete_outline, size: 18),
              onPressed: () => setState(() {
                for (final c in _orari.removeAt(n)) {
                  WidgetsBinding.instance.addPostFrameCallback((_) => c.dispose());
                }
              }),
            ),
          ]),
        ),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(
          icon: const Icon(Icons.add, size: 18),
          label: Text(_orari.isEmpty ? 'Orari diversi per questo procedimento' : 'Aggiungi una fascia oraria'),
          onPressed: () => setState(() => _orari.add([TextEditingController(), TextEditingController(), TextEditingController()])),
        ),
      ),
      const SizedBox(height: 8),
    ]);
  }

  void _salva() {
    final istanza = _v['istanza_di_parte'] == 'SI';
    String? t(String k) => _c[k]!.text.trim().isEmpty ? null : _c[k]!.text.trim();
    for (final (k, etichetta) in [
      if (istanza) ('ist_modulistica', 'Atti e modulistica'),
      ('servizio_online_link', 'Servizio online'),
      ('link_pagamenti', 'Modalità di pagamento'),
    ]) {
      final v = t(k);
      if (v != null && !_reUrl.hasMatch(v)) return setState(() => _errore = '$etichetta: il link deve iniziare con http:// o https://');
    }
    final orari = [
      if (istanza)
        for (final r in _orari)
          if (r.any((c) => c.text.trim().isNotEmpty)) {'giorni': r[0].text.trim(), 'ora_inizio': r[1].text.trim(), 'ora_fine': r[2].text.trim()},
    ];
    if (orari.any((o) => o.values.any((v) => v.isEmpty))) {
      return setState(() => _errore = 'Orari: per ogni fascia indica giorni, ora di inizio e ora di fine');
    }
    bool tenuto(String k) =>
        (istanza || !(k.startsWith('ist_') || k == 'orari')) && (_finaleDiverso || !k.startsWith('uff_finale_'));
    final risultato = <String, dynamic>{
      for (final k in _c.keys)
        if (tenuto(k) && t(k) != null) k: t(k),
      for (final k in _scelte)
        if (tenuto(k) && _v[k] != null) k: _v[k],
      if (orari.isNotEmpty) 'orari': orari,
    };
    Navigator.pop(context, risultato);
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.procedimento;
    final tema = Theme.of(context);
    final responsabile = _struttura(p['struttura_id']);
    final dalProcedimento = [
      ('Denominazione', p['denominazione']),
      ('Breve descrizione', p['descrizione']),
      ('Riferimenti normativi', p['norma_riferimento']),
      ('Termine di conclusione', p['termine_conclusione']),
      ('Unità responsabile dell\'istruttoria', responsabile == null ? null : '${responsabile['codice']} - ${responsabile['descrizione']}'),
    ];
    return AlertDialog(
      title: const Text('Dati per la trasparenza (art. 35)'),
      content: SizedBox(
        width: 640,
        child: SingleChildScrollView(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
            _titolo('Dati sul procedimento'),
            _testo('tipologia', 'Tipologia di procedimento', aiuto: 'es. Autorizzazioni, Contributi economici, Certificazioni'),
            if (p.isNotEmpty) ...[
              Text('Dal procedimento (si modificano con "Modifica" del procedimento):', style: tema.textTheme.bodySmall),
              for (final (etichetta, valore) in dalProcedimento)
                Text('• $etichetta: ${valore == null || '$valore'.trim().isEmpty ? 'manca' : valore}', style: tema.textTheme.bodySmall),
            ],

            _titolo('Ufficio responsabile del procedimento'),
            _ufficio('uff_resp_struttura_id', 'Ufficio responsabile del procedimento',
                vuota: responsabile == null ? 'La struttura responsabile del procedimento' : 'La struttura responsabile: ${responsabile['codice']} - ${responsabile['descrizione']}',
                predefinita: p['struttura_id'],
                recapiti: const [('uff_resp_tel', 'telefono'), ('uff_resp_peo', 'peo'), ('uff_resp_pec', 'pec')]),

            _titolo('Ufficio competente all\'adozione del provvedimento finale'),
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: DropdownButtonFormField<bool>(
                initialValue: _finaleDiverso,
                decoration: const InputDecoration(labelText: 'L\'ufficio competente per il provvedimento finale è diverso?'),
                items: const [
                  DropdownMenuItem(value: false, child: Text('No, è lo stesso ufficio responsabile')),
                  DropdownMenuItem(value: true, child: Text('Sì')),
                ],
                onChanged: (v) => setState(() => _finaleDiverso = v ?? false),
              ),
            ),
            if (_finaleDiverso)
              _ufficio('uff_finale_struttura_id', 'Ufficio competente per il provvedimento finale', vuota: '—', recapiti: const [
                ('uff_finale_resp', 'responsabile'), ('uff_finale_tel', 'telefono'), ('uff_finale_peo', 'peo'), ('uff_finale_pec', 'pec'),
              ]),

            _titolo('Procedimento a istanza di parte'),
            _siNo('istanza_di_parte', 'Procedimento a istanza di parte?'),
            if (_v['istanza_di_parte'] == 'SI') ...[
              _ufficio('ist_struttura_id', 'Ufficio cui rivolgersi per informazioni e istanze', vuota: '—', recapiti: const [
                ('ist_indirizzo', 'sede'), ('ist_telefono', 'telefono'), ('ist_peo', 'peo'), ('ist_pec', 'pec'), ('orari', 'orari'),
              ]),
              _testo('ist_modulistica', 'Atti e modulistica (link)', aiuto: 'Link a atti, documenti, modulistica e fac-simile di autocertificazione'),
            ],

            _titolo('Informazioni, termini e tutele'),
            _testo('modalita_info', 'Modalità per ottenere informazioni sui procedimenti in corso', righe: 3),
            _siNo('dichiarazione_sostitutiva', 'Provvedimento sostituibile da dichiarazione dell\'interessato'),
            _siNo('silenzio_assenso', 'Silenzio assenso'),
            _testo('strumenti_tutela', 'Strumenti di tutela a favore dell\'interessato e modi per attivarli', righe: 3),
            _testo('servizio_online_link', 'Link di accesso al servizio online'),
            _testo('servizio_online_tempi', 'Tempi previsti per l\'attivazione del servizio online', aiuto: 'Solo se il servizio online non è ancora disponibile'),
            _testo('link_pagamenti', 'Modalità per effettuare i pagamenti (link)', aiuto: 'Pagina con le informazioni sui pagamenti (art. 36)'),

            _titolo('Potere sostitutivo in caso di inerzia'),
            _ufficio('sost_struttura_id', 'Ufficio del titolare del potere sostitutivo', vuota: '—', recapiti: const [
              ('sost_nominativo', 'responsabile'), ('sost_qualifica', 'qualifica'), ('sost_tel', 'telefono'), ('sost_peo', 'peo'),
              ('sost_pec', 'pec'),
            ]),
            _testo('sost_attivazione', 'Modalità per attivare il potere sostitutivo', righe: 3),
            if (_errore != null)
              Padding(padding: const EdgeInsets.only(top: 8), child: Text(_errore!, style: TextStyle(color: tema.colorScheme.error))),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FilledButton(onPressed: _salva, child: const Text('Salva')),
      ],
    );
  }
}

/// Scheda del procedimento con tutti i dati dell'allegato 11, divisa nelle sue sezioni.
/// Link e indirizzi email si possono cliccare.
class SchedaArt35 extends StatelessWidget {
  const SchedaArt35(this.scheda, {super.key});

  final Map<String, dynamic> scheda;

  String _v(String k) => (scheda[k] as String?)?.trim() ?? '';

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    String siNo(String k) => switch (_v(k)) { 'SI' => 'Sì', 'NO' => 'No', _ => '' };
    Widget riga(String etichetta, String valore) => Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(etichetta, style: tema.textTheme.labelMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
            valore.isEmpty ? const Text('—') : TestoAssistenza(valore),
          ]),
        );
    Widget sezione(String titolo, List<Widget> righe) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Semantics(header: true, headingLevel: 3, child: Text(titolo, style: tema.textTheme.titleSmall)),
            const SizedBox(height: 6),
            ...righe,
          ]),
        );
    List<Widget> recapiti(String p) => [
          riga('Telefono', _v('${p}_tel')),
          riga('PEO', _v('${p}_peo')),
          riga('PEC', _v('${p}_pec')),
        ];
    final orari = (scheda['orari'] as List? ?? const []).cast<Map>();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      sezione('Dati sul procedimento', [
        riga('Tipologia', _v('tipologia')),
        riga('Denominazione', _v('denominazione')),
        riga('Breve descrizione', _v('descrizione')),
        riga('Riferimenti normativi', _v('riferimenti_normativi')),
        riga('Unità organizzativa responsabile dell\'istruttoria', _v('unita_istruttoria')),
      ]),
      sezione('Ufficio responsabile del procedimento', [riga('Ufficio', _v('uff_resp_denom')), ...recapiti('uff_resp')]),
      sezione('Ufficio competente all\'adozione del provvedimento finale', [
        if (_v('ufficio_finale_diverso') == 'SI') ...[
          riga('Ufficio', _v('uff_finale_denom')),
          riga('Responsabile', _v('uff_finale_resp')),
          ...recapiti('uff_finale'),
        ] else
          const Text('Lo stesso ufficio responsabile del procedimento.'),
      ]),
      sezione('Procedimento a istanza di parte', [
        if (_v('istanza_di_parte') == 'SI') ...[
          riga('Ufficio cui rivolgersi per informazioni e istanze', _v('ist_ufficio')),
          riga('Indirizzo', _v('ist_indirizzo')),
          riga('Telefono', _v('ist_telefono')),
          riga('PEO', _v('ist_peo')),
          riga('PEC', _v('ist_pec')),
          riga('Atti e modulistica', _v('ist_modulistica')),
          riga('Orari di apertura al pubblico',
              orari.map((o) => '${o['giorni']}: dalle ${o['ora_inizio']} alle ${o['ora_fine']}').join('\n')),
        ] else
          Text(_v('istanza_di_parte') == 'NO' ? 'Il procedimento non è a istanza di parte.' : '—'),
      ]),
      sezione('Informazioni, termini e tutele', [
        riga('Come avere informazioni sui procedimenti in corso', _v('modalita_info')),
        riga('Termine di conclusione e altri termini rilevanti', _v('termine_conclusione')),
        riga('Provvedimento sostituibile da dichiarazione dell\'interessato', siNo('dichiarazione_sostitutiva')),
        riga('Silenzio assenso', siNo('silenzio_assenso')),
        riga('Strumenti di tutela e modi per attivarli', _v('strumenti_tutela')),
        riga('Servizio online',
            _v('servizio_online_link').isNotEmpty ? _v('servizio_online_link') : _v('servizio_online_tempi').isEmpty ? '' : 'Attivazione prevista: ${_v('servizio_online_tempi')}'),
        riga('Modalità per effettuare i pagamenti', _v('link_pagamenti')),
      ]),
      sezione('Potere sostitutivo in caso di inerzia', [
        riga('Titolare', _v('sost_nominativo')),
        riga('Qualifica', _v('sost_qualifica')),
        riga('Ufficio', _v('sost_ufficio')),
        ...recapiti('sost'),
        riga('Modalità di attivazione', _v('sost_attivazione')),
      ]),
    ]);
  }
}

/// Indicatore di completezza dei dati art. 35 di un procedimento.
class CompletezzaArt35 extends StatelessWidget {
  const CompletezzaArt35(this.mancanti, {super.key});

  final int mancanti;

  @override
  Widget build(BuildContext context) {
    final colore = mancanti == 0 ? Colors.green : Colors.orange;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: colore.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colore.withValues(alpha: 0.6)),
      ),
      child: Text(mancanti == 0 ? 'Art. 35 completo' : 'Art. 35: ${mancanti == 1 ? 'manca 1 dato' : 'mancano $mancanti dati'}',
          style: TextStyle(color: colore.shade800, fontSize: 12, fontWeight: FontWeight.w600)),
    );
  }
}

/// Sezione del procedimento nella mappatura: completezza, dati mancanti e scheda; con
/// [onModifica] il pulsante per modificare (o proporre di modificare) i dati.
class SezioneArt35 extends StatelessWidget {
  const SezioneArt35({super.key, required this.scheda, required this.mancanti, this.onModifica, this.etichettaModifica = 'Modifica'});

  final Map<String, dynamic> scheda;
  final List<String> mancanti;
  final VoidCallback? onModifica;
  final String etichettaModifica;

  @override
  Widget build(BuildContext context) => Sezione(
        titolo: 'Dati per la trasparenza (art. 35 d.lgs. 33/2013)',
        azioni: [
          if (onModifica != null)
            TextButton.icon(icon: const Icon(Icons.edit_outlined, size: 18), label: Text(etichettaModifica), onPressed: onModifica),
        ],
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          CompletezzaArt35(mancanti.length),
          if (mancanti.isNotEmpty)
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                dense: true,
                tilePadding: EdgeInsets.zero,
                title: const Text('Dati mancanti o da correggere'),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                children: [for (final m in mancanti) Text('• $m')],
              ),
            ),
          const SizedBox(height: 8),
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              dense: true,
              tilePadding: EdgeInsets.zero,
              title: const Text('Scheda del procedimento (allegato 11)'),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [SchedaArt35(scheda)],
            ),
          ),
        ]),
      );
}
