import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/anticorruzione/mappatura.dart';
import 'package:atti_pa/ui/pubblico/procedimenti_pubblici.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Procedimenti e art. 35: nella mappatura il procedimento mostra la completezza dei dati e la
/// scheda dell'allegato 11; la pagina pubblica va dalle strutture ai procedimenti alla scheda.
const _scheda = {
  'tipologia': 'Contributi economici', 'denominazione': 'Contributo affitto', 'descrizione': 'Contributo per il canone',
  'riferimenti_normativi': 'L. 431/1998', 'unita_istruttoria': 'Servizi sociali',
  'uff_resp_denom': 'Servizi sociali', 'uff_resp_tel': '0583 1234', 'uff_resp_peo': 'sociali@ente.it', 'uff_resp_pec': '',
  'ufficio_finale_diverso': 'NO', 'istanza_di_parte': 'SI', 'ist_ufficio': 'Sportello sociale', 'ist_indirizzo': 'Via Roma 1',
  'ist_telefono': '0583 1234', 'ist_peo': 'sportello@ente.it', 'ist_pec': '', 'ist_modulistica': 'https://www.ente.it/moduli',
  'orari': [{'giorni': 'Lunedì', 'ora_inizio': '09:00', 'ora_fine': '12:30'}],
  'modalita_info': 'Allo sportello', 'termine_conclusione': '30 giorni', 'dichiarazione_sostitutiva': 'NO',
  'silenzio_assenso': 'SI', 'strumenti_tutela': 'Ricorso al TAR', 'servizio_online_link': '', 'servizio_online_tempi': 'Entro il 2027',
  'link_pagamenti': '', 'sost_nominativo': 'Anna Bianchi', 'sost_ufficio': 'Segreteria generale', 'sost_qualifica': 'Segretario generale',
  'sost_tel': '0583 9999', 'sost_peo': 'segreteria@ente.it', 'sost_pec': '', 'sost_attivazione': 'Istanza scritta',
};

http.Response _json(Object corpo) => http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});

void main() {
  testWidgets('pagina pubblica: strutture, procedimenti, scheda dell\'allegato 11', (tester) async {
    tester.view.physicalSize = const Size(1400, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = ApiClient('http://prova', client: MockClient((r) async {
      if (r.url.path.endsWith('/pubblico/procedimenti')) {
        return _json({
          'ente': {'nome': 'Comune di Prova', 'logo': false},
          'strutture': [{'id': 's1', 'codice': 'SETTORE 4', 'descrizione': 'Servizi sociali'}],
          'procedimenti': [
            {'id': 'p1', 'codice': 'A.1', 'denominazione': 'Contributo affitto', 'tipologia': 'Contributi economici', 'struttura_id': 's1'},
            {'id': 'p2', 'codice': 'A.2', 'denominazione': 'Accesso agli atti', 'tipologia': null, 'struttura_id': null},
          ],
        });
      }
      if (r.url.path.endsWith('/pubblico/procedimenti/ricerca')) {
        expect(r.url.queryParameters['testo'], 'come pago la locazione?');
        return _json({'semantica': false, 'risultati': [{'id': 'p1', 'parole': ['locazion'], 'semantica': false}]});
      }
      return _json({'id': 'p1', 'codice': 'A.1', 'struttura_id': 's1', 'scheda': _scheda});
    }));
    await tester.pumpWidget(MultiProvider(
      providers: [Provider<ApiClient>.value(value: api), ChangeNotifierProvider(create: (_) => AuthState(api))],
      child: const MaterialApp(home: ProcedimentiPubbliciPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Tipologie di procedimento'), findsOneWidget);
    expect(find.text('SETTORE 4 - Servizi sociali'), findsOneWidget);
    expect(find.text('Procedimenti comuni a tutte le strutture'), findsOneWidget);

    // ricerca in tutte le strutture
    await tester.enterText(find.byType(TextField), 'accesso');
    await tester.pump();
    expect(find.text('Accesso agli atti'), findsOneWidget);
    expect(find.text('Contributo affitto'), findsNothing);
    // una domanda: risultati del server (per parole e sinonimi)
    await tester.enterText(find.byType(TextField), 'come pago la locazione?');
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Contributo affitto'), findsOneWidget);
    expect(find.text('Accesso agli atti'), findsNothing);
    expect(find.text('1 risultato. In ordine di pertinenza: per parole e sinonimi.'), findsOneWidget);
    await tester.enterText(find.byType(TextField), '');
    await tester.pump();

    await tester.tap(find.text('SETTORE 4 - Servizi sociali'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Contributo affitto'));
    await tester.pumpAndSettle();
    for (final sezione in [
      'Dati sul procedimento', 'Ufficio responsabile del procedimento', 'Procedimento a istanza di parte',
      'Informazioni, termini e tutele', 'Potere sostitutivo in caso di inerzia',
    ]) {
      expect(find.text(sezione), findsOneWidget, reason: sezione);
    }
    expect(find.text('Lo stesso ufficio responsabile del procedimento.'), findsOneWidget);
    expect(find.text('Lunedì: dalle 09:00 alle 12:30'), findsOneWidget);
    expect(find.text('Attivazione prevista: Entro il 2027'), findsOneWidget);
    expect(find.text('Anna Bianchi'), findsOneWidget);
    expect(find.text('sportello@ente.it'), findsOneWidget); // email cliccabile

    await tester.tap(find.text('Strutture'));
    await tester.pumpAndSettle();
    expect(find.text('SETTORE 4 - Servizi sociali'), findsOneWidget);
  });

  testWidgets('nella mappatura il procedimento mostra la completezza dei dati art. 35', (tester) async {
    tester.view.physicalSize = const Size(1400, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = ApiClient('http://prova', client: MockClient((r) async {
      if (r.url.path.endsWith('/processi')) {
        return _json([
          {'id': 'p1', 'codice': 'A.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'a', 'denominazione': 'Contributo affitto',
           'struttura_id': null, 'attivita': 0, 'rischi': 0, 'misure': 0, 'livello_massimo': null, 'art35_mancanti': 2},
        ]);
      }
      if (r.url.path.endsWith('/processi/p1')) {
        return _json({
          'id': 'p1', 'codice': 'A.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'a', 'denominazione': 'Contributo affitto',
          'art35': {'tipologia': 'Contributi economici'}, 'attivita': [],
          'scheda_art35': _scheda, 'art35_mancanti': ['Ufficio responsabile - PEC istituzionale: campo obbligatorio', 'Altro'],
        });
      }
      return _json(const []);
    }));
    final dati = DatiAnticorruzione(
      metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto']},
      aree: const [{'id': 'a', 'codice': 'A', 'descrizione': 'Servizi sociali', 'descrizione_breve': null}],
      strutture: const [],
      obblighi: const [],
    );
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => AuthState(api)),
        Provider.value(value: dati),
      ],
      child: MaterialApp(home: Scaffold(body: MappaturaTab(onDatiCambiati: () {}))),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('A - Servizi sociali'));
    await tester.pumpAndSettle();
    expect(find.text('Art. 35: mancano 2 dati'), findsOneWidget); // nell'elenco
    await tester.tap(find.text('A.1 - Contributo affitto'));
    await tester.pumpAndSettle();
    expect(find.text('Dati per la trasparenza (art. 35 d.lgs. 33/2013)'), findsOneWidget);
    expect(find.text('Art. 35: mancano 2 dati'), findsOneWidget);
    await tester.tap(find.text('Dati mancanti o da correggere'));
    await tester.pumpAndSettle();
    expect(find.textContaining('PEC istituzionale: campo obbligatorio'), findsOneWidget);
    await tester.tap(find.text('Scheda del procedimento (allegato 11)'));
    await tester.pumpAndSettle();
    expect(find.text('Potere sostitutivo in caso di inerzia'), findsOneWidget);
  });
}
