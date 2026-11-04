import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:atti_pa/ui/anticorruzione/mappatura.dart';
import 'package:atti_pa/ui/anticorruzione/proposte.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

/// Proposte del referente: sui processi della sua struttura gli stessi pulsanti del RPCT
/// inviano una proposta per l'elemento; la modifica mostra solo i campi che cambiano.
void main() {
  final dati = DatiAnticorruzione(
    metodologia: const {'scala': <String>[], 'livelli': ['Basso', 'Alto']},
    aree: const [
      {'id': 'c', 'codice': 'C', 'descrizione': 'Contratti pubblici', 'descrizione_breve': null},
    ],
    strutture: const [],
    obblighi: const [],
  );
  final processo = {
    'id': 'p1', 'codice': 'C.1', 'tipo': 'PROCEDIMENTO', 'area_id': 'c', 'denominazione': 'Gare',
    'termine_conclusione': '30 giorni', 'proponibile': true,
    'attivita': [
      {'id': 'a1', 'codice': 'C.1.1', 'descrizione': 'Bando', 'rischi': [
        {'id': 'r1', 'codice': 'C.1.1_R.1', 'evento': 'Bando su misura', 'valori_probabilita': null, 'misure': [
          {'id': 'm1', 'codice': 'C.1.1_R.1_M.1', 'descrizione': 'Doppia verifica', 'tipo': 'SPECIFICA'},
        ]},
      ]},
    ],
  };

  Future<void> apri(WidgetTester tester, MockClient client, Widget pagina) async {
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = ApiClient('http://prova', client: client);
    final auth = AuthState(api)
      ..utente = Utente.daJson({
        'id': 'u1', 'username': 'referente', 'ruoli': ['ANTICORRUZIONE_REFERENTE'],
        'ente': {'codice': 'prova', 'nome': 'Ente', 'moduli': ['anticorruzione']},
      });
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthState>.value(value: auth),
        Provider.value(value: dati),
      ],
      child: MaterialApp(home: Scaffold(body: pagina)),
    ));
    await tester.pumpAndSettle();
  }

  http.Response json(Object corpo) => http.Response(jsonEncode(corpo), 200, headers: {'content-type': 'application/json; charset=utf-8'});

  testWidgets('il referente propone l\'eliminazione di una misura dalla mappatura', (tester) async {
    Map<String, dynamic>? inviata;
    final client = MockClient((r) async {
      if (r.method == 'POST' && r.url.path.endsWith('/proposte')) {
        inviata = jsonDecode(r.body) as Map<String, dynamic>;
        return json({'id': 'pr1', 'stato': 'INVIATA'});
      }
      return json(processo);
    });
    await apri(tester, client, VistaProcesso(processoId: 'p1', onAree: () {}, onArea: (_) {}, onChiuso: () {}));

    expect(find.textContaining('Procedimento C.1'), findsOneWidget);
    expect(find.text('Proponi un\'attività'), findsOneWidget);
    await tester.tap(find.text('C.1.1 - Bando'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Proponi l\'eliminazione della misura'));
    await tester.pumpAndSettle();
    expect(find.text('Proporre l\'eliminazione?'), findsOneWidget);
    await tester.tap(find.text('Conferma'));
    await tester.pumpAndSettle();

    // va subito al RPCT: nessuna pagina da aprire, solo la conferma
    expect(inviata, {'tipo': 'ELIMINA', 'oggetto': 'MISURA', 'elemento_id': 'm1'});
    expect(find.textContaining('Proposta inviata al RPCT'), findsOneWidget);
    expect(find.byType(PropostaPage), findsNothing);
  });

  testWidgets('una modifica mostra solo i campi che cambiano', (tester) async {
    final client = MockClient((r) async => json({
          'id': 'pr2', 'tipo': 'MODIFICA', 'oggetto': 'ATTIVITA', 'stato': 'INVIATA', 'utente_id': 'altro', 'autore': 'Referente',
          'codice': 'C.1.1', 'percorso': ['C.1 Gare'],
          'prima': {'codice': 'C.1.1', 'descrizione': 'Bando', 'strutture_coinvolte': 'Ufficio gare'},
          'dati': {'descrizione': 'Bando e capitolato', 'strutture_coinvolte': 'Ufficio gare'},
        }));
    await apri(tester, client, const PropostaPage(propostaId: 'pr2'));

    expect(find.text('Modifica dell\'attività C.1.1'), findsOneWidget);
    expect(find.text('Bando'), findsOneWidget); // com'era
    expect(find.text('Bando e capitolato'), findsOneWidget); // come diventa
    expect(find.text('Strutture coinvolte'), findsNothing); // invariato
    expect(find.text('Salva'), findsNothing); // di un altro utente: non si corregge
  });

  testWidgets('la rivalutazione mostra i valori degli indicatori, con quelli cambiati', (tester) async {
    final conIndicatori = DatiAnticorruzione(
      metodologia: const {
        'scala': ['Basso', 'Alto'],
        'livelli': ['Rischio Basso', 'Rischio Alto'],
        'indicatori_probabilita': [{'id': '1', 'nome': 'Discrezionalità'}, {'id': '2', 'nome': 'Interessi esterni'}],
        'indicatori_impatto': [{'id': '1', 'nome': 'Danno reputazionale'}],
      },
      aree: const [],
      strutture: const [],
      obblighi: const [],
    );
    Map<String, dynamic> valutazione(String discrezionalita) => {
          'valori_probabilita': {'1': discrezionalita, '2': 'Basso'},
          'valori_impatto': {'1': 'Basso'},
          'probabilita_calcolata': 'Basso', 'impatto_calcolato': 'Basso', 'livello': 'Rischio Basso',
        };
    final client = MockClient((r) async => json({
          'id': 'pr3', 'tipo': 'MODIFICA', 'oggetto': 'RISCHIO', 'stato': 'INVIATA', 'utente_id': 'altro', 'autore': 'Referente',
          'codice': 'C.1.1_R.1', 'percorso': ['C.1 Gare', 'C.1.1 Bando'],
          'prima': {'evento': 'Bando su misura', 'valutazione': valutazione('Basso')},
          'dati': {'evento': 'Bando su misura', 'valutazione': valutazione('Alto')}, // stesso livello
        }));
    tester.view.physicalSize = const Size(1400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = ApiClient('http://prova', client: client);
    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider<AuthState>.value(value: AuthState(api)),
        Provider.value(value: conIndicatori),
      ],
      child: const MaterialApp(home: PropostaPage(propostaId: 'pr3')),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Nessuna differenza rispetto all\'elemento attuale.'), findsNothing);
    expect(find.text('1. Discrezionalità'), findsOneWidget);
    expect(find.text('Basso → Alto'), findsOneWidget); // l'indicatore cambiato
    expect(find.text('2. Interessi esterni'), findsOneWidget);
  });
}
