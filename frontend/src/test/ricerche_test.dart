import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/pubblico/procedimenti_pubblici.dart';
import 'package:atti_pa/ui/ricerche/ricerche_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

http.Response _json(Object corpo, [int stato = 200]) =>
    http.Response(jsonEncode(corpo), stato, headers: {'content-type': 'application/json'});

/// Registro delle ricerche e feedback: il cittadino cerca, apre un risultato (ricerca trovata)
/// e lascia il feedback sulla scheda; una ricerca senza risultati si registra quando cambia il
/// testo; chi analizza le ricerche le vede raggruppate e le segna gestite.
void main() {
  testWidgets('pagina pubblica: ricerca conclusa e feedback', (tester) async {
    tester.view.physicalSize = const Size(1400, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final inviati = <String, List<Map<String, dynamic>>>{'registro': [], 'feedback': []};
    final api = ApiClient('http://prova', client: MockClient((r) async {
      final p = r.url.path;
      if (p.endsWith('/pubblico/procedimenti')) {
        return _json({
          'ente': {'nome': 'Comune di Prova', 'logo': false},
          'strutture': [{'id': 's1', 'codice': 'SETTORE 4', 'descrizione': 'Servizi sociali'}],
          'procedimenti': [
            {'id': 'p1', 'codice': 'A.1', 'denominazione': 'Contributo affitto', 'tipologia': null, 'struttura_id': 's1'},
            {'id': 'p2', 'codice': 'A.2', 'denominazione': 'Accesso agli atti', 'tipologia': null, 'struttura_id': 's1'},
          ],
        });
      }
      if (p.endsWith('/procedimenti/ricerca')) {
        final trovati = r.url.queryParameters['testo'] == 'locazione' ? ['p1'] : <String>[];
        return _json({'semantica': true, 'risultati': [for (final id in trovati) {'id': id, 'parole': ['locazion'], 'semantica': false}]});
      }
      if (p.endsWith('/ricerche/registro') || p.endsWith('/ricerche/feedback')) {
        final chiave = p.endsWith('registro') ? 'registro' : 'feedback';
        inviati[chiave]!.add(jsonDecode(r.body) as Map<String, dynamic>);
        return _json({'id': '$chiave${inviati[chiave]!.length}'}, 201);
      }
      return _json({'id': 'p1', 'codice': 'A.1', 'struttura_id': 's1', 'scheda': <String, dynamic>{}});
    }));
    await tester.pumpWidget(MultiProvider(
      providers: [Provider<ApiClient>.value(value: api), ChangeNotifierProvider(create: (_) => AuthState(api))],
      child: const MaterialApp(home: ProcedimentiPubbliciPage()),
    ));
    await tester.pumpAndSettle();

    // senza risultati: si registra quando si cambia il testo dopo averli visti
    await tester.enterText(find.byType(TextField), 'passo carrabile');
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Nessun procedimento trovato.'), findsOneWidget);
    expect(find.text('Hai trovato quello che cercavi?'), findsOneWidget);
    expect(inviati['registro'], isEmpty); // nessun frammento registrato mentre si scrive
    await tester.pump(const Duration(seconds: 3));
    await tester.enterText(find.byType(TextField), 'locazione');
    await tester.pump(const Duration(milliseconds: 50));
    expect(inviati['registro']!.single,
        {'testo': 'passo carrabile', 'risultati': 0, 'esito': 'NESSUN_RISULTATO', 'semantica': true, 'ambito': 'PROCEDIMENTI'});

    // trovata: si apre il risultato
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.text('Contributo affitto'));
    await tester.pumpAndSettle();
    expect(inviati['registro']!.last, containsPair('esito', 'TROVATA'));
    expect(inviati['registro']!.last, containsPair('posizione', 1));

    // feedback sulla scheda, con il commento facoltativo
    expect(find.text('Questa pagina ti è stata utile?'), findsOneWidget);
    await tester.tap(find.text('No'));
    await tester.pump();
    await tester.enterText(find.widgetWithText(TextField, 'Cosa mancava? (facoltativo)'), 'Il modulo');
    await tester.tap(find.text('Invia'));
    await tester.pumpAndSettle();
    expect(inviati['feedback']!.single, {
      'tipo': 'SCHEDA', 'riferimento_id': 'p1', 'riferimento': 'A.1 Contributo affitto', 'utile': false,
      'commento': 'Il modulo', 'ambito': 'PROCEDIMENTI',
    });
    expect(find.text('Grazie per la segnalazione.'), findsOneWidget);
    expect(inviati['registro'], hasLength(2)); // la ricerca conclusa non si registra due volte
  });

  testWidgets('consultazione: domande senza risposta, gestione, feedback e riepilogo', (tester) async {
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final chiamate = <String>[];
    Map<String, dynamic>? gestione;
    final api = ApiClient('http://prova', client: MockClient((r) async {
      chiamate.add('${r.method} ${r.url.path}?${r.url.query}');
      final p = r.url.path;
      if (p.endsWith('/ambiti')) return _json([{'id': 'PROCEDIMENTI', 'descrizione': 'Procedimenti (art. 35)'}]);
      if (p.endsWith('/senza-risposta/gestione')) {
        gestione = jsonDecode(r.body) as Map<String, dynamic>;
        return _json({'gestite': 2});
      }
      if (p.endsWith('/senza-risposta')) {
        return _json([
          {'ambito': 'PROCEDIMENTI', 'chiave': 'affitt contrib', 'testo': 'contributo affitto',
           'varianti': ['contributo affitto', 'affitti contributi'], 'volte': 2, 'da_gestire': 2, 'pubbliche': 2,
           'esiti': {'NESSUN_RISULTATO': 2}, 'ultima': '2026-11-07T10:00:00', 'nota': null, 'gestita_da': null, 'gestita_il': null},
        ]);
      }
      if (p.endsWith('/feedback')) {
        return _json([
          {'id': 'f1', 'ambito': 'PROCEDIMENTI', 'pubblica': true, 'tipo': 'SCHEDA', 'testo': null, 'riferimento_id': 'p1',
           'riferimento': 'A.1 Contributo affitto', 'utile': false, 'commento': 'Manca il modulo',
           'quando': '2026-11-07T10:00:00', 'gestito_il': null, 'gestito_da': null, 'nota': null},
        ]);
      }
      if (p.endsWith('/riepilogo')) {
        return _json({
          'mesi': [{'mese': '2026-11', 'ricerche': 10, 'trovate': 7, 'senza_risposta': 3, 'utili': 2, 'non_utili': 1}],
          'schede_non_utili': [{'riferimento': 'A.1 Contributo affitto', 'volte': 1}],
        });
      }
      return _json(const []);
    }));
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: api,
      child: const MaterialApp(home: Scaffold(body: RicerchePage())),
    ));
    await tester.pumpAndSettle();
    expect(find.text('contributo affitto'), findsOneWidget);
    expect(find.text('Anche: affitti contributi'), findsOneWidget);
    expect(find.textContaining('2 volte (2 da gestire)'), findsOneWidget);
    expect(chiamate.firstWhere((c) => c.contains('/senza-risposta')), contains('da='));

    await tester.tap(find.text('Segna gestita'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'Aggiunta la parola locazione');
    await tester.tap(find.widgetWithText(FilledButton, 'Segna gestita'));
    await tester.pumpAndSettle();
    expect(gestione, {'ambito': 'PROCEDIMENTI', 'chiave': 'affitt contrib', 'nota': 'Aggiunta la parola locazione'});

    await tester.tap(find.text('Feedback').first);
    await tester.pumpAndSettle();
    expect(find.text('Pagina: A.1 Contributo affitto'), findsOneWidget);
    expect(find.text('«Manca il modulo»'), findsOneWidget);
    expect(chiamate.lastWhere((c) => c.contains('/feedback')), contains('utile=false'));

    await tester.tap(find.text('Riepilogo'));
    await tester.pumpAndSettle();
    expect(find.text('70%'), findsOneWidget);
    expect(find.text('Pagine giudicate non utili'), findsOneWidget);
  });
}
