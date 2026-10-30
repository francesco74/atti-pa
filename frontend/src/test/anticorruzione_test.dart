import 'package:atti_pa/ui/anticorruzione/albero.dart';
import 'package:atti_pa/ui/anticorruzione/comune.dart';
import 'package:flutter_test/flutter_test.dart';

/// Valutazione mostrata dall'app prima del salvataggio (come il server: moda con la parità
/// verso il più alto, matrice con "Critico" sotto "Alto") e albero del processo nel formato
/// delle proposte.
void main() {
  final dati = DatiAnticorruzione(
    metodologia: {
      'scala': ['Basso', 'Medio', 'Alto'],
      'livelli': ['Rischio Minimo', 'Rischio Basso', 'Rischio Medio', 'Rischio Critico', 'Rischio Alto'],
      'matrice': {
        'Alto': {'Alto': 'Rischio Alto', 'Medio': 'Rischio Critico', 'Basso': 'Rischio Medio'},
        'Medio': {'Alto': 'Rischio Critico', 'Medio': 'Rischio Medio', 'Basso': 'Rischio Basso'},
        'Basso': {'Alto': 'Rischio Medio', 'Medio': 'Rischio Basso', 'Basso': 'Rischio Minimo'},
      },
      'indicatori_probabilita': [],
      'indicatori_impatto': [],
    },
    aree: const [],
    strutture: const [],
    obblighi: const [],
  );

  test('moda e matrice', () {
    expect(dati.moda(['Medio', 'Alto', 'Alto', 'Medio', 'Basso']), 'Alto');
    expect(dati.moda(['Basso', 'Basso', 'Alto']), 'Basso');
    expect(dati.livelloDa('Alto', 'Medio'), 'Rischio Critico');
    expect(dati.livelli.indexOf('Rischio Critico') < dati.livelli.indexOf('Rischio Alto'), isTrue);
  });

  test('albero nel formato delle proposte', () {
    final albero = daAlbero({
      'id': 'p', 'codice': 'C.1', 'area_id': null, 'denominazione': 'Gare', 'descrizione': null, 'tempi': null,
      'attori_esterni': null, 'struttura_id': null, 'obiettivi': [],
      'attivita': [
        {'id': 'a', 'codice': 'C.1.1', 'descrizione': 'Bando', 'rischi': [
          {'id': 'r', 'codice': 'C.1.1_R.1', 'evento': 'e', 'valori_probabilita': {'1': 'Alto'}, 'valori_impatto': {'1': 'Alto'},
           'probabilita': 'Alto', 'impatto': 'Alto', 'livello': 'Rischio Alto', 'misure': []},
          {'id': 'r2', 'codice': 'C.1.1_R.2', 'evento': 'f', 'valori_probabilita': null, 'misure': []},
        ]},
      ],
    });
    final rischi = (albero['attivita'] as List).first['rischi'] as List;
    expect((rischi[0]['valutazione'] as Map)['livello'], 'Rischio Alto');
    expect(rischi[1]['valutazione'], isNull);
    expect((albero['processo'] as Map)['codice'], 'C.1');
  });
}
