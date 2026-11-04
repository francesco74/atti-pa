import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/home_shell.dart';
import 'package:atti_pa/ui/libreria/libreria_page.dart';
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
      'ente': {'codice': 'prova', 'nome': 'Ente di prova', 'moduli': ['redazione']},
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

  testWidgets('le pagine aperte lasciano il menu visibile e chiedono prima di uscire', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = ApiClient(
      'http://api.test',
      client: MockClient((r) async => http.Response(jsonEncode([]), 200, headers: {'content-type': 'application/json'})),
    );
    final utente = Utente.daJson({
      'id': 'u1',
      'username': 'prova',
      'nome_completo': 'Utente di prova',
      'ruoli': ['CONTROLLORE'],
      'ente': {'codice': 'prova', 'nome': 'Ente di prova', 'moduli': ['redazione']},
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

    var richieste = 0;
    Navigator.of(tester.element(find.byType(LibreriaPage))).push(MaterialPageRoute(
      builder: (_) => PopScope(
        canPop: false,
        onPopInvokedWithResult: (_, _) => richieste++,
        child: const Scaffold(body: Text('Dettaglio')),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Dettaglio'), findsOneWidget);
    expect(find.text('Controllo atti'), findsOneWidget); // il menu resta

    await tester.tap(find.text('Controllo atti'));
    await tester.pumpAndSettle();
    expect(find.text('Dettaglio'), findsOneWidget); // non si perde nulla senza conferma
    expect(richieste, 1);
  });

  testWidgets('la struttura si sceglie nel profilo una sola volta', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    Map<String, dynamic>? inviato;
    final strutture = [
      {'id': 's1', 'codice': 'SETTORE 2', 'descrizione': 'Risorse umane', 'attiva': true},
      {'id': 's2', 'codice': 'SETTORE 9', 'descrizione': 'Soppresso', 'attiva': false},
    ];
    Map<String, dynamic> utente(String? struttura) => {
          'id': 'u1', 'username': 'referente', 'nome_completo': 'Referente', 'ruoli': ['ANTICORRUZIONE_REFERENTE'],
          'struttura_id': struttura, 'ente': {'codice': 'prova', 'nome': 'Ente di prova', 'moduli': <String>[]},
        };
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      if (r.method == 'PUT') {
        inviato = jsonDecode(r.body) as Map<String, dynamic>;
        return http.Response(jsonEncode(utente(inviato!['struttura_id'] as String?)), 200,
            headers: {'content-type': 'application/json'});
      }
      return http.Response(jsonEncode(r.url.path.endsWith('/strutture') ? strutture : []), 200,
          headers: {'content-type': 'application/json'});
    }));
    final auth = AuthState(api)
      ..utente = Utente.daJson(utente(null))
      ..stato = StatoAuth.autenticato;
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthState>.value(value: auth),
      ],
      child: MaterialApp(home: HomeShell(utente: auth.utente!)),
    ));
    await tester.pumpAndSettle();

    Future<void> apriProfilo() async {
      await tester.tap(find.byType(CircleAvatar));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Il mio profilo'));
      await tester.pumpAndSettle();
    }

    await apriProfilo();
    await tester.tap(find.text('Non indicata'));
    await tester.pumpAndSettle();
    expect(find.text('SETTORE 9 - Soppresso'), findsNothing); // le disattivate non si scelgono
    await tester.tap(find.text('SETTORE 2 - Risorse umane').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(inviato?['struttura_id'], 's1');
    expect(auth.utente!.strutturaId, 's1');

    // assegnata: si vede ma non si cambia (prima sparisce il messaggio sopra l'avatar)
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    await apriProfilo();
    expect(find.text('SETTORE 2 - Risorse umane'), findsOneWidget);
    expect(find.text('Per cambiarla rivolgiti all\'amministratore.'), findsOneWidget);
    expect(find.byType(DropdownButtonFormField<String?>), findsNothing);
  });
}
