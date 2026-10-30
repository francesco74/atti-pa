import 'package:atti_pa/ui/admin/strutture.dart';
import 'package:flutter_test/flutter_test.dart';

/// Albero delle strutture organizzative: ogni struttura seguita dalle sottostanti, con la
/// profondità; una struttura con il padre mancante va al primo livello.
void main() {
  test('strutture in ordine di albero', () {
    Map<String, dynamic> s(String id, String? padre) =>
        {'id': id, 'codice': id, 'descrizione': id, 'padre_id': padre, 'attiva': true};
    final albero = alberoStrutture([
      s('U.O. 2.1', 'SETTORE 2'),
      s('SETTORE 1', null),
      s('U.O. 1.1', 'SETTORE 1'),
      s('SETTORE 2', null),
      s('ORFANA', 'CANCELLATA'),
    ]);
    expect([for (final (x, livello) in albero) '${x['id']}:$livello'],
        ['SETTORE 1:0', 'U.O. 1.1:1', 'SETTORE 2:0', 'U.O. 2.1:1', 'ORFANA:0']);
  });
}
