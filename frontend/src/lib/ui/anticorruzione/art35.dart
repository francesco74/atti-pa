import 'package:flutter/material.dart';

import '../comuni.dart';
import 'comune.dart';

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
};

const _siNo = [(null, '—'), ('SI', 'Sì'), ('NO', 'No')];

/// Finestra dei dati art. 35 del procedimento: uffici scelti tra le strutture (con i loro
/// recapiti), il resto testo. Restituisce la mappa `art35` da salvare.
Future<Map<String, dynamic>?> modificaArt35(BuildContext context, DatiAnticorruzione d, Map<String, dynamic>? art35) {
  List<(String?, String)> strutture(String vuota) => [
        (null, vuota),
        for (final s in d.strutture)
          if (s['attiva'] != false) (s['id'] as String, '${s['codice']} - ${s['descrizione']}'),
      ];
  return modificaCampi(context, titolo: 'Dati per la trasparenza (art. 35)', valori: {...?art35}, campi: [
    const Campo('tipologia', 'Tipologia di procedimento', aiuto: 'es. Autorizzazioni, Contributi economici, Certificazioni'),
    Campo('uff_resp_struttura_id', 'Ufficio responsabile del procedimento',
        scelte: strutture('La struttura responsabile del procedimento'),
        aiuto: 'Recapiti (telefono, PEO, PEC) dalla struttura: Amministrazione → Strutture'),
    Campo('uff_finale_struttura_id', 'Ufficio competente per il provvedimento finale',
        scelte: strutture('Lo stesso ufficio responsabile'), aiuto: 'Solo se diverso; nome del responsabile e recapiti dalla struttura'),
    const Campo('istanza_di_parte', 'Procedimento a istanza di parte', scelte: _siNo),
    Campo('ist_struttura_id', 'Ufficio per informazioni e istanze',
        scelte: strutture('—'), aiuto: 'Solo a istanza di parte: sede, recapiti e orari dalla struttura'),
    const Campo('ist_modulistica', 'Atti e modulistica (link)', aiuto: 'Solo a istanza di parte: link a moduli e fac-simile'),
    const Campo('modalita_info', 'Come avere informazioni sui procedimenti in corso', righe: 3),
    const Campo('dichiarazione_sostitutiva', 'Provvedimento sostituibile da dichiarazione dell\'interessato', scelte: _siNo),
    const Campo('silenzio_assenso', 'Silenzio assenso', scelte: _siNo),
    const Campo('strumenti_tutela', 'Strumenti di tutela e modi per attivarli', righe: 3),
    const Campo('servizio_online_link', 'Servizio online (link)'),
    const Campo('servizio_online_tempi', 'Tempi previsti per attivare il servizio online', aiuto: 'Solo se non c\'è ancora'),
    const Campo('link_pagamenti', 'Modalità di pagamento (link)', aiuto: 'Pagina con le informazioni sui pagamenti (art. 36)'),
    Campo('sost_struttura_id', 'Ufficio del titolare del potere sostitutivo',
        scelte: strutture('—'), aiuto: 'Nominativo, qualifica e recapiti dal responsabile della struttura'),
    const Campo('sost_attivazione', 'Come attivare il potere sostitutivo', righe: 3),
  ]).then((v) => v == null ? null : {for (final e in v.entries) if (e.value != null) e.key: e.value});
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
