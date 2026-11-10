import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/performance/performance_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Performance: il responsabile vede gli obiettivi della sua struttura nell'anno con il totale
/// degli impegni e i nuovi obiettivi proposti, apre un obiettivo con azioni, misure, ritardi e
/// storico, propone modifiche (bozza, poi invio); gli indicatori mostrano target e valore
/// rilevato, che si aggiorna con l'avanzamento; l'approvatore decide le proposte; la scheda
/// PIAO c'è solo per l'amministratore.
final _schedaPiao = find.descendant(of: find.byType(TabBar), matching: find.text('PIAO'));

void main() {
  final corpi = <String, Object?>{}; // corpo delle richieste, per metodo e percorso

  Future<List<String>> apri(WidgetTester tester, {bool amministratore = false, bool approvatore = false}) async {
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final chiamate = <String>[];
    final anno = DateTime.now().year;
    corpi.clear();
    final client = MockClient((r) async {
      chiamate.add('${r.method} ${r.url.path}${r.url.query.isEmpty ? '' : '?${r.url.query}'}');
      if (r.body.isNotEmpty) corpi['${r.method} ${r.url.path}'] = jsonDecode(r.body);
      final p = r.url.path;
      Object? corpo = const [];
      final proposta = {
        'id': 'pr1', 'tipo': 'MODIFICA', 'stato': approvatore ? 'INVIATA' : 'BOZZA', 'piao_id': 'piao', 'anno': anno,
        'struttura_id': 'uo', 'obiettivo_id': 'o1', 'titolo': 'P2_OS3 - Digitalizzare i concorsi', 'impegno': 60,
        'nota': null, 'motivazione': null, 'autore': approvatore ? 'Responsabile' : null,
        'created_at': '$anno-03-01T10:00:00', 'inviata_il': null, 'decisa_il': null,
        'piao': {'id': 'piao', 'titolo': 'PIAO $anno', 'stato': 'APERTO'},
        'dati': {'codice': 'P2_OS3', 'titolo': 'Digitalizzare i concorsi', 'descrizione': null, 'tipo': 'OPERATIVO', 'impegno': 60,
          'elementi': [
            {'id': 'e1', 'tipo': 'AZIONE', 'descrizione': 'Piattaforma online', 'misura_id': null, 'misura_codice': null,
             'impegno': 70, 'scadenza': '$anno-06-30', 'indicatori': [
               {'id': 'i1', 'descrizione': 'Servizi online', 'tipo': 'NUMERO', 'unita': 'servizi', 'partenza': null, 'target': 5,
                'target_data': null, 'verso': 'CRESCENTE', 'fonte': null}]},
            {'id': 'nuovo-1', 'tipo': 'AZIONE', 'descrizione': 'Formazione', 'misura_id': null, 'misura_codice': null,
             'impegno': 30, 'scadenza': '$anno-09-30'},
          ]},
        'prima': {'codice': 'P2_OS3', 'titolo': 'Digitalizzare i concorsi', 'descrizione': null, 'tipo': 'OPERATIVO', 'impegno': 60,
          'elementi': [
            {'id': 'e1', 'tipo': 'AZIONE', 'descrizione': 'Piattaforma online', 'misura_id': null, 'misura_codice': null,
             'impegno': 60, 'scadenza': '$anno-06-30'},
            {'id': 'e2', 'tipo': 'MISURA', 'descrizione': 'Rotazione dei commissari', 'misura_id': 'm1', 'misura_codice': 'A.1.1_R.1_M.1',
             'impegno': 40, 'scadenza': '$anno-12-31'},
          ]},
        'confronto': {'obiettivo': {}, 'elementi': [
          {'id': 'e1', 'stato': 'MODIFICATO', 'campi': {'impegno': [60, 70],
            'indicatori': [['Servizi online: 3 servizi'], ['Servizi online: 5 servizi']]}},
          {'id': 'nuovo-1', 'stato': 'NUOVO', 'campi': {}},
          {'id': 'e2', 'stato': 'ELIMINATO', 'campi': {}},
        ]},
        'impegno_elementi': 100, 'disponibile': 100, 'controlli': [], 'cambiato': false, 'eliminato': false,
        'modificabile': !approvatore, 'inviabile': !approvatore, 'ritirabile': false, 'scartabile': !approvatore,
        'decidibile': approvatore,
      };
      if (p.endsWith('/contesto')) {
        corpo = {'amministratore': amministratore, 'approvatore': approvatore, 'da_decidere': approvatore ? 1 : 0,
                 'struttura_id': approvatore ? null : 'uo', 'visibili': approvatore ? null : ['uo'], 'misure': true};
      } else if (p.endsWith('/proposte/pr1') || p.endsWith('/proposte') && r.method == 'POST') {
        corpo = proposta;
      } else if (p.contains('/proposte/pr1/')) {
        corpo = {...proposta, 'stato': p.endsWith('/approva') ? 'APPROVATA' : 'INVIATA', 'modificabile': false,
                 'inviabile': false, 'decidibile': false};
      } else if (p.endsWith('/performance/proposte')) {
        corpo = [proposta];
      } else if (p.endsWith('/performance/piao')) {
        corpo = [
          {'id': 'piao', 'anno_inizio': anno, 'anni': [anno, anno + 1, anno + 2], 'titolo': 'PIAO $anno', 'atto': null, 'stato': 'APERTO'},
        ];
      } else if (p.endsWith('/ente/strutture')) {
        corpo = [
          {'id': 'uo', 'codice': 'U.O. 2.1', 'descrizione': 'Personale', 'attiva': true},
          {'id': 'altra', 'codice': 'SETTORE 3', 'descrizione': 'Lavori', 'attiva': true},
        ];
      } else if (p.endsWith('/performance/obiettivi')) {
        corpo = {
          'obiettivi': [
            {'id': 'o1', 'piao_id': 'piao', 'anno': anno, 'struttura_id': 'uo', 'codice': 'P2_OS3', 'titolo': 'Digitalizzare i concorsi',
             'tipo': 'OPERATIVO', 'impegno': 60, 'completamento': 65.0, 'impegno_elementi': 100, 'completo': true,
             'azioni': 1, 'misure': 1, 'ritardi': 1, 'avvisi': 1, 'modificabile': approvatore, 'proponibile': !approvatore,
             'avanzamento': true, 'proposta': null},
          ],
          'proposte': [
            {'id': 'pr2', 'tipo': 'CREA', 'stato': 'INVIATA', 'titolo': 'Formazione del personale', 'impegno': 40},
          ],
          'impegno_totale': 60, 'completo': false, 'completamento': 65.0, 'aggiunta': approvatore ? 'DIRETTA' : 'PROPOSTA',
        };
      } else if (p.endsWith('/obiettivi/o1')) {
        corpo = {
          'id': 'o1', 'piao_id': 'piao', 'anno': anno, 'struttura_id': 'uo', 'codice': 'P2_OS3', 'titolo': 'Digitalizzare i concorsi',
          'descrizione': null, 'tipo': 'OPERATIVO', 'impegno': 60, 'completamento': 65.0, 'impegno_elementi': 100, 'completo': true,
          'azioni': 1, 'misure': 1, 'ritardi': 1, 'modificabile': approvatore, 'proponibile': !approvatore, 'avanzamento': true,
          'proposta': null, 'piao': {'id': 'piao', 'stato': 'APERTO'},
          'controlli': [{'livello': 'AVVISO', 'testo': 'Azione «Piattaforma online»: impegno 0%, non conta nel completamento'}],
          'elementi': [
            {'id': 'e1', 'tipo': 'AZIONE', 'descrizione': 'Piattaforma online', 'misura_id': null, 'misura_codice': null,
             'impegno': 70, 'completamento': 67, 'scadenza': '$anno-01-01', 'in_ritardo': true, 'calcolato': true, 'indicatori': [
               {'id': 'i1', 'descrizione': 'Eventi a cui si partecipa', 'tipo': 'NUMERO', 'unita': 'eventi', 'partenza': null,
                'target': 3.0, 'target_data': null, 'verso': 'CRESCENTE', 'fonte': null, 'rilevato': 2.0, 'rilevato_data': null,
                'rilevato_il': '$anno-03-01T10:00:00', 'raggiungimento': 66.7, 'testo': 'Eventi a cui si partecipa: 3 eventi'},
             ]},
            {'id': 'e2', 'tipo': 'MISURA', 'descrizione': 'Rotazione dei commissari', 'misura_id': 'm1', 'misura_codice': 'A.1.1_R.1_M.1',
             'impegno': 30, 'completamento': 100, 'scadenza': '$anno-12-31', 'in_ritardo': false, 'calcolato': false,
             'indicatori': []},
          ],
        };
      } else if (p.endsWith('/storico')) {
        corpo = [
          {'id': 1, 'oggetto': 'AZIONE', 'azione': 'MODIFICATO', 'descrizione': 'Piattaforma online',
           'campi': {'completamento': [20, 50]}, 'nota': 'Avanzamento', 'utente': 'Responsabile', 'quando': '$anno-03-01T10:00:00'},
        ];
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
    });
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: ApiClient('http://prova', client: client),
      child: const MaterialApp(home: Scaffold(body: PerformancePage())),
    ));
    await tester.pumpAndSettle();
    return chiamate;
  }

  testWidgets('obiettivi della struttura, dettaglio e storico', (tester) async {
    final chiamate = await apri(tester);
    expect(_schedaPiao, findsNothing); // scheda solo per l'amministratore
    expect(chiamate.where((c) => c.contains('/performance/obiettivi?')).single, contains('struttura_id=uo'));
    expect(find.text('P2_OS3 - Digitalizzare i concorsi'), findsOneWidget);
    expect(find.text('Impegno assegnato: 60% su 100% (incompleto)'), findsOneWidget);
    expect(find.text('Proponi un nuovo obiettivo'), findsOneWidget);
    expect(find.text('Formazione del personale'), findsOneWidget); // nuovo obiettivo proposto
    expect(find.text('In attesa di approvazione'), findsOneWidget);
    expect(find.text('1 in ritardo'), findsOneWidget);
    expect(find.text('1 avviso'), findsOneWidget);

    await tester.tap(find.text('P2_OS3 - Digitalizzare i concorsi'));
    await tester.pumpAndSettle();
    expect(find.text('Piattaforma online'), findsOneWidget);
    expect(find.text('A.1.1_R.1_M.1 - Rotazione dei commissari'), findsOneWidget);
    expect(find.text('In ritardo'), findsOneWidget);
    expect(find.text('Impegno delle azioni e misure: 100%'), findsOneWidget);
    expect(find.text('65%'), findsWidgets);
    expect(find.textContaining('impegno 0%, non conta'), findsOneWidget); // controlli
    // il responsabile non modifica direttamente: propone e aggiorna l'avanzamento
    expect(find.text('Proponi modifiche'), findsOneWidget);
    expect(find.text('Proponi eliminazione'), findsOneWidget);
    expect(find.byTooltip('Modifica'), findsNothing);
    expect(find.byTooltip('Aggiorna l\'avanzamento'), findsNWidgets(2));

    await tester.tap(find.text('Storico delle modifiche'));
    await tester.pumpAndSettle();
    expect(find.textContaining('completamento: 20% → 50%'), findsOneWidget);
    expect(find.textContaining('Nota: Avanzamento'), findsOneWidget);

    // il percorso riporta all'elenco
    await tester.tap(find.textContaining('Obiettivi ${DateTime.now().year}'));
    await tester.pumpAndSettle();
    expect(find.text('Proponi un nuovo obiettivo'), findsOneWidget);
  });

  testWidgets('indicatori: target, valore rilevato e avanzamento', (tester) async {
    final chiamate = await apri(tester);
    await tester.tap(find.text('P2_OS3 - Digitalizzare i concorsi'));
    await tester.pumpAndSettle();
    expect(find.text('Eventi a cui si partecipa: 3 eventi · rilevato 2 eventi'), findsOneWidget);
    expect(find.text('raggiunto 66.7%'), findsOneWidget);
    expect(find.text('Senza indicatori'), findsOneWidget); // la misura

    // azione con indicatore: si inserisce il valore rilevato, non il completamento
    await tester.tap(find.byTooltip('Aggiorna l\'avanzamento').first);
    await tester.pumpAndSettle();
    expect(find.text('Completamento'), findsNothing);
    await tester.enterText(find.widgetWithText(TextField, 'Valore rilevato'), '3');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(chiamate, contains('PUT /api/v1/performance/elementi/e1/avanzamento'));
    expect(corpi['PUT /api/v1/performance/elementi/e1/avanzamento'], {
      'indicatori': [{'id': 'i1', 'rilevato': 3.0}],
    });

    // misura senza indicatori: il completamento a mano
    await tester.tap(find.byTooltip('Aggiorna l\'avanzamento').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Completamento'), '80');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(corpi['PUT /api/v1/performance/elementi/e2/avanzamento'], {'completamento': 80});
  });

  testWidgets('l\'approvatore aggiunge un\'azione con un indicatore', (tester) async {
    await apri(tester, approvatore: true);
    await tester.tap(find.text('P2_OS3 - Digitalizzare i concorsi'));
    await tester.pumpAndSettle();
    expect(find.text('Azione'), findsNothing); // impegni già al 100%: niente aggiunte
    expect(find.byTooltip('Aggiorna l\'avanzamento'), findsNWidgets(2)); // anche l'approvatore inserisce i valori rilevati
    await tester.tap(find.byTooltip('Modifica').first);
    await tester.pumpAndSettle();
    expect(find.text('Eventi a cui si partecipa: 3 eventi'), findsOneWidget);
    expect(find.text('Il completamento si calcola dai valori rilevati degli indicatori.'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Completamento'), findsNothing);

    // nuovo indicatore: senza target non si salva
    await tester.tap(find.widgetWithText(TextButton, 'Indicatore'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Cosa si misura *'), 'Partecipanti');
    await tester.tap(find.text('Salva').last);
    await tester.pumpAndSettle();
    expect(find.text('Indica il target (un numero)'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Unità di misura'), 'persone');
    await tester.enterText(find.widgetWithText(TextField, 'Target *'), '200');
    await tester.tap(find.text('Salva').last);
    await tester.pumpAndSettle();
    expect(find.text('Partecipanti: 200 persone'), findsOneWidget);
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    final corpo = corpi['PUT /api/v1/performance/elementi/e1'] as Map;
    expect(corpo['indicatori'], [
      {'id': 'i1', 'descrizione': 'Eventi a cui si partecipa', 'tipo': 'NUMERO', 'unita': 'eventi', 'partenza': null, 'target': 3.0,
       'target_data': null, 'verso': 'CRESCENTE', 'fonte': null},
      {'descrizione': 'Partecipanti', 'tipo': 'NUMERO', 'unita': 'persone', 'partenza': null, 'target': 200.0, 'target_data': null,
       'verso': 'CRESCENTE', 'fonte': null},
    ]);
    expect(corpo['completamento'], 67); // invariato: si calcola
  });

  testWidgets('il responsabile propone una modifica e la invia', (tester) async {
    final chiamate = await apri(tester);
    await tester.tap(find.text('P2_OS3 - Digitalizzare i concorsi'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Proponi modifiche'));
    await tester.pumpAndSettle();
    expect(chiamate, contains('POST /api/v1/performance/proposte'));
    // la bozza: cosa cambia rispetto all'obiettivo
    expect(find.text('In bozza'), findsOneWidget);
    expect(find.text('Modificata'), findsOneWidget);
    expect(find.text('Impegno: 60% → 70%'), findsOneWidget);
    expect(find.text('Servizi online: 5 servizi'), findsOneWidget); // indicatore proposto
    expect(find.text('Indicatori: Servizi online: 3 servizi → Servizi online: 5 servizi'), findsOneWidget);
    expect(find.text('Nuova'), findsOneWidget);
    expect(find.text('Tolta'), findsOneWidget);
    expect(find.text('Approva'), findsNothing);
    await tester.tap(find.text('Invia'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'Ripianificato');
    await tester.tap(find.text('Conferma'));
    await tester.pumpAndSettle();
    expect(chiamate, contains('POST /api/v1/performance/proposte/pr1/invia'));
    expect(find.text('In attesa di approvazione'), findsOneWidget);
  });

  testWidgets('l\'approvatore decide dalla scheda Proposte', (tester) async {
    final chiamate = await apri(tester, approvatore: true);
    expect(find.text('Nuovo obiettivo'), findsOneWidget); // aggiunta diretta
    expect(find.text('1'), findsOneWidget); // proposte da decidere
    await tester.tap(find.descendant(of: find.byType(TabBar), matching: find.text('Proposte')));
    await tester.pumpAndSettle();
    expect(chiamate.last, contains('stato=INVIATA'));
    await tester.tap(find.text('Modifica: P2_OS3 - Digitalizzare i concorsi'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Inviata da Responsabile'), findsOneWidget);
    expect(find.text('Invia'), findsNothing);
    await tester.tap(find.text('Restituisci'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Conferma'));
    await tester.pumpAndSettle();
    expect(find.text('Obbligatoria'), findsOneWidget); // la motivazione serve
    await tester.enterText(find.byType(TextField).last, 'Rivedi le scadenze');
    await tester.tap(find.text('Conferma'));
    await tester.pumpAndSettle();
    expect(chiamate, contains('POST /api/v1/performance/proposte/pr1/restituisci'));
  });

  testWidgets('l\'amministratore ha la scheda PIAO', (tester) async {
    await apri(tester, amministratore: true);
    await tester.tap(_schedaPiao);
    await tester.pumpAndSettle();
    expect(find.text('Nuovo PIAO'), findsOneWidget);
    expect(find.text('Chiudi'), findsOneWidget);
  });
}
