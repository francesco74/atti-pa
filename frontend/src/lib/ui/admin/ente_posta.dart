import 'package:flutter/material.dart';

import '../comuni.dart';

/// Posta in uscita dell'ente: il server SMTP da cui partono le notifiche (es. le proposte
/// dell'anticorruzione al RPCT e gli esiti ai referenti). La password, salvata cifrata, non si
/// rilegge: si può solo sostituire. La prova invia un'email all'indirizzo indicato.
class PostaEntePage extends StatefulWidget {
  const PostaEntePage({super.key});

  @override
  State<PostaEntePage> createState() => _PostaEntePageState();
}

class _PostaEntePageState extends State<PostaEntePage> {
  late Future<Map<String, dynamic>> _dati;
  final _host = TextEditingController();
  final _porta = TextEditingController();
  final _utente = TextEditingController();
  final _password = TextEditingController();
  final _mittente = TextEditingController();
  final _rispondiA = TextEditingController();
  final _destinatarioProva = TextEditingController();
  String _sicurezza = 'STARTTLS';
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
    for (final c in [_host, _porta, _utente, _password, _mittente, _rispondiA, _destinatarioProva]) {
      c.dispose();
    }
    super.dispose();
  }

  void _carica() {
    setState(() {
      _dati = apiDi(context).get('/api/v1/ente/posta').then((v) {
        final d = v as Map<String, dynamic>;
        _host.text = d['host'] as String? ?? '';
        _porta.text = '${d['porta'] ?? 587}';
        _sicurezza = d['sicurezza'] as String? ?? 'STARTTLS';
        _utente.text = d['utente'] as String? ?? '';
        _mittente.text = d['mittente'] as String? ?? '';
        _rispondiA.text = d['rispondi_a'] as String? ?? '';
        _password.clear();
        return d;
      });
    });
  }

  Future<void> _salva() async {
    final porta = int.tryParse(_porta.text.trim());
    if (porta == null) {
      mostraMessaggio(context, 'La porta è un numero (di solito 587 con STARTTLS, 465 con SSL)');
      return;
    }
    setState(() => _salvataggio = true);
    try {
      await apiDi(context).put('/api/v1/ente/posta', {
        'host': _host.text.trim(),
        'porta': porta,
        'sicurezza': _sicurezza,
        'utente': _utente.text.trim().isEmpty ? null : _utente.text.trim(),
        if (_password.text.isNotEmpty) 'password': _password.text,
        'mittente': _mittente.text.trim(),
        'rispondi_a': _rispondiA.text.trim().isEmpty ? null : _rispondiA.text.trim(),
      });
      if (!mounted) return;
      mostraMessaggio(context, 'Posta in uscita salvata');
      _esitoProva = null;
      _carica();
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _salvataggio = false);
    }
  }

  Future<void> _prova() async {
    setState(() => _esitoProva = 'Invio in corso...');
    try {
      final r = await apiDi(context).post('/api/v1/ente/posta/prova', {
        if (_destinatarioProva.text.trim().isNotEmpty) 'destinatario': _destinatarioProva.text.trim(),
      }) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _provaRiuscita = r['esito'] == 'OK';
        _esitoProva = '${r['messaggio']}';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _esitoProva = null);
      mostraErrore(context, e);
    }
  }

  Future<void> _togli() async {
    if (!await conferma(context, 'Togliere la posta in uscita?', 'Le notifiche via email non verranno più inviate.')) {
      return;
    }
    if (!mounted) return;
    try {
      await apiDi(context).delete('/api/v1/ente/posta');
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
        final configurata = dati['configurata'] == true;
        final passwordSalvata = dati['password_impostata'] == true;
        final colori = Theme.of(context).colorScheme;
        return ListView(padding: const EdgeInsets.all(16), children: [
          Sezione(
            titolo: 'Posta in uscita',
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Text('Server da cui partono le notifiche via email: al RPCT quando un referente invia o '
                  'reinvia una proposta, al referente quando il RPCT la approva, la respinge o la restituisce. '
                  'Le email arrivano agli indirizzi degli utenti (Accesso → Utenti, o da Active Directory).'),
              const SizedBox(height: 12),
              Wrap(spacing: 12, runSpacing: 12, children: [
                SizedBox(
                  width: 320,
                  child: TextField(
                    controller: _host,
                    decoration: const InputDecoration(labelText: 'Server SMTP', hintText: 'smtp.ente.it'),
                  ),
                ),
                SizedBox(
                  width: 120,
                  child: TextField(
                    controller: _porta,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Porta'),
                  ),
                ),
                SizedBox(
                  width: 200,
                  child: DropdownButtonFormField<String>(
                    initialValue: _sicurezza,
                    decoration: const InputDecoration(labelText: 'Sicurezza'),
                    items: const [
                      DropdownMenuItem(value: 'STARTTLS', child: Text('STARTTLS')),
                      DropdownMenuItem(value: 'SSL', child: Text('SSL/TLS')),
                      DropdownMenuItem(value: 'NESSUNA', child: Text('Nessuna')),
                    ],
                    onChanged: (v) => setState(() => _sicurezza = v ?? 'STARTTLS'),
                  ),
                ),
              ]),
              const SizedBox(height: 12),
              Wrap(spacing: 12, runSpacing: 12, children: [
                SizedBox(
                  width: 320,
                  child: TextField(
                    controller: _utente,
                    decoration: const InputDecoration(labelText: 'Utente', helperText: 'Vuoto: senza autenticazione'),
                  ),
                ),
                SizedBox(
                  width: 320,
                  child: TextField(
                    controller: _password,
                    obscureText: true,
                    decoration: InputDecoration(
                      labelText: 'Password',
                      helperText: passwordSalvata
                          ? 'Una password è già salvata: lascia vuoto per mantenerla'
                          : 'Salvata cifrata: non si potrà rileggere',
                    ),
                  ),
                ),
              ]),
              const SizedBox(height: 12),
              Wrap(spacing: 12, runSpacing: 12, children: [
                SizedBox(
                  width: 320,
                  child: TextField(
                    controller: _mittente,
                    decoration: const InputDecoration(labelText: 'Mittente', hintText: 'Comune di ... <anticorruzione@ente.it>'),
                  ),
                ),
                SizedBox(
                  width: 320,
                  child: TextField(
                    controller: _rispondiA,
                    decoration: const InputDecoration(labelText: 'Rispondi a (facoltativo)', hintText: 'rpct@ente.it'),
                  ),
                ),
              ]),
              const SizedBox(height: 12),
              Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                FilledButton.icon(
                  onPressed: _salvataggio ? null : _salva,
                  icon: const Icon(Icons.save),
                  label: const Text('Salva'),
                ),
                if (configurata)
                  TextButton.icon(onPressed: _togli, icon: const IconaElimina(), label: const Text('Togli la posta in uscita')),
              ]),
            ]),
          ),
          if (configurata)
            Sezione(
              titolo: 'Prova',
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  SizedBox(
                    width: 320,
                    child: TextField(
                      controller: _destinatarioProva,
                      decoration: const InputDecoration(labelText: 'Invia a', helperText: 'Vuoto: il tuo indirizzo'),
                    ),
                  ),
                  OutlinedButton.icon(onPressed: _prova, icon: const Icon(Icons.send_outlined), label: const Text('Invia un\'email di prova')),
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
