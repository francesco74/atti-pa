import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';

/// Elementi di impaginazione comuni alle schede di analisi e di generazione:
/// passi numerati, pannello informativo, pulsanti con esito e conferma prima
/// di cancellare dati inseriti.

/// Passo numerato di un modulo: numero, titolo, eventuale nota e contenuto.
class SezioneNumerata extends StatelessWidget {
  final int numero;
  final String titolo;
  final String? sottotitolo;
  final Widget? azione;
  final Widget child;

  const SezioneNumerata({
    super.key,
    required this.numero,
    required this.titolo,
    this.sottotitolo,
    this.azione,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final colori = Theme.of(context).colorScheme;
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 14,
                  backgroundColor: colori.primary,
                  foregroundColor: colori.onPrimary,
                  child: Text(
                    '$numero',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    titolo,
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                ?azione,
              ],
            ),
            if (sottotitolo != null)
              Padding(
                padding: const EdgeInsets.only(left: 40, top: 4),
                child: Text(
                  sottotitolo!,
                  style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
                ),
              ),
            const SizedBox(height: 16),
            child,
          ],
        ),
      ),
    );
  }
}

/// Riquadro con voci "etichetta: valore" ed eventuale nota in evidenza.
class PannelloInfo extends StatelessWidget {
  final List<(String, String)> voci;
  final String? nota;

  const PannelloInfo({super.key, required this.voci, this.nota});

  @override
  Widget build(BuildContext context) {
    final colori = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colori.primaryContainer.withValues(alpha: 0.35),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colori.primaryContainer),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final (etichetta, valore) in voci)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text.rich(
                TextSpan(
                  children: [
                    TextSpan(
                      text: '$etichetta: ',
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    ),
                    TextSpan(text: valore),
                  ],
                ),
                style: const TextStyle(fontSize: 13, height: 1.3),
              ),
            ),
          if (nota != null && nota!.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.info_outline,
                    size: 18,
                    color: Colors.orange.shade800,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      nota!,
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.orange.shade900,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Pulsante principale, pulsante secondario, avanzamento ed esito.
class BarraAzioni extends StatelessWidget {
  final String etichetta;
  final IconData icona;
  final VoidCallback? onPressed;
  final String etichettaSecondaria;
  final IconData iconaSecondaria;
  final VoidCallback? onSecondaria;
  final bool inCorso;
  final String messaggioInCorso;
  // Cosa manca per poter procedere (mostrato sopra i pulsanti).
  final String? avviso;
  final String? esito;
  final bool esitoPositivo;

  const BarraAzioni({
    super.key,
    required this.etichetta,
    required this.icona,
    required this.onPressed,
    required this.etichettaSecondaria,
    required this.iconaSecondaria,
    required this.onSecondaria,
    required this.inCorso,
    required this.messaggioInCorso,
    this.avviso,
    this.esito,
    this.esitoPositivo = false,
  });

  @override
  Widget build(BuildContext context) {
    final colori = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (avviso != null && !inCorso)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(avviso!, style: TextStyle(color: Colors.grey.shade800)),
          ),
        if (inCorso) ...[
          const LinearProgressIndicator(),
          const SizedBox(height: 8),
          Text(messaggioInCorso, textAlign: TextAlign.center),
          const SizedBox(height: 12),
        ],
        Row(
          children: [
            OutlinedButton.icon(
              icon: Icon(iconaSecondaria),
              label: Text(etichettaSecondaria),
              onPressed: inCorso ? null : onSecondaria,
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 18,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton.icon(
                icon: Icon(icona),
                label: Text(etichetta),
                onPressed: inCorso ? null : onPressed,
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 18),
                  textStyle: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
          ],
        ),
        if (esito != null)
          Container(
            margin: const EdgeInsets.only(top: 16),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: esitoPositivo
                  ? Colors.green.shade50
                  : colori.errorContainer,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Icon(
                  esitoPositivo ? Icons.check_circle : Icons.error_outline,
                  color: esitoPositivo ? Colors.green.shade700 : colori.error,
                ),
                const SizedBox(width: 8),
                Expanded(child: Text(esito!)),
              ],
            ),
          ),
      ],
    );
  }
}

/// Chiede conferma prima di un'operazione che cancella dati inseriti.
Future<bool> confermaPerditaDati(
  BuildContext context, {
  String titolo = 'Dati inseriti',
  required String messaggio,
  String conferma = 'Continua',
}) async {
  final risposta = await showDialog<bool>(
    context: context,
    // PointerInterceptor: sopra l'editor (un iframe) i clic finirebbero
    // altrimenti all'iframe invece che al dialog.
    builder: (context) => PointerInterceptor(
      child: AlertDialog(
      title: Row(
        children: [
          Icon(Icons.warning_amber_rounded, color: Colors.orange.shade800),
          const SizedBox(width: 10),
          Expanded(child: Text(titolo)),
        ],
      ),
      content: Text('$messaggio\nVuoi continuare?'),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: const Text('Annulla'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, true),
          child: Text(conferma),
        ),
      ],
      ),
    ),
  );
  return risposta ?? false;
}
