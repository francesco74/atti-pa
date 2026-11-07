import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../stato/auth_state.dart';
import '../logo_ente.dart';
import '../ricerca.dart';
import 'accessibile.dart';

const apiPubblico = '/api/v1/pubblico';

/// Logo dell'ente come fondo della pagina e icona della scheda del browser, come nell'app.
void caricaLogoPubblico(BuildContext context, Map<String, dynamic> ente) {
  if (ente['logo'] != true) return;
  final auth = context.read<AuthState>();
  context
      .read<ApiClient>()
      .getBytes('$apiPubblico/logo')
      .then(auth.impostaLogo, onError: (_) {});
}

/// Impaginazione delle pagine pubbliche: salto al contenuto, logo e nome dell'ente, titolo
/// (intestazione di primo livello), introduzione, contenuto su una colonna centrale e piè di
/// pagina con la dichiarazione di accessibilità e la segnalazione dei problemi. Usa il tema
/// accessibile delle pagine pubbliche (focus visibile, bersagli ampi): vedi accessibile.dart.
class PaginaPubblica extends StatefulWidget {
  const PaginaPubblica({
    super.key,
    required this.ente,
    required this.titolo,
    required this.introduzione,
    required this.child,
    this.registro,
  });

  final Map<String, dynamic> ente; // nome, logo, dichiarazione_accessibilita
  final String titolo;
  final String introduzione;
  final Widget child;
  final RegistroRicerche?
  registro; // per la segnalazione dei problemi di accessibilità

  @override
  State<PaginaPubblica> createState() => _PaginaPubblicaState();
}

class _PaginaPubblicaState extends State<PaginaPubblica> {
  final _contenuto = FocusNode(debugLabel: 'contenuto');

  @override
  void dispose() {
    _contenuto.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tema = temaPubblico(Theme.of(context));
    final nome = '${widget.ente['nome']}';
    return Theme(
      data: tema,
      child: FocusTraversalGroup(
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1100),
            // intestazione e introduzione scorrono con il contenuto: a 320 px o con il testo
            // ingrandito non tolgono spazio all'elenco (WCAG 1.4.10)
            child: NestedScrollView(
              headerSliverBuilder: (context, _) => [
                SliverToBoxAdapter(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      SaltaAlContenuto(destinazione: _contenuto),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
                        child: Row(
                          children: [
                            ExcludeSemantics(
                              child: IconaEnte(
                                logo: context.select<AuthState, Uint8List?>(
                                  (a) => a.logo,
                                ),
                                dimensione: 48,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    nome,
                                    style: tema.textTheme.titleSmall?.copyWith(
                                      color: tema.colorScheme.onSurfaceVariant,
                                    ),
                                  ),
                                  Intestazione(
                                    widget.titolo,
                                    livello: 1,
                                    stile: tema.textTheme.titleLarge,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                        child: Text(
                          widget.introduzione,
                          style: tema.textTheme.bodyMedium,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              body: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: Focus(focusNode: _contenuto, child: widget.child),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: PiePaginaPubblico(
                      dichiarazione:
                          widget.ente['dichiarazione_accessibilita'] as String?,
                      registro: widget.registro,
                      pagina: '${widget.titolo} – $nome',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
