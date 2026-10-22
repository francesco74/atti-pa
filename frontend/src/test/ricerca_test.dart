import 'package:atti_pa/ui/configurazione/editor_comune.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('la ricerca ignora maiuscole e accenti', () {
    expect(normalizzaRicerca('Comunità ÈTICA'), 'comunita etica');
    expect(corrisponde('comunita', ['Servizi alla Comunità']), isTrue);
    expect(corrisponde('PERCHÉ', ['perche no']), isTrue);
    expect(corrisponde('cig', ['importo', null]), isFalse);
    expect(corrisponde('  ', ['qualsiasi']), isTrue); // ricerca vuota: tutto
  });

  test('le norme si trovano anche in forma breve', () {
    const urn = 'urn:nir:stato:decreto.legislativo:2023-03-31;36~art50';
    expect(normaBreve(urn), 'art. 50 D.Lgs. 36/2023');
    expect(corrisponde('36/2023', [urn, normaBreve(urn)]), isTrue);
  });
}
