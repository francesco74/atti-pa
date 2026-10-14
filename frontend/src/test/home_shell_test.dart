import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/home_shell.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('ogni selezione di una voce del menu ricarica la pagina', (tester) async {
    tester.view.physicalSize = const Size(1400, 900); // menu laterale
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    final richieste = <String>[];
    final api = ApiClient(
      'http://api.test',
      client: MockClient((r) async {
        richieste.add(r.url.path);
        return http.Response(jsonEncode([]), 200, headers: {'content-type': 'application/json'});
      }),
    );
    final utente = Utente.daJson({
      'id': 'u1',
      'username': 'prova',
      'nome_completo': 'Utente di prova',
      'ruoli': ['CONTROLLORE'],
    });

    final auth = AuthState(api)
      ..utente = utente
      ..stato = StatoAuth.autenticato;
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthState>.value(value: auth),
      ],
      child: MaterialApp(home: HomeShell(utente: utente)),
    ));
    await tester.pumpAndSettle();
    int elenchi() => richieste.where((p) => p == '/api/v1/controllo/controlli').length;
    expect(elenchi(), 0); // all'avvio è aperta la Libreria normativa

    await tester.tap(find.text('Controllo atti'));
    await tester.pumpAndSettle();
    expect(elenchi(), 1);

    await tester.tap(find.text('Libreria normativa'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Controllo atti'));
    await tester.pumpAndSettle();
    expect(elenchi(), 2); // tornando sulla voce i dati vengono richiesti di nuovo

    await tester.tap(find.text('Controllo atti'));
    await tester.pumpAndSettle();
    expect(elenchi(), 3); // anche riselezionando la voce già aperta
  });
}
