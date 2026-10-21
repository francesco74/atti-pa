import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../util/download.dart';
import '../comuni.dart';
import 'pacchetti.dart';

/// Da dove viene un modello o una checklist: dal pacchetto standard (eventualmente
/// modificato dall'ente) oppure creato dall'ente.
String provenienza(Map<String, dynamic> o) => o['pacchetto'] == null
    ? 'creato dall\'ente'
    : o['impronta'] == o['impronta_base']
        ? 'standard (${o['pacchetto']})'
        : 'standard modificato dall\'ente';

class AdminPage extends StatelessWidget {
  const AdminPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const DefaultTabController(
      length: 3,
      child: Column(children: [
        TabBar(tabs: [
          Tab(icon: Icon(Icons.apartment), text: 'Dati dell\'ente'),
          Tab(icon: Icon(Icons.inventory_2_outlined), text: 'Pacchetti'),
          Tab(icon: Icon(Icons.sync), text: 'Aggiornamenti Normattiva'),
        ]),
        Expanded(child: TabBarView(children: [_ModelliEnte(), PacchettiPage(), _Aggiornamenti()])),
      ]),
    );
  }
}

// --- Modelli di atto e dati dell'ente ------------------------------------------------

/// Dati dell'ente usati da tutti i modelli e carta intestata. Modelli, specificità e
/// checklist si gestiscono in "Modelli e checklist".
class _ModelliEnte extends StatefulWidget {
  const _ModelliEnte();

  @override
  State<_ModelliEnte> createState() => _ModelliEnteState();
}

class _ModelliEnteState extends State<_ModelliEnte> {
  late Future<Map<String, dynamic>> _ente;
  final Map<String, TextEditingController> _valori = {};
  bool _salvataggio = false;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    for (final c in _valori.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _carica() {
    final api = apiDi(context);
    setState(() {
      _ente = api.get('/api/v1/ente').then((v) {
        final dati = v as Map<String, dynamic>;
        final valori = Map<String, dynamic>.from(dati['valori'] as Map);
        for (final c in List<Map<String, dynamic>>.from(dati['campi'] as List)) {
          _valori.putIfAbsent(c['nome'] as String, TextEditingController.new).text =
              valori[c['nome']]?.toString() ?? '';
        }
        return dati;
      });
    });
  }

  Future<void> _salvaDati() async {
    setState(() => _salvataggio = true);
    try {
      await apiDi(context).put('/api/v1/ente', {
        'valori': {for (final e in _valori.entries) e.key: e.value.text.trim()},
      });
      if (mounted) mostraMessaggio(context, 'Dati dell\'ente salvati');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _salvataggio = false);
    }
  }

  Future<void> _caricaCarta() async {
    final file = await FilePicker.pickFile(type: FileType.custom, allowedExtensions: ['odt']);
    if (file == null || !mounted) return;
    try {
      await apiDi(context).postMultipart(
        '/api/v1/ente/carta-intestata',
        campi: {},
        campoFile: 'file',
        bytes: await file.readAsBytes(),
        nomeFile: file.name,
      );
      if (mounted) mostraMessaggio(context, 'Carta intestata caricata');
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _eliminaCarta() async {
    if (!await conferma(context, 'Togliere la carta intestata?',
        'I documenti useranno l\'impaginazione semplice predefinita.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('/api/v1/ente/carta-intestata');
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(padding: const EdgeInsets.all(16), children: [
      Caricamento<Map<String, dynamic>>(
        future: _ente,
        riprova: _carica,
        builder: (context, ente) {
          final campi = List<Map<String, dynamic>>.from(ente['campi'] as List);
          final segnaposto = List<String>.from(ente['segnaposto_carta'] as List)
              .map((s) => '{{$s}}')
              .join(', ');
          return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Sezione(
              titolo: 'Dati dell\'ente',
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Text('Dati che si ripetono in tutti gli atti (delibere di programmazione, '
                    'luogo, sezione del TAR...). Negli atti sono proposti in automatico e '
                    'l\'utente può comunque modificarli. Vanno aggiornati a ogni nuovo esercizio.'),
                const SizedBox(height: 12),
                if (campi.isEmpty) const Text('Nessun modello attivo richiede dati dell\'ente.'),
                Wrap(spacing: 16, runSpacing: 12, children: [
                  for (final c in campi)
                    SizedBox(
                      width: 360,
                      child: TextField(
                        controller: _valori.putIfAbsent(c['nome'] as String, TextEditingController.new),
                        decoration: InputDecoration(
                          labelText: c['etichetta'] as String,
                          helperText: c['aiuto'] as String?,
                          helperMaxLines: 3,
                        ),
                      ),
                    ),
                ]),
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerLeft,
                  child: FilledButton.icon(
                    onPressed: _salvataggio ? null : _salvaDati,
                    icon: const Icon(Icons.save),
                    label: const Text('Salva i dati dell\'ente'),
                  ),
                ),
              ]),
            ),
            Sezione(
              titolo: 'Carta intestata',
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text('Documento ODT con logo e impaginazione dell\'ente, con i segnaposto '
                    '$segnaposto nei punti in cui inserire le quattro parti dell\'atto. '
                    'Senza carta intestata si usa un\'impaginazione semplice.'),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  Text(ente['carta_intestata'] == null
                      ? 'Nessuna carta intestata caricata.'
                      : 'In uso: ${ente['carta_intestata']}'),
                  OutlinedButton.icon(
                    onPressed: _caricaCarta,
                    icon: const Icon(Icons.upload_file),
                    label: const Text('Carica .odt'),
                  ),
                  if (ente['carta_intestata'] != null) ...[
                    OutlinedButton.icon(
                      onPressed: () => salvaFile(apiDi(context), '/api/v1/ente/carta-intestata',
                          ente['carta_intestata'] as String),
                      icon: const Icon(Icons.download),
                      label: const Text('Scarica'),
                    ),
                    TextButton(onPressed: _eliminaCarta, child: const Text('Togli')),
                  ],
                ]),
              ]),
            ),
          ]);
        },
      ),
    ]);
  }
}

// --- Aggiornamenti Normattiva --------------------------------------------------------

class _Aggiornamenti extends StatelessWidget {
  const _Aggiornamenti();

  @override
  Widget build(BuildContext context) {
    return Caricamento<dynamic>(
      future: apiDi(context).get('/api/v1/norme/aggiornamenti'),
      builder: (context, dati) {
        final lista = (dati as List).cast<Map<String, dynamic>>();
        if (lista.isEmpty) {
          return const Center(child: Text('Il job di aggiornamento non è ancora stato eseguito.'));
        }
        return ListView(padding: const EdgeInsets.all(16), children: [
          for (final s in lista)
            ListTile(
              leading: Icon(
                s['esito'] == 'OK' ? Icons.check_circle : Icons.warning,
                color: s['esito'] == 'OK' ? Colors.green : Colors.orange,
              ),
              title: Text('${formatData(s['eseguito_il'])} · ${s['esito']}'),
              subtitle: Text('${s['atti_modificati']} atti modificati, '
                  '${s['articoli_aggiornati']} articoli aggiornati'
                  '${s['dettaglio'] != null ? '\n${s['dettaglio']}' : ''}'),
            ),
        ]);
      },
    );
  }
}
