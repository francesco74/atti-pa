import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:url_launcher/url_launcher.dart';

import '../ricerca.dart';

/// Accessibilità delle pagine pubbliche (WCAG 2.1 livello AA, linee guida AgID). Su web Flutter
/// disegna su un canvas e affida ai lettori di schermo un albero di nodi ARIA (semantics): questi
/// widget lo completano con intestazioni, annunci, titolo della pagina, salto al contenuto,
/// focus visibile e bersagli ampi. Criteri principali coperti:
/// 1.3.1 ([Intestazione]), 1.4.3/1.4.11 ([temaPubblico]), 1.4.10 ([LarghezzaMassima]),
/// 2.4.1 ([SaltaAlContenuto]), 2.4.2/2.4.3 ([VistaPubblica]), 2.4.7 ([temaPubblico]),
/// 4.1.3 ([annuncia], `liveRegion`). Limite noto: 1.4.12 (spaziatura del testo imposta
/// dall'utente) non si applica al canvas.

/// Attiva l'albero di accessibilità senza aspettare il pulsante "Enable accessibility" che
/// Flutter web mostra ai lettori di schermo: nelle pagine pubbliche deve esserci sempre.
void attivaAccessibilita() => SemanticsBinding.instance.ensureSemantics();

/// Messaggio letto dai lettori di schermo senza spostare il focus (4.1.3).
void annuncia(BuildContext context, String testo) =>
    SemanticsService.sendAnnouncement(View.of(context), testo, Directionality.of(context));

/// Tema delle pagine pubbliche: densità normale e bersagli di almeno 48 px, focus da tastiera
/// ben visibile (riempimento più marcato e bordo sui pulsanti).
ThemeData temaPubblico(ThemeData base) {
  final colori = base.colorScheme;
  final focus = colori.primary.withValues(alpha: 0.24);
  final bordoFocus = WidgetStateProperty.resolveWith<BorderSide?>(
    (stati) => stati.contains(WidgetState.focused) ? BorderSide(color: colori.primary, width: 3) : null,
  );
  return base.copyWith(
    visualDensity: VisualDensity.standard,
    materialTapTargetSize: MaterialTapTargetSize.padded,
    focusColor: focus,
    textButtonTheme: TextButtonThemeData(style: ButtonStyle(side: bordoFocus, minimumSize: const WidgetStatePropertyAll(Size(48, 48)))),
    outlinedButtonTheme: OutlinedButtonThemeData(style: ButtonStyle(side: bordoFocus)),
    filledButtonTheme: FilledButtonThemeData(style: ButtonStyle(side: bordoFocus)),
    listTileTheme: ListTileThemeData(minVerticalPadding: 8, selectedColor: colori.primary),
  );
}

/// Titolo marcato come intestazione, con il livello (1 il titolo della pagina, 2 le sezioni).
class Intestazione extends StatelessWidget {
  const Intestazione(this.testo, {super.key, this.livello = 2, this.stile});

  final String testo;
  final int livello;
  final TextStyle? stile;

  @override
  Widget build(BuildContext context) => Semantics(
        header: true,
        headingLevel: livello,
        child: Text(testo, style: stile),
      );
}

/// Una vista della pagina (es. l'elenco delle strutture, la scheda di un procedimento): imposta
/// il titolo della scheda del browser (2.4.2) e, quando si cambia vista ([chiave]), porta il
/// focus all'inizio del nuovo contenuto e ne annuncia il titolo (2.4.3, 4.1.3).
class VistaPubblica extends StatefulWidget {
  const VistaPubblica({super.key, required this.titolo, required this.chiave, required this.child});

  final String titolo; // es. "Contributo affitto – Tipologie di procedimento – Comune di …"
  final Object? chiave;
  final Widget child;

  @override
  State<VistaPubblica> createState() => _VistaPubblicaState();
}

class _VistaPubblicaState extends State<VistaPubblica> {
  final _inizio = FocusNode(debugLabel: 'inizio della vista');

  @override
  void didUpdateWidget(VistaPubblica prima) {
    super.didUpdateWidget(prima);
    if (prima.chiave != widget.chiave) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _inizio.requestFocus();
        annuncia(context, widget.titolo.split(' – ').first);
      });
    }
  }

  @override
  void dispose() {
    _inizio.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Title(
        title: widget.titolo,
        color: Theme.of(context).colorScheme.primary,
        child: Focus(focusNode: _inizio, child: widget.child),
      );
}

/// "Vai al contenuto" (2.4.1): primo elemento raggiungibile con il tasto Tab, visibile solo
/// quando ha il focus; sposta il focus su [destinazione].
class SaltaAlContenuto extends StatefulWidget {
  const SaltaAlContenuto({super.key, required this.destinazione});

  final FocusNode destinazione;

  @override
  State<SaltaAlContenuto> createState() => _SaltaAlContenutoState();
}

class _SaltaAlContenutoState extends State<SaltaAlContenuto> {
  bool _visibile = false;

  @override
  Widget build(BuildContext context) => Focus(
        skipTraversal: true,
        onFocusChange: (v) => setState(() => _visibile = v),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Opacity(
            opacity: _visibile ? 1 : 0,
            child: SizedBox(
              height: _visibile ? null : 1,
              child: TextButton(
                onPressed: widget.destinazione.requestFocus,
                child: const Text('Vai al contenuto'),
              ),
            ),
          ),
        ),
      );
}

/// Campo largo al più [massima] ma mai oltre lo spazio disponibile: a 320 px (o con lo zoom al
/// 200%) i campi non escono dalla pagina (1.4.10).
class LarghezzaMassima extends StatelessWidget {
  const LarghezzaMassima(this.massima, {super.key, required this.child});

  final double massima;
  final Widget child;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, vincoli) => SizedBox(
          width: vincoli.maxWidth.isFinite && vincoli.maxWidth < massima ? vincoli.maxWidth : massima,
          child: child,
        ),
      );
}

/// Fondo delle pagine pubbliche: dichiarazione di accessibilità dell'ente e segnalazione di un
/// problema di accessibilità (meccanismo di feedback richiesto dalle linee guida AgID).
class PiePaginaPubblico extends StatelessWidget {
  const PiePaginaPubblico({super.key, required this.dichiarazione, required this.registro, required this.pagina});

  final String? dichiarazione; // indirizzo della dichiarazione di accessibilità
  final RegistroRicerche? registro;
  final String pagina; // titolo della pagina, per la segnalazione

  @override
  Widget build(BuildContext context) {
    final indirizzo = dichiarazione;
    final registro = this.registro;
    final voci = <Widget>[
      if (indirizzo != null)
        TextButton.icon(
          icon: const Icon(Icons.accessibility_new),
          label: const Text('Dichiarazione di accessibilità'),
          onPressed: () => launchUrl(Uri.parse(indirizzo), webOnlyWindowName: '_blank'),
        ),
      if (registro != null)
        TextButton.icon(
          icon: const Icon(Icons.report_outlined),
          label: const Text('Segnala un problema di accessibilità'),
          onPressed: () => showDialog<void>(
            context: context,
            builder: (_) => _SegnalaAccessibilita(registro: registro, pagina: pagina),
          ),
        ),
    ];
    if (voci.isEmpty) return const SizedBox.shrink();
    return Semantics(
      container: true,
      label: 'Piè di pagina',
      child: LayoutBuilder(builder: (context, vincoli) {
        // spazio stretto: un solo pulsante "Accessibilità" che apre le due voci, così il piè di
        // pagina non toglie spazio al contenuto (WCAG 1.4.10)
        if (vincoli.maxWidth >= 640 * MediaQuery.textScalerOf(context).scale(1)) {
          return Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: voci);
        }
        return Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            icon: const Icon(Icons.accessibility_new),
            label: const Text('Accessibilità'),
            onPressed: () => showDialog<void>(
              context: context,
              builder: (contesto) => SimpleDialog(
                title: const Intestazione('Accessibilità'),
                children: [
                  for (final v in voci)
                    Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: Align(alignment: Alignment.centerLeft, child: v)),
                ],
              ),
            ),
          ),
        );
      }),
    );
  }
}

class _SegnalaAccessibilita extends StatefulWidget {
  const _SegnalaAccessibilita({required this.registro, required this.pagina});

  final RegistroRicerche registro;
  final String pagina;

  @override
  State<_SegnalaAccessibilita> createState() => _SegnalaAccessibilitaState();
}

class _SegnalaAccessibilitaState extends State<_SegnalaAccessibilita> {
  final _problema = TextEditingController();
  final _email = TextEditingController();
  String? _errore;
  bool _invio = false, _inviata = false;

  static final _reEmail = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

  @override
  void dispose() {
    _problema.dispose();
    _email.dispose();
    super.dispose();
  }

  Future<void> _invia() async {
    final email = _email.text.trim();
    if (_problema.text.trim().isEmpty) {
      setState(() => _errore = 'Descrivi il problema.');
      return;
    }
    if (email.isNotEmpty && !_reEmail.hasMatch(email)) {
      setState(() => _errore = 'Indirizzo email non valido.');
      return;
    }
    setState(() {
      _errore = null;
      _invio = true;
    });
    final fatto = await widget.registro.feedback({
      'tipo': 'ACCESSIBILITA',
      'riferimento': widget.pagina,
      'utile': false,
      'commento': _problema.text.trim(),
      if (email.isNotEmpty) 'contatto': email,
    });
    if (!mounted) return;
    setState(() {
      _invio = false;
      _inviata = fatto;
      if (!fatto) _errore = 'Invio non riuscito, riprova più tardi.';
    });
    if (fatto) annuncia(context, 'Segnalazione inviata');
  }

  @override
  Widget build(BuildContext context) {
    if (_inviata) {
      return AlertDialog(
        title: const Intestazione('Segnalazione inviata', livello: 2),
        content: const Text('Grazie. L\'ente esamina le segnalazioni e risponde, se hai lasciato un indirizzo email.'),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Chiudi'))],
      );
    }
    return AlertDialog(
      title: const Intestazione('Segnala un problema di accessibilità', livello: 2),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Pagina: ${widget.pagina}'),
            const SizedBox(height: 12),
            TextField(
              controller: _problema,
              autofocus: true,
              minLines: 3,
              maxLines: 8,
              maxLength: 2000,
              decoration: const InputDecoration(
                labelText: 'Descrivi il problema (obbligatorio)',
                helperText: 'Cosa non riesci a fare e con quale strumento (es. lettore di schermo, solo tastiera)',
                helperMaxLines: 3,
              ),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
              decoration: const InputDecoration(
                labelText: 'Email per la risposta (facoltativa)',
                helperText: 'Usata solo per risponderti su questa segnalazione',
                helperMaxLines: 2,
              ),
            ),
            if (_errore != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Semantics(
                  liveRegion: true,
                  child: Text(_errore!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
              ),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annulla')),
        FilledButton(onPressed: _invio ? null : _invia, child: const Text('Invia la segnalazione')),
      ],
    );
  }
}
