import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'api/api_client.dart';
import 'config.dart';
import 'stato/auth_state.dart';
import 'ui/home_shell.dart';
import 'ui/login_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Config.carica();
  final api = ApiClient(Config.apiUrl);
  runApp(MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      ChangeNotifierProvider(create: (_) => AuthState(api)..avvia()),
    ],
    child: const AttiPaApp(),
  ));
}

class AttiPaApp extends StatelessWidget {
  const AttiPaApp({super.key});

  @override
  Widget build(BuildContext context) {
    final tema = ColorScheme.fromSeed(seedColor: const Color(0xFF1F4E79));
    return MaterialApp(
      title: 'Atti PA',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: tema,
        fontFamily: 'Roboto',
        useMaterial3: true,
        inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
        cardTheme: const CardThemeData(elevation: 0.5),
      ),
      locale: const Locale('it'),
      supportedLocales: const [Locale('it')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: const _Radice(),
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
      StatoAuth.autenticato => HomeShell(utente: auth.utente!),
    };
  }
}
