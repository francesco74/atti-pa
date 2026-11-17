import 'package:atti_pa/util/markdown_testo.dart';
import 'package:flutter_test/flutter_test.dart';

/// La risposta dell'assistente copiata fuori dall'app: HTML con la formattazione vera e testo
/// semplice senza i simboli del markdown.
void main() {
  const risposta = '''## Esito

La determina è **regolare**, salvo *una* nota.

1. Verificare il `CIG`
2. Pubblicare in [Amministrazione trasparente](https://ente.it/at)
   - entro 30 giorni
   - nella sezione Bandi

| Voce | Importo |
|------|---------|
| Arredi | 1.000 € |

> Citazione''';

  test('in HTML il grassetto è grassetto e le tabelle hanno i bordi', () {
    final html = markdownInHtml(risposta);
    expect(html, contains('<strong>regolare</strong>'));
    expect(html, contains('<em>una</em>'));
    expect(html, contains('<ol>'));
    expect(html, contains('<table style="border-collapse: collapse">'));
    expect(html, contains('<td style="border: 1px solid #999; padding: 4px 8px">Arredi</td>'));
    expect(html, isNot(contains('**')));
  });

  test('in testo semplice niente simboli del markdown', () {
    expect(
      markdownInTesto(risposta),
      'Esito\n\n'
      'La determina è regolare, salvo una nota.\n\n'
      '1. Verificare il CIG\n'
      '2. Pubblicare in Amministrazione trasparente (https://ente.it/at)\n'
      '   - entro 30 giorni\n'
      '   - nella sezione Bandi\n\n'
      'Voce\tImporto\n'
      'Arredi\t1.000 €\n\n'
      'Citazione',
    );
  });

  test('i caratteri speciali restano tali', () {
    expect(markdownInTesto('Art. 3 & "comma" <2>'), 'Art. 3 & "comma" <2>');
  });
}
