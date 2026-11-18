import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/admin/strutture.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Finestra della struttura: i campi obbligatori si controllano prima di salvare e la finestra
/// si chiude solo se il salvataggio riesce; con un errore resta aperta, con i dati inseriti.
void main() {
  testWidgets('la finestra si chiude solo a salvataggio riuscito', (tester) async {
    tester.view.physicalSize = const Size(1200, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    var risposta = 409;
    final inviati = <Map>[];
    final api = ApiClient('http://prova', client: MockClient((r) async {
      if (r.method == 'POST') {
        inviati.add(jsonDecode(r.body) as Map);
        return risposta == 409
            ? http.Response(jsonEncode({'detail': 'Codice già usato'}), 409, headers: {'content-type': 'application/json'})
            : http.Response(jsonEncode({'id': 's9'}), 201, headers: {'content-type': 'application/json'});
      }
      return http.Response(jsonEncode([]), 200, headers: {'content-type': 'application/json'});
    }));
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: api,
      child: const MaterialApp(home: Scaffold(body: StrutturePage())),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Nuova struttura'));
    await tester.pumpAndSettle();

    // il codice è proposto (STR.n); tolto, niente invio e la finestra resta aperta
    expect(find.widgetWithText(TextField, 'STR.1'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'STR.1'), '');
    await tester.enterText(find.widgetWithText(TextField, 'Descrizione *'), 'Servizi tecnici');
    await tester.enterText(find.widgetWithText(TextField, 'Telefono'), '0583 123456');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Compila: codice'), findsOneWidget);
    expect(inviati, isEmpty);

    // errore del server: si legge nella finestra, i dati restano
    await tester.enterText(find.widgetWithText(TextField, 'Codice *'), 'SETTORE 2');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Codice già usato'), findsOneWidget);
    expect(find.widgetWithText(TextField, '0583 123456'), findsOneWidget);

    // salvataggio riuscito: la finestra si chiude
    risposta = 201;
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Salva'), findsNothing);
    expect((inviati.last['codice'], inviati.last['telefono']), ('SETTORE 2', '0583 123456'));
  });
}
