import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';

ApiClient apiDi(BuildContext context) => context.read<ApiClient>();

void mostraErrore(BuildContext context, Object errore) {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    content: Text(errore.toString()),
    backgroundColor: Theme.of(context).colorScheme.error,
    behavior: SnackBarBehavior.floating,
  ));
}

void mostraMessaggio(BuildContext context, String testo) {
  if (!context.mounted) return;
  ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(testo), behavior: SnackBarBehavior.floating));
}

/// "2026-10-12" o "2026-10-12T10:00:00" -> "12/10/2026"
String formatData(Object? valore) {
  if (valore == null) return '—';
  final testo = valore.toString();
  if (testo.length < 10) return testo;
  final p = testo.substring(0, 10).split('-');
  return p.length == 3 ? '${p[2]}/${p[1]}/${p[0]}' : testo;
}

String isoData(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

DateTime? daIso(String? valore) => valore == null ? null : DateTime.tryParse(valore);

Future<DateTime?> scegliData(BuildContext context, DateTime? iniziale) => showDatePicker(
      context: context,
      initialDate: iniziale ?? DateTime.now(),
      firstDate: DateTime(1990),
      lastDate: DateTime(2100),
      locale: const Locale('it'),
    );

const _coloriEsito = {
  'CONFORME': Colors.green,
  'VIGENTE': Colors.green,
  'NON_CONFORME': Colors.red,
  'NON_TROVATO': Colors.red,
  'ABROGATO': Colors.red,
  'PARTIZIONE_INESISTENTE': Colors.red,
  'ERRORE': Colors.red,
  'ERRORE_VERIFICA': Colors.orange,
  'DUBBIO': Colors.orange,
  'ATTO_SENZA_ARTICOLO': Colors.orange,
  'NON_APPLICABILE': Colors.grey,
  'NON_VALUTATO': Colors.grey,
};

const _etichetteEsito = {
  'CONFORME': 'Conforme',
  'NON_CONFORME': 'Non conforme',
  'NON_APPLICABILE': 'Non applicabile',
  'NON_VALUTATO': 'Non valutato',
  'DUBBIO': 'Dubbio',
  'VIGENTE': 'Vigente',
  'NON_TROVATO': 'Non trovato',
  'ABROGATO': 'Abrogata',
  'PARTIZIONE_INESISTENTE': 'Comma/lettera inesistente',
  'ATTO_SENZA_ARTICOLO': 'Senza articolo',
  'ERRORE_VERIFICA': 'Non verificabile',
  'ERRORE': 'Errore',
};

String etichettaEsito(String? esito) => _etichetteEsito[esito] ?? (esito ?? '—');

class EsitoChip extends StatelessWidget {
  const EsitoChip(this.esito, {super.key});

  final String? esito;

  @override
  Widget build(BuildContext context) {
    final colore = _coloriEsito[esito] ?? Colors.blueGrey;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: colore.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colore.withValues(alpha: 0.6)),
      ),
      child: Text(etichettaEsito(esito),
          style: TextStyle(color: colore, fontSize: 12, fontWeight: FontWeight.w600)),
    );
  }
}

class Sezione extends StatelessWidget {
  const Sezione({super.key, required this.titolo, required this.child, this.azioni});

  final String titolo;
  final Widget child;
  final List<Widget>? azioni;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(child: Text(titolo, style: Theme.of(context).textTheme.titleMedium)),
              ...?azioni,
            ]),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}

/// Schermo piccolo o basso: i menu e le schede mostrano solo le icone.
bool schermoPiccolo(BuildContext context) {
  final misura = MediaQuery.sizeOf(context);
  return misura.width < 700 || misura.height < 600;
}

/// Scheda con icona e testo; sugli schermi piccoli solo l'icona, con il testo al passaggio
/// del mouse.
class Scheda extends StatelessWidget {
  const Scheda(this.icona, this.testo, {super.key});

  final Widget icona;
  final String testo;

  @override
  Widget build(BuildContext context) => schermoPiccolo(context)
      ? Tab(icon: Tooltip(message: testo, child: icona))
      : Tab(icon: icona, text: testo);
}

/// Icona di cancellazione: rossa in tutta l'app, grigia (dal pulsante) se non è attiva.
class IconaElimina extends StatelessWidget {
  const IconaElimina({super.key, this.size, this.attiva = true});

  final double? size;
  final bool attiva;

  @override
  Widget build(BuildContext context) =>
      Icon(Icons.delete_outline, size: size, color: attiva ? Theme.of(context).colorScheme.error : null);
}

/// Mostra il risultato di un Future con indicatore di caricamento ed errore riprovabile.
class Caricamento<T> extends StatelessWidget {
  const Caricamento({super.key, required this.future, required this.builder, this.riprova});

  final Future<T> future;
  final Widget Function(BuildContext, T) builder;
  final VoidCallback? riprova;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: Padding(
            padding: EdgeInsets.all(24),
            child: CircularProgressIndicator(),
          ));
        }
        if (snap.hasError) {
          return Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text(snap.error.toString(), textAlign: TextAlign.center),
              if (riprova != null)
                TextButton.icon(
                    onPressed: riprova, icon: const Icon(Icons.refresh), label: const Text('Riprova')),
            ]),
          );
        }
        return builder(context, snap.data as T);
      },
    );
  }
}

Future<bool> conferma(BuildContext context, String titolo, String testo) async {
  final esito = await showDialog<bool>(
    context: context,
    // PointerInterceptor: la conferma può comparire sopra l'editor dei risultati della
    // trasparenza (un iframe), che altrimenti prenderebbe i clic sui pulsanti
    builder: (c) => PointerInterceptor(
      child: AlertDialog(
        title: Text(titolo),
        content: Text(testo),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Conferma')),
        ],
      ),
    ),
  );
  return esito ?? false;
}

/// Testo per l'assistenza agli utenti configurato dall'ente (Amministrazione → Profilo): gli
/// indirizzi email e i link diventano cliccabili.
class TestoAssistenza extends StatelessWidget {
  const TestoAssistenza(this.testo, {super.key, this.stile, this.allineamento = TextAlign.start});

  final String testo;
  final TextStyle? stile;
  final TextAlign allineamento;

  static final _collegamento = RegExp(r'(https?://[^\s<>"]+[^\s<>".,;:!?)]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)');

  @override
  Widget build(BuildContext context) {
    final colore = Theme.of(context).colorScheme.primary;
    final parti = <InlineSpan>[];
    var inizio = 0;
    for (final m in _collegamento.allMatches(testo)) {
      if (m.start > inizio) parti.add(TextSpan(text: testo.substring(inizio, m.start)));
      final valore = m.group(0)!;
      final destinazione = valore.contains('@') && !valore.startsWith('http') ? Uri(scheme: 'mailto', path: valore) : Uri.parse(valore);
      parti.add(WidgetSpan(
        alignment: PlaceholderAlignment.baseline,
        baseline: TextBaseline.alphabetic,
        child: InkWell(
          onTap: () => launchUrl(destinazione, webOnlyWindowName: '_blank'),
          child: Text(valore, style: (stile ?? const TextStyle()).copyWith(color: colore, decoration: TextDecoration.underline)),
        ),
      ));
      inizio = m.end;
    }
    if (inizio < testo.length) parti.add(TextSpan(text: testo.substring(inizio)));
    return Text.rich(TextSpan(style: stile, children: parti), textAlign: allineamento);
  }
}
