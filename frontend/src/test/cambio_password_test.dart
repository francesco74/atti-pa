import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/cambio_password_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

Map<String, dynamic> _utente({required bool cambio}) => {
      'id': 'u1',
      'username': 'admin',
      'nome_completo': 'Amministratore',
      'ruoli': ['ADMIN'],
      'origine': 'LOCALE',
      'cambio_password': cambio,
      'ente': {'codice': 'comune', 'nome': 'Comune di Prova', 'moduli': <String>[]},
    };

/// Con la password iniziale l'utente vede solo la scelta della nuova password; cambiata,
/// l'app prosegue.
void main() {
  testWidgets('password iniziale da cambiare al primo accesso', (tester) async {
    Map<String, dynamic>? cambio;
    final api = ApiClient(
      'http://api.test',
      client: MockClient((r) async {
        final json = {'content-type': 'application/json'};
        if (r.url.path == '/api/v1/auth/login') {
          return http.Response(jsonEncode({'token': 't', 'utente': _utente(cambio: true)}), 200, headers: json);
        }
        cambio = jsonDecode(r.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'token': 't', 'utente': _utente(cambio: false)}), 200, headers: json);
      }),
    );
    final auth = AuthState(api);
    await auth.login('admin', 'Iniziale-1234');
    expect(auth.utente!.cambioPassword, isTrue);

    await tester.pumpWidget(ChangeNotifierProvider<AuthState>.value(
      value: auth,
      child: const MaterialApp(home: CambioPasswordPage()),
    ));
    expect(find.text('Comune di Prova'), findsOneWidget);
    final campi = find.byType(TextFormField);
    await tester.enterText(campi.at(0), 'Iniziale-1234');
    await tester.enterText(campi.at(1), 'Nuova-password-1');
    await tester.enterText(campi.at(2), 'Diversa-password-2');
    await tester.ensureVisible(find.text('Cambia e continua'));
    await tester.tap(find.text('Cambia e continua'));
    await tester.pumpAndSettle();
    expect(find.text('Le due password non coincidono'), findsOneWidget);
    expect(cambio, isNull);

    await tester.enterText(campi.at(2), 'Nuova-password-1');
    await tester.ensureVisible(find.text('Cambia e continua'));
    await tester.tap(find.text('Cambia e continua'));
    await tester.pumpAndSettle();
    expect(cambio, {'attuale': 'Iniziale-1234', 'nuova': 'Nuova-password-1'});
    expect(auth.utente!.cambioPassword, isFalse);
  });
}
