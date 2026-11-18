import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/anticorruzione/albero.dart';
import 'package:atti_pa/util/codici.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Codici proposti nelle finestre di creazione, che l'utente può cambiare.
void main() {
  test('il successivo della serie, ignorando gli altri codici', () {
    expect(prossimoCodice('STR.', const []), 'STR.1');
    expect(prossimoCodice('STR.', const ['SETTORE 2', 'STR.1', 'str.7', 'STR.3', null, 'STR.x']), 'STR.8');
    expect(prossimoCodice('DD_ACQUISTI_', const ['DD_ACQUISTI'], primo: 2), 'DD_ACQUISTI_2');
    expect(prossimoCodice('MODELLO_', const ['MODELLO_1', 'MODELLO_12']), 'MODELLO_13');
  });

  testWidgets('nuova area: il codice proposto dal sistema si può cambiare', (tester) async {
    final richieste = <String>[];
    final api = ApiClient('http://prova', client: MockClient((r) async {
      richieste.add(r.url.path);
      return http.Response(jsonEncode({'codice': 'F'}), 200, headers: {'content-type': 'application/json'});
    }));
    late BuildContext contesto;
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: api,
      child: MaterialApp(home: Scaffold(body: Builder(builder: (c) {
        contesto = c;
        return const SizedBox();
      }))),
    ));
    final esito = modificaArea(contesto);
    await tester.pumpAndSettle();
    expect(richieste, ['/api/v1/anticorruzione/aree/codice-proposto']);
    expect(find.widgetWithText(TextField, 'F'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'F'), 'URB');
    await tester.enterText(find.widgetWithText(TextField, 'Descrizione *'), 'Governo del territorio');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    final v = await esito;
    expect((v?['codice'], v?['descrizione']), ('URB', 'Governo del territorio'));
  });
}
