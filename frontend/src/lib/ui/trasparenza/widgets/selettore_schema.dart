import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';

/// Scelta del tipo di atto tra gli schemi ANAC (GET /schemi): schema ed
/// eventuale variante di audit.
class SceltaSchema {
  final Map<String, dynamic> schema;
  final Map<String, dynamic>? variante;

  const SceltaSchema(this.schema, [this.variante]);
}

String maiuscola(String testo) =>
    testo.isEmpty ? testo : testo[0].toUpperCase() + testo.substring(1);

/// Vero se lo schema deriva da una delibera ANAC (art. 48 d.lgs. 33/2013);
/// falso per le schede ricavate direttamente dalla norma.
bool schemaAnac(Map<String, dynamic> schema) => schema['schema_anac'] != false;

/// Avviso per le schede che non derivano da uno schema approvato da ANAC.
class AvvisoSchemaNonAnac extends StatelessWidget {
  final Map<String, dynamic> schema;

  const AvvisoSchemaNonAnac({super.key, required this.schema});

  @override
  Widget build(BuildContext context) {
    final norme = ((schema['fonte']?['norme'] as List?) ?? const []).join('; ');
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.orange.shade50,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.orange.shade300),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.gavel, size: 20, color: Colors.orange.shade900),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Per questo obbligo ANAC non ha approvato uno schema di pubblicazione: '
              'la scheda è ricavata direttamente dalla norma ($norme) e la sua struttura '
              'non corrisponde a un modello ufficiale.',
              style: TextStyle(fontSize: 13, color: Colors.orange.shade900),
            ),
          ),
        ],
      ),
    );
  }
}

/// Dialog con gli schemi raggruppati per sotto-sezione di Amministrazione
/// trasparente e un campo di ricerca. Con [conVarianti] elenca anche le
/// varianti di audit di ciascuno schema.
Future<SceltaSchema?> mostraSelettoreSchema(
  BuildContext context, {
  required List<Map<String, dynamic>> schemi,
  required String titolo,
  bool conVarianti = false,
  String? idSchema,
  String? idVariante,
}) {
  return showDialog<SceltaSchema>(
    context: context,
    builder: (_) => _SelettoreSchema(
      schemi: schemi,
      titolo: titolo,
      conVarianti: conVarianti,
      idSchema: idSchema,
      idVariante: idVariante,
    ),
  );
}

class _SelettoreSchema extends StatefulWidget {
  final List<Map<String, dynamic>> schemi;
  final String titolo;
  final bool conVarianti;
  final String? idSchema;
  final String? idVariante;

  const _SelettoreSchema({
    required this.schemi,
    required this.titolo,
    required this.conVarianti,
    this.idSchema,
    this.idVariante,
  });

  @override
  State<_SelettoreSchema> createState() => _SelettoreSchemaState();
}

class _SelettoreSchemaState extends State<_SelettoreSchema> {
  String _filtro = '';

  List<Map<String, dynamic>> _varianti(Map<String, dynamic> schema) =>
      widget.conVarianti
      ? ((schema['audit'] as List?) ?? const []).cast<Map<String, dynamic>>()
      : const [];

  bool _soloVarianti(Map<String, dynamic> schema) =>
      schema['solo_varianti'] == true && _varianti(schema).isNotEmpty;

  String _titoloVoce(SceltaSchema voce) {
    final variante = voce.variante;
    if (variante != null) return maiuscola(variante['titolo'] as String);
    final titolo = voce.schema['titolo'] as String;
    return _varianti(voce.schema).isEmpty ? titolo : '$titolo: tutte le sezioni';
  }

  bool _corrisponde(SceltaSchema voce, String categoria) {
    if (_filtro.isEmpty) return true;
    final testo = [
      categoria,
      voce.schema['titolo'],
      voce.schema['riferimento'],
      voce.schema['articolo'],
      voce.variante?['titolo'] ?? '',
    ].join(' ').toLowerCase();
    return _filtro
        .toLowerCase()
        .split(RegExp(r'\s+'))
        .every((parola) => testo.contains(parola));
  }

  @override
  Widget build(BuildContext context) {
    final gruppi = <String, List<SceltaSchema>>{};
    for (final schema in widget.schemi) {
      final categoria = schema['categoria_at'] as String;
      final voci = [
        // Con 'solo_varianti' si sceglie sempre uno dei controlli dedicati.
        if (!_soloVarianti(schema)) SceltaSchema(schema),
        for (final v in _varianti(schema)) SceltaSchema(schema, v),
      ].where((v) => _corrisponde(v, categoria));
      if (voci.isNotEmpty) gruppi.putIfAbsent(categoria, () => []).addAll(voci);
    }
    final categorie = gruppi.keys.toList()..sort();
    final colore = Theme.of(context).colorScheme.primary;

    // PointerInterceptor: il selettore si apre anche sopra l'editor (iframe)
    // della scheda dei risultati.
    return PointerInterceptor(
      child: AlertDialog(
      title: Text(widget.titolo),
      content: SizedBox(
        width: 700,
        height: MediaQuery.of(context).size.height * 0.6,
        child: Column(
          children: [
            TextField(
              autofocus: true,
              decoration: const InputDecoration(
                hintText: 'Cerca per titolo, articolo o sotto-sezione',
                prefixIcon: Icon(Icons.search),
                isDense: true,
              ),
              onChanged: (v) => setState(() => _filtro = v.trim()),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: categorie.isEmpty
                  ? const Center(child: Text('Nessun risultato.'))
                  : ListView(
                      children: [
                        for (final categoria in categorie)
                          ExpansionTile(
                            // La chiave cambia con il filtro: durante una
                            // ricerca i gruppi si riaprono tutti.
                            key: ValueKey('$categoria|$_filtro'),
                            leading: const Icon(Icons.folder_outlined),
                            title: Text(
                              categoria,
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            initiallyExpanded:
                                _filtro.isNotEmpty ||
                                gruppi[categoria]!.any(
                                  (v) => v.schema['id'] == widget.idSchema,
                                ),
                            children: [
                              for (final voce in gruppi[categoria]!)
                                _voce(context, voce, colore),
                            ],
                          ),
                      ],
                    ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Annulla'),
        ),
      ],
      ),
    );
  }

  Widget _voce(BuildContext context, SceltaSchema voce, Color colore) {
    // Le varianti sono rientrate sotto la voce dello schema, se questa c'è.
    final rientrata = voce.variante != null && !_soloVarianti(voce.schema);
    final selezionata =
        voce.schema['id'] == widget.idSchema &&
        voce.variante?['id'] == widget.idVariante;
    return ListTile(
      selected: selezionata,
      selectedColor: colore,
      contentPadding: EdgeInsets.only(left: rientrata ? 64 : 40, right: 16),
      leading: Icon(
        rientrata
            ? Icons.subdirectory_arrow_right
            : Icons.description_outlined,
        size: 20,
      ),
      title: Text(
        _titoloVoce(voce),
        style: TextStyle(
          fontSize: 14,
          fontWeight: selezionata ? FontWeight.bold : FontWeight.normal,
        ),
      ),
      subtitle: Text(
        voce.schema['riferimento'] as String,
        style: TextStyle(
          fontSize: 12,
          color: schemaAnac(voce.schema) ? null : Colors.orange.shade900,
        ),
      ),
      onTap: () => Navigator.pop(context, voce),
    );
  }
}

/// Scheda informativa costruita dallo schema: fonte, ambito soggettivo e
/// sezioni (limitate a quelle della variante, se indicata).
void mostraInfoSchema(
  BuildContext context,
  Map<String, dynamic> schema, [
  Map<String, dynamic>? variante,
]) {
  final sezioniVariante = ((variante?['sezioni'] as List?) ?? const [])
      .cast<String>();
  final sezioni = (schema['sezioni'] as List)
      .cast<Map<String, dynamic>>()
      .where(
        (s) => sezioniVariante.isEmpty || sezioniVariante.contains(s['id']),
      )
      .toList();
  final ambito = (schema['ambito_soggettivo'] as String? ?? '').trim();

  showDialog(
    context: context,
    builder: (BuildContext context) {
      return AlertDialog(
        title: Row(
          children: [
            Icon(
              Icons.info_outline,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(width: 8),
            const Expanded(child: Text('Dettagli normativi')),
          ],
        ),
        content: SizedBox(
          width: 800,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${schema['titolo']} (${maiuscola(schema['articolo'] as String)} d.lgs. 33/2013)',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                if (schemaAnac(schema))
                  Text(
                    'Schema ANAC: ${schema['fonte_descrizione']}',
                    style: TextStyle(color: Colors.grey.shade700),
                  )
                else
                  AvvisoSchemaNonAnac(schema: schema),
                if (ambito.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  const Text(
                    'Ambito soggettivo',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(ambito.replaceAll('\n', ' ')),
                ],
                const SizedBox(height: 16),
                Text(
                  sezioni.length == 1 ? 'Sezione' : 'Sezioni',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                for (final sezione in sezioni)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '• ${sezione['titolo']}',
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        Padding(
                          padding: const EdgeInsets.only(left: 12, top: 2),
                          child: Text(
                            'Collocazione: ${sezione['collocazione']}\n'
                            'Aggiornamento: ${sezione['aggiornamento']}\n'
                            'Riferimenti: ${(sezione['norme'] as List).join('; ')}',
                            style: TextStyle(
                              fontSize: 13,
                              color: Colors.grey.shade800,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
        actions: <Widget>[
          TextButton(
            child: const Text('Chiudi'),
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      );
    },
  );
}
