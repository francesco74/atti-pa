import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'api/api_client.dart';
import 'config.dart';
import 'stato/auth_state.dart';
import 'ui/cambio_password_page.dart';
import 'ui/home_shell.dart';
import 'ui/login_page.dart';
import 'ui/logo_ente.dart';
import 'ui/pubblico/mappatura_pubblica.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Config.carica();
  final api = ApiClient(Config.apiUrl);
  // pagina pubblica (link dal sito dell'ente): si apre senza accesso
  final pubblica = Uri.base.path.replaceFirst(RegExp(r'/+$'), '') == percorsoMappaturaPubblica;
  runApp(MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      ChangeNotifierProvider(create: (_) {
        final auth = AuthState(api);
        if (!pubblica) auth.avvia();
        return auth;
      }),
    ],
    child: AttiPaApp(pubblica: pubblica),
  ));
}

class AttiPaApp extends StatelessWidget {
  const AttiPaApp({super.key, this.pubblica = false});

  final bool pubblica; // mappatura pubblica dell'anticorruzione al posto dell'app

  @override
  Widget build(BuildContext context) {
    final tema = ColorScheme.fromSeed(seedColor: const Color(0xFF1F4E79));
    return MaterialApp(
      title: pubblica ? 'Mappatura dei processi' : 'Atti PA',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: tema,
        fontFamily: 'Roboto',
        useMaterial3: true,
        // righe degli elenchi e altre voci cliccabili: al passaggio del mouse si evidenziano
        // con un colore pieno, che copre il logo di sfondo (il testo resta sopra)
        hoverColor: Color.alphaBlend(tema.primary.withValues(alpha: 0.16), tema.surface),
        inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
        cardTheme: const CardThemeData(elevation: 0.5),
        // fondo con il logo dell'ente sotto ogni pagina (TransizioneConSfondo): gli Scaffold
        // sono trasparenti
        scaffoldBackgroundColor: Colors.transparent,
        pageTransitionsTheme: PageTransitionsTheme(builders: {
          for (final piattaforma in TargetPlatform.values) piattaforma: const TransizioneConSfondo(),
        }),
      ),
      locale: const Locale('it'),
      supportedLocales: const [Locale('it')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: pubblica ? const MappaturaPubblicaPage() : const _Radice(),
    );
  }
}

class _Radice extends StatelessWidget {
  const _Radice();

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthState>();
    return switch (auth.stato) {
      StatoAuth.verifica => const Scaffold(body: Center(child: CircularProgressIndicator())),
      StatoAuth.anonimo => const LoginPage(),
      StatoAuth.autenticato =>
        auth.utente!.cambioPassword ? const CambioPasswordPage() : HomeShell(utente: auth.utente!),
    };
  }
}
