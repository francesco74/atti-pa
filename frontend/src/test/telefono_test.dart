import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/anticorruzione/mappatura.dart';
import 'package:atti_pa/ui/assistente/assistente_page.dart';
import 'package:atti_pa/ui/home_shell.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Le pagine sullo schermo di un telefono (390 x 844, come la maggior parte degli
/// smartphone). Oltre agli sbordamenti, che il framework segnala da solo, cerca i testi
/// schiacciati: un testo lungo chiuso in una colonna stretta da pulsanti o etichette
/// accanto, che si allunga in verticale e rende la pagina inutilizzabile.
const _telefono = Size(390, 844);

Future<void> _suTelefono(WidgetTester tester) async {
  tester.view.physicalSize = _telefono;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

/// Testi di almeno 40 caratteri larghi meno del 40% dello schermo: vanno a capo ogni
/// poche parole perché qualcosa accanto si prende lo spazio.
void _nessunTestoSchiacciato(WidgetTester tester) {
  final schiacciati = <String>[];
  void visita(RenderObject o) {
    if (o is RenderParagraph && o.hasSize) {
      final testo = o.text.toPlainText();
      if (testo.length >= 40 && o.size.width < _telefono.width * 0.4) {
        schiacciati.add('"${testo.length > 60 ? '${testo.substring(0, 60)}…' : testo}" '
            '(largo ${o.size.width.round()} px)');
      }
    }
    o.visitChildren(visita);
  }

  visita(tester.binding.rootElement!.renderObject!);
  expect(schiacciati, isEmpty, reason: 'testi schiacciati sullo schermo del telefono');
}

http.Response _json(Object corpo) =>
    http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json; charset=utf-8'});

void main() {
  testWidgets('assistente: la descrizione non viene schiacciata dai pulsanti', (tester) async {
    await _suTelefono(tester);
    final api = ApiClient('http://api.test', client: MockClient((r) async => _json({'llm_esterno': false, 'formati_documenti': ['pdf', 'docx']})));
    final c = ConversazioneAssistente();
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: api,
      child: MaterialApp(home: AssistentePage(conversazione: c)),
    ));
    await tester.pumpAndSettle();

    expect(find.textContaining('Documenti (0)'), findsOneWidget);
    _nessunTestoSchiacciato(tester);
  });

  testWidgets('mappatura: processi, attività e rischi leggibili, con le azioni', (tester) async {
    await _suTelefono(tester);
    const descrizione = 'Predisposizione del bando di gara e dei documenti di gara allegati';
    final client = MockClient((r) async {
      if (r.url.path.endsWith('/processi')) {
        return _json([
          {
            'id': 'p1', 'codice': 'C.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'c',
            'denominazione': 'Affidamento di lavori, servizi e forniture con procedura aperta',
            'struttura_id': null, 'attivita': 1, 'rischi': 1, 'misure': 1, 'livello_massimo': null,
          },
        ]);
      }
      if (r.url.path.endsWith('/processi/p1')) {
        return _json({
          'id': 'p1', 'codice': 'C.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'c',
          'denominazione': 'Affidamento di lavori, servizi e forniture con procedura aperta',
          'attivita': [
            {'id': 'a1', 'codice': 'C.1.1', 'descrizione': descrizione, 'rischi': [
              {'id': 'r1', 'codice': 'C.1.1_R.1', 'evento': 'Definizione dei requisiti di accesso su misura di un concorrente',
                'valori_probabilita': null, 'misure': [
                {'id': 'm1', 'codice': 'C.1.1_R.1_M.1', 'descrizione': 'Doppia verifica dei requisiti da parte di due funzionari', 'tipo': 'SPECIFICA'},
              ]},
            ]},
          ],
        });
      }
      return _json(const []);
    });
    final api = ApiClient('http://prova', client: client);
    final auth = AuthState(api)
      ..utente = Utente.daJson({
        'id': 'u1', 'username': 'rpct', 'ruoli': ['ANTICORRUZIONE_RPCT'],
        'ente': {'codice': 'prova', 'nome': 'Ente', 'moduli': ['anticorruzione']},
      });
    final dati = DatiAnticorruzione(
      metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto']},
      aree: const [
        {'id': 'c', 'codice': 'C', 'descrizione': 'Contratti pubblici e affidamenti di lavori, servizi e forniture', 'descrizione_breve': null},
      ],
      strutture: const [],
      obblighi: const [],
    );
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthState>.value(value: auth),
        Provider.value(value: dati),
      ],
      child: MaterialApp(home: Scaffold(body: MappaturaTab(onDatiCambiati: () {}))),
    ));
    await tester.pumpAndSettle();
    _nessunTestoSchiacciato(tester); // aree, con modifica ed eliminazione

    await tester.tap(find.textContaining('C - Contratti pubblici'));
    await tester.pumpAndSettle();
    _nessunTestoSchiacciato(tester); // processi, con il livello

    await tester.tap(find.textContaining('C.1 - Affidamento'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('C.1.1 - $descrizione'), 200, scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    expect(find.text('Non valutato'), findsWidgets);
    _nessunTestoSchiacciato(tester); // attività, con livello, modifica ed eliminazione

    await tester.tap(find.text('C.1.1 - $descrizione'));
    await tester.pumpAndSettle();
    _nessunTestoSchiacciato(tester); // rischi e misure
  });

  testWidgets('tutte le voci del menu e tutte le schede', (tester) async {
    await _suTelefono(tester);
    // elenchi vuoti; i dati di base dei moduli, perché si aprano con tutte le schede
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      if (r.url.path.endsWith('/anticorruzione/metodologia')) {
        return _json({
          'scala': ['Basso', 'Alto'], 'livelli': ['Basso', 'Alto'], 'matrice': <String, Object>{},
          'indicatori_probabilita': <Object>[], 'indicatori_impatto': <Object>[],
          'categorie_misure': <Object>[], 'fattori_abilitanti': <Object>[],
        });
      }
      if (r.url.path.endsWith('/performance/contesto')) {
        return _json({'amministratore': true, 'approvatore': true, 'misure': true, 'da_decidere': 0});
      }
      return _json(const []);
    }));
    final utente = Utente.daJson({
      'id': 'u1', 'username': 'admin', 'nome_completo': 'Amministratore di prova', 'ruoli': ['ADMIN'],
      'ente': {
        'codice': 'prova', 'nome': 'Comune di Prova',
        'moduli': ['redazione', 'trasparenza', 'anticorruzione', 'performance', 'assistente'],
      },
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

    final voci = tester.widget<NavigationBar>(find.byType(NavigationBar)).destinations.length;
    for (var v = 0; v < voci; v++) {
      await tester.tap(find.byType(NavigationDestination).at(v));
      await tester.pumpAndSettle();
      final voce = (tester.widget<NavigationDestination>(find.byType(NavigationDestination).at(v))).label;
      debugPrint('VOCE: $voce');
      _nessunTestoSchiacciato(tester);
      final schede = find.byType(Tab).evaluate().length;
      for (var t = 0; t < schede; t++) {
        await tester.tap(find.byType(Tab).at(t));
        await tester.pumpAndSettle();
        debugPrint('  SCHEDA ${t + 1} di $schede');
        _nessunTestoSchiacciato(tester);
      }
    }
  });
}
