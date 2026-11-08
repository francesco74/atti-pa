import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/pubblico/mappatura_pubblica.dart';
import 'package:atti_pa/ui/pubblico/procedimenti_pubblici.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

http.Response _json(Object corpo, [int stato = 200]) =>
    http.Response(jsonEncode(corpo), stato, headers: {'content-type': 'application/json'});

const _ente = {'nome': 'Comune di Prova', 'logo': false, 'dichiarazione_accessibilita': 'https://form.agid.gov.it/view/prova'};

/// Accessibilità delle pagine pubbliche (WCAG 2.1 AA): contrasto del testo, pulsanti con
/// etichetta e bersagli di almeno 48 px (controlli di Flutter), intestazioni, titolo della
/// scheda del browser, impaginazione a 320 px con il testo al 200%, piè di pagina con la
/// dichiarazione e la segnalazione dei problemi di accessibilità.
void main() {
  final segnalazioni = <Map<String, dynamic>>[];

  MockClient client() => MockClient((r) async {
        final p = r.url.path;
        if (p.endsWith('/pubblico/procedimenti')) {
          return _json({
            'ente': _ente,
            'strutture': [{'id': 's1', 'codice': 'SETTORE 4', 'descrizione': 'Servizi sociali'}],
            'procedimenti': [
              {'id': 'p1', 'codice': 'A.1', 'denominazione': 'Contributo affitto', 'tipologia': 'Contributi', 'struttura_id': 's1'},
            ],
          });
        }
        if (p.endsWith('/pubblico/mappatura')) {
          return _json({
            'ente': _ente,
            'livelli': ['Rischio Minimo', 'Rischio Basso', 'Rischio Medio', 'Rischio Alto', 'Rischio Critico'],
            'aree': [{'id': 'c', 'codice': 'C', 'descrizione': 'Contratti pubblici', 'descrizione_breve': null}],
            'strutture': [{'id': 's1', 'codice': 'SETTORE 4', 'descrizione': 'Servizi sociali'}],
          });
        }
        if (p.endsWith('/mappatura/processi')) {
          return _json([
            {'id': 'p1', 'codice': 'C.1', 'tipo': 'PROCESSO', 'area_id': 'c', 'denominazione': 'Gare', 'struttura_id': 's1',
             'attivita': 1, 'rischi': 1, 'misure': 1, 'livello_massimo': 'Rischio Medio'},
          ]);
        }
        if (p.endsWith('/ricerche/feedback')) {
          segnalazioni.add(jsonDecode(r.body) as Map<String, dynamic>);
          return _json({'id': 'f1'}, 201);
        }
        if (p.endsWith('/procedimenti/p1')) return _json({'id': 'p1', 'codice': 'A.1', 'struttura_id': 's1', 'scheda': <String, dynamic>{}});
        return _json(const []);
      });

  Future<void> apri(WidgetTester tester, Widget pagina, {double larghezza = 1280, double testo = 1}) async {
    tester.view.physicalSize = Size(larghezza, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = ApiClient('http://prova', client: client());
    await tester.pumpWidget(MultiProvider(
      providers: [Provider<ApiClient>.value(value: api), ChangeNotifierProvider(create: (_) => AuthState(api))],
      child: MaterialApp(
        theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1F4E79))),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(testo)),
          child: child!,
        ),
        home: pagina,
      ),
    ));
    await tester.pumpAndSettle();
  }

  Future<void> controlliWcag(WidgetTester tester) async {
    await expectLater(tester, meetsGuideline(textContrastGuideline)); // 1.4.3
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline)); // 4.1.2
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline)); // bersagli di 48 px
  }

  bool titoloScheda(String titolo) => find.byWidgetPredicate((w) => w is Title && w.title == titolo).evaluate().isNotEmpty;

  testWidgets('procedimenti: linee guida, intestazioni, titolo e navigazione', (tester) async {
    final semantica = tester.ensureSemantics();
    await apri(tester, const ProcedimentiPubbliciPage());
    await controlliWcag(tester);
    expect(tester.getSemantics(find.text('Tipologie di procedimento')), isSemantics(isHeader: true));
    expect(tester.getSemantics(find.text('Strutture responsabili')), isSemantics(isHeader: true));
    expect(titoloScheda('Tipologie di procedimento – Comune di Prova'), isTrue);
    expect(find.text('Dichiarazione di accessibilità'), findsOneWidget);
    expect(find.text('Codice sorgente (AGPL-3.0)'), findsOneWidget); // licenza AGPL, art. 13

    // struttura: il titolo della scheda del browser cambia
    await tester.tap(find.text('SETTORE 4 - Servizi sociali'));
    await tester.pumpAndSettle();
    expect(titoloScheda('SETTORE 4 - Servizi sociali – Tipologie di procedimento – Comune di Prova'), isTrue);
    expect(tester.getSemantics(find.text('Strutture')), isSemantics(isLink: true));
    await controlliWcag(tester);

    // scheda del procedimento
    await tester.tap(find.text('Contributo affitto'));
    await tester.pumpAndSettle();
    expect(titoloScheda('Contributo affitto – Tipologie di procedimento – Comune di Prova'), isTrue);
    expect(tester.getSemantics(find.text('Dati sul procedimento')), isSemantics(isHeader: true));
    await controlliWcag(tester);
    semantica.dispose();
  });

  testWidgets('mappatura: linee guida e livello di rischio scritto, non solo colorato', (tester) async {
    final semantica = tester.ensureSemantics();
    await apri(tester, const MappaturaPubblicaPage());
    await controlliWcag(tester);
    await tester.tap(find.text('C - Contratti pubblici'));
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel(RegExp('Livello di rischio: Rischio Medio')), findsOneWidget);
    expect(titoloScheda('C - Contratti pubblici – Mappatura dei processi – Comune di Prova'), isTrue);
    await controlliWcag(tester);
    semantica.dispose();
  });

  testWidgets('320 px con il testo al 200%: niente esce dalla pagina', (tester) async {
    await apri(tester, const ProcedimentiPubbliciPage(), larghezza: 320, testo: 2);
    expect(tester.takeException(), isNull);
    // piè di pagina compatto: le voci sono nella finestra "Informazioni"
    expect(find.text('Codice sorgente (AGPL-3.0)'), findsNothing);
    await tester.dragUntilVisible(find.text('Informazioni'), find.byType(NestedScrollView), const Offset(0, -200));
    await tester.tap(find.text('Informazioni'));
    await tester.pumpAndSettle();
    expect(find.text('Codice sorgente (AGPL-3.0)'), findsOneWidget);
    expect(find.text('Segnala un problema di accessibilità'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tapAt(const Offset(5, 5)); // chiude la finestra
    await tester.pumpAndSettle();
    await apri(tester, const MappaturaPubblicaPage(), larghezza: 320, testo: 2);
    expect(tester.takeException(), isNull);
    // la pagina scorre tutta (intestazione compresa) fino all'area
    await tester.dragUntilVisible(find.text('C - Contratti pubblici'), find.byType(NestedScrollView), const Offset(0, -200));
    await tester.tap(find.text('C - Contratti pubblici'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('segnalazione di un problema di accessibilità', (tester) async {
    segnalazioni.clear();
    await apri(tester, const ProcedimentiPubbliciPage());
    await tester.tap(find.text('Segnala un problema di accessibilità'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Invia la segnalazione'));
    await tester.pump();
    expect(find.text('Descrivi il problema.'), findsOneWidget); // obbligatorio
    await tester.enterText(find.widgetWithText(TextField, 'Descrivi il problema (obbligatorio)'), 'Il lettore non legge i recapiti');
    await tester.enterText(find.widgetWithText(TextField, 'Email per la risposta (facoltativa)'), 'mario@esempio');
    await tester.tap(find.text('Invia la segnalazione'));
    await tester.pump();
    expect(find.text('Indirizzo email non valido.'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Email per la risposta (facoltativa)'), 'mario@esempio.it');
    await tester.tap(find.text('Invia la segnalazione'));
    await tester.pumpAndSettle();
    expect(segnalazioni.single, {
      'tipo': 'ACCESSIBILITA', 'riferimento': 'Tipologie di procedimento – Comune di Prova', 'utile': false,
      'commento': 'Il lettore non legge i recapiti', 'contatto': 'mario@esempio.it', 'ambito': 'PROCEDIMENTI',
    });
    expect(find.text('Segnalazione inviata'), findsOneWidget);
  });
}
