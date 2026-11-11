import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/admin/ente_accesso.dart';
import 'package:atti_pa/ui/comuni.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

http.Response _json(Object corpo, [int stato = 200]) =>
    http.Response(jsonEncode(corpo), stato, headers: {'content-type': 'application/json'});

/// Nuovo utente: se la password o il server danno errore la finestra resta aperta con i dati
/// scritti e il messaggio; si chiude solo a salvataggio riuscito.
void main() {
  test('regole della password come sul server', () {
    expect(erroreNuovaPassword('corta1'), isNotNull);
    expect(erroreNuovaPassword('sololettere'), isNotNull);
    expect(erroreNuovaPassword('1234567890'), isNotNull);
    expect(erroreNuovaPassword('lettere1'), isNull); // 8 caratteri bastano a un utente
    // un amministratore ne vuole 16
    expect(erroreNuovaPassword('lettere-e-1', amministratore: true),
        'La password deve avere almeno 16 caratteri per un amministratore.');
    expect(erroreNuovaPassword('lettere-e-numeri-1', amministratore: true), isNull);
  });

  testWidgets('la finestra del nuovo utente non si chiude sugli errori', (tester) async {
    tester.view.physicalSize = const Size(1400, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final creati = <Map<String, dynamic>>[];
    final client = MockClient((r) async {
      if (r.method == 'POST' && r.url.path == '/api/v1/ente/utenti') {
        final d = jsonDecode(r.body) as Map<String, dynamic>;
        if (d['username'] == 'mrossi') return _json({'detail': 'Nome utente già in uso'}, 409);
        creati.add(d);
        return _json({'id': 'u1'}, 201);
      }
      return _json(const []);
    });
    await tester.pumpWidget(
      Provider<ApiClient>.value(
        value: ApiClient('http://prova', client: client),
        child: const MaterialApp(home: Scaffold(body: UtentiEntePage())),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Nuovo utente dell\'app'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Nome utente'), 'mrossi');
    await tester.enterText(find.widgetWithText(TextField, 'Nome e cognome'), 'Mario Rossi');
    await tester.enterText(find.widgetWithText(TextField, 'Password iniziale'), 'corta1');
    await tester.pump();
    expect(find.text('La password deve avere almeno 8 caratteri.'), findsOneWidget); // subito, sotto il campo

    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Nuovo utente dell\'app'), findsWidgets); // la finestra è ancora aperta
    expect(find.text('Mario Rossi'), findsOneWidget); // con i dati scritti
    expect(creati, isEmpty);

    // password valida, ma il server rifiuta il nome utente: la finestra resta aperta
    await tester.enterText(find.widgetWithText(TextField, 'Password iniziale'), 'lettere-e-1');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Nome utente già in uso'), findsOneWidget);
    expect(find.text('Mario Rossi'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextField, 'Nome utente'), 'mario.rossi');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(creati.single['username'], 'mario.rossi');
    expect(creati.single['password'], 'lettere-e-1');
    expect(find.byType(AlertDialog), findsNothing); // chiusa
  });
}
