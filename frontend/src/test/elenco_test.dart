import 'dart:convert';
import 'dart:io';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/anticorruzione/elenco.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Elenco piatto della mappatura: livello, percorso nelle colonne, filtri (struttura con le
/// sottostrutture e le trasversali, lacune), ricerca sul server, esportazione, scheda
/// dell'elemento con il percorso cliccabile.
void main() {
  late List<String> chiamate;
  late Map<String, Object?> corpi;

  Future<void> apri(WidgetTester tester, {double larghezza = 1800}) async {
    tester.view.physicalSize = Size(larghezza, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    chiamate = [];
    corpi = {};
    final client = MockClient((r) async {
      chiamate.add('${r.method} ${r.url.path}${r.url.query.isEmpty ? '' : '?${r.url.query}'}');
      if (r.body.isNotEmpty) corpi['${r.method} ${r.url.path}'] = jsonDecode(r.body);
      Object? corpo = const [];
      if (r.url.path.endsWith('/elenco/esporta')) return http.Response.bytes([80, 75], 200);
      if (r.url.path.endsWith('/elenco/ricerca')) {
        corpo = {
          'semantica': true,
          'risultati': [
            {'id': 'm2', 'parole': <String>[], 'semantica': true},
          ],
        };
      } else if (r.url.path.endsWith('/elenco')) {
        corpo = {
          'aree': [
            {'id': 'c', 'codice': 'C', 'descrizione': 'Contratti pubblici', 'descrizione_breve': null},
            {'id': 'd', 'codice': 'D', 'descrizione': 'Personale', 'descrizione_breve': null},
          ],
          'processi': [
            {'id': 'p1', 'codice': 'C.1', 'tipo': 'PROCESSO', 'area_id': 'c', 'denominazione': 'Gare', 'struttura_id': 'uo'},
            {'id': 'p3', 'codice': 'C.2', 'tipo': 'PROCESSO', 'area_id': 'c', 'denominazione': 'Affidamenti diretti', 'struttura_id': 's3'},
            {'id': 'p2', 'codice': 'D.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'd', 'denominazione': 'Concorsi', 'struttura_id': null,
             'coinvolte': ['s3'],
             'art35_mancanti': ['Tipologia di procedimento: obbligatorio', 'Silenzio assenso: obbligatorio'],
             'scheda_art35': {'denominazione': 'Concorsi', 'istanza_di_parte': 'SI', 'ist_ufficio': 'Ufficio personale'}},
          ],
          'attivita': [
            {'id': 'a1', 'processo_id': 'p1', 'codice': 'C.1.1', 'descrizione': 'Bando'},
          ],
          'rischi': [
            {'id': 'r1', 'attivita_id': 'a1', 'codice': 'C.1.1_R.1', 'evento': 'Bando su misura', 'livello': 'Alto',
             'probabilita': 'Alto', 'impatto': 'Alto'},
          ],
          'misure': [
            {'id': 'm1', 'rischio_id': 'r1', 'codice': 'C.1.1_R.1_M.1', 'descrizione': 'Doppia verifica', 'tipo': 'SPECIFICA',
             'categoria': 'Controllo', 'struttura_id': null, 'indicatore': 'Verifiche fatte', 'target': '100%'},
            {'id': 'm2', 'rischio_id': 'r1', 'codice': 'C.1.1_R.1_M.2', 'descrizione': 'Rotazione dei commissari',
             'tipo': 'GENERALE', 'categoria': 'Rotazione', 'struttura_id': 's3', 'indicatore': null},
          ],
        };
      }
      return http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json'});
    });
    final api = ApiClient('http://prova', client: client);
    final dati = DatiAnticorruzione(
      metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto']},
      aree: const [
        {'id': 'c', 'codice': 'C', 'descrizione': 'Contratti pubblici', 'descrizione_breve': null},
        {'id': 'd', 'codice': 'D', 'descrizione': 'Personale', 'descrizione_breve': null},
      ],
      strutture: const [
        {'id': 's2', 'codice': 'SETTORE 2', 'descrizione': 'Servizi tecnici', 'padre_id': null, 'attiva': true},
        {'id': 'uo', 'codice': 'U.O. 2.1', 'descrizione': 'Gare', 'padre_id': 's2', 'attiva': true},
        {'id': 's3', 'codice': 'SETTORE 3', 'descrizione': 'Finanze', 'padre_id': null, 'attiva': true},
      ],
      obblighi: const [],
    );
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => AuthState(api)),
        Provider.value(value: dati),
      ],
      child: const MaterialApp(home: Scaffold(body: ElencoTab())),
    ));
    await tester.pumpAndSettle();
  }

  Future<void> scegli(WidgetTester tester, String menu, String voce) async {
    await tester.tap(find.widgetWithText(DropdownButtonFormField<String?>, menu));
    await tester.pumpAndSettle();
    await tester.tap(find.text(voce).last);
    await tester.pumpAndSettle();
  }

  testWidgets('processi per struttura, con le sottostrutture e le trasversali', (tester) async {
    await apri(tester);
    expect(find.text('3 processi e procedimenti'), findsOneWidget); // si apre sui processi
    expect(find.text('Gare'), findsOneWidget);
    expect(find.text('Trasversale'), findsOneWidget);

    // il settore comprende la sua U.O.
    await scegli(tester, 'Struttura organizzativa', 'SETTORE 2 - Servizi tecnici');
    expect(find.text('1 processi e procedimenti su 3'), findsOneWidget);
    expect(find.text('Gare'), findsOneWidget);
    expect(find.text('Affidamenti diretti'), findsNothing);
    // la tabella è alta quanto le righe filtrate, senza righe vuote in fondo
    final tabella = tester.widget<PaginatedDataTable>(find.byType(PaginatedDataTable));
    expect(tabella.rowsPerPage, 1);
    expect(tabella.onRowsPerPageChanged, isNull);
    await tester.tap(find.text('Comprese le sottostrutture'));
    await tester.pumpAndSettle();
    expect(find.text('Nessun elemento con questi filtri.'), findsOneWidget);
    await tester.tap(find.text('Comprese le trasversali'));
    await tester.pumpAndSettle();
    expect(find.text('Concorsi'), findsOneWidget);

    // completezza dei dati art. 35 dei procedimenti, filtro e scheda
    expect(find.text('Art. 35: mancano 2 dati'), findsOneWidget);
    await scegli(tester, 'Mostra solo', 'Procedimenti con dati art. 35 mancanti');
    expect(find.text('1 processi e procedimenti su 3'), findsOneWidget);
    await tester.tap(find.text('Concorsi'));
    await tester.pumpAndSettle();
    expect(find.text('Dati per la trasparenza (art. 35 d.lgs. 33/2013)'), findsOneWidget);
    expect(find.text('Dati mancanti o da correggere'), findsOneWidget);
    await tester.tap(find.text('Scheda del procedimento (allegato 11)'));
    await tester.pumpAndSettle();
    expect(find.text('Ufficio personale'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    // lacune: processi senza attività
    await tester.tap(find.text('Azzera i filtri'));
    await tester.pumpAndSettle();
    await scegli(tester, 'Mostra solo', 'Senza attività');
    expect(find.text('2 processi e procedimenti su 3'), findsOneWidget);
    expect(find.text('Gare'), findsNothing);
  });

  testWidgets('misure: percorso, struttura ereditata, ricerca, esportazione e scheda', (tester) async {
    await apri(tester);
    await tester.tap(find.descendant(of: find.byType(SegmentedButton<String>), matching: find.text('Misure')));
    await tester.pumpAndSettle();
    expect(find.text('2 misure'), findsOneWidget);
    expect(find.text('C.1 - Gare'), findsNWidgets(2)); // il processo nel percorso
    expect(find.text('U.O. 2.1 - Gare (dal processo)'), findsOneWidget);
    expect(find.text('SETTORE 3 - Finanze'), findsOneWidget);

    // la struttura della misura vale più di quella del processo
    await scegli(tester, 'Struttura organizzativa', 'SETTORE 3 - Finanze');
    expect(find.text('1 misure su 2'), findsOneWidget);
    expect(find.text('Rotazione dei commissari'), findsOneWidget);
    await tester.tap(find.text('Azzera i filtri'));
    await tester.pumpAndSettle();
    await scegli(tester, 'Mostra solo', 'Senza indicatore');
    expect(find.text('Rotazione dei commissari'), findsOneWidget);
    expect(find.text('Doppia verifica'), findsNothing);
    await tester.tap(find.text('Azzera i filtri'));
    await tester.pumpAndSettle();

    // ricerca sul server, nel livello scelto
    await tester.enterText(find.widgetWithText(TextField, 'Cerca in misure'), 'commissione di gara');
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pumpAndSettle();
    expect(chiamate.where((c) => c.contains('/elenco/ricerca')).last, contains('livello=MISURA'));
    expect(find.text('Rotazione dei commissari'), findsOneWidget);
    expect(find.text('Doppia verifica'), findsNothing);

    await tester.tap(find.text('Esporta in Excel'));
    await tester.pumpAndSettle();
    final esportato = corpi['POST /api/v1/anticorruzione/elenco/esporta'] as Map;
    expect(esportato['titolo'], 'Misure');
    expect((esportato['righe'] as List).length, 1);
    expect(esportato['intestazioni'], contains('Struttura'));

    // la riga apre la scheda della misura; il percorso porta al rischio
    await tester.tap(find.text('Rotazione dei commissari'));
    await tester.pumpAndSettle();
    expect(find.text('Misura C.1.1_R.1_M.2'), findsOneWidget);
    expect(find.text('Apri nella mappatura'), findsOneWidget);
    expect(find.textContaining('Rotazione'), findsWidgets);
    await tester.tap(find.text('C.1.1_R.1 - Bando su misura'));
    await tester.pumpAndSettle();
    expect(find.text('Rischio C.1.1_R.1'), findsOneWidget);
    expect(find.text('Misure (2)'), findsOneWidget);
    expect(find.text('C.1.1_R.1_M.1 - Doppia verifica'), findsOneWidget);
  });

  testWidgets('strutture coinvolte: il filtro trova anche il processo in cui la struttura è coinvolta', (tester) async {
    await apri(tester);
    await scegli(tester, 'Struttura organizzativa', 'SETTORE 3 - Finanze');
    // Affidamenti diretti è del settore; Concorsi è trasversale, con il settore coinvolto
    expect(find.text('2 processi e procedimenti su 3'), findsOneWidget);
    expect(find.text('Affidamenti diretti'), findsOneWidget);
    expect(find.text('Concorsi'), findsOneWidget);
    await tester.tap(find.text('Concorsi'));
    await tester.pumpAndSettle();
    // nella scheda, tra le strutture coinvolte
    expect(find.textContaining('Strutture coinvolte', findRichText: true), findsOneWidget);
    expect(find.textContaining('SETTORE 3 - Finanze', findRichText: true), findsOneWidget);
  });

  testWidgets('schermo di 1024 px: la tabella sta nella pagina, le colonne secondarie si scelgono', (tester) async {
    // il font vero dell'app: quello dei test ha tutti i caratteri larghi quanto il corpo, e le
    // colonne misurate sul testo risulterebbero larghe il doppio
    await tester.runAsync(() async {
      final roboto = FontLoader('Roboto');
      for (final f in ['Regular', 'Medium', 'Bold']) {
        roboto.addFont(File('assets/fonts/Roboto-$f.ttf').readAsBytes().then(ByteData.sublistView));
      }
      await roboto.load();
    });
    await apri(tester, larghezza: 944); // 1024 meno il menu laterale
    final pagina = tester.getSize(find.byType(ElencoTab)).width;
    double tabella() => tester.getSize(find.byType(DataTable)).width;

    for (final livello in ['Aree', 'Processi e procedimenti', 'Attività', 'Rischi', 'Misure']) {
      await tester.tap(find.descendant(of: find.byType(SegmentedButton<String>), matching: find.text(livello)));
      await tester.pumpAndSettle();
      expect(tabella(), lessThanOrEqualTo(pagina - 32), reason: livello);
    }

    // nelle misure categoria e struttura partono nascoste; si aggiungono con "Colonne"
    Finder inTabella(String testo) => find.descendant(of: find.byType(DataTable), matching: find.text(testo));
    expect(inTabella('Categoria'), findsNothing);
    expect(find.text('Colonne (6 di 8)'), findsOneWidget);
    await tester.tap(find.text('Colonne (6 di 8)'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(CheckboxListTile, 'Categoria'));
    await tester.tap(find.text('Applica'));
    await tester.pumpAndSettle();
    expect(inTabella('Categoria'), findsOneWidget);
    expect(find.text('Colonne (7 di 8)'), findsOneWidget);

    // l'Excel ha sempre tutte le colonne
    await tester.tap(find.text('Esporta in Excel'));
    await tester.pumpAndSettle();
    final esportato = corpi['POST /api/v1/anticorruzione/elenco/esporta'] as Map;
    expect(esportato['intestazioni'], containsAll(['Categoria', 'Struttura']));

    // la scelta vale per il livello: tornando ai processi, Area resta nascosta
    await tester.tap(find.descendant(of: find.byType(SegmentedButton<String>), matching: find.text('Processi e procedimenti')));
    await tester.pumpAndSettle();
    expect(find.text('Colonne (7 di 11)'), findsOneWidget);
  });
}
