import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/anticorruzione/albero.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Valutazione del rischio con il parere dell'IA: si chiede dopo aver dato i propri valori, gli
/// indicatori diversi si vedono, i valori e il giudizio si adottano solo con un clic e si
/// salvano con la valutazione.
void main() {
  final dati = DatiAnticorruzione(
    metodologia: const {
      'scala': ['Basso', 'Medio', 'Alto'],
      'livelli': ['Minimo', 'Basso', 'Medio', 'Alto', 'Critico'],
      'matrice': {
        'Alto': {'Alto': 'Critico', 'Medio': 'Alto', 'Basso': 'Medio'},
        'Medio': {'Alto': 'Alto', 'Medio': 'Medio', 'Basso': 'Basso'},
        'Basso': {'Alto': 'Medio', 'Medio': 'Basso', 'Basso': 'Minimo'},
      },
      'indicatori_probabilita': [
        {'id': '1', 'nome': 'Discrezionalità'},
        {'id': '2', 'nome': 'Interessi esterni'},
      ],
      'indicatori_impatto': [
        {'id': '3', 'nome': 'Immagine'},
      ],
    },
    aree: const [],
    strutture: const [],
    obblighi: const [],
  );

  testWidgets('parere dell\'IA: confronto, valori e giudizio adottati', (tester) async {
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    Object? richiesta;
    final client = MockClient((r) async {
      richiesta = jsonDecode(r.body);
      return http.Response(jsonEncode({
        'valori_probabilita': {'1': 'Alto', '2': 'Medio'},
        'valori_impatto': {'3': 'Medio'},
        'motivazioni': {'1': 'Ampia discrezionalità tecnica', '2': 'Interessi rilevanti', '3': 'Danno d\'immagine'},
        'motivazione_valutazione': 'Rischio alto per la discrezionalità.',
        'probabilita': 'Alto', 'impatto': 'Medio', 'livello': 'Alto',
      }), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    });
    Map<String, dynamic>? salvato;
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: ApiClient('http://prova', client: client),
      child: MaterialApp(home: Scaffold(body: Builder(builder: (context) => TextButton(
        onPressed: () => valutaRischio(context, dati, {'id': 'r1', 'codice': 'A.1.1_R.1', 'evento': 'Commissari in conflitto'},
            salva: (v) async => salvato = v),
        child: const Text('apri'),
      )))),
    ));
    await tester.tap(find.text('apri'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Dai prima i tuoi valori'), findsOneWidget);
    await tester.tap(find.text('Parere dell\'IA'));
    await tester.pumpAndSettle();
    expect(richiesta, {'evento': 'Commissari in conflitto', 'fattore_abilitante': null, 'rischio_id': 'r1'});
    // i valori di partenza sono "Medio": diverso solo l'indicatore 1
    expect(find.textContaining('Proposta dell\'IA: probabilità Alto, impatto Medio, Alto.'), findsOneWidget);
    expect(find.textContaining('Indicatori diversi dai tuoi: 1'), findsOneWidget);
    expect(find.text('IA: Alto'), findsOneWidget);
    expect(find.text('IA: Medio'), findsNWidgets(2));

    await tester.tap(find.text('Usa i valori dell\'IA'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Gli indicatori coincidono con i tuoi'), findsOneWidget);
    await tester.tap(find.text('Usa il giudizio dell\'IA'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextField, 'Rischio alto per la discrezionalità.'), findsOneWidget);
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(salvato?['valori_probabilita'], {'1': 'Alto', '2': 'Medio'});
    expect(salvato?['motivazione_valutazione'], 'Rischio alto per la discrezionalità.');
    expect(salvato?['livello'], 'Alto');
  });
}
