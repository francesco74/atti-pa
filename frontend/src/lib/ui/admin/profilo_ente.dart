import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';
import '../../util/scelta_file.dart';

/// Profilo dell'ente, comune a tutti i moduli: logo nei documenti generati,
/// caratteristiche dell'amministrazione, date all'LLM come contesto delle analisi, e testo per
/// l'assistenza agli utenti (pagina di accesso, menu dell'app, pagine di aiuto).
class ProfiloEntePage extends StatefulWidget {
  const ProfiloEntePage({super.key});

  @override
  State<ProfiloEntePage> createState() => _ProfiloEntePageState();
}

class _ProfiloEntePageState extends State<ProfiloEntePage> {
  late Future<Map<String, dynamic>> _profilo;
  Future<Uint8List>? _logo;
  final _caratteristiche = TextEditingController();
  final _assistenza = TextEditingController();
  final _dichiarazione = TextEditingController();
  bool _salvataggio = false;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _caratteristiche.dispose();
    _assistenza.dispose();
    _dichiarazione.dispose();
    super.dispose();
  }

  void _carica() {
    final api = apiDi(context);
    setState(() {
      _profilo = api.get('/api/v1/ente/profilo').then((v) {
        final p = v as Map<String, dynamic>;
        _caratteristiche.text = p['caratteristiche'] as String? ?? '';
        _assistenza.text = p['assistenza'] as String? ?? '';
        _dichiarazione.text = p['dichiarazione_accessibilita'] as String? ?? '';
        _logo = p['logo'] == true ? api.getBytes('/api/v1/ente/logo') : null;
        return p;
      });
    });
  }

  /// Salva solo i campi indicati (gli altri restano come sono).
  Future<void> _salva(Map<String, String> campi) async {
    setState(() => _salvataggio = true);
    try {
      await apiDi(context).put('/api/v1/ente/profilo', campi);
      if (mounted) mostraMessaggio(context, 'Profilo dell\'ente salvato');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _salvataggio = false);
    }
  }

  Future<void> _caricaLogo() async {
    final file = await scegliFile(['png', 'jpg', 'jpeg']);
    if (file == null || !mounted) return;
    try {
      await apiDi(context).postMultipart(
        '/api/v1/ente/logo',
        campi: {},
        campoFile: 'file',
        bytes: file.bytes,
        nomeFile: file.name,
      );
      if (!mounted) return;
      context.read<AuthState>().impostaLogo(file.bytes);
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _eliminaLogo() async {
    if (!await conferma(context, 'Togliere il logo?', 'I documenti generati non avranno il logo.')) return;
    if (!mounted) return;
    try {
      await apiDi(context).delete('/api/v1/ente/logo');
      if (!mounted) return;
      context.read<AuthState>().impostaLogo(null);
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Caricamento<Map<String, dynamic>>(
      future: _profilo,
      riprova: _carica,
      builder: (context, profilo) => ListView(padding: const EdgeInsets.all(16), children: [
        Sezione(
          titolo: 'Logo',
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Immagine PNG o JPEG (al massimo 2 MB) riportata in testa ai documenti '
                'generati, come le schede e i verbali della trasparenza, e usata come icona e sfondo dell\'app.'),
            const SizedBox(height: 12),
            if (_logo != null)
              FutureBuilder<Uint8List>(
                future: _logo,
                builder: (context, s) => s.hasData
                    ? Image.memory(s.data!, height: 96, fit: BoxFit.contain, alignment: Alignment.centerLeft)
                    : const SizedBox(height: 96),
              )
            else
              const Text('Nessun logo caricato.'),
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: [
              OutlinedButton.icon(
                onPressed: _caricaLogo,
                icon: const Icon(Icons.upload_file),
                label: Text(_logo == null ? 'Carica il logo' : 'Sostituisci'),
              ),
              if (_logo != null) TextButton(onPressed: _eliminaLogo, child: const Text('Togli')),
            ]),
          ]),
        ),
        Sezione(
          titolo: 'Caratteristiche dell\'amministrazione',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Descrizione dell\'ente usata come contesto nelle analisi con l\'IA: tipo di '
                'amministrazione, dimensione, organi, società partecipate, obblighi che non la '
                'riguardano...'),
            const SizedBox(height: 12),
            TextField(
              controller: _caratteristiche,
              minLines: 5,
              maxLines: 15,
              maxLength: 10000,
              decoration: InputDecoration(labelText: profilo['nome'] as String),
            ),
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.icon(
                onPressed: _salvataggio ? null : () => _salva({'caratteristiche': _caratteristiche.text}),
                icon: const Icon(Icons.save),
                label: const Text('Salva'),
              ),
            ),
          ]),
        ),
        Sezione(
          titolo: 'Assistenza agli utenti',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Frase mostrata dove l\'utente può aver bisogno di aiuto: pagina di accesso ("Serve aiuto?"), '
                'voce Assistenza del menu dell\'utente, pagina della normativa della trasparenza. Indirizzi email e '
                'link diventano cliccabili. Vuoto: non compare da nessuna parte.'),
            const SizedBox(height: 12),
            TextField(
              controller: _assistenza,
              minLines: 2,
              maxLines: 6,
              maxLength: 2000,
              decoration: const InputDecoration(
                labelText: 'Testo per l\'assistenza',
                hintText: 'es. Per assistenza scrivi a supporto@ente.it o chiama l\'interno 1234',
              ),
            ),
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.icon(
                onPressed: _salvataggio ? null : () => _salva({'assistenza': _assistenza.text}),
                icon: const Icon(Icons.save),
                label: const Text('Salva'),
              ),
            ),
          ]),
        ),
        Sezione(
          titolo: 'Dichiarazione di accessibilità',
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Indirizzo della dichiarazione di accessibilità dell\'ente (compilata su form.agid.gov.it): '
                'compare in fondo alle pagine pubbliche per i cittadini, insieme al modulo per segnalare un problema '
                'di accessibilità. Le segnalazioni arrivano in "Ricerche e feedback".'),
            const SizedBox(height: 12),
            TextField(
              controller: _dichiarazione,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Indirizzo della dichiarazione',
                hintText: 'https://form.agid.gov.it/view/...',
              ),
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.icon(
                onPressed: _salvataggio ? null : () => _salva({'dichiarazione_accessibilita': _dichiarazione.text.trim()}),
                icon: const Icon(Icons.save),
                label: const Text('Salva'),
              ),
            ),
          ]),
        ),
      ]),
    );
  }
}
