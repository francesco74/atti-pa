import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/pubblico/mappatura_pubblica.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Mappatura pubblica: senza accesso, dalle aree alle misure con la ricerca e senza alcun
/// pulsante di modifica; se l'ente non l'ha pubblicata, un messaggio.
void main() {
  Future<List<String>> apri(WidgetTester tester, {bool pubblicata = true}) async {
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final chiamate = <String>[];
    final client = MockClient((r) async {
      chiamate.add('${r.method} ${r.url.path}');
      if (!pubblicata) return http.Response(jsonEncode({'detail': 'Mappatura non pubblicata'}), 404);
      Object? corpo = const [];
      if (r.url.path.endsWith('/pubblico/mappatura')) {
        corpo = {
          'ente': {'nome': 'Comune di Prova', 'logo': false},
          'livelli': ['Basso', 'Alto'],
          'aree': [
            {'id': 'c', 'codice': 'C', 'descrizione': 'Contratti pubblici', 'descrizione_breve': null},
            {'id': 'd', 'codice': 'D', 'descrizione': 'Personale', 'descrizione_breve': null},
          ],
          'strutture': [
            {'id': 's1', 'codice': 'SETTORE 1', 'descrizione': 'Gare'},
          ],
        };
      } else if (r.url.path.endsWith('/processi')) {
        corpo = [
          {'id': 'p1', 'codice': 'C.1', 'tipo': 'PROCESSO', 'area_id': 'c', 'denominazione': 'Gare', 'struttura_id': 's1', 'attivita': 1, 'rischi': 1, 'misure': 1, 'livello_massimo': 'Alto'},
          {'id': 'p2', 'codice': 'D.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'd', 'denominazione': 'Concorsi', 'struttura_id': null, 'attivita': 0, 'rischi': 0, 'misure': 0, 'livello_massimo': null},
        ];
      } else if (r.url.path.endsWith('/processi/p1')) {
        corpo = {
          'id': 'p1', 'codice': 'C.1', 'tipo': 'PROCESSO', 'area_id': 'c', 'denominazione': 'Gare', 'struttura_id': 's1',
          'descrizione': 'Affidamento di lavori',
          'attivita': [
            {'id': 'a1', 'codice': 'C.1.1', 'descrizione': 'Bando', 'rischi': [
              {'id': 'r1', 'codice': 'C.1.1_R.1', 'evento': 'Bando su misura', 'fattore_abilitante': null, 'livello': 'Alto', 'misure': [
                {'id': 'm1', 'codice': 'C.1.1_R.1_M.1', 'descrizione': 'Doppia verifica', 'tipo': 'SPECIFICA', 'struttura_id': 's1', 'target': '100%'},
              ]},
            ]},
          ],
        };
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
    });
    final api = ApiClient('http://prova', client: client);
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => AuthState(api)),
      ],
      child: const MaterialApp(home: MappaturaPubblicaPage()),
    ));
    await tester.pumpAndSettle();
    return chiamate;
  }

  testWidgets('dalle aree alle misure, in sola lettura', (tester) async {
    final chiamate = await apri(tester);
    expect(find.text('Comune di Prova'), findsOneWidget);
    expect(find.text('C) Contratti pubblici'), findsOneWidget);

    // la ricerca trova il processo in tutte le aree
    await tester.enterText(find.byType(TextField), 'conc');
    await tester.pump();
    expect(find.text('D.1 - Concorsi'), findsOneWidget);
    expect(find.text('C) Contratti pubblici'), findsNothing);
    await tester.enterText(find.byType(TextField), '');
    await tester.pump();

    await tester.tap(find.text('C) Contratti pubblici'));
    await tester.pumpAndSettle();
    expect(find.text('C.1 - Gare'), findsOneWidget);
    expect(find.text('D.1 - Concorsi'), findsNothing);

    await tester.tap(find.text('C.1 - Gare'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Affidamento di lavori'), findsOneWidget);
    await tester.tap(find.text('C.1.1 - Bando'));
    await tester.pumpAndSettle();
    expect(find.text('Bando su misura'), findsOneWidget);
    expect(find.text('C.1.1_R.1_M.1 - Doppia verifica'), findsOneWidget);
    expect(find.textContaining('Responsabile: SETTORE 1 - Gare'), findsOneWidget);

    // nessun pulsante: solo lettura, solo le API pubbliche
    expect(find.byType(FilledButton), findsNothing);
    expect(find.byType(IconButton), findsNothing);
    expect(find.byIcon(Icons.edit_outlined), findsNothing);
    expect(chiamate.every((c) => c.startsWith('GET /api/v1/pubblico/')), isTrue, reason: '$chiamate');

    // il percorso riporta alle aree
    await tester.tap(find.text('Aree di rischio'));
    await tester.pumpAndSettle();
    expect(find.text('D) Personale'), findsOneWidget);
  });

  testWidgets('mappatura non pubblicata', (tester) async {
    await apri(tester, pubblicata: false);
    expect(find.text('La mappatura dei processi di questo ente non è pubblicata.'), findsOneWidget);
  });
}
