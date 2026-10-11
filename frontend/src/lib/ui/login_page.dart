import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../stato/auth_state.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _form = GlobalKey<FormState>();
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _inCorso = false;
  String? _errore;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _accedi() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _inCorso = true;
      _errore = null;
    });
    try {
      await context.read<AuthState>().login(_username.text.trim(), _password.text);
    } catch (e) {
      setState(() => _errore = e.toString());
    } finally {
      if (mounted) setState(() => _inCorso = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 400),
          child: Card(
            margin: const EdgeInsets.all(24),
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Form(
                key: _form,
                child: AutofillGroup(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Icon(Icons.gavel, size: 48, color: tema.colorScheme.primary),
                      const SizedBox(height: 12),
                      Text('Atti PA', textAlign: TextAlign.center, style: tema.textTheme.headlineSmall),
                      Text('Accedi con le credenziali di rete',
                          textAlign: TextAlign.center, style: tema.textTheme.bodyMedium),
                      const SizedBox(height: 24),
                      TextFormField(
                        controller: _username,
                        autofillHints: const [AutofillHints.username],
                        decoration: const InputDecoration(
                            labelText: 'Nome utente', prefixIcon: Icon(Icons.person)),
                        validator: (v) =>
                            (v == null || v.trim().isEmpty) ? 'Inserire il nome utente' : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _password,
                        obscureText: true,
                        autofillHints: const [AutofillHints.password],
                        decoration: const InputDecoration(
                            labelText: 'Password', prefixIcon: Icon(Icons.lock)),
                        validator: (v) => (v == null || v.isEmpty) ? 'Inserire la password' : null,
                        onFieldSubmitted: (_) => _accedi(),
                      ),
                      if (_errore != null) ...[
                        const SizedBox(height: 12),
                        Text(_errore!, style: TextStyle(color: tema.colorScheme.error)),
                      ],
                      const SizedBox(height: 20),
                      FilledButton(
                        onPressed: _inCorso ? null : _accedi,
                        child: _inCorso
                            ? const SizedBox(
                                height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Text('Accedi'),
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
