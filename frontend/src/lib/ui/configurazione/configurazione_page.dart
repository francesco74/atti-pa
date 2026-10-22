import 'package:flutter/material.dart';

import '../comuni.dart';
import 'editor_checklist_page.dart';
import 'editor_comune.dart';
import 'editor_modello_page.dart';

/// Modelli di atto, specificità e checklist dell'ente: elenco con lo stato (standard,
/// modificato, bozza in corso, proposte dei redattori) e apertura dell'editor.
class ConfigurazionePage extends StatefulWidget {
  const ConfigurazionePage({super.key});

  @override
  State<ConfigurazionePage> createState() => _ConfigurazionePageState();
}

class _ConfigurazionePageState extends State<ConfigurazionePage> {
  late Future<Map<String, dynamic>> _elenco;
  bool _disattivati = false; // mostra anche gli oggetti disattivati

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _elenco = apiDi(context).get('/api/v1/configurazione').then((v) => v as Map<String, dynamic>);
      });

  Future<void> _apri(String tipo, String codice) async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => tipo == 'checklist'
          ? EditorChecklistPage(codice: codice)
          : EditorModelloPage(tipo: tipo, codice: codice),
    ));
    if (mounted) _carica();
  }

  Future<void> _nuovo(String tipo, List<Map<String, dynamic>> esistenti) async {
    final codice = TextEditingController();
    String? copiaDa;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: Text(switch (tipo) {
            'modello' => 'Nuovo modello di atto',
            'modulo' => 'Nuova specificità',
            _ => 'Nuova checklist',
          }),
          content: SizedBox(
            width: 460,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(
                controller: codice,
                autofocus: true,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(
                  labelText: 'Codice',
                  helperText: 'Lettere maiuscole, cifre e _ (es. DD_ACQUISTO_ARREDI)',
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String?>(
                initialValue: copiaDa,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Parti da'),
                items: [
                  const DropdownMenuItem<String?>(value: null, child: Text('Vuoto')),
                  for (final e in esistenti)
                    if (e['nuovo'] != true && e['stato'] != 'DISATTIVATO')
                      DropdownMenuItem<String?>(value: e['codice'] as String, child: Text('Copia di: ${e['titolo']}')),
                ],
                onChanged: (v) => aggiorna(() => copiaDa = v),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Crea la bozza')),
          ],
        ),
      ),
    );
    final valore = codice.text.trim().toUpperCase();
    codice.dispose();
    if (ok != true || !mounted) return;
    if (!RegExp(r'^[A-Z0-9_-]{2,}$').hasMatch(valore)) {
      mostraErrore(context, 'Codice non valido: lettere maiuscole, cifre, _ e -');
      return;
    }
    try {
      await apiDi(context).post('/api/v1/configurazione/$tipo/nuovo', {'codice': valore, 'copia_da': copiaDa});
      if (mounted) await _apri(tipo, valore);
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _stato(Map<String, dynamic> o) {
    final tema = Theme.of(context);
    Widget chip(String t, Color sfondo, [IconData? icona]) => Padding(
          padding: const EdgeInsets.only(right: 4),
          child: Chip(
            visualDensity: VisualDensity.compact,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            avatar: icona == null ? null : Icon(icona, size: 16),
            label: Text(t, style: tema.textTheme.labelSmall),
            backgroundColor: sfondo,
          ),
        );
    final redazione = o['redazione'] as Map<String, dynamic>?;
    return Wrap(children: [
      if (o['stato'] == 'DISATTIVATO') chip('disattivato', tema.colorScheme.errorContainer, Icons.block),
      if (o['stato'] == 'IN_REDAZIONE')
        chip(
          redazione?['mia'] == true ? 'in redazione da te' : 'in redazione da ${redazione?['autore'] ?? 'altro utente'}',
          Colors.amber.shade100,
          redazione?['mia'] == true ? Icons.edit_note : Icons.lock_outline,
        ),
      if (o['nuovo'] == true)
        chip('nuovo, mai pubblicato', tema.colorScheme.tertiaryContainer)
      else if (o['pacchetto'] == null)
        chip('creato dall\'ente', tema.colorScheme.surfaceContainerHighest)
      else if (o['modificato'] == true)
        chip('standard modificato', tema.colorScheme.secondaryContainer)
      else
        chip('standard', tema.colorScheme.surfaceContainerHighest),
      if ((o['proposte'] ?? 0) > 0)
        chip('${o['proposte']} proposte', tema.colorScheme.tertiaryContainer, Icons.feedback_outlined),
    ]);
  }

  Widget _elencoDi(String tipo, List<Map<String, dynamic>> tutte, String vuoto, String Function(Map<String, dynamic>) sotto) {
    final voci = [for (final o in tutte) if (_disattivati || o['stato'] != 'DISATTIVATO') o];
    final nascosti = tutte.length - voci.length;
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        heroTag: tipo,
        onPressed: () => _nuovo(tipo, voci),
        icon: const Icon(Icons.add),
        label: Text(switch (tipo) {
          'modello' => 'Nuovo modello',
          'modulo' => 'Nuova specificità',
          _ => 'Nuova checklist',
        }),
      ),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 88), children: [
        Row(children: [
          Expanded(
            child: Text(nascosti > 0 ? '$nascosti disattivati nascosti' : '', style: Theme.of(context).textTheme.bodySmall),
          ),
          const Text('Mostra disattivati'),
          Switch(value: _disattivati, onChanged: (v) => setState(() => _disattivati = v)),
        ]),
        if (voci.isEmpty) Text(vuoto),
        for (final o in voci)
          Card(
            child: ListTile(
              title: Text(
                '${o['titolo']}${o['versione'] != null ? ' (v${o['versione']})' : ''}',
                style: o['stato'] == 'DISATTIVATO' ? TextStyle(color: Theme.of(context).disabledColor) : null,
              ),
              subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text([o['codice'], sotto(o)].where((s) => s.toString().isNotEmpty).join(' · ')),
                const SizedBox(height: 4),
                _stato(o),
              ]),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _apri(tipo, o['codice'] as String),
            ),
          ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Caricamento<Map<String, dynamic>>(
      future: _elenco,
      riprova: _carica,
      builder: (context, e) {
        final modelli = listaDi(e['modelli']);
        final moduli = listaDi(e['moduli']);
        final schede = listaDi(e['checklist']);
        final vuoto = modelli.isEmpty && moduli.isEmpty && schede.isEmpty;
        final titoli = {for (final m in modelli) m['codice']: m['titolo'], for (final m in moduli) m['codice']: m['titolo']};
        return DefaultTabController(
          length: 3,
          child: Column(children: [
            if (vuoto)
              const MaterialBanner(
                leading: Icon(Icons.info_outline),
                content: Text('Nessun modello, specificità o checklist installato. Un amministratore '
                    'carica il pacchetto standard in Amministrazione → Pacchetti; in alternativa si '
                    'creano qui da zero con il pulsante "Nuovo".'),
                actions: [SizedBox.shrink()],
              ),
            TabBar(tabs: [
              Tab(icon: const Icon(Icons.article_outlined), text: 'Modelli di atto (${modelli.length})'),
              Tab(icon: const Icon(Icons.extension_outlined), text: 'Specificità (${moduli.length})'),
              Tab(icon: const Icon(Icons.checklist), text: 'Checklist (${schede.length})'),
            ]),
            Expanded(
              child: TabBarView(children: [
                _elencoDi('modello', modelli, 'Nessun modello.', (_) => ''),
                _elencoDi('modulo', moduli, 'Nessuna specificità.', (_) => ''),
                _elencoDi('checklist', schede, 'Nessuna checklist.', (c) => c['modello'] != null
                    ? 'modello: ${titoli[c['modello']] ?? c['modello']}'
                    : c['modulo'] != null
                        ? 'specificità: ${titoli[c['modulo']] ?? c['modulo']}'
                        : c['nuovo'] == true
                            ? ''
                            : 'generica della tipologia'),
              ]),
            ),
          ]),
        );
      },
    );
  }
}
