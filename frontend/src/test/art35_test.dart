import 'package:atti_pa/ui/anticorruzione/art35.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Finestra dei dati art. 35, guidata come nella trasparenza: le parti che dipendono da una
/// risposta compaiono solo quando servono; gli uffici si scelgono dall'organigramma, se ne
/// vedono i recapiti e si possono scrivere quelli propri del procedimento.
void main() {
  const strutture = [
    {'id': 's1', 'codice': 'SETTORE 4', 'descrizione': 'Servizi sociali', 'padre_id': null, 'attiva': true,
     'telefono': '0583 1234', 'peo': 'sociale@ente.it', 'pec': null, 'sede': 'Via Roma 1',
     'orari': [{'giorni': 'Lunedì', 'ora_inizio': '09:00', 'ora_fine': '12:00'}]},
    {'id': 's2', 'codice': 'U.O. 4.1', 'descrizione': 'Sportello', 'padre_id': 's1', 'attiva': true, 'orari': []},
  ];

  Future<void> scegli(WidgetTester tester, String menu, String voce) async {
    await tester.tap(find.byWidgetPredicate((w) => w is DropdownButtonFormField && (w.decoration.labelText == menu)));
    await tester.pumpAndSettle();
    await tester.tap(find.text(voce).last);
    await tester.pumpAndSettle();
  }

  testWidgets('a istanza di parte: ufficio dall\'organigramma con recapiti e orari propri', (tester) async {
    Map<String, dynamic>? risultato;
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (c) => TextButton(
          onPressed: () async => risultato = await modificaArt35(c, strutture, null,
              procedimento: {'denominazione': 'Contributo affitto', 'struttura_id': 's1', 'termine_conclusione': '30 giorni'}),
          child: const Text('apri'),
        ),
      ),
    ));
    await tester.tap(find.text('apri'));
    await tester.pumpAndSettle();

    // dati che vengono dal procedimento; ufficio responsabile = struttura responsabile
    expect(find.textContaining('Termine di conclusione: 30 giorni'), findsOneWidget);
    expect(find.text('La struttura responsabile: SETTORE 4 - Servizi sociali'), findsOneWidget);
    expect(find.text('0583 1234'), findsOneWidget); // telefono della struttura, come suggerimento
    // finché non si risponde, niente ufficio istanze né ufficio finale
    expect(find.text('Ufficio cui rivolgersi per informazioni e istanze'), findsNothing);
    expect(find.text('Atti e modulistica (link)'), findsNothing);
    expect(find.text('Ufficio competente per il provvedimento finale'), findsNothing);

    await scegli(tester, 'Procedimento a istanza di parte?', 'Sì');
    expect(find.text('Ufficio cui rivolgersi per informazioni e istanze'), findsOneWidget);
    expect(find.text('Atti e modulistica (link)'), findsOneWidget);
    await scegli(tester, 'Ufficio cui rivolgersi per informazioni e istanze', 'U.O. 4.1 - Sportello');
    // lo sportello non ha recapiti né orari: si vede subito
    expect(find.text('La struttura non ha orari: aggiungili qui o in Amministrazione → Strutture.'), findsOneWidget);
    expect(find.textContaining('Manca nella struttura'), findsWidgets);
    await tester.enterText(find.widgetWithText(TextField, 'Telefono').last, '0583 9999');
    await tester.tap(find.text('Orari diversi per questo procedimento'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Giorni'), 'Martedì');
    await tester.enterText(find.widgetWithText(TextField, 'Dalle'), '15:00');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Orari: per ogni fascia indica giorni, ora di inizio e ora di fine'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Alle'), '17:00');
    await tester.enterText(find.widgetWithText(TextField, 'Atti e modulistica (link)'), 'moduli');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.textContaining('il link deve iniziare con http'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Atti e modulistica (link)'), 'https://ente.it/moduli');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(risultato, {
      'ist_modulistica': 'https://ente.it/moduli',
      'ist_telefono': '0583 9999',
      'ist_struttura_id': 's2',
      'istanza_di_parte': 'SI',
      'orari': [{'giorni': 'Martedì', 'ora_inizio': '15:00', 'ora_fine': '17:00'}],
    });
  });

  testWidgets('non a istanza di parte: i dati dell\'ufficio istanze non si chiedono e non si salvano', (tester) async {
    Map<String, dynamic>? risultato;
    tester.view.physicalSize = const Size(1200, 4000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (c) => TextButton(
          onPressed: () async => risultato = await modificaArt35(c, strutture, {
            'istanza_di_parte': 'SI', 'ist_struttura_id': 's1', 'ist_telefono': '1', 'uff_finale_struttura_id': 's2', 'tipologia': 'Contributi',
          }),
          child: const Text('apri'),
        ),
      ),
    ));
    await tester.tap(find.text('apri'));
    await tester.pumpAndSettle();
    expect(find.text('Ufficio competente per il provvedimento finale'), findsOneWidget); // era diverso
    await scegli(tester, 'Procedimento a istanza di parte?', 'No');
    expect(find.text('Ufficio cui rivolgersi per informazioni e istanze'), findsNothing);
    await scegli(tester, 'L\'ufficio competente per il provvedimento finale è diverso?', 'No, è lo stesso ufficio responsabile');
    expect(find.text('Ufficio competente per il provvedimento finale'), findsNothing);
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(risultato, {'tipologia': 'Contributi', 'istanza_di_parte': 'NO'});
  });
}
