import 'dart:convert';
import 'dart:typed_data';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/assistente/assistente_page.dart';
import 'package:atti_pa/util/scelta_file.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

http.Response _json(Object corpo, [int stato = 200]) =>
    http.Response(jsonEncode(corpo), stato, headers: {'content-type': 'application/json; charset=utf-8'});

Future<void> _apri(WidgetTester tester, ApiClient api, ConversazioneAssistente c) async {
  tester.view.physicalSize = const Size(1200, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(Provider<ApiClient>.value(
    value: api,
    child: MaterialApp(home: AssistentePage(conversazione: c)),
  ));
  await tester.pumpAndSettle();
}

void main() {
  const avviso = 'fornitore esterno';

  testWidgets('invia la conversazione intera; l\'avviso compare solo con un LLM esterno', (tester) async {
    final inviati = <List<dynamic>>[];
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      if (r.method == 'GET') return _json({'llm_esterno': true});
      final messaggi = jsonDecode(r.body)['messaggi'] as List<dynamic>;
      inviati.add(messaggi);
      return _json({'testo': 'Risposta ${inviati.length}'});
    }));
    final c = ConversazioneAssistente();
    await _apri(tester, api, c);
    expect(find.textContaining(avviso), findsOneWidget);

    for (final testo in ['Prima domanda', 'Seconda domanda']) {
      await tester.enterText(find.byType(TextField), testo);
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();
    }
    expect(inviati.last.map((m) => m['content']), ['Prima domanda', 'Risposta 1', 'Seconda domanda']);
    expect(find.textContaining('Risposta 2', findRichText: true), findsOneWidget);

    await tester.tap(find.text('Nuova conversazione'));
    await tester.pumpAndSettle();
    expect(c.messaggi, isEmpty);
    expect(find.textContaining(avviso), findsOneWidget);
  });

  testWidgets('modello locale: nessun avviso; dopo un errore si può riprovare', (tester) async {
    var tentativi = 0;
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      if (r.method == 'GET') return _json({'llm_esterno': false});
      return ++tentativi == 1 ? _json({'message': 'Modello non raggiungibile'}, 502) : _json({'testo': 'Ora funziona'});
    }));
    final c = ConversazioneAssistente();
    await _apri(tester, api, c);
    expect(find.textContaining(avviso), findsNothing);

    await tester.enterText(find.byType(TextField), 'Domanda');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    expect(c.errore, isNotNull);

    await tester.tap(find.text('Riprova'));
    await tester.pumpAndSettle();
    expect(c.errore, isNull);
    expect(c.messaggi.map((m) => m['content']), ['Domanda', 'Ora funziona']);
  });

  testWidgets('la conversazione resta quando la pagina viene ricreata', (tester) async {
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      if (r.method == 'GET') return _json({'llm_esterno': false});
      return _json({'testo': 'Risposta conservata'});
    }));
    final c = ConversazioneAssistente();
    await _apri(tester, api, c);
    await tester.enterText(find.byType(TextField), 'Domanda');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    await tester.pumpWidget(const SizedBox());
    await _apri(tester, api, c);
    expect(find.text('Domanda'), findsOneWidget);
    expect(find.textContaining('Risposta conservata', findRichText: true), findsOneWidget);
  });

  testWidgets('documenti della conversazione: caricamento, domanda sui selezionati, fonti, chiusura', (tester) async {
    final richieste = <http.Request>[];
    var letture = 0;
    final id = 'd' * 32;
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      richieste.add(r);
      switch (r.url.path) {
        case '/api/v1/assistente':
          return _json({'llm_esterno': false, 'formati_documenti': ['pdf', 'docx'], 'max_mb_documento': 20});
        case '/api/v1/assistente/sessione':
          if (r.method == 'DELETE') return http.Response('', 204);
          return _json({'sessione': 'token-firmato', 'limiti': {'max_documenti': 10, 'max_token': 500000}}, 201);
        case '/api/v1/assistente/sessione/documenti':
          return _json({'id': id, 'nome': 'Delibera.pdf', 'stato': 'in_coda'}, 202);
        case '/api/v1/assistente/messaggi':
          final corpo = jsonDecode(r.body) as Map<String, dynamic>;
          return _json({
            'testo': 'Il contributo è di 15.000 euro [Delibera.pdf, parte 3].',
            if (corpo['documenti'] != null) 'fonti': [{'documento': 'Delibera.pdf', 'parte': 3, 'id': id}],
          });
      }
      return _json(++letture == 1
          ? {'id': id, 'nome': 'Delibera.pdf', 'stato': 'indicizzazione'}
          : {'id': id, 'nome': 'Delibera.pdf', 'stato': 'pronto', 'token': 1200, 'parti': 3});
    }));
    final c = ConversazioneAssistente();
    await _apri(tester, api, c);
    expect(find.text('Carica'), findsOneWidget); // pannello a lato su schermo largo

    c.carica(api, FileScelto('Delibera.pdf', Uint8List.fromList([1, 2, 3])));
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('in coda'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
    await tester.pump(const Duration(seconds: 3));
    expect(find.text('3 parti · 1.200 token'), findsOneWidget);
    expect(find.textContaining('1.200 di 500.000 token'), findsOneWidget);
    final caricamento = richieste.firstWhere((r) => r.url.path.endsWith('/sessione/documenti'));
    expect(caricamento.headers['X-Assistente-Sessione'], 'token-firmato');

    await tester.enterText(find.byType(TextField), 'Di quanto è il contributo?');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    final domanda = richieste.lastWhere((r) => r.url.path.endsWith('/messaggi'));
    expect(jsonDecode(domanda.body)['documenti'], [id]);
    expect(domanda.headers['X-Assistente-Sessione'], 'token-firmato');
    expect(find.textContaining('Passaggi consultati: Delibera.pdf (parte 3)'), findsOneWidget);

    // deselezionato: la domanda torna libera, senza documenti né sessione
    await tester.tap(find.byType(Checkbox));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'Scrivi una email');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    final libera = richieste.lastWhere((r) => r.url.path.endsWith('/messaggi'));
    expect((jsonDecode(libera.body) as Map).containsKey('documenti'), isFalse);
    expect(libera.headers.containsKey('X-Assistente-Sessione'), isFalse);

    await tester.tap(find.text('Nuova conversazione'));
    await tester.pumpAndSettle();
    expect(c.documenti, isEmpty);
    expect(richieste.last.method, 'DELETE');
    expect(richieste.last.url.path, '/api/v1/assistente/sessione');
  });

  testWidgets('azione Riassumi: avanzamento, risultato nella conversazione', (tester) async {
    final richieste = <http.Request>[];
    var letture = 0;
    final id = 'd' * 32;
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      richieste.add(r);
      switch (r.url.path) {
        case '/api/v1/assistente':
          return _json({'llm_esterno': false, 'formati_documenti': ['pdf']});
        case '/api/v1/assistente/sessione':
          return _json({'sessione': 't', 'limiti': {'max_documenti': 10, 'max_token': 500000}}, 201);
        case '/api/v1/assistente/sessione/documenti':
          return _json({'id': id, 'nome': 'Legge.pdf', 'stato': 'pronto', 'token': 90000, 'parti': 60}, 202);
        case '/api/v1/assistente/azioni':
          return _json({'id': 'lavoro-1', 'tipo': 'riassunto', 'stato': 'in_coda', 'avanzamento': {'fatti': 0, 'totale': 0}}, 202);
      }
      return _json(++letture == 1
          ? {'stato': 'in_corso', 'avanzamento': {'fatti': 3, 'totale': 9}}
          : {'stato': 'completata', 'avanzamento': {'fatti': 9, 'totale': 9}, 'testo': 'La legge disciplina il turismo.'});
    }));
    final c = ConversazioneAssistente();
    await _apri(tester, api, c);
    c.carica(api, FileScelto('Legge.pdf', Uint8List.fromList([1])));
    await tester.pump();
    await tester.pump();
    expect(find.text('Confronta'), findsOneWidget);
    final confronta = tester.widget<OutlinedButton>(find.ancestor(of: find.text('Confronta'), matching: find.byType(OutlinedButton)));
    expect(confronta.onPressed, isNull); // un solo documento

    await tester.tap(find.text('Riassumi'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 3));
    expect(find.text('Riassunto in corso: passo 3 di 9'), findsOneWidget);
    final avvio = richieste.firstWhere((r) => r.url.path == '/api/v1/assistente/azioni');
    expect(jsonDecode(avvio.body), {'tipo': 'riassunto', 'documenti': [id], 'istruzioni': ''});
    expect(avvio.headers['X-Assistente-Sessione'], 't');

    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();
    expect(find.textContaining('La legge disciplina il turismo', findRichText: true), findsOneWidget);
    expect(c.inAttesa, isFalse);
    expect(c.messaggi.first['content'], 'Riassumi: Legge.pdf');
  });

  testWidgets('sessione scaduta nel RAG: i documenti vanno ricaricati', (tester) async {
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      switch (r.url.path) {
        case '/api/v1/assistente':
          return _json({'llm_esterno': false, 'formati_documenti': ['pdf']});
        case '/api/v1/assistente/sessione':
          return _json({'sessione': 't', 'limiti': {'max_documenti': 10, 'max_token': 500000}}, 201);
        case '/api/v1/assistente/sessione/documenti':
          return _json({'id': 'e' * 32, 'nome': 'Legge.pdf', 'stato': 'in_coda'}, 202);
      }
      return _json({'detail': 'La sessione dei documenti è scaduta: caricali di nuovo'}, 404);
    }));
    final c = ConversazioneAssistente();
    await _apri(tester, api, c);
    c.carica(api, FileScelto('Legge.pdf', Uint8List.fromList([1])));
    await tester.pump();
    await tester.pump(const Duration(seconds: 3));
    expect(c.documenti.single.fallito, isTrue);
    expect(find.textContaining('Sessione scaduta'), findsOneWidget);
  });

  testWidgets('senza collegamento al RAG non c\'è il pannello dei documenti', (tester) async {
    final api = ApiClient('http://api.test', client: MockClient((r) async => _json({'llm_esterno': false, 'formati_documenti': []})));
    await _apri(tester, api, ConversazioneAssistente());
    expect(find.text('Carica'), findsNothing);
    expect(find.textContaining('Documenti'), findsNothing);
  });
}
