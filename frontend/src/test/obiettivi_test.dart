import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/anticorruzione/obiettivi.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Scheda obiettivi: si sceglie il PIAO in alto, sotto compaiono gli obiettivi; aprendone
/// uno, processi e attività collegati si gestiscono nella scheda stessa.
void main() {
  testWidgets('PIAO, obiettivi e dettaglio nella stessa scheda', (tester) async {
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    String? collegamento;
    final client = MockClient((r) async {
      Object? corpo = const [];
      if (r.method == 'POST') {
        collegamento = r.body;
      } else if (r.url.path.endsWith('/processi')) {
        corpo = [
          {'id': 'x', 'codice': 'C.1', 'area_id': 'ac', 'denominazione': 'Gare'},
          {'id': 'y', 'codice': 'C.2', 'area_id': 'ac', 'denominazione': 'Affidamenti'},
        ];
      } else if (r.url.path.endsWith('/processi/x')) {
        corpo = {'attivita': const []};
      } else if (r.url.path.endsWith('/processi/y')) {
        corpo = {
          'attivita': [
            {'id': 'a1', 'codice': 'C.2.1', 'descrizione': 'Scelta del contraente'},
          ],
        };
      } else if (r.url.path.endsWith('/piao')) {
        corpo = [
          {'id': 'p2', 'anno_inizio': 2026, 'anno_fine': 2028, 'descrizione': 'PIAO 2026-2028', 'atto': 'DGC 59'},
          {'id': 'p1', 'anno_inizio': 2025, 'anno_fine': 2027, 'descrizione': 'PIAO 2025-2027', 'atto': null},
        ];
      } else if (r.url.path.endsWith('/piao/p2/obiettivi')) {
        corpo = [
          {'id': 'o1', 'codice': 'OB.1', 'anno': 2026, 'titolo': 'Primo obiettivo', 'tipo': 'Operativo', 'struttura_id': null, 'centro_piano': null, 'collegamenti': 2},
        ];
      } else if (r.url.path.endsWith('/piao/p1/obiettivi')) {
        corpo = [
          {'id': 'o2', 'codice': 'OB.9', 'anno': 2025, 'titolo': 'Obiettivo vecchio', 'tipo': null, 'struttura_id': null, 'centro_piano': null, 'collegamenti': 0},
        ];
      } else if (r.url.path.endsWith('/obiettivi/o1')) {
        corpo = {
          'id': 'o1', 'codice': 'OB.1', 'anno': 2026, 'titolo': 'Primo obiettivo', 'tipo': null, 'struttura_id': null,
          'centro_piano': null, 'responsabile': null,
          'collegamenti': [
            {'id': 'c', 'tipo': 'processo', 'elemento_id': 'x', 'codice': 'C.1', 'descrizione': 'Gare', 'processo': 'C.1', 'processo_id': 'x'},
          ],
        };
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
    });
    final api = ApiClient('http://prova', client: client);
    final dati = DatiAnticorruzione(metodologia: const {}, aree: const [
      {'id': 'ac', 'codice': 'C', 'descrizione': 'Contratti pubblici', 'descrizione_breve': null},
    ], strutture: const [], obblighi: const []);
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => AuthState(api)),
        Provider.value(value: dati),
      ],
      child: const MaterialApp(home: Scaffold(body: ObiettiviTab())),
    ));
    await tester.pumpAndSettle();

    // il PIAO più recente è già scelto e i suoi obiettivi sono sotto
    expect(find.text('Obiettivi di PIAO 2026-2028'), findsOneWidget);
    expect(find.text('OB.1 (2026) - Primo obiettivo'), findsOneWidget);
    expect(find.textContaining('2 collegamenti'), findsOneWidget);

    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('PIAO 2025-2027').last);
    await tester.pumpAndSettle();
    expect(find.text('OB.9 (2025) - Obiettivo vecchio'), findsOneWidget);
    expect(find.text('OB.1 (2026) - Primo obiettivo'), findsNothing);

    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('PIAO 2026-2028').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('OB.1 (2026) - Primo obiettivo'));
    await tester.pumpAndSettle();
    expect(find.text('Processi e attività collegati'), findsOneWidget);
    expect(find.text('C.1 - Gare'), findsOneWidget);

    // albero area -> processo -> attività; il processo già collegato non si può scegliere
    await tester.tap(find.text('Collega un processo o un\'attività'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('C) Contratti pubblici'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('C.1 - Gare').last);
    await tester.pumpAndSettle();
    expect(find.text('Già collegato'), findsOneWidget);
    await tester.tap(find.text('C.2 - Affidamenti'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Attività C.2.1 - Scelta del contraente'));
    await tester.pumpAndSettle();
    expect(jsonDecode(collegamento!), {'attivita_id': 'a1'});

    await tester.tap(find.text('Tutti gli obiettivi'));
    await tester.pumpAndSettle();
    expect(find.textContaining('2 collegamenti'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
