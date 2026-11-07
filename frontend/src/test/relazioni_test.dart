import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/relazioni/relazioni.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Relazioni: si prepara la bozza (dati e tabelle dal sistema), il modello scrive il testo di
/// una sezione con i numeri da verificare, si esporta la bozza rivista.
void main() {
  testWidgets('bozza, testo con i numeri da verificare, esportazione', (tester) async {
    tester.view.physicalSize = const Size(1400, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    Map<String, dynamic>? esportata;
    final client = MockClient((r) async {
      http.Response json(Object corpo) => http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
      final p = r.url.path;
      if (p == '/api/v1/relazioni') {
        return json([
          {'id': 'RPCT', 'titolo': 'Relazione annuale del RPCT', 'piao': false},
          {'id': 'PERFORMANCE', 'titolo': 'Relazione sulla performance', 'piao': true},
        ]);
      }
      if (p == '/api/v1/relazioni/RPCT') {
        return json({
          'tipo': 'RPCT', 'titolo': 'Relazione annuale del RPCT', 'sottotitolo': 'Anno ${r.url.queryParameters['anno']}',
          'ente': 'Comune di Prova',
          'sezioni': [
            {'id': 'mappatura', 'titolo': 'Mappatura dei processi', 'dati': {'rischi': 2},
             'tabelle': [{'titolo': 'Rischi per area', 'intestazioni': ['Area', 'Rischi'], 'righe': [['A - Personale', 2]]}]},
          ],
        });
      }
      if (p == '/api/v1/relazioni/RPCT/testo') {
        return json({'sezione': 'mappatura', 'testo': 'Sono stati mappati 2 rischi e 9 misure.', 'numeri_da_verificare': ['9']});
      }
      if (p == '/api/v1/relazioni/esporta') {
        esportata = jsonDecode(r.body) as Map<String, dynamic>;
        return http.Response('DOCX', 200);
      }
      return json(const []);
    });
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: ApiClient('http://prova', client: client),
      child: const MaterialApp(home: Scaffold(body: RelazioniTab(tipi: ['RPCT']))),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Relazione'), findsNothing); // una sola relazione nel modulo: niente scelta

    await tester.tap(find.text('Prepara la bozza'));
    await tester.pumpAndSettle();
    expect(find.text('Comune di Prova - Anno ${DateTime.now().year}'), findsOneWidget);
    expect(find.text('Rischi per area'), findsOneWidget);
    expect(find.text('A - Personale'), findsOneWidget);

    await tester.tap(find.text('Scrivi il testo'));
    await tester.pumpAndSettle();
    expect(find.text('Sono stati mappati 2 rischi e 9 misure.'), findsOneWidget);
    expect(find.textContaining('Numeri da verificare (non compaiono nei dati): 9'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextField, 'Testo della sezione'), 'Testo rivisto.');
    await tester.tap(find.text('Scarica DOCX'));
    await tester.pumpAndSettle();
    expect(esportata?['formato'], 'docx');
    expect(((esportata?['sezioni'] as List).first as Map)['testo'], 'Testo rivisto.');
  });
}
