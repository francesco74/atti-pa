import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/anticorruzione/mappatura.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Mappatura un livello alla volta: aree, processi, attività, rischi e misure; il percorso
/// riporta indietro e la ricerca trova i processi in tutte le aree.
void main() {
  testWidgets('dalle aree alle misure, e ritorno', (tester) async {
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final client = MockClient((r) async {
      Object? corpo = const [];
      if (r.url.path.endsWith('/processi')) {
        corpo = [
          {'id': 'p1', 'codice': 'C.1', 'area_id': 'c', 'denominazione': 'Gare', 'struttura_id': null, 'attivita': 1, 'rischi': 1, 'misure': 1, 'livello_massimo': 'Alto'},
          {'id': 'p2', 'codice': 'D.1', 'area_id': 'd', 'denominazione': 'Concorsi', 'struttura_id': null, 'attivita': 0, 'rischi': 0, 'misure': 0, 'livello_massimo': null},
        ];
      } else if (r.url.path.endsWith('/processi/p1')) {
        corpo = {
          'id': 'p1', 'codice': 'C.1', 'area_id': 'c', 'denominazione': 'Gare',
          'attivita': [
            {'id': 'a1', 'codice': 'C.1.1', 'descrizione': 'Bando', 'rischi': [
              {'id': 'r1', 'codice': 'C.1.1_R.1', 'evento': 'Bando su misura', 'valori_probabilita': null, 'misure': [
                {'id': 'm1', 'codice': 'C.1.1_R.1_M.1', 'descrizione': 'Doppia verifica', 'tipo': 'SPECIFICA'},
              ]},
            ]},
          ],
        };
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
    });
    final api = ApiClient('http://prova', client: client);
    final dati = DatiAnticorruzione(
      metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto']},
      aree: const [
        {'id': 'c', 'codice': 'C', 'descrizione': 'Contratti pubblici', 'descrizione_breve': null},
        {'id': 'd', 'codice': 'D', 'descrizione': 'Personale', 'descrizione_breve': null},
      ],
      strutture: const [],
      obblighi: const [],
    );
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => AuthState(api)),
        Provider.value(value: dati),
      ],
      child: MaterialApp(home: Scaffold(body: MappaturaTab(onDatiCambiati: () {}))),
    ));
    await tester.pumpAndSettle();

    // aree: nessun processo in vista finché non si apre un'area
    expect(find.text('C - Contratti pubblici'), findsOneWidget);
    expect(find.text('C.1 - Gare'), findsNothing);

    // la ricerca trova il processo in tutte le aree
    await tester.enterText(find.byType(TextField), 'conc');
    await tester.pump();
    expect(find.text('D.1 - Concorsi'), findsOneWidget);
    expect(find.text('C - Contratti pubblici'), findsNothing);
    await tester.enterText(find.byType(TextField), '');
    await tester.pump();

    await tester.tap(find.text('C - Contratti pubblici'));
    await tester.pumpAndSettle();
    expect(find.text('C.1 - Gare'), findsOneWidget);
    expect(find.text('D.1 - Concorsi'), findsNothing);

    // ricerca nei processi dell'area aperta
    await tester.enterText(find.widgetWithText(TextField, 'Cerca nell\'area (codice o denominazione)'), 'xyz');
    await tester.pump();
    expect(find.text('C.1 - Gare'), findsNothing);
    expect(find.text('Nessun processo trovato.'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Cerca nell\'area (codice o denominazione)'), 'gar');
    await tester.pump();
    expect(find.text('C.1 - Gare'), findsOneWidget);

    await tester.tap(find.text('C.1 - Gare'));
    await tester.pumpAndSettle();
    expect(find.text('C.1.1 - Bando'), findsOneWidget);
    expect(find.text('Bando su misura'), findsNothing);

    await tester.tap(find.text('C.1.1 - Bando'));
    await tester.pumpAndSettle();
    expect(find.text('Bando su misura'), findsOneWidget);
    expect(find.text('C.1.1_R.1_M.1 - Doppia verifica'), findsOneWidget);

    // il percorso riporta indietro di un livello alla volta
    await tester.tap(find.text('C.1 Gare'));
    await tester.pumpAndSettle();
    expect(find.text('Bando su misura'), findsNothing);
    await tester.tap(find.text('C - Contratti pubblici'));
    await tester.pumpAndSettle();
    expect(find.text('C.1 - Gare'), findsOneWidget);
    await tester.tap(find.text('Aree di rischio'));
    await tester.pumpAndSettle();
    expect(find.text('D - Personale'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
