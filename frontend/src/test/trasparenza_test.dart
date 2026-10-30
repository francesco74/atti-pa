import 'dart:convert';

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/ui/trasparenza/coda_analisi.dart';
import 'package:atti_pa/ui/trasparenza/servizio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Analisi della trasparenza: l'app avvia il lavoro (con i file in multipart) e ne segue lo
/// stato finché il worker non lo conclude; un lavoro in errore porta il messaggio del worker.
void main() {
  http.Response json(Object corpo, [int stato = 200]) =>
      http.Response(jsonEncode(corpo), stato, headers: {'content-type': 'application/json'});

  test('analisi avviata con i file e seguita fino al risultato', () async {
    final richieste = <http.BaseRequest>[];
    var letture = 0;
    final api = ApiClient(
      'http://api.test',
      client: MockClient((r) async {
        richieste.add(r);
        if (r.url.path == '/api/v1/trasparenza/analisi') {
          expect(r.headers['content-type'], startsWith('multipart/form-data'));
          expect(r.body, contains('"controllo":"ART_23_DIRIGENTI"'));
          expect(r.body, contains('filename="elenco.csv"'));
          return json({'id': 'l1', 'stato': 'IN_CODA'}, 202);
        }
        letture++;
        return json(letture < 2
            ? {'id': 'l1', 'stato': 'IN_CORSO'}
            : {'id': 'l1', 'stato': 'COMPLETATA', 'risultato': {'html': '<p>report</p>'}});
      }),
    );
    final servizio = ServizioTrasparenza(api);
    final lavoro = await servizio.avviaAnalisi(
      {'controllo': 'ART_23_DIRIGENTI'},
      [('elenco.csv', utf8.encode('data;numero'))],
    );
    final risultato = await servizio.attendi(lavoro['id'] as String, intervallo: Duration.zero);
    expect(risultato['html'], '<p>report</p>');
    expect(letture, 2);
    expect(richieste.last.url.path, '/api/v1/trasparenza/lavori/l1');
  });

  test('lavoro in errore', () async {
    final api = ApiClient(
      'http://api.test',
      client: MockClient((r) async => json({'id': 'l2', 'stato': 'ERRORE', 'errore': 'Pagina non raggiungibile'})),
    );
    expect(
      ServizioTrasparenza(api).attendi('l2', intervallo: Duration.zero),
      throwsA(isA<LavoroNonRiuscito>().having((e) => e.messaggio, 'messaggio', 'Pagina non raggiungibile')),
    );
  });

  test('analisi avviate: si seguono finché sono in coda e si avvisa alla fine', () async {
    var letture = 0;
    final api = ApiClient(
      'http://api.test',
      client: MockClient((r) async {
        letture++;
        return json([
          {'id': 'a1', 'stato': letture < 2 ? 'IN_CORSO' : 'COMPLETATA', 'titolo': 'Art. 23'},
          {'id': 'a0', 'stato': 'ERRORE', 'titolo': 'Art. 12'},
        ]);
      }),
    );
    final concluse = <String>[];
    final coda = CodaAnalisi(ServizioTrasparenza(api), intervallo: const Duration(milliseconds: 1))
      ..suConclusa = (l) => concluse.add(l['id'] as String);
    await coda.aggiorna();
    expect(coda.inCorso, 1);
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(coda.inCorso, 0);
    expect(concluse, ['a1']); // quella già in errore non si annuncia
    expect(letture, 2); // senza analisi attive non si rilegge più
    coda.dispose();
  });
}
