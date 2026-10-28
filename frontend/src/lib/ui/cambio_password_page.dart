import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../stato/auth_state.dart';

/// Primo accesso con una password iniziale (l'admin di un nuovo ente, o un utente a cui
/// l'amministratore ha dato o reimpostato la password): prima di usare l'app va scelta una
/// password propria. L'API non accetta altre operazioni finché non è cambiata.
class CambioPasswordPage extends StatefulWidget {
  const CambioPasswordPage({super.key});

  @override
  State<CambioPasswordPage> createState() => _CambioPasswordPageState();
}

class _CambioPasswordPageState extends State<CambioPasswordPage> {
  final _form = GlobalKey<FormState>();
  final _attuale = TextEditingController();
  final _nuova = TextEditingController();
  final _ripeti = TextEditingController();
  bool _inCorso = false;
  String? _errore;

  @override
  void dispose() {
    _attuale.dispose();
    _nuova.dispose();
    _ripeti.dispose();
    super.dispose();
  }

  Future<void> _cambia() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _inCorso = true;
      _errore = null;
    });
    try {
      await context.read<AuthState>().cambiaPassword(_attuale.text, _nuova.text);
    } catch (e) {
      if (mounted) setState(() => _errore = e.toString());
    } finally {
      if (mounted) setState(() => _inCorso = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final utente = context.watch<AuthState>().utente!;
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Card(
              margin: const EdgeInsets.all(24),
              child: Padding(
                padding: const EdgeInsets.all(32),
                child: Form(
                  key: _form,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Icon(Icons.lock_reset, size: 48, color: tema.colorScheme.primary),
                      const SizedBox(height: 12),
                      Text('Scegli la tua password', textAlign: TextAlign.center, style: tema.textTheme.headlineSmall),
                      Text(utente.ente.nome, textAlign: TextAlign.center, style: tema.textTheme.titleMedium),
                      const SizedBox(height: 8),
                      Text(
                        'Stai usando una password iniziale (utente ${utente.username}): prima di '
                        'continuare scegline una tua.',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: _attuale,
                        obscureText: true,
                        decoration: const InputDecoration(labelText: 'Password attuale', prefixIcon: Icon(Icons.lock_open)),
                        validator: (v) => (v == null || v.isEmpty) ? 'Inserire la password attuale' : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _nuova,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Nuova password',
                          helperText: 'Almeno 10 caratteri, con lettere e numeri o simboli',
                          prefixIcon: Icon(Icons.lock),
                        ),
                        validator: (v) => (v == null || v.isEmpty) ? 'Inserire la nuova password' : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _ripeti,
                        obscureText: true,
                        decoration: const InputDecoration(labelText: 'Ripeti la nuova password', prefixIcon: Icon(Icons.lock)),
                        validator: (v) => v != _nuova.text ? 'Le due password non coincidono' : null,
                        onFieldSubmitted: (_) => _cambia(),
                      ),
                      if (_errore != null) ...[
                        const SizedBox(height: 12),
                        Text(_errore!, style: TextStyle(color: tema.colorScheme.error)),
                      ],
                      const SizedBox(height: 20),
                      FilledButton(
                        onPressed: _inCorso ? null : _cambia,
                        child: _inCorso
                            ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Text('Cambia e continua'),
                      ),
                      TextButton(
                        onPressed: () => context.read<AuthState>().logout(),
                        child: const Text('Esci'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
