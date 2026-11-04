import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/admin/ente_posta.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Posta in uscita: si salva il server (la password solo se scritta), poi si prova l'invio.
void main() {
  testWidgets('configurazione e prova della posta in uscita', (tester) async {
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    Map<String, dynamic> stato = {'configurata': false};
    final inviati = <String, Object?>{};
    final client = MockClient((r) async {
      Object? corpo = stato;
      if (r.method == 'PUT' && r.url.path == '/api/v1/ente/posta') {
        final d = jsonDecode(r.body) as Map<String, dynamic>;
        inviati.addAll(d);
        stato = {
          'configurata': true, 'host': d['host'], 'porta': d['porta'], 'sicurezza': d['sicurezza'],
          'utente': d['utente'], 'password_impostata': d['password'] != null, 'mittente': d['mittente'], 'rispondi_a': null,
        };
        corpo = stato;
      } else if (r.url.path == '/api/v1/ente/posta/prova') {
        corpo = {'esito': 'OK', 'messaggio': 'Email di prova inviata a admin@ente.it'};
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
    });
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: ApiClient('http://prova', client: client),
      child: const MaterialApp(home: Scaffold(body: PostaEntePage())),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Invia un\'email di prova'), findsNothing); // non ancora configurata

    await tester.enterText(find.widgetWithText(TextField, 'Server SMTP'), 'smtp.ente.it');
    await tester.enterText(find.widgetWithText(TextField, 'Utente'), 'atti');
    await tester.enterText(find.widgetWithText(TextField, 'Password'), 'segreta');
    await tester.enterText(find.widgetWithText(TextField, 'Mittente'), 'atti@ente.it');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(inviati['host'], 'smtp.ente.it');
    expect(inviati['porta'], 587);
    expect(inviati['password'], 'segreta');
    expect(find.text('Una password è già salvata: lascia vuoto per mantenerla'), findsOneWidget);

    await tester.tap(find.text('Invia un\'email di prova'));
    await tester.pumpAndSettle();
    expect(find.text('Email di prova inviata a admin@ente.it'), findsOneWidget);
  });
}
