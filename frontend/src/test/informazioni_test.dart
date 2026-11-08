import 'package:atti_pa/ui/comuni.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Informazioni e licenza (menu dell'utente): licenza AGPL, link al sorgente e licenze dei
/// componenti.
void main() {
  testWidgets('informazioni e licenza', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => TextButton(onPressed: () => mostraInformazioni(context), child: const Text('apri')),
      ),
    ));
    await tester.tap(find.text('apri'));
    await tester.pumpAndSettle();
    expect(find.textContaining('GNU Affero General Public License'), findsOneWidget);
    expect(find.text('Codice sorgente (AGPL-3.0)'), findsOneWidget);
    expect(find.byType(TextButton), findsWidgets); // "Visualizza licenze" dei componenti
  });
}
