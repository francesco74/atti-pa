import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/login_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// La pagina di accesso mostra l'ente del dominio e, se l'ente li ha entrambi, la scelta
/// tra account di dominio e utente dell'app; il modo scelto arriva all'API.
void main() {
  testWidgets('accesso con l\'ente del dominio e il modo scelto', (tester) async {
    Map<String, dynamic>? login;
    final api = ApiClient(
      'http://api.test',
      client: MockClient((r) async {
        if (r.url.path == '/api/v1/auth/ente') {
          return http.Response(
            jsonEncode({
              'ente': {'codice': 'comune', 'nome': 'Comune di Prova', 'assistenza': 'Scrivi a supporto@comune.it'},
              'dominio': 'atti.comune.it',
              'accesso_locale': true,
              'accesso_ldap': true,
              'dominio_ldap': 'comune.local',
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        login = jsonDecode(r.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'detail': 'Credenziali non valide'}), 401,
            headers: {'content-type': 'application/json'});
      }),
    );
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthState>(create: (_) => AuthState(api)),
      ],
      child: const MaterialApp(home: LoginPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Comune di Prova'), findsOneWidget);
    expect(find.textContaining('comune.local'), findsOneWidget); // predefinito: dominio

    await tester.tap(find.text('Utente dell\'app'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).first, 'mario');
    await tester.enterText(find.byType(TextFormField).last, 'segreta');
    await tester.tap(find.text('Accedi').last);
    await tester.pumpAndSettle();
    // la password si può vedere e nascondere
    TextField campoPassword() => tester.widget<TextField>(find.byType(TextField).last);
    expect(campoPassword().obscureText, isTrue);
    await tester.tap(find.byTooltip('Mostra la password'));
    await tester.pump();
    expect(campoPassword().obscureText, isFalse);
    await tester.tap(find.byTooltip('Nascondi la password'));
    await tester.pump();
    expect(campoPassword().obscureText, isTrue);
    // testo di assistenza dell'ente, con l'indirizzo cliccabile
    expect(find.text('Serve aiuto?'), findsOneWidget);
    expect(find.text('supporto@comune.it'), findsOneWidget);
    expect(login?['modo'], 'locale');
    expect(login?['username'], 'mario');
    expect(find.textContaining('Credenziali non valide'), findsOneWidget);
  });
}
