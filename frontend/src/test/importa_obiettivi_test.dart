import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/performance/comune.dart';
import 'package:atti_pa/ui/performance/importa_obiettivi.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Obiettivi letti dal PIAO: si indica il documento, si attende la lettura (con le parti lette),
/// si rivedono gli obiettivi (struttura proposta, già presenti esclusi, avvisi) e si salvano
/// quelli scelti; senza struttura non si salva.
void main() {
  testWidgets('lettura, revisione e salvataggio degli obiettivi', (tester) async {
    tester.view.physicalSize = const Size(1400, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final corpi = <String, Object?>{};
    var controlli = 0;
    final client = MockClient((r) async {
      if (r.body.isNotEmpty) corpi['${r.method} ${r.url.path}'] = jsonDecode(r.body);
      Object? corpo = const {};
      if (r.url.path.endsWith('/importazioni') && r.method == 'POST') {
        corpo = {'id': 'l1', 'stato': 'IN_CODA'};
      } else if (r.url.path.endsWith('/importazioni/l1')) {
        expect(r.url.queryParameters, {'piao_id': 'piao', 'anno': '2026'});
        corpo = ++controlli == 1
            ? {'id': 'l1', 'stato': 'IN_CORSO', 'avanzamento': [2, 5]}
            : {
                'id': 'l1', 'stato': 'COMPLETATA', 'avvisi': ['Parte 4 di 5 del documento non letta'],
                'obiettivi': [
                  {'codice': 'P1_26_1', 'titolo': 'Concorsi più rapidi', 'descrizione': 'Ridurre i tempi', 'tipo': 'OPERATIVO',
                   'struttura': 'Settore 2 Risorse umane', 'responsabile': 'Rossi', 'struttura_id': 's2', 'presente': null,
                   'avvisi': ['«Qualità»: valore atteso non riconosciuto, impostato come sì/no'],
                   'elementi': [{'descrizione': 'Bando unico', 'scadenza': '2026-06-30', 'indicatori': [
                     {'descrizione': 'Pubblicazione del bando', 'tipo': 'DATA', 'target_data': '2026-06-30', 'unita': null,
                      'partenza': null, 'target': null, 'verso': 'CRESCENTE', 'fonte': null}]}]},
                  {'codice': 'P1_26_2', 'titolo': 'Strade', 'descrizione': null, 'tipo': 'OPERATIVO', 'struttura': 'Ufficio X',
                   'responsabile': null, 'struttura_id': null, 'presente': null, 'avvisi': [],
                   'elementi': [{'descrizione': 'Strade', 'scadenza': '2026-12-31', 'indicatori': []}]},
                  {'codice': 'P1_26_3', 'titolo': 'Verde', 'descrizione': null, 'tipo': 'OPERATIVO', 'struttura': 'Settore 2',
                   'responsabile': null, 'struttura_id': 's2', 'avvisi': [],
                   'presente': {'id': 'o9', 'codice': 'P1_26_3', 'titolo': 'Verde', 'struttura_id': 's2'},
                   'elementi': [{'descrizione': 'Verde', 'scadenza': '2026-12-31', 'indicatori': []}]},
                ],
              };
      } else if (r.url.path.endsWith('/obiettivi/importati')) {
        corpo = {'creati': 1, 'ids': ['n1']};
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    });
    final dati = DatiPerformance(contesto: const {'approvatore': true}, piao: const [], strutture: const [
      {'id': 's2', 'codice': 'SETTORE 2', 'descrizione': 'Risorse umane', 'attiva': true},
      {'id': 's3', 'codice': 'SETTORE 3', 'descrizione': 'Lavori pubblici', 'attiva': true},
    ]);
    bool? esito;
    await tester.pumpWidget(Provider<ApiClient>.value(
      value: ApiClient('http://prova', client: client),
      child: MaterialApp(home: Builder(builder: (context) => TextButton(
        onPressed: () async => esito = await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => ImportaObiettiviPage(
          dati: dati, piao: const {'id': 'piao', 'titolo': 'PIAO 2026-2028', 'anno_inizio': 2026, 'stato': 'APERTO'}, anno: 2026))),
        child: const Text('apri'),
      ))),
    ));
    await tester.tap(find.text('apri'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Indirizzo del documento'), 'https://www.ente.it/piao.pdf');
    await tester.pump();
    await tester.tap(find.text('Leggi gli obiettivi'));
    await tester.pump();
    expect(corpi['POST /api/v1/performance/importazioni'], {'url': 'https://www.ente.it/piao.pdf'});
    await tester.pump(const Duration(seconds: 3));
    await tester.pump();
    expect(find.text('Lette 2 parti su 5'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();

    // il primo è scelto (struttura trovata), il secondo no (senza struttura), il terzo c'è già
    expect(find.textContaining('Trovati 3 obiettivi per il 2026'), findsOneWidget);
    expect(find.text('Importa 1 obiettivi'), findsOneWidget);
    expect(find.textContaining('Parte 4 di 5'), findsOneWidget);
    await tester.tap(find.text('Seleziona tutti'));
    await tester.pump();
    await tester.tap(find.text('Importa 3 obiettivi'));
    await tester.pump();
    expect(find.text('Scegli la struttura di ogni obiettivo da importare'), findsOneWidget);
    await tester.tap(find.text('Nessuno'));
    await tester.pump();
    await tester.tap(find.byType(Checkbox).first);
    await tester.pump();
    await tester.tap(find.text('P1_26_1 - Concorsi più rapidi'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Pubblicazione del bando'), findsOneWidget);
    expect(find.textContaining('Avviso: «Qualità»'), findsOneWidget);
    await tester.tap(find.text('Importa 1 obiettivi'));
    await tester.pumpAndSettle();
    final salvato = corpi['POST /api/v1/performance/obiettivi/importati'] as Map;
    expect((salvato['piao_id'], salvato['anno'], salvato['fonte']), ('piao', 2026, 'https://www.ente.it/piao.pdf'));
    final o = (salvato['obiettivi'] as List).single as Map;
    expect((o['struttura_id'], o['codice'], (o['elementi'] as List).length), ('s2', 'P1_26_1', 1));
    expect(esito, isTrue);
  });
}
