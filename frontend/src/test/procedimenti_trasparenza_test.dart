import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/trasparenza/tabs/procedimenti_tab.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Procedimenti nella trasparenza (catalogo condiviso con l'anticorruzione): con la sola
/// trasparenza si creano, importano e modificano qui; con l'anticorruzione si consultano. In
/// entrambi i casi c'è l'interruttore della sola pagina pubblica dei procedimenti.
void main() {
  Future<List<String>> apri(WidgetTester tester, {required bool conIter}) async {
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final chiamate = <String>[];
    final procedimento = {
      'id': 'p1', 'codice': 'P.1', 'tipo': 'PROCEDIMENTO', 'denominazione': 'Cambio di residenza', 'descrizione': null,
      'termine_conclusione': '45 giorni', 'norma_riferimento': null, 'struttura_id': 's1', 'area_id': null,
      'art35': {'tipologia': 'Anagrafe'}, 'scheda_art35': {'denominazione': 'Cambio di residenza', 'tipologia': 'Anagrafe'},
      'art35_mancanti': ['Ufficio responsabile del procedimento'],
    };
    final client = MockClient((r) async {
      chiamate.add('${r.method} ${r.url.path}');
      final p = r.url.path;
      Object? corpo = const [];
      if (p.endsWith('/procedimenti/pubblicazione')) {
        corpo = {'con_iter': conIter, 'procedimenti_attiva': false, 'percorso_procedimenti': '/pubblico/procedimenti'};
      } else if (p.endsWith('/trasparenza/procedimenti')) {
        corpo = [procedimento];
      } else if (p.endsWith('/procedimenti/p1')) {
        corpo = procedimento;
      } else if (p.endsWith('/ente/strutture')) {
        corpo = [{'id': 's1', 'codice': 'U.O. 1', 'descrizione': 'Anagrafe', 'attiva': true}];
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
    });
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: ApiClient('http://prova', client: client),
      child: const MaterialApp(home: Scaffold(body: ProcedimentiTab())),
    ));
    await tester.pumpAndSettle();
    return chiamate;
  }

  testWidgets('con la sola trasparenza si gestiscono qui', (tester) async {
    await apri(tester, conIter: false);
    expect(find.text('P.1 - Cambio di residenza'), findsOneWidget);
    expect(find.text('Art. 35: manca 1 dato'), findsOneWidget);
    expect(find.text('Nuovo procedimento'), findsOneWidget);
    expect(find.text('Importa dal sito o da documenti'), findsOneWidget);
    expect(find.text('Pubblica i procedimenti (art. 35)'), findsOneWidget);
    expect(find.text('Pubblica la mappatura'), findsNothing); // la mappatura è dell'anticorruzione

    await tester.tap(find.text('P.1 - Cambio di residenza'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Modifica'), findsOneWidget);
    expect(find.byTooltip('Elimina'), findsOneWidget);
    expect(find.text('Termine di conclusione: 45 giorni'), findsOneWidget);
  });

  testWidgets('con l\'anticorruzione si consultano', (tester) async {
    await apri(tester, conIter: true);
    expect(find.textContaining('si modificano lì, con l\'iter'), findsOneWidget);
    expect(find.text('Nuovo procedimento'), findsNothing);
    expect(find.text('Importa dal sito o da documenti'), findsNothing);
    expect(find.text('Pubblica i procedimenti (art. 35)'), findsOneWidget);

    await tester.tap(find.text('P.1 - Cambio di residenza'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Modifica'), findsNothing);
    expect(find.text('Si modifica nella mappatura dell\'anticorruzione.'), findsOneWidget);
  });
}
