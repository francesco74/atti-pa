import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/anticorruzione/importa_procedimenti.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Importazione dei procedimenti dal sito AT: si avvia la lettura, si attende il worker, si
/// rivedono abbinamenti, uffici e dati; si salva aggiornando quello esistente (la denominazione
/// della mappatura resta) e creando quello nuovo.
void main() {
  testWidgets('dal sito alla mappatura, con la revisione', (tester) async {
    tester.view.physicalSize = const Size(1400, 2600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final scritti = <String, Map<String, dynamic>>{};
    final client = MockClient((r) async {
      http.Response json(Object corpo, [int stato = 200]) =>
          http.Response(jsonEncode(corpo), stato, headers: {'content-type': 'application/json'});
      final p = r.url.path;
      if (r.method == 'POST' && p.endsWith('/procedimenti/importazioni')) return json({'id': 'l1', 'stato': 'IN_CODA'}, 202);
      if (p.endsWith('/procedimenti/importazioni/l1')) {
        return json({
          'id': 'l1', 'stato': 'COMPLETATA', 'avvisi': ['Orari non trovati'],
          'procedimenti': [
            {
              'elemento': {'denominazione': 'Assegnazione alloggi di ERP', 'tipologia': 'Concessioni', 'silenzio_assenso': 'NO',
                           'uff_resp_denom': 'Politiche abitative'},
              'procedimento_id': 'p1', 'somiglianza': 0.9,
              'uffici': {'uff_resp_struttura_id': {'nome': 'Politiche abitative', 'struttura_id': 's1'}},
            },
            {'elemento': {'denominazione': 'Contributo morosità', 'termine_conclusione': '60 giorni'},
             'procedimento_id': null, 'somiglianza': 0.3, 'uffici': {}},
          ],
        });
      }
      if (r.method == 'GET' && p.endsWith('/processi')) {
        return json([
          {'id': 'p1', 'codice': 'A.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'a', 'denominazione': 'Assegnazione alloggi ERP',
           'descrizione': null, 'struttura_id': null, 'art35': {'modalita_info': 'Allo sportello'}},
        ]);
      }
      if (r.method == 'PUT' || r.method == 'POST') {
        scritti['${r.method} $p'] = jsonDecode(r.body) as Map<String, dynamic>;
        return json({'id': 'nuovo'}, r.method == 'POST' ? 201 : 200);
      }
      return json(const []);
    });
    final api = ApiClient('http://prova', client: client);
    final dati = DatiAnticorruzione(
      metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto']},
      aree: const [{'id': 'a', 'codice': 'A', 'descrizione': 'Casa', 'descrizione_breve': null}],
      strutture: const [{'id': 's1', 'codice': 'SETTORE 9', 'descrizione': 'Politiche abitative', 'attiva': true}],
      obblighi: const [],
    );
    await tester.pumpWidget(MultiProvider(
      providers: [Provider<ApiClient>.value(value: api), ChangeNotifierProvider(create: (_) => AuthState(api))],
      child: MaterialApp(home: ImportaProcedimentiPage(strutture: dati.strutture, aree: dati.aree)),
    ));
    await tester.enterText(find.byType(TextField), 'https://www.ente.it/at/tipologie-di-procedimento');
    await tester.pump();
    await tester.tap(find.text('Leggi i procedimenti'));
    await tester.pump();
    expect(find.textContaining('Lettura in corso'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();

    expect(find.text('Procedimenti trovati: 2. Per ciascuno scegli se aggiornarne uno della mappatura o crearne uno nuovo, '
        'gli uffici e i dati da prendere.'), findsOneWidget);
    expect(find.text('• Orari non trovati'), findsOneWidget);
    expect(find.text('Aggiorna A.1 - Assegnazione alloggi ERP'), findsOneWidget);
    expect(find.text('Nuovo procedimento'), findsWidgets);
    expect(find.text('Nella fonte: Concessioni'), findsOneWidget);
    expect(find.text('Ora: Allo sportello'), findsNothing); // la fonte non ha questo dato

    await tester.tap(find.text('Salva 2 procedimenti'));
    await tester.pumpAndSettle();
    final aggiornato = scritti['PUT /api/v1/anticorruzione/processi/p1']!;
    expect(aggiornato['denominazione'], 'Assegnazione alloggi ERP'); // resta quella della mappatura
    expect((aggiornato['art35'] as Map)['tipologia'], 'Concessioni');
    expect((aggiornato['art35'] as Map)['modalita_info'], 'Allo sportello'); // i dati presenti restano
    expect((aggiornato['art35'] as Map)['uff_resp_struttura_id'], 's1');
    final creato = scritti['POST /api/v1/anticorruzione/processi']!;
    expect((creato['denominazione'], creato['termine_conclusione'], creato['tipo']), ('Contributo morosità', '60 giorni', 'PROCEDIMENTO'));
    expect(find.text('Aggiornato'), findsOneWidget);
    expect(find.text('Creato'), findsOneWidget);
  });
}
