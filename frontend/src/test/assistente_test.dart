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

  testWidgets('un documento allegato viene convertito e il suo testo entra nel messaggio', (tester) async {
    final inviati = <List<dynamic>>[];
    var letture = 0;
    final api = ApiClient('http://api.test', client: MockClient((r) async {
      if (r.url.path == '/api/v1/assistente') {
        return _json({'llm_esterno': false, 'formati_allegati': ['pdf', 'docx'], 'max_mb_allegato': 20});
      }
      if (r.url.path == '/api/v1/assistente/allegati') return _json({'job_id': 'a' * 32, 'nome': 'relazione.pdf'}, 202);
      if (r.url.path.startsWith('/api/v1/assistente/allegati/')) {
        return _json(++letture == 1 ? {'stato': 'running'} : {'stato': 'completed', 'testo': 'Testo della relazione'});
      }
      inviati.add(jsonDecode(r.body)['messaggi'] as List<dynamic>);
      return _json({'testo': 'Ecco il riassunto'});
    }));
    final c = ConversazioneAssistente();
    await _apri(tester, api, c);
    expect(find.byIcon(Icons.attach_file), findsOneWidget);

    c.allega(api, FileScelto('relazione.pdf', Uint8List.fromList([1, 2, 3])));
    await tester.pump();
    expect(find.textContaining('in conversione'), findsOneWidget);
    final invio = tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.send));
    expect(invio.onPressed, isNull); // finché il testo del documento non è pronto
    await tester.pump(const Duration(seconds: 3));
    await tester.pump(const Duration(seconds: 3));
    expect(find.textContaining('21 caratteri'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'Riassumi');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();
    final contenuto = inviati.single.single['content'] as String;
    expect(contenuto, startsWith('Riassumi'));
    expect(contenuto, contains('Testo della relazione'));
    expect(inviati.single.single.keys, unorderedEquals(['role', 'content']));
    expect(find.text('relazione.pdf'), findsOneWidget); // nella chat il nome, non il testo
    expect(find.textContaining('Testo della relazione'), findsNothing);
    expect(c.allegati, isEmpty);
  });

  testWidgets('senza collegamento al RAG non si possono allegare documenti', (tester) async {
    final api = ApiClient('http://api.test', client: MockClient((r) async => _json({'llm_esterno': false, 'formati_allegati': []})));
    await _apri(tester, api, ConversazioneAssistente());
    expect(find.byIcon(Icons.attach_file), findsNothing);
  });
}
