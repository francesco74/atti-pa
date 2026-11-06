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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: colore.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colore.withValues(alpha: 0.7)),
      ),
      child: Text(livello ?? 'Non valutato',
          style: TextStyle(color: colore.shade800, fontSize: 12, fontWeight: FontWeight.w600)),
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
  Widget build(BuildContext context) => ListTile(
        leading: Icon(icona),
        title: Text(titolo),
        subtitle: dettagli.isEmpty ? null : Text(dettagli.join(' · ')),
        trailing: finale.isEmpty
            ? null
            : Row(mainAxisSize: MainAxisSize.min, children: [
                for (final f in finale) Padding(padding: const EdgeInsets.only(left: 4), child: f),
              ]),
        onTap: onTap,
      );
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
    Widget voce(String testo, VoidCallback? azione) => ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 320),
          child: azione == null
              ? Text(testo, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600))
              : InkWell(
                  onTap: azione,
                  child: Text(testo, overflow: TextOverflow.ellipsis, style: TextStyle(color: colori.primary)),
                ),
        );
    return Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 4, runSpacing: 4, children: [
      for (var i = 0; i < voci.length; i++) ...[
        if (i > 0) Icon(Icons.chevron_right, size: 18, color: colori.outline),
        voce(voci[i].$1, voci[i].$2),
      ],
    ]);
  }
}

/// Campo di testo con il valore iniziale; restituisce null se vuoto.
String? testoOppureNull(TextEditingController c) => c.text.trim().isEmpty ? null : c.text.trim();

/// Finestra di modifica con campi di testo (multilinea dove serve) e menu a tendina: usata
/// per aree, processi, attività, rischi e misure.
class Campo {
  const Campo(this.chiave, this.etichetta, {this.righe = 1, this.obbligatorio = false, this.scelte, this.aiuto});

  final String chiave;
  final String etichetta;
  final int righe;
  final bool obbligatorio;
  final List<(String?, String)>? scelte; // (valore, etichetta): menu a tendina
  final String? aiuto;
}

Future<Map<String, dynamic>?> modificaCampi(
  BuildContext context, {
  required String titolo,
  required List<Campo> campi,
  Map<String, dynamic> valori = const {},
}) async {
  final testi = {
    for (final c in campi)
      if (c.scelte == null) c.chiave: TextEditingController(text: valori[c.chiave]?.toString() ?? ''),
  };
  final scelte = <String, String?>{
    for (final c in campi)
      if (c.scelte != null) c.chiave: valori[c.chiave] as String?,
  };
  String? errore;
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => StatefulBuilder(
      builder: (c, aggiorna) => AlertDialog(
        title: Text(titolo),
        content: SizedBox(
          width: 560,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              for (final campo in campi)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: campo.scelte == null
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
    ),
  );
  final risultato = <String, dynamic>{
    for (final e in testi.entries) e.key: testoOppureNull(e.value),
    ...scelte,
  };
  for (final t in testi.values) {
    t.dispose();
  }
  return ok == true ? risultato : null;
}

/// Messaggio dopo l'invio di una proposta del referente.
void propostaInviata(BuildContext context) => mostraMessaggio(
    context, 'Proposta inviata al RPCT. Finché non decide la trovi in Proposte, dove puoi completarla o ritirarla.');
