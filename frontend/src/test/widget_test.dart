import 'package:atti_pa/ui/comuni.dart';
import 'package:atti_pa/ui/login_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('formatData converte le date ISO', () {
    expect(formatData('2026-10-12'), '12/10/2026');
    expect(formatData('2026-10-12T08:30:00'), '12/10/2026');
    expect(formatData(null), '—');
    expect(isoData(DateTime(2026, 3, 5)), '2026-03-05');
  });

  testWidgets('la pagina di login valida i campi', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: LoginPage()));
    await tester.tap(find.text('Accedi').last);
    await tester.pump();
    expect(find.text('Inserire il nome utente'), findsOneWidget);
    expect(find.text('Inserire la password'), findsOneWidget);
  });
}
