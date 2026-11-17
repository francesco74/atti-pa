import 'package:atti_pa/ui/anticorruzione/albero.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Finestra del processo: oltre alla struttura responsabile, le strutture coinvolte si
/// aggiungono e si tolgono una per una; le non più attive restano se già scelte.
void main() {
  final dati = DatiAnticorruzione(
    metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto']},
    aree: const [],
    strutture: const [
      {'id': 's1', 'codice': 'SETTORE 1', 'descrizione': 'Affari generali', 'attiva': true},
      {'id': 's2', 'codice': 'U.O. 2.1', 'descrizione': 'Personale', 'attiva': true},
      {'id': 's3', 'codice': 'U.O. 9.9', 'descrizione': 'Soppressa', 'attiva': false},
    ],
    obblighi: const [],
  );

  testWidgets('si aggiungono e si tolgono le strutture coinvolte', (tester) async {
    tester.view.physicalSize = const Size(1200, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    Map<String, dynamic>? risultato;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () async => risultato = await modificaProcesso(context, dati, p: {
              'codice': 'C.1', 'tipo': 'PROCESSO', 'denominazione': 'Gare', 'struttura_id': 's1', 'coinvolte': ['s3'],
            }),
            child: const Text('apri'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('apri'));
    await tester.pumpAndSettle();
    expect(find.text('Strutture coinvolte'), findsOneWidget);
    expect(find.text('U.O. 9.9 - Soppressa'), findsOneWidget); // non più attiva, ma già scelta

    await tester.tap(find.text('Aggiungi'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(SimpleDialogOption, 'U.O. 9.9 - Soppressa'), findsNothing); // già scelta
    await tester.tap(find.widgetWithText(SimpleDialogOption, 'U.O. 2.1 - Personale'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Togli').first); // via la soppressa
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(risultato?['coinvolte'], ['s2']);
    expect(risultato?['struttura_id'], 's1');
  });

  test('nomi delle strutture coinvolte', () {
    expect(dati.coinvolte(['s1', 's2']), 'SETTORE 1 - Affari generali, U.O. 2.1 - Personale');
    expect(dati.coinvolte(const []), isNull);
    expect(dati.coinvolte(null), isNull);
  });
}
