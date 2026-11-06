import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../stato/auth_state.dart';
import 'comuni.dart';

/// Accesso all'ente del dominio: con l'account di dominio (Active Directory dell'ente) o con
/// un utente dell'applicazione, secondo come l'ente è configurato.
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
  bool _passwordVisibile = false;
  String? _errore;

  Map<String, dynamic>? _ente; // risposta di /auth/ente
  String _modo = 'locale';

  @override
  void initState() {
    super.initState();
    _caricaEnte();
  }

  Future<void> _caricaEnte() async {
    ApiClient? api;
    try {
      api = context.read<ApiClient>();
    } catch (_) {
      return; // senza API (es. nei test della sola pagina)
    }
    try {
      final e = await api.enteDelDominio();
      if (!mounted) return;
      setState(() {
        _ente = e;
        _modo = e['accesso_ldap'] == true ? 'ldap' : 'locale';
      });
    } catch (_) {}
  }

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
      await context.read<AuthState>().login(_username.text.trim(), _password.text, modo: _modo);
    } catch (e) {
      setState(() => _errore = e.toString());
    } finally {
      if (mounted) setState(() => _inCorso = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final ente = _ente?['ente'] as Map<String, dynamic>?;
    final ldap = _ente?['accesso_ldap'] == true;
    final locale = _ente == null || _ente!['accesso_locale'] == true;
    final dominioLdap = _ente?['dominio_ldap'] as String?;
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
                  child: AutofillGroup(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Icon(Icons.gavel, size: 48, color: tema.colorScheme.primary),
                        const SizedBox(height: 12),
                        Text(
                          'Atti PA',
                          textAlign: TextAlign.center,
                          style: tema.textTheme.headlineSmall,
                        ),
                        if (ente != null)
                          Text(
                            ente['nome'] as String,
                            textAlign: TextAlign.center,
                            style: tema.textTheme.titleMedium,
                          )
                        else if (_ente != null) ...[
                          const SizedBox(height: 16),
                          Text(
                            'Questo indirizzo (${_ente!['dominio']}) non è associato a un ente. '
                            'Usa l\'indirizzo del tuo ente.',
                            textAlign: TextAlign.center,
                            style: tema.textTheme.bodyMedium,
                          ),
                        ],
                        if (_ente == null || ente != null) ...[
                        const SizedBox(height: 16),
                        if (ldap && locale)
                          SegmentedButton<String>(
                            segments: const [
                              ButtonSegment(value: 'ldap', label: Text('Account di dominio')),
                              ButtonSegment(value: 'locale', label: Text('Utente dell\'app')),
                            ],
                            selected: {_modo},
                            onSelectionChanged: (s) => setState(() => _modo = s.first),
                          ),
                        const SizedBox(height: 8),
                        Text(
                          _modo == 'ldap'
                              ? 'Accedi con le credenziali di rete${dominioLdap != null ? ' ($dominioLdap)' : ''}'
                              : 'Accedi con l\'utente e la password dell\'applicazione',
                          textAlign: TextAlign.center,
                          style: tema.textTheme.bodyMedium,
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: _username,
                          autofillHints: const [AutofillHints.username],
                          decoration: const InputDecoration(
                            labelText: 'Nome utente',
                            prefixIcon: Icon(Icons.person),
                          ),
                          validator: (v) =>
                              (v == null || v.trim().isEmpty) ? 'Inserire il nome utente' : null,
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _password,
                          obscureText: !_passwordVisibile,
                          autofillHints: const [AutofillHints.password],
                          decoration: InputDecoration(
                            labelText: 'Password',
                            prefixIcon: const Icon(Icons.lock),
                            suffixIcon: IconButton(
                              tooltip: _passwordVisibile ? 'Nascondi la password' : 'Mostra la password',
                              icon: Icon(_passwordVisibile ? Icons.visibility_off : Icons.visibility),
                              onPressed: () => setState(() => _passwordVisibile = !_passwordVisibile),
                            ),
                          ),
                          validator: (v) =>
                              (v == null || v.isEmpty) ? 'Inserire la password' : null,
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
                                  height: 20,
                                  width: 20,
                                  child: CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Text('Accedi'),
                        ),
                        ],
                        if ((ente?['assistenza'] as String?)?.trim().isNotEmpty ?? false) ...[
                          const SizedBox(height: 24),
                          Text('Serve aiuto?', textAlign: TextAlign.center, style: tema.textTheme.titleSmall),
                          const SizedBox(height: 4),
                          TestoAssistenza(
                            (ente!['assistenza'] as String).trim(),
                            stile: tema.textTheme.bodyMedium,
                            allineamento: TextAlign.center,
                          ),
                        ],
                      ],
                    ),
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
