import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../comuni.dart';

const apiAnticorruzione = '/api/v1/anticorruzione';

/// Dati usati da tutte le schede del modulo: metodologia dell'ente, aree di rischio,
/// strutture organizzative e obblighi di pubblicazione. Si caricano all'apertura del modulo
/// e si ricaricano dopo una modifica (es. nuova area).
class DatiAnticorruzione {
  DatiAnticorruzione({
    required this.metodologia,
    required this.aree,
    required this.strutture,
    required this.obblighi,
  });

  final Map<String, dynamic> metodologia;
  final List<Map<String, dynamic>> aree;
  final List<Map<String, dynamic>> strutture;
  final List<Map<String, dynamic>> obblighi;

  static Future<DatiAnticorruzione> carica(ApiClient api) async {
    final r = await Future.wait([
      api.get('$apiAnticorruzione/metodologia'),
      api.get('$apiAnticorruzione/aree'),
      api.get('/api/v1/ente/strutture'),
      api.get('$apiAnticorruzione/obblighi'),
    ]);
    List<Map<String, dynamic>> lista(Object? v) => (v as List).cast<Map<String, dynamic>>();
    return DatiAnticorruzione(
      metodologia: r[0] as Map<String, dynamic>,
      aree: lista(r[1]),
      strutture: lista(r[2]),
      obblighi: lista(r[3]),
    );
  }

  List<String> get scala => List<String>.from(metodologia['scala'] as List);
  List<String> get livelli => List<String>.from(metodologia['livelli'] as List); // dal più basso
  List<Map<String, dynamic>> get indicatoriProbabilita =>
      (metodologia['indicatori_probabilita'] as List).cast<Map<String, dynamic>>();
  List<Map<String, dynamic>> get indicatoriImpatto =>
      (metodologia['indicatori_impatto'] as List).cast<Map<String, dynamic>>();
  List<String> get fattori => List<String>.from(metodologia['fattori_abilitanti'] as List? ?? const []);
  List<String> get categorie => List<String>.from(metodologia['categorie_misure'] as List? ?? const []);

  String? area(Object? id) {
    for (final a in aree) {
      if (a['id'] == id) return '${a['codice']} - ${a['descrizione_breve'] ?? a['descrizione']}';
    }
    return null;
  }

  String? struttura(Object? id) {
    for (final s in strutture) {
      if (s['id'] == id) return '${s['codice']} - ${s['descrizione']}';
    }
    return null;
  }

  /// Nomi delle strutture coinvolte (elenco di id), separati da virgola; null se non ce ne sono.
  String? coinvolte(Object? ids) {
    final nomi = [for (final id in (ids as List?) ?? const []) struttura(id) ?? '?'];
    return nomi.isEmpty ? null : nomi.join(', ');
  }

  /// Valore più frequente; a parità il più alto nella scala (come il server).
  String moda(Iterable<String> valori) {
    final conteggi = <String, int>{};
    for (final v in valori) {
      conteggi[v] = (conteggi[v] ?? 0) + 1;
    }
    final massimo = conteggi.values.fold(0, (a, b) => a > b ? a : b);
    return conteggi.entries
        .where((e) => e.value == massimo)
        .map((e) => e.key)
        .reduce((a, b) => scala.indexOf(a) >= scala.indexOf(b) ? a : b);
  }

  String? livelloDa(String? probabilita, String? impatto) {
    if (probabilita == null || impatto == null) return null;
    final riga = (metodologia['matrice'] as Map)[probabilita] as Map?;
    return riga?[impatto] as String?;
  }

  /// Colore del livello: dal verde (il più basso) al rosso (il più alto).
  Color colore(String? livello) {
    final i = livello == null ? -1 : livelli.indexOf(livello);
    if (i < 0) return Colors.blueGrey;
    const scalaColori = [Colors.green, Colors.lightGreen, Colors.amber, Colors.orange, Colors.red];
    final posizione = livelli.length == 1 ? 0 : (i * (scalaColori.length - 1) / (livelli.length - 1)).round();
    return scalaColori[posizione];
  }
}

/// Etichetta colorata del livello di rischio.
class LivelloChip extends StatelessWidget {
  const LivelloChip(this.dati, this.livello, {super.key});

  final DatiAnticorruzione dati;
  final String? livello;

  @override
  Widget build(BuildContext context) {
    final colore = dati.colore(livello);
    // il colore è solo un aiuto: il livello è sempre scritto (WCAG 1.4.1), con il testo scuro
    // per il contrasto (1.4.3: i toni di giallo e arancio sul fondo chiaro non bastano)
    return Semantics(
      label: 'Livello di rischio: ${livello ?? 'non valutato'}',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: colore.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: colore.shade800, width: 1.5),
        ),
        child: Text(livello ?? 'Non valutato',
            style: TextStyle(color: Theme.of(context).colorScheme.onSurface, fontSize: 12, fontWeight: FontWeight.w600)),
      ),
    );
  }
}

extension on Color {
  Color get shade800 => this is MaterialColor ? (this as MaterialColor).shade800 : this;
}

/// Riga di un elenco: icona, titolo, dettagli sotto, stato e azioni a destra.
class RigaVoce extends StatelessWidget {
  const RigaVoce({super.key, required this.icona, required this.titolo, this.dettagli = const [], this.finale = const [], this.onTap});

  final IconData icona;
  final String titolo;
  final List<String> dettagli;
  final List<Widget> finale;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, vincoli) {
        // spazio stretto: stato e azioni vanno sotto il testo invece che a destra
        final stretto = spazioStretto(context, vincoli.maxWidth);
        final dettaglio = dettagli.isEmpty ? null : Text(dettagli.join(' · '));
        return ListTile(
          leading: Icon(icona),
          title: Text(titolo),
          subtitle: stretto && finale.isNotEmpty
              ? Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  ?dettaglio,
                  Wrap(spacing: 4, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: finale),
                ])
              : dettaglio,
          trailing: finale.isEmpty || stretto
              ? null
              : Row(mainAxisSize: MainAxisSize.min, children: [
                  for (final f in finale) Padding(padding: const EdgeInsets.only(left: 4), child: f),
                ]),
          onTap: onTap,
        );
      });
}

/// Azione con la sola icona, per le righe degli elenchi.
class IconaAzione extends StatelessWidget {
  const IconaAzione(this.icona, this.testo, this.onPressed, {super.key});

  final IconData icona;
  final String testo;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) =>
      IconButton(tooltip: testo, visualDensity: VisualDensity.compact, icon: icona == Icons.delete_outline ? IconaElimina(size: 18, attiva: onPressed != null) : Icon(icona, size: 18), onPressed: onPressed);
}

/// Percorso di navigazione: le voci con un'azione si possono cliccare, l'ultima è dove si è.
class Percorso extends StatelessWidget {
  const Percorso(this.voci, {super.key});

  final List<(String, VoidCallback?)> voci;

  @override
  Widget build(BuildContext context) {
    final colori = Theme.of(context).colorScheme;
    // per i lettori di schermo: un gruppo "Percorso", voci come link, l'ultima è la pagina
    // corrente; le frecce sono decorative. Le voci sono alte almeno 48 px (bersagli ampi).
    Widget voce(String testo, VoidCallback? azione) => ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 320, minHeight: 48),
          child: azione == null
              ? Semantics(
                  label: '$testo, pagina corrente',
                  excludeSemantics: true,
                  child: Align(
                    widthFactor: 1,
                    child: Text(testo, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
                  ),
                )
              : Semantics(
                  link: true,
                  child: InkWell(
                    onTap: azione,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 12),
                      child: Text(testo,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: colori.primary, decoration: TextDecoration.underline)),
                    ),
                  ),
                ),
        );
    return Semantics(
      container: true,
      label: 'Percorso',
      child: Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 4, runSpacing: 0, children: [
        for (var i = 0; i < voci.length; i++) ...[
          if (i > 0) ExcludeSemantics(child: Icon(Icons.chevron_right, size: 18, color: colori.outline)),
          voce(voci[i].$1, voci[i].$2),
        ],
      ]),
    );
  }
}

/// Campo di testo con il valore iniziale; restituisce null se vuoto.
String? testoOppureNull(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();

/// Finestra di modifica con campi di testo (multilinea dove serve) e menu a tendina: usata
/// per aree, processi, attività, rischi e misure.
class Campo {
  const Campo(this.chiave, this.etichetta, {this.righe = 1, this.obbligatorio = false, this.scelte, this.aiuto, this.multipla = false});

  final String chiave;
  final String etichetta;
  final int righe;
  final bool obbligatorio;
  final List<(String?, String)>? scelte; // (valore, etichetta): menu a tendina
  final String? aiuto;
  final bool multipla; // con le scelte: più valori (elenco), es. le strutture coinvolte
}

/// Campo a scelta multipla: i valori scelti come etichette (si tolgono con la x) e
/// "Aggiungi" per sceglierne un altro.
Widget _campoMultiplo(BuildContext context, Campo campo, List<String> scelti, void Function(VoidCallback) aggiorna) {
  final nomi = {for (final (v, e) in campo.scelte!) ?v: e};
  return InputDecorator(
    decoration: InputDecoration(labelText: campo.etichetta, helperText: campo.aiuto, helperMaxLines: 3),
    child: Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
      for (final v in scelti)
        InputChip(
          label: Text(nomi[v] ?? v, overflow: TextOverflow.ellipsis),
          deleteButtonTooltipMessage: 'Togli',
          onDeleted: () => aggiorna(() => scelti.remove(v)),
        ),
      ActionChip(
        avatar: const Icon(Icons.add, size: 18),
        label: const Text('Aggiungi'),
        onPressed: () async {
          final v = await showDialog<String>(
            context: context,
            builder: (d) => SimpleDialog(title: Text(campo.etichetta), children: [
              for (final (id, e) in campo.scelte!)
                if (id != null && !scelti.contains(id)) SimpleDialogOption(onPressed: () => Navigator.pop(d, id), child: Text(e)),
            ]),
          );
          if (v != null) aggiorna(() => scelti.add(v));
        },
      ),
    ]),
  );
}

Future<Map<String, dynamic>?> modificaCampi(
  BuildContext context, {
  required String titolo,
  required List<Campo> campi,
  Map<String, dynamic> valori = const {},
  String? nota, // spiegazione sopra i campi (es. la voce del catalogo)
}) async {
  final testi = {
    for (final c in campi)
      if (c.scelte == null) c.chiave: TextEditingController(text: valori[c.chiave]?.toString() ?? ''),
  };
  final scelte = <String, String?>{
    for (final c in campi)
      if (c.scelte != null && !c.multipla) c.chiave: valori[c.chiave] as String?,
  };
  final multiple = <String, List<String>>{
    for (final c in campi)
      if (c.multipla) c.chiave: [...((valori[c.chiave] as List?) ?? const []).cast<String>()],
  };
  String? errore;
  final ok = await showDialog<bool>(
    context: context,
    // i campi si liberano quando la finestra è sparita, non appena si chiude: l'animazione di
    // chiusura li usa ancora
    builder: (c) => _LiberaAllaFine(testi.values.toList(), child: StatefulBuilder(
      builder: (c, aggiorna) => AlertDialog(
        title: Text(titolo),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (nota != null)
                Padding(padding: const EdgeInsets.only(bottom: 12), child: Text(nota, style: Theme.of(c).textTheme.bodySmall)),
              for (final campo in campi)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: campo.multipla
                      ? _campoMultiplo(c, campo, multiple[campo.chiave]!, aggiorna)
                      : campo.scelte == null
                      ? TextField(
                          controller: testi[campo.chiave],
                          minLines: campo.righe == 1 ? 1 : 2,
                          maxLines: campo.righe,
                          decoration: InputDecoration(
                            labelText: campo.etichetta + (campo.obbligatorio ? ' *' : ''),
                            helperText: campo.aiuto,
                            helperMaxLines: 3,
                          ),
                        )
                      : DropdownButtonFormField<String?>(
                          initialValue: campo.scelte!.any((s) => s.$1 == scelte[campo.chiave]) ? scelte[campo.chiave] : null,
                          isExpanded: true,
                          decoration: InputDecoration(labelText: campo.etichetta, helperText: campo.aiuto),
                          items: [
                            for (final (v, e) in campo.scelte!)
                              DropdownMenuItem(value: v, child: Text(e, overflow: TextOverflow.ellipsis)),
                          ],
                          onChanged: (v) => aggiorna(() => scelte[campo.chiave] = v),
                        ),
                ),
              if (errore != null) Text(errore!, style: TextStyle(color: Theme.of(c).colorScheme.error)),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(
            onPressed: () {
              final mancanti = campi.where((x) => x.obbligatorio && x.scelte == null && testi[x.chiave]!.text.trim().isEmpty);
              if (mancanti.isNotEmpty) {
                aggiorna(() => errore = 'Compila: ${mancanti.map((x) => x.etichetta).join(', ')}');
                return;
              }
              Navigator.pop(c, true);
            },
            child: const Text('Salva'),
          ),
        ],
      ),
    )),
  );
  final risultato = <String, dynamic>{
    for (final e in testi.entries) e.key: testoOppureNull(e.value),
    ...scelte,
    ...multiple,
  };
  return ok == true ? risultato : null;
}

/// Il testo per riconoscere le voci uguali (come il server): senza differenze di maiuscole,
/// spazi, apostrofi tipografici e punteggiatura finale.
String normalizzaTesto(String? testo) => (testo ?? '')
    .toLowerCase()
    .replaceAll('\u2019', "'")
    .replaceAll('\u2018', "'")
    .replaceAll('\u201c', '"')
    .replaceAll('\u201d', '"')
    .replaceAll(RegExp(r'\s+'), ' ')
    .trim()
    .replaceAll(RegExp(r'[ .;:,]+$'), '')
    .trim();

/// La voce del catalogo da cui viene l'elemento, quando il testo nel processo è stato
/// ritoccato (null se è lo stesso o se l'elemento non ha voce).
String? voceRitoccata(Map el, String? testo) {
  final v = el['voce'] as Map?;
  if (v == null || normalizzaTesto(v['descrizione'] as String?) == normalizzaTesto(testo)) return null;
  return 'Dal catalogo (${v['codice']}): ${v['descrizione']}';
}

/// Libera i campi di testo quando il widget sparisce (fine dell'animazione della finestra).
class _LiberaAllaFine extends StatefulWidget {
  const _LiberaAllaFine(this.controllori, {required this.child});

  final List<TextEditingController> controllori;
  final Widget child;

  @override
  State<_LiberaAllaFine> createState() => _LiberaAllaFineState();
}

class _LiberaAllaFineState extends State<_LiberaAllaFine> {
  @override
  void dispose() {
    for (final c in widget.controllori) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// Messaggio dopo l'invio di una proposta del referente.
void propostaInviata(BuildContext context) => mostraMessaggio(
    context, 'Proposta inviata al RPCT. Finché non decide la trovi in Proposte, dove puoi completarla o ritirarla.');
