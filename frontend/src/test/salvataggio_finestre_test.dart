import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/comuni.dart';
import 'package:atti_pa/ui/performance/comune.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Le finestre che salvano: si chiudono solo a salvataggio riuscito; se non riesce l'errore si
/// legge nella finestra, che resta aperta con i dati inseriti; Annullato la lascia aperta senza
/// errore.
void main() {
  Future<void> apri(WidgetTester tester, Future<void> Function(BuildContext) finestra) async {
    tester.view.physicalSize = const Size(1200, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: Builder(builder: (context) => TextButton(onPressed: () => finestra(context), child: const Text('apri')))),
    ));
    await tester.tap(find.text('apri'));
    await tester.pumpAndSettle();
  }

  testWidgets('modificaCampi: errore nella finestra, poi chiusura a salvataggio riuscito', (tester) async {
    var tentativi = 0;
    Map<String, dynamic>? risultato;
    await apri(tester, (context) async {
      risultato = await modificaCampi(context,
          titolo: 'Area',
          campi: const [Campo('denominazione', 'Denominazione', obbligatorio: true)],
          valori: const {},
          salva: (v) async {
            if (++tentativi == 1) throw 'Denominazione già usata';
            if (tentativi == 2) throw const Annullato();
          });
    });
    await tester.enterText(find.byType(TextField), 'Contratti');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Denominazione già usata'), findsOneWidget);
    expect(find.text('Contratti'), findsOneWidget); // i dati restano
    expect(risultato, isNull);

    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Denominazione già usata'), findsNothing);
    expect(find.text('Area'), findsOneWidget); // annullato: resta aperta

    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Area'), findsNothing);
    expect(risultato?['denominazione'], 'Contratti');
    expect(tentativi, 3);
  });

  testWidgets('chiediTesto (performance): la motivazione resta se l\'invio non riesce', (tester) async {
    var riesce = false;
    String? risultato;
    await apri(tester, (context) async {
      risultato = await chiediTesto(context, 'Restituisci la proposta', etichetta: 'Motivazione', obbligatoria: true,
          salva: (t) async {
        if (!riesce) throw 'Proposta già decisa';
      });
    });
    await tester.tap(find.text('Conferma'));
    await tester.pumpAndSettle();
    expect(find.text('Obbligatoria'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'Manca l\'indicatore');
    await tester.tap(find.text('Conferma'));
    await tester.pumpAndSettle();
    expect(find.text('Proposta già decisa'), findsOneWidget);
    expect(find.text('Manca l\'indicatore'), findsOneWidget);

    riesce = true;
    await tester.tap(find.text('Conferma'));
    await tester.pumpAndSettle();
    expect(find.text('Restituisci la proposta'), findsNothing);
    expect(risultato, 'Manca l\'indicatore');
  });
}
