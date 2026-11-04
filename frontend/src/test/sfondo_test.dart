import 'dart:ui' as ui;

import 'package:atti_pa/api/api_client.dart';
import 'package:atti_pa/stato/auth_state.dart';
import 'package:atti_pa/ui/logo_ente.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('una riga senza Scaffold né Card si evidenzia sopra il fondo con il logo', (tester) async {
    tester.view.physicalSize = const Size(800, 600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    const evidenziata = Color(0xFFFF0000);
    final cornice = GlobalKey();
    await tester.pumpWidget(ChangeNotifierProvider<AuthState>.value(
      value: AuthState(ApiClient('http://api.test')),
      child: RepaintBoundary(
        key: cornice,
        child: MaterialApp(
          theme: ThemeData(
            hoverColor: evidenziata,
            scaffoldBackgroundColor: Colors.transparent,
            pageTransitionsTheme: PageTransitionsTheme(builders: {
              for (final p in TargetPlatform.values) p: const TransizioneConSfondo(),
            }),
          ),
          // come nel menu: le pagine stanno in un Navigator annidato, senza Scaffold propria
          home: Scaffold(
            body: Navigator(
              onGenerateRoute: (s) => MaterialPageRoute(
                settings: s,
                builder: (_) => Column(children: [ListTile(title: const Text('Riga'), onTap: () {})]),
              ),
            ),
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    final riga = tester.getCenter(find.text('Riga'));
    final punto = Offset(riga.dx + 200, riga.dy); // fuori dal testo
    Future<Color> colore() async {
      final immagine = await tester.runAsync(
          () => (cornice.currentContext!.findRenderObject() as RenderRepaintBoundary).toImage());
      final byte = await tester.runAsync(() => immagine!.toByteData(format: ui.ImageByteFormat.rawRgba));
      final rgba = byte!.getUint32((punto.dy.toInt() * immagine!.width + punto.dx.toInt()) * 4);
      return Color((rgba >> 8) | (rgba << 24) & 0xFF000000);
    }

    expect(await colore(), isNot(evidenziata));
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: const Offset(790, 590));
    await mouse.moveTo(riga);
    await tester.pumpAndSettle();
    expect(await colore(), evidenziata);
    await mouse.removePointer();
  });
}
