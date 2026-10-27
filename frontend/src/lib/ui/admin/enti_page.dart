import 'package:flutter/material.dart';

import '../comuni.dart';

const _etichetteModuli = {'redazione': 'Redazione e controllo degli atti'};

/// Enti dell'installazione (amministratore dell'installazione): nome, domini con cui si
/// raggiungono, moduli abilitati, primo amministratore. Per un nuovo dominio servono anche
/// il record DNS, l'host nell'Ingress e il certificato.
class EntiPage extends StatefulWidget {
  const EntiPage({super.key});

  @override
  State<EntiPage> createState() => _EntiPageState();
}

class _EntiPageState extends State<EntiPage> {
  late Future<Map<String, dynamic>> _dati;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _dati = apiDi(context).get('/api/v1/enti').then((v) => v as Map<String, dynamic>);
      });

  Future<void> _modifica(List<String> moduliDisponibili, [Map<String, dynamic>? e]) async {
    final nuovo = e == null;
    final codice = TextEditingController(text: e?['codice'] as String? ?? '');
    final nome = TextEditingController(text: e?['nome'] as String? ?? '');
    final domini = TextEditingController(text: (e?['domini'] as List? ?? const []).join('\n'));
    final moduli = <String>{...List<String>.from(e?['moduli'] as List? ?? moduliDisponibili)};
    var attivo = e?['attivo'] != false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, aggiorna) => AlertDialog(
          title: Text(nuovo ? 'Nuovo ente' : 'Ente ${e['codice']}'),
          content: SizedBox(
            width: 480,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (nuovo)
                  TextField(
                    controller: codice,
                    decoration: const InputDecoration(
                      labelText: 'Codice',
                      helperText: 'Lettere minuscole e cifre, es. comunelucca. Non si cambia più.',
                    ),
                  ),
                TextField(controller: nome, decoration: const InputDecoration(labelText: 'Nome')),
                TextField(
                  controller: domini,
                  minLines: 2,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    labelText: 'Domini (uno per riga)',
                    helperText: 'Es. comunelucca.provincia.lucca.it. Servono anche DNS, Ingress e certificato.',
                    helperMaxLines: 2,
                  ),
                ),
                const SizedBox(height: 12),
                const Text('Moduli abilitati'),
                for (final m in moduliDisponibili)
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(_etichetteModuli[m] ?? m),
                    value: moduli.contains(m),
                    onChanged: (v) => aggiorna(() => v == true ? moduli.add(m) : moduli.remove(m)),
                  ),
                if (!nuovo)
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Attivo'),
                    subtitle: const Text('Un ente disattivato non si raggiunge più dai suoi domini'),
                    value: attivo,
                    onChanged: (v) => aggiorna(() => attivo = v),
                  ),
              ]),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Salva')),
          ],
        ),
      ),
    );
    final corpo = {
      'nome': nome.text.trim(),
      'domini': domini.text.split('\n').map((d) => d.trim()).where((d) => d.isNotEmpty).toList(),
      'moduli': moduli.toList(),
      'attivo': attivo,
    };
    final cod = codice.text.trim().toLowerCase();
    for (final c in [codice, nome, domini]) {
      c.dispose();
    }
    if (ok != true || !mounted) return;
    try {
      final api = apiDi(context);
      if (nuovo) {
        await api.post('/api/v1/enti', {...corpo, 'codice': cod});
      } else {
        await api.put('/api/v1/enti/${e['id']}', corpo);
      }
      _carica();
    } catch (err) {
      if (mounted) mostraErrore(context, err);
    }
  }

  Future<void> _amministratore(Map<String, dynamic> e) async {
    final username = TextEditingController();
    final nome = TextEditingController();
    final password = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Amministratore di ${e['nome']}'),
        content: SizedBox(
          width: 420,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('Utente dell\'app con il ruolo di amministratore dell\'ente: poi configura da sé '
                'Active Directory e utenti.'),
            TextField(controller: username, decoration: const InputDecoration(labelText: 'Nome utente')),
            TextField(controller: nome, decoration: const InputDecoration(labelText: 'Nome e cognome')),
            TextField(
              controller: password,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Password iniziale', helperText: 'Almeno 10 caratteri'),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Crea')),
        ],
      ),
    );
    final corpo = {
      'username': username.text.trim(),
      'nome_completo': nome.text.trim().isEmpty ? null : nome.text.trim(),
      'password': password.text,
    };
    for (final c in [username, nome, password]) {
      c.dispose();
    }
    if (ok != true || !mounted) return;
    try {
      await apiDi(context).post('/api/v1/enti/${e['id']}/amministratori', corpo);
      _carica();
    } catch (err) {
      if (mounted) mostraErrore(context, err);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Caricamento<Map<String, dynamic>>(
      future: _dati,
      riprova: _carica,
      builder: (context, dati) {
        final moduli = List<String>.from(dati['moduli'] as List);
        final enti = (dati['enti'] as List).cast<Map<String, dynamic>>();
        return Scaffold(
          floatingActionButton: FloatingActionButton.extended(
            heroTag: 'enti',
            onPressed: () => _modifica(moduli),
            icon: const Icon(Icons.add_business),
            label: const Text('Nuovo ente'),
          ),
          body: ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 88), children: [
            if (enti.isEmpty) const Text('Nessun ente.'),
            for (final e in enti)
              Card(
                child: ListTile(
                  leading: Icon(Icons.domain, color: e['attivo'] == true ? null : Theme.of(context).disabledColor),
                  title: Text('${e['nome']}${e['attivo'] == true ? '' : ' (disattivato)'}'),
                  subtitle: Text([
                    e['codice'],
                    (e['domini'] as List).isEmpty ? 'nessun dominio' : (e['domini'] as List).join(', '),
                    'moduli: ${(e['moduli'] as List).isEmpty ? 'nessuno' : (e['moduli'] as List).map((m) => _etichetteModuli[m] ?? m).join(', ')}',
                    'accesso: ${[if (e['accesso_locale'] == true) 'utenti dell\'app', if (e['accesso_ldap'] == true) 'Active Directory'].join(' e ')}',
                    '${e['utenti']} utenti',
                    if ((e['amministratori'] as List).isNotEmpty) 'amministratori: ${(e['amministratori'] as List).join(', ')}',
                  ].join(' · ')),
                  trailing: IconButton(
                    tooltip: 'Crea un amministratore dell\'ente',
                    icon: const Icon(Icons.admin_panel_settings_outlined),
                    onPressed: () => _amministratore(e),
                  ),
                  onTap: () => _modifica(moduli, e),
                ),
              ),
          ]),
        );
      },
    );
  }
}
