import 'package:flutter/material.dart';

import '../comuni.dart';

/// Collegamento dell'ente al RAG (progetto esterno, collegato tramite API): indirizzo e chiave.
/// Serve per convertire in testo i documenti allegati all'assistente (anche scansioni). La
/// chiave, salvata cifrata, non si rilegge: si può solo sostituire.
class RagEntePage extends StatefulWidget {
  const RagEntePage({super.key});

  @override
  State<RagEntePage> createState() => _RagEntePageState();
}

class _RagEntePageState extends State<RagEntePage> {
  late Future<Map<String, dynamic>> _dati;
  final _url = TextEditingController();
  final _chiave = TextEditingController();
  bool _salvataggio = false;
  String? _esitoProva;
  bool _provaRiuscita = false;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    _url.dispose();
    _chiave.dispose();
    super.dispose();
  }

  void _carica() {
    setState(() {
      _dati = apiDi(context).get('/api/v1/ente/rag').then((v) {
        final d = v as Map<String, dynamic>;
        _url.text = d['url'] as String? ?? '';
        _chiave.clear();
        return d;
      });
    });
  }

  Future<void> _salva() async {
    setState(() => _salvataggio = true);
    try {
      await apiDi(context).put('/api/v1/ente/rag', {
        'url': _url.text.trim(),
        if (_chiave.text.trim().isNotEmpty) 'chiave': _chiave.text.trim(),
      });
      if (!mounted) return;
      mostraMessaggio(context, 'Collegamento al RAG salvato');
      _esitoProva = null;
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _salvataggio = false);
    }
  }

  Future<void> _prova() async {
    try {
      final r = await apiDi(context).post('/api/v1/ente/rag/prova') as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _provaRiuscita = r['esito'] == 'OK';
        final topics = [for (final t in r['topics'] as List? ?? const []) '${t['id']}'];
        _esitoProva = _provaRiuscita
            ? 'Collegamento riuscito. Topic consultabili: ${topics.isEmpty ? 'nessuno' : topics.join(', ')}'
            : '${r['messaggio']}';
      });
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Future<void> _togli() async {
    if (!await conferma(context, 'Togliere il collegamento al RAG?',
        'L\'assistente non potrà più ricevere documenti allegati.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('/api/v1/ente/rag');
      if (!mounted) return;
      _esitoProva = null;
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Caricamento<Map<String, dynamic>>(
      future: _dati,
      riprova: _carica,
      builder: (context, dati) {
        final configurato = dati['chiave_impostata'] == true;
        final colori = Theme.of(context).colorScheme;
        return ListView(padding: const EdgeInsets.all(16), children: [
          Sezione(
            titolo: 'Collegamento al RAG',
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Text('Il RAG converte in testo i documenti allegati all\'assistente, anche le scansioni. '
                  'La chiave la rilascia chi gestisce il RAG e determina i topic che l\'ente può consultare.'),
              const SizedBox(height: 12),
              TextField(
                controller: _url,
                decoration: const InputDecoration(
                  labelText: 'Indirizzo dell\'API',
                  hintText: 'https://rag.ente.it/api',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _chiave,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: 'Chiave',
                  helperText: configurato
                      ? 'Una chiave è già salvata: lascia vuoto per mantenerla'
                      : 'Salvata cifrata: non si potrà rileggere',
                ),
              ),
              const SizedBox(height: 12),
              Wrap(spacing: 8, runSpacing: 8, children: [
                FilledButton.icon(
                  onPressed: _salvataggio ? null : _salva,
                  icon: const Icon(Icons.save),
                  label: const Text('Salva'),
                ),
                if (configurato) ...[
                  OutlinedButton.icon(onPressed: _prova, icon: const Icon(Icons.wifi_tethering), label: const Text('Prova')),
                  TextButton.icon(
                    onPressed: _togli,
                    icon: const IconaElimina(),
                    label: const Text('Togli il collegamento'),
                  ),
                ],
              ]),
              if (_esitoProva != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(_esitoProva!, style: TextStyle(color: _provaRiuscita ? colori.primary : colori.error)),
                ),
            ]),
          ),
        ]);
      },
    );
  }
}
