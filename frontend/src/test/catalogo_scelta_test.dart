import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/albero.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Elementi nuovi della mappatura scelti dal catalogo: la voce dà il testo, che si ritocca;
/// la voce che manca il RPCT la crea, il referente la propone. L'attività può essere invece un
/// procedimento del catalogo dei procedimenti.
void main() {
  final corpi = <String, Object?>{};
  final dati = DatiAnticorruzione(
    metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto'], 'categorie_misure': ['Controllo', 'Rotazione']},
    aree: const [],
    strutture: const [],
    obblighi: const [],
  );

  Future<Future<Map<String, dynamic>?> Function()> apri(WidgetTester tester,
      {required bool rpct, required String tipo, bool simili = false}) async {
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    corpi.clear();
    final client = MockClient((r) async {
      if (r.body.isNotEmpty) corpi['${r.method} ${r.url.path}'] = jsonDecode(r.body);
      Object? corpo = const [];
      if (r.url.path.endsWith('/catalogo') && r.method == 'GET') {
        corpo = [
          if (r.url.queryParameters['tipo'] == 'ATTIVITA')
            {'id': 'v1', 'tipo': 'ATTIVITA', 'codice': 'ATT-0012', 'descrizione': 'Pubblicazione del bando', 'attiva': true, 'usi': 3},
          if (r.url.queryParameters['tipo'] == 'MISURA')
            {'id': 'v2', 'tipo': 'MISURA', 'codice': 'MIS-0007', 'descrizione': 'Doppia firma', 'tipo_misura': 'GENERALE',
             'categoria': 'Controllo', 'indicatore': 'Atti firmati', 'target': '100%', 'attiva': true, 'usi': 1},
        ];
      } else if (r.url.path.endsWith('/procedimenti') && r.method == 'GET') {
        corpo = [
          {'id': 'pr7', 'codice': 'P.7', 'denominazione': 'Rilascio del permesso di costruire', 'usi': 0,
           'termine_conclusione': '60 giorni', 'art35_mancanti': <String>[]},
        ];
      } else if (r.url.path.endsWith('/catalogo/simili') && simili) {
        corpo = [
          {'id': 'v5', 'tipo': 'ATTIVITA', 'codice': 'ATT-0031', 'descrizione': 'Collaudo delle opere pubbliche',
           'attiva': true, 'usi': 2, 'somiglianza': 0.91},
        ];
      } else if (r.url.path.endsWith('/catalogo') && r.method == 'POST') {
        corpo = {'id': 'v9', 'tipo': 'ATTIVITA', 'codice': 'ATT-E001', 'descrizione': (jsonDecode(r.body) as Map)['descrizione'],
                 'attiva': true, 'usi': 0};
      } else if (r.url.path.endsWith('/proposte')) {
        corpo = {'id': 'pr1'};
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    });
    final api = ApiClient('http://prova', client: client);
    final auth = AuthState(api)
      ..utente = Utente.daJson({
        'id': 'u1', 'username': 'u', 'ruoli': [rpct ? 'ANTICORRUZIONE_RPCT' : 'ANTICORRUZIONE_REFERENTE'],
        'ente': {'codice': 'prova', 'nome': 'Ente', 'moduli': ['anticorruzione']},
      });
    Map<String, dynamic>? risultato;
    late BuildContext contesto;
    await tester.pumpWidget(MultiProvider(
      providers: [Provider<ApiClient>.value(value: api), ChangeNotifierProvider<AuthState>.value(value: auth)],
      child: MaterialApp(home: Scaffold(body: Builder(builder: (c) {
        contesto = c;
        return const SizedBox();
      }))),
    ));
    return () async {
      risultato = await (tipo == 'ATTIVITA' ? modificaAttivita(contesto, dati) : modificaMisura(contesto, dati));
      return risultato;
    };
  }

  testWidgets('l\'attività nuova si sceglie dal catalogo e il testo si ritocca', (tester) async {
    final avvia = await apri(tester, rpct: false, tipo: 'ATTIVITA');
    final esito = avvia();
    await tester.pumpAndSettle();
    expect(find.text('Nuova attività: dal catalogo o un procedimento'), findsOneWidget);
    await tester.tap(find.text('ATT-0012 - Pubblicazione del bando'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Voce del catalogo ATT-0012'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Pubblicazione del bando'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Pubblicazione del bando'), 'Pubblicazione del bando sul portale');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    final v = await esito;
    expect((v?['descrizione'], v?['voce_id']), ('Pubblicazione del bando sul portale', 'v1'));
  });

  testWidgets('l\'attività nuova può essere un procedimento del catalogo', (tester) async {
    final avvia = await apri(tester, rpct: true, tipo: 'ATTIVITA');
    final esito = avvia();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Procedimento'));
    await tester.pumpAndSettle();
    expect(find.text('ATT-0012 - Pubblicazione del bando'), findsNothing);
    expect(find.text('Nuovo procedimento'), findsOneWidget); // il RPCT crea quello che manca
    await tester.tap(find.text('P.7 - Rilascio del permesso di costruire'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Procedimento P.7'), findsWidgets);
    expect(find.widgetWithText(TextField, 'Rilascio del permesso di costruire'), findsOneWidget);
    // adattamento per questo processo: vuoto vale il catalogo
    expect(find.textContaining('Nel catalogo: 60 giorni'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, 'Termine di conclusione (per questo processo)'), '90 giorni');
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    final v = await esito;
    expect((v?['descrizione'], v?['procedimento_id'], v?.containsKey('voce_id')), ('Rilascio del permesso di costruire', 'pr7', false));
    expect(v?['procedimento_adattato'], {'termine_conclusione': '90 giorni'});
    expect(v?.keys.where((k) => k.startsWith('adatta_')), isEmpty);
    expect((v?['procedimento'] as Map?)?['codice'], 'P.7');
  });

  testWidgets('la misura nuova prende dalla voce tipo, categoria, indicatore e target', (tester) async {
    final avvia = await apri(tester, rpct: true, tipo: 'MISURA');
    final esito = avvia();
    await tester.pumpAndSettle();
    await tester.tap(find.text('MIS-0007 - Doppia firma'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    final v = await esito;
    expect((v?['voce_id'], v?['tipo'], v?['categoria'], v?['indicatore'], v?['target']),
        ('v2', 'GENERALE', 'Controllo', 'Atti firmati', '100%'));
  });

  testWidgets('il referente propone la voce che manca', (tester) async {
    final avvia = await apri(tester, rpct: false, tipo: 'ATTIVITA');
    final esito = avvia();
    await tester.pumpAndSettle();
    expect(find.text('Nuova voce'), findsNothing);
    await tester.enterText(find.widgetWithText(TextField, 'Cerca (codice o testo)'), 'Collaudo delle opere');
    await tester.tap(find.text('Proponi una voce nuova'));
    await tester.pumpAndSettle();
    // la voce parte dal testo cercato (sotto resta la ricerca)
    expect(find.widgetWithText(TextField, 'Collaudo delle opere'), findsNWidgets(2));
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(await esito, isNull); // finché non è approvata non si sceglie
    expect(corpi['POST /api/v1/anticorruzione/proposte'],
        {'tipo': 'CREA', 'oggetto': 'VOCE', 'dati': {'descrizione': 'Collaudo delle opere', 'tipo_voce': 'ATTIVITA'}});
  });

  testWidgets('il RPCT crea la voce che manca e la usa subito', (tester) async {
    final avvia = await apri(tester, rpct: true, tipo: 'ATTIVITA');
    final esito = avvia();
    await tester.pumpAndSettle();
    expect(find.text('Proponi una voce nuova'), findsNothing);
    await tester.enterText(find.widgetWithText(TextField, 'Cerca (codice o testo)'), 'Collaudo delle opere');
    await tester.tap(find.text('Nuova voce'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Voce del catalogo ATT-E001'), findsOneWidget);
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    final v = await esito;
    expect((v?['descrizione'], v?['voce_id']), ('Collaudo delle opere', 'v9'));
  });

  testWidgets('prima di proporre una voce si vedono le simili e se ne sceglie una', (tester) async {
    final avvia = await apri(tester, rpct: false, tipo: 'ATTIVITA', simili: true);
    final esito = avvia();
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Cerca (codice o testo)'), 'Collaudo dei lavori');
    await tester.tap(find.text('Proponi una voce nuova'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Nel catalogo ci sono voci simili'), findsOneWidget);
    expect(find.text('somiglianza 91% · usata in 2 elementi'), findsOneWidget);

    // si torna alla modifica: la voce scritta resta
    await tester.tap(find.text('Torna alla modifica'));
    await tester.pumpAndSettle();
    expect(find.text('Nuova voce: attività'), findsOneWidget);
    expect(corpi['POST /api/v1/anticorruzione/proposte'], isNull);

    // si sceglie la simile: niente proposta, l'attività nasce da quella voce
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    expect(find.text('Proponi comunque'), findsOneWidget);
    await tester.tap(find.text('Scegli questa'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Voce del catalogo ATT-0031'), findsOneWidget);
    await tester.tap(find.text('Salva'));
    await tester.pumpAndSettle();
    final v = await esito;
    expect((v?['descrizione'], v?['voce_id']), ('Collaudo delle opere pubbliche', 'v5'));
    expect(corpi['POST /api/v1/anticorruzione/proposte'], isNull);
  });

  test('voce originale solo se il testo è stato ritoccato', () {
    final el = {'voce': {'codice': 'ATT-0012', 'descrizione': 'Pubblicazione del bando'}};
    expect(voceRitoccata(el, 'pubblicazione  del bando.'), isNull);
    expect(voceRitoccata(el, 'Pubblicazione del bando sul portale'), 'Dal catalogo (ATT-0012): Pubblicazione del bando');
    expect(voceRitoccata(const {}, 'x'), isNull);
  });
}
