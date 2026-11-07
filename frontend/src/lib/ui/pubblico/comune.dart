import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../stato/auth_state.dart';
import '../logo_ente.dart';

const apiPubblico = '/api/v1/pubblico';

/// Logo dell'ente come fondo della pagina e icona della scheda del browser, come nell'app.
void caricaLogoPubblico(BuildContext context, Map<String, dynamic> ente) {
  if (ente['logo'] != true) return;
  final auth = context.read<AuthState>();
  context.read<ApiClient>().getBytes('$apiPubblico/logo').then(auth.impostaLogo, onError: (_) {});
}

/// Impaginazione delle pagine pubbliche: logo e nome dell'ente, titolo, introduzione e il
/// contenuto, su una colonna centrale.
class PaginaPubblica extends StatelessWidget {
  const PaginaPubblica({super.key, required this.ente, required this.titolo, required this.introduzione, required this.child});

  final String ente;
  final String titolo;
  final String introduzione;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1100),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Row(children: [
              IconaEnte(logo: context.select<AuthState, Uint8List?>((a) => a.logo), dimensione: 48),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(ente, style: tema.textTheme.titleSmall?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
                  Text(titolo, style: tema.textTheme.titleLarge),
                ]),
              ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text(introduzione, style: tema.textTheme.bodyMedium),
          ),
          Expanded(child: child),
        ]),
      ),
    );
  }
}
