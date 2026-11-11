import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../config.dart';

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
              Expanded(
                child: Semantics(
                  header: true,
                  headingLevel: 2,
                  child: Text(titolo, style: Theme.of(context).textTheme.titleMedium),
                ),
              ),
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
            child: CircularProgressIndicator(semanticsLabel: 'Caricamento in corso'),
          ));
        }
        if (snap.hasError) {
          return Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              // annunciato ai lettori di schermo (WCAG 4.1.3)
              Semantics(liveRegion: true, child: Text(snap.error.toString(), textAlign: TextAlign.center)),
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
        child: Semantics(
          link: true,
          hint: 'si apre in una nuova finestra',
          child: InkWell(
            onTap: () => launchUrl(destinazione, webOnlyWindowName: '_blank'),
            child: Text(valore, style: (stile ?? const TextStyle()).copyWith(color: colore, decoration: TextDecoration.underline)),
          ),
        ),
      ));
      inizio = m.end;
    }
    if (inizio < testo.length) parti.add(TextSpan(text: testo.substring(inizio)));
    return Text.rich(TextSpan(style: stile, children: parti), textAlign: allineamento);
  }
}

/// Controlli oggettivi (proposte dell'anticorruzione, obiettivi della performance): avvisi
/// in arancio, informazioni in grigio. Calcolati dal server sulle regole, senza modello.
class ElencoControlli extends StatelessWidget {
  const ElencoControlli(this.controlli, {super.key});

  final List<Map<String, dynamic>> controlli;

  @override
  Widget build(BuildContext context) {
    final grigio = Theme.of(context).colorScheme.onSurfaceVariant;
    if (controlli.isEmpty) {
      return const Row(children: [
        Icon(Icons.check_circle_outline, color: Colors.green, size: 20),
        SizedBox(width: 8),
        Expanded(child: Text('Nessun problema trovato dai controlli.')),
      ]);
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final c in controlli)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(c['livello'] == 'AVVISO' ? Icons.warning_amber_rounded : Icons.info_outline,
                size: 20, color: c['livello'] == 'AVVISO' ? Colors.orange.shade800 : grigio),
            const SizedBox(width: 8),
            Expanded(child: Text('${c['testo']}')),
          ]),
        ),
    ]);
  }
}

/// Link della pagina da seguire nella lettura di una fonte web (default e limite del server).
const linkPredefiniti = 5;
const linkMassimi = 15;

/// Documenti collegati alla pagina da leggere (default e limite del server).
const documentiPredefiniti = 5;
const documentiMassimi = 10;

/// Formati dei documenti collegati che si leggono, per le etichette.
const formatiDocumentiCollegati = 'PDF, Word, OpenDocument, fogli di calcolo, CSV, XML, JSON';

/// Casella "segui i link" con il numero massimo di pagine collegate da leggere (5-15): più
/// link rendono la lettura più completa ma più lunga. Con [minimo], [massimo] e [unita] vale
/// anche per i documenti collegati ([SceltaLink.documenti]).
class SceltaLink extends StatelessWidget {
  const SceltaLink({
    super.key,
    required this.titolo,
    required this.segui,
    required this.numero,
    required this.onSegui,
    required this.onNumero,
    this.dense = false,
    this.minimo = linkPredefiniti,
    this.massimo = linkMassimi,
    this.unita = 'link',
  });

  /// "Leggi anche i documenti collegati" con il numero massimo di documenti (5-10).
  const SceltaLink.documenti({
    super.key,
    required this.titolo,
    required this.segui,
    required this.numero,
    required this.onSegui,
    required this.onNumero,
    this.dense = false,
  })  : minimo = documentiPredefiniti,
        massimo = documentiMassimi,
        unita = 'documenti';

  final String titolo;
  final bool segui;
  final int numero;
  final ValueChanged<bool>? onSegui; // null: disabilitata
  final ValueChanged<int> onNumero;
  final bool dense;
  final int minimo;
  final int massimo;
  final String unita;

  @override
  Widget build(BuildContext context) => CheckboxListTile(
        title: Text(titolo),
        value: segui,
        onChanged: onSegui == null ? null : (v) => onSegui!(v ?? false),
        controlAffinity: ListTileControlAffinity.leading,
        contentPadding: EdgeInsets.zero,
        dense: dense,
        secondary: DropdownButton<int>(
          value: numero,
          underline: const SizedBox.shrink(),
          items: [
            for (var n = minimo; n <= massimo; n++) DropdownMenuItem(value: n, child: Text('fino a $n $unita')),
          ],
          onChanged: segui && onSegui != null ? (v) => onNumero(v ?? numero) : null,
        ),
      );
}


/// Informazioni sull'applicazione: licenza (AGPL-3.0), link al codice sorgente e licenze dei
/// componenti usati (pagina standard di Flutter).
void mostraInformazioni(BuildContext context) {
  showAboutDialog(
    context: context,
    applicationName: 'atti-pa',
    applicationLegalese: '© 2026 Francesco Bertozzi\n'
        'Software libero, distribuito con licenza GNU Affero General Public License v3.0 o '
        'successiva, senza alcuna garanzia.',
    children: [
      const SizedBox(height: 16),
      const LinkSorgente(),
    ],
  );
}

/// Link al codice sorgente dell'app (Config.sorgenteUrl), in una nuova finestra.
class LinkSorgente extends StatelessWidget {
  const LinkSorgente({super.key, this.icona = false});

  final bool icona;

  void _apri() => launchUrl(Uri.parse(Config.sorgenteUrl), webOnlyWindowName: '_blank');

  @override
  Widget build(BuildContext context) {
    const testo = Text('Codice sorgente (AGPL-3.0)');
    return Semantics(
      hint: 'si apre in una nuova finestra',
      child: icona
          ? TextButton.icon(icon: const Icon(Icons.code), label: testo, onPressed: _apri)
          : TextButton(onPressed: _apri, child: testo),
    );
  }
}

/// Lunghezza minima della password, come sul server (auth/password.py): più alta per gli
/// amministratori dell'ente.
int lunghezzaMinimaPassword({bool amministratore = false}) => amministratore ? 16 : 8;

/// Testo d'aiuto dei campi password.
String aiutoPassword({bool amministratore = false}) =>
    'Almeno ${lunghezzaMinimaPassword(amministratore: amministratore)} caratteri'
    '${amministratore ? ' (utente amministratore)' : ''}, con lettere e numeri o simboli';

/// Errore della nuova password con le stesse regole del server (auth/password.py), così lo
/// si vede subito; il server resta il controllo definitivo.
String? erroreNuovaPassword(String password, {bool amministratore = false}) {
  final minima = lunghezzaMinimaPassword(amministratore: amministratore);
  if (password.length < minima) {
    return 'La password deve avere almeno $minima caratteri${amministratore ? ' per un amministratore' : ''}.';
  }
  if (RegExp(r'^\p{L}+$', unicode: true).hasMatch(password) || RegExp(r'^\d+$').hasMatch(password)) {
    return 'La password deve contenere sia lettere sia numeri o simboli.';
  }
  return null;
}
