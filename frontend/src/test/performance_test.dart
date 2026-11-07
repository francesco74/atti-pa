import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/performance/performance_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Performance: il responsabile vede gli obiettivi della sua struttura nell'anno con il totale
/// degli impegni, apre un obiettivo con azioni, misure, ritardi e storico; la scheda PIAO
/// c'è solo per l'amministratore.
final _schedaPiao = find.descendant(of: find.byType(TabBar), matching: find.text('PIAO'));

void main() {
  Future<List<String>> apri(WidgetTester tester, {bool amministratore = false}) async {
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final chiamate = <String>[];
    final anno = DateTime.now().year;
    final client = MockClient((r) async {
      chiamate.add('${r.method} ${r.url.path}${r.url.query.isEmpty ? '' : '?${r.url.query}'}');
      final p = r.url.path;
      Object? corpo = const [];
      if (p.endsWith('/contesto')) {
        corpo = {'amministratore': amministratore, 'struttura_id': 'uo', 'visibili': ['uo'], 'misure': true};
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
             'azioni': 1, 'misure': 1, 'ritardi': 1, 'avvisi': 1, 'modificabile': true},
          ],
          'impegno_totale': 60, 'completo': false, 'completamento': 65.0, 'modificabile': true,
        };
      } else if (p.endsWith('/obiettivi/o1')) {
        corpo = {
          'id': 'o1', 'piao_id': 'piao', 'anno': anno, 'struttura_id': 'uo', 'codice': 'P2_OS3', 'titolo': 'Digitalizzare i concorsi',
          'descrizione': null, 'tipo': 'OPERATIVO', 'impegno': 60, 'completamento': 65.0, 'impegno_elementi': 100, 'completo': true,
          'azioni': 1, 'misure': 1, 'ritardi': 1, 'modificabile': true, 'piao': {'id': 'piao', 'stato': 'APERTO'},
          'controlli': [{'livello': 'AVVISO', 'testo': 'Azione «Piattaforma online»: impegno 0%, non conta nel completamento'}],
          'elementi': [
            {'id': 'e1', 'tipo': 'AZIONE', 'descrizione': 'Piattaforma online', 'misura_id': null, 'misura_codice': null,
             'impegno': 70, 'completamento': 50, 'scadenza': '$anno-01-01', 'in_ritardo': true},
            {'id': 'e2', 'tipo': 'MISURA', 'descrizione': 'Rotazione dei commissari', 'misura_id': 'm1', 'misura_codice': 'A.1.1_R.1_M.1',
             'impegno': 30, 'completamento': 100, 'scadenza': '$anno-12-31', 'in_ritardo': false},
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
    expect(find.text('Nuovo obiettivo'), findsOneWidget);
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

    await tester.tap(find.text('Storico delle modifiche'));
    await tester.pumpAndSettle();
    expect(find.textContaining('completamento: 20% → 50%'), findsOneWidget);
    expect(find.textContaining('Nota: Avanzamento'), findsOneWidget);

    // il percorso riporta all'elenco
    await tester.tap(find.textContaining('Obiettivi ${DateTime.now().year}'));
    await tester.pumpAndSettle();
    expect(find.text('Nuovo obiettivo'), findsOneWidget);
  });

  testWidgets('l\'amministratore ha la scheda PIAO', (tester) async {
    await apri(tester, amministratore: true);
    await tester.tap(_schedaPiao);
    await tester.pumpAndSettle();
    expect(find.text('Nuovo PIAO'), findsOneWidget);
    expect(find.text('Chiudi'), findsOneWidget);
  });
}
