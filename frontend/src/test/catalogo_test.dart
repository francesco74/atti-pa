import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/catalogo.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Catalogo della mappatura: le voci per tipo con quante volte sono usate; la scheda della
/// voce elenca dove è usata e, per il RPCT, modificarla chiede conferma mostrando gli usi.
void main() {
  final corpi = <String, Object?>{};

  Future<void> apri(WidgetTester tester, {required bool rpct}) async {
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    corpi.clear();
    final voce = {
      'id': 'v1', 'tipo': 'MISURA', 'codice': 'MIS-0007', 'descrizione': 'Rotazione dei professionisti invitati',
      'tipo_misura': 'SPECIFICA', 'categoria': 'Rotazione', 'indicatore': null, 'target': null, 'attiva': true, 'standard': true,
    };
    final client = MockClient((r) async {
      if (r.body.isNotEmpty) corpi['${r.method} ${r.url.path}'] = jsonDecode(r.body);
      Object? corpo = const [];
      if (r.url.path.endsWith('/catalogo') && r.method == 'GET') {
        corpo = r.url.queryParameters['tipo'] == 'MISURA'
            ? [{...voce, 'usi': 2}, {...voce, 'id': 'v2', 'codice': 'MIS-E001', 'descrizione': 'Doppia firma', 'standard': false, 'usi': 0, 'attiva': false}]
            : [];
      } else if (r.url.path.endsWith('/catalogo/v1')) {
        corpo = {
          ...voce, 'usi': 2,
          'elementi': [
            {'id': 'm1', 'codice': 'C.4.1_R.1_M.1', 'testo': 'Rotazione dei professionisti invitati', 'diverso': false,
             'attivita_id': 'a1', 'processo': {'id': 'p1', 'codice': 'C.4', 'denominazione': 'Affidamento di servizi di ingegneria'}},
            {'id': 'm2', 'codice': 'C.4.1_R.2_M.1', 'testo': 'Rotazione dei professionisti', 'diverso': true,
             'attivita_id': 'a1', 'processo': {'id': 'p1', 'codice': 'C.4', 'denominazione': 'Affidamento di servizi di ingegneria'}},
          ],
        };
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    });
    final api = ApiClient('http://prova', client: client);
    final auth = AuthState(api)
      ..utente = Utente.daJson({
        'id': 'u1', 'username': 'u', 'ruoli': [rpct ? 'ANTICORRUZIONE_RPCT' : 'ANTICORRUZIONE_REFERENTE'],
        'ente': {'codice': 'prova', 'nome': 'Ente', 'moduli': ['anticorruzione']},
      });
    final dati = DatiAnticorruzione(
      metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto'], 'categorie_misure': ['Rotazione', 'Controllo']},
      aree: const [],
      strutture: const [],
      obblighi: const [],
    );
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthState>.value(value: auth),
        Provider.value(value: dati),
      ],
      child: const MaterialApp(home: Scaffold(body: CatalogoTab())),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Misure'));
    await tester.pumpAndSettle();
  }

  testWidgets('il RPCT modifica una voce usata dopo aver visto dove è usata', (tester) async {
    await apri(tester, rpct: true);
    expect(find.text('MIS-0007 - Rotazione dei professionisti invitati'), findsOneWidget);
    expect(find.textContaining('usata in 2 elementi'), findsOneWidget);
    expect(find.text('Disattivata'), findsOneWidget);
    expect(find.text('Nuova voce (misura)'), findsOneWidget);

    await tester.tap(find.text('MIS-0007 - Rotazione dei professionisti invitati'));
    await tester.pumpAndSettle();
    expect(find.text('Usata in 2 elementi della mappatura'), findsOneWidget);
    expect(find.textContaining('testo ritoccato nel processo'), findsOneWidget);
    expect(find.text('Elimina'), findsNothing); // usata: solo disattivare

    await tester.tap(find.text('Modifica'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Descrizione *'), 'Rotazione dei professionisti');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    // prima di salvare: dove è usata e conferma
    expect(find.text('Modificare una voce usata?'), findsOneWidget);
    expect(find.textContaining('• C.4.1_R.2_M.1 (C.4 - Affidamento di servizi di ingegneria)'), findsOneWidget);
    await tester.tap(find.text('Procedi comunque'));
    await tester.pumpAndSettle();
    final corpo = corpi['PUT /api/v1/anticorruzione/catalogo/v1'] as Map;
    expect((corpo['descrizione'], corpo['conferma'], corpo['categoria']), ('Rotazione dei professionisti', true, 'Rotazione'));
  });

  testWidgets('il referente vede il catalogo senza poterlo cambiare', (tester) async {
    await apri(tester, rpct: false);
    expect(find.text('Nuova voce (misura)'), findsNothing);
    await tester.tap(find.text('MIS-0007 - Rotazione dei professionisti invitati'));
    await tester.pumpAndSettle();
    expect(find.text('Usata in 2 elementi della mappatura'), findsOneWidget);
    expect(find.text('Modifica'), findsNothing);
    expect(find.text('Unisci'), findsNothing);
  });
}
