import 'package:flutter/material.dart';

import '../comuni.dart';
import 'strutture.dart';

const _etichetteRuoli = {
  'REDATTORE': 'Redattore',
  'CONTROLLORE': 'Controllore',
  'GESTORE_MODELLI': 'Gestore dei modelli',
  'TRASPARENZA': 'Operatore della trasparenza',
  'ANTICORRUZIONE_REFERENTE': 'Referente / dirigente anticorruzione',
  'ANTICORRUZIONE_RPCT': 'RPCT e staff anticorruzione',
  'PERFORMANCE_RESPONSABILE': 'Dirigente / responsabile (performance)',
  'PERFORMANCE_AMMINISTRATORE': 'Amministratore della performance',
  'ANALISI_RICERCHE': 'Analisi delle ricerche e dei feedback',
  'ADMIN': 'Amministratore dell\'ente',
};

String etichettaRuolo(String r) => _etichetteRuoli[r] ?? r;

/// Modi di accesso dell'ente: utenti dell'app e/o Active Directory dell'ente (URL, dominio,
/// certificato della CA, gruppi che danno i ruoli), con la prova su un account reale.
class AccessoEntePage extends StatefulWidget {
  const AccessoEntePage({super.key});

  @override
  State<AccessoEntePage> createState() => _AccessoEntePageState();
}

class _AccessoEntePageState extends State<AccessoEntePage> {
  late Future<Map<String, dynamic>> _dati;
  bool _locale = true;
  bool _ldapAttivo = false;
  bool _verifica = true;
  final _url = TextEditingController();
  final _dominio = TextEditingController();
  final _baseDn = TextEditingController();
  final _ca = TextEditingController();
  final _timeout = TextEditingController(text: '10');
  final Map<String, TextEditingController> _gruppi = {};
  List<String> _ruoli = const [];
  bool _salvataggio = false;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  @override
  void dispose() {
    for (final c in [_url, _dominio, _baseDn, _ca, _timeout, ..._gruppi.values]) {
      c.dispose();
    }
    super.dispose();
  }

  void _carica() {
    setState(() {
      _dati = apiDi(context).get('/api/v1/ente/accesso').then((v) {
        final d = v as Map<String, dynamic>;
        final ldap = d['ldap'] as Map<String, dynamic>?;
        final predefiniti = Map<String, dynamic>.from(d['gruppi_predefiniti'] as Map);
        final gruppi = Map<String, dynamic>.from((ldap?['gruppi'] as Map?) ?? predefiniti);
        _ruoli = List<String>.from(d['ruoli'] as List);
        _locale = d['accesso_locale'] == true;
        _ldapAttivo = ldap != null;
        _url.text = ldap?['url'] as String? ?? 'ldaps://';
        _dominio.text = ldap?['dominio'] as String? ?? '';
        _baseDn.text = ldap?['base_dn'] as String? ?? '';
        _ca.text = ldap?['ca_pem'] as String? ?? '';
        _verifica = ldap?['verifica_certificato'] != false;
        _timeout.text = '${ldap?['timeout'] ?? 10}';
        for (final r in _ruoli) {
          _gruppi.putIfAbsent(r, TextEditingController.new).text = gruppi[r]?.toString() ?? '';
        }
        return d;
      });
    });
  }

  Map<String, dynamic> _configLdap() => {
    'url': _url.text.trim(),
    'dominio': _dominio.text.trim(),
    'base_dn': _baseDn.text.trim(),
    'ca_pem': _ca.text.trim().isEmpty ? null : _ca.text.trim(),
    'verifica_certificato': _verifica,
    'timeout': int.tryParse(_timeout.text.trim()) ?? 10,
    'gruppi': {for (final r in _ruoli) r: _gruppi[r]!.text.trim()},
  };

  Future<void> _salva() async {
    setState(() => _salvataggio = true);
    try {
      await apiDi(
        context,
      ).put('/api/v1/ente/accesso', {'accesso_locale': _locale, 'ldap': _ldapAttivo ? _configLdap() : null});
      if (mounted) mostraMessaggio(context, 'Accesso dell\'ente salvato');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    } finally {
      if (mounted) setState(() => _salvataggio = false);
    }
  }

  Future<void> _prova() async {
    final utente = TextEditingController();
    final password = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Prova Active Directory'),
        content: SizedBox(
          width: 380,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('Usa la configurazione scritta qui sopra, anche se non è ancora salvata.'),
              TextField(
                controller: utente,
                decoration: const InputDecoration(labelText: 'Utente di dominio'),
              ),
              TextField(
                controller: password,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Password'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Prova')),
        ],
      ),
    );
    final credenziali = (utente.text.trim(), password.text);
    utente.dispose();
    password.dispose();
    if (ok != true || !mounted) return;
    try {
      final r =
          await apiDi(context).post('/api/v1/ente/accesso/prova', {
                'ldap': _configLdap(),
                'username': credenziali.$1,
                'password': credenziali.$2,
              })
              as Map<String, dynamic>;
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(r['esito'] == 'OK' ? 'Accesso riuscito' : 'Accesso non riuscito'),
          content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
              child: r['esito'] != 'OK'
                  ? Text(r['messaggio'].toString())
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${r['nome'] ?? r['utente']}'),
                        const SizedBox(height: 8),
                        Text(
                          (r['ruoli'] as List).isEmpty
                              ? 'Nessun ruolo: l\'utente non è in nessuno dei gruppi indicati e non potrebbe accedere.'
                              : 'Ruoli: ${(r['ruoli'] as List).map((x) => etichettaRuolo(x.toString())).join(', ')}',
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(height: 8),
                        const Text('Gruppi letti da Active Directory:'),
                        for (final g in r['gruppi'] as List)
                          SelectableText(g.toString(), style: Theme.of(c).textTheme.bodySmall),
                      ],
                    ),
            ),
          ),
          actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
        ),
      );
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  Widget _campo(String etichetta, TextEditingController c, {String? aiuto, int righe = 1}) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      controller: c,
      minLines: righe,
      maxLines: righe == 1 ? 1 : null,
      decoration: InputDecoration(
        labelText: etichetta,
        helperText: aiuto,
        helperMaxLines: 3,
        border: const OutlineInputBorder(),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    return Caricamento<Map<String, dynamic>>(
      future: _dati,
      riprova: _carica,
      builder: (context, _) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Sezione(
            titolo: 'Modi di accesso',
            child: Column(
              children: [
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Utenti dell\'applicazione'),
                  subtitle: const Text(
                    'Utente e password gestiti qui (scheda Utenti), per chi non è in Active Directory',
                  ),
                  value: _locale,
                  onChanged: (v) => setState(() => _locale = v),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Active Directory dell\'ente'),
                  subtitle: const Text('Credenziali di rete; i ruoli vengono dai gruppi, a ogni accesso'),
                  value: _ldapAttivo,
                  onChanged: (v) => setState(() => _ldapAttivo = v),
                ),
              ],
            ),
          ),
          if (_ldapAttivo)
            Sezione(
              titolo: 'Active Directory',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _campo('Indirizzo del server', _url, aiuto: 'Es. ldaps://dc.ente.local (ldaps: connessione cifrata)'),
                  _campo('Dominio', _dominio, aiuto: 'Per l\'accesso come utente@dominio, es. ente.local'),
                  _campo('Base DN', _baseDn, aiuto: 'Dove cercare gli utenti, es. DC=ente,DC=local'),
                  _campo(
                    'Certificato della CA (PEM)',
                    _ca,
                    righe: 4,
                    aiuto:
                        'Certificato dell\'autorità che ha firmato quello del domain controller, da '
                        '-----BEGIN CERTIFICATE----- a -----END CERTIFICATE-----. Vuoto: CA di sistema.',
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Verifica il certificato del server'),
                    subtitle: const Text(
                      'Disattivare solo per prove: senza verifica non è garantito di parlare con il vero domain controller',
                    ),
                    value: _verifica,
                    onChanged: (v) => setState(() => _verifica = v),
                  ),
                  _campo('Attesa massima (secondi)', _timeout),
                  const SizedBox(height: 8),
                  Text('Gruppi che danno i ruoli', style: Theme.of(context).textTheme.titleSmall),
                  const Text('Nome del gruppo (CN) o DN completo. Vuoto: il ruolo non si ottiene da Active Directory.'),
                  const SizedBox(height: 8),
                  for (final r in _ruoli) _campo(etichettaRuolo(r), _gruppi[r]!),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: OutlinedButton.icon(
                      onPressed: _prova,
                      icon: const Icon(Icons.science_outlined),
                      label: const Text('Prova con un account'),
                    ),
                  ),
                ],
              ),
            ),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.icon(
              onPressed: _salvataggio ? null : _salva,
              icon: const Icon(Icons.save),
              label: const Text('Salva'),
            ),
          ),
        ],
      ),
    );
  }
}

/// Utenti dell'ente: quelli di Active Directory compaiono dopo il primo accesso (ruoli dai
/// gruppi); quelli dell'app si creano qui, con ruoli e password.
class UtentiEntePage extends StatefulWidget {
  const UtentiEntePage({super.key});

  @override
  State<UtentiEntePage> createState() => _UtentiEntePageState();
}

class _UtentiEntePageState extends State<UtentiEntePage> {
  late Future<List<dynamic>> _utenti;
  List<Map<String, dynamic>> _strutture = const [];

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
    final api = apiDi(context);
    _utenti = Future.wait([api.get('/api/v1/ente/utenti'), api.get('/api/v1/ente/strutture')]).then((v) {
      _strutture = (v[1] as List).cast<Map<String, dynamic>>();
      return v[0] as List;
    });
  });

  String? _struttura(Object? id) {
    for (final s in _strutture) {
      if (s['id'] == id) return s['codice'] as String;
    }
    return null;
  }

  Future<void> _modifica([Map<String, dynamic>? u]) async {
    final nuovo = u == null;
    final locale = nuovo || u['origine'] == 'LOCALE';
    final username = TextEditingController(text: u?['username'] as String? ?? '');
    final nome = TextEditingController(text: u?['nome_completo'] as String? ?? '');
    final email = TextEditingController(text: u?['email'] as String? ?? '');
    final password = TextEditingController();
    final ruoli = <String>{
      ...List<String>.from(u?['ruoli'] as List? ?? const ['REDATTORE']),
    };
    var attivo = u?['attivo'] != false;
    var strutturaId = u?['struttura_id'] as String?;
    final api = apiDi(context);

    // il salvataggio avviene dentro la finestra: se il server rifiuta, la finestra resta aperta
    // con i dati scritti e l'errore
    Future<void> salva() async {
      final nomeCompleto = nome.text.trim().isEmpty ? null : nome.text.trim();
      final mail = email.text.trim().isEmpty ? null : email.text.trim();
      if (nuovo) {
        await api.post('/api/v1/ente/utenti', {
          'username': username.text.trim(),
          'nome_completo': nomeCompleto,
          'email': mail,
          'password': password.text,
          'ruoli': ruoli.toList(),
          'struttura_id': strutturaId,
        });
      } else {
        await api.put('/api/v1/ente/utenti/${u['id']}', {
          'nome_completo': nomeCompleto,
          'email': mail,
          'ruoli': locale ? ruoli.toList() : null,
          'attivo': attivo,
          'struttura_id': strutturaId,
        });
      }
    }

    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => _FinestraSalvataggio(
        titolo: nuovo ? 'Nuovo utente dell\'app' : 'Utente ${u['username']}',
        azione: 'Salva',
        campi: [username, nome, email, password],
        controlla: () => nuovo
            ? (username.text.trim().isEmpty ? 'Inserire il nome utente.' : erroreNuovaPassword(password.text))
            : null,
        salva: salva,
        contenuto: (aggiorna) => [
          if (nuovo)
            TextField(
              controller: username,
              decoration: const InputDecoration(labelText: 'Nome utente'),
            ),
          if (!locale)
            const Padding(
              padding: EdgeInsets.only(bottom: 8),
              child: Text('Utente di Active Directory: nome e ruoli vengono dal dominio a ogni accesso.'),
            ),
          if (locale) ...[
            TextField(
              controller: nome,
              decoration: const InputDecoration(labelText: 'Nome e cognome'),
            ),
            TextField(
              controller: email,
              decoration: const InputDecoration(labelText: 'Email'),
            ),
            if (nuovo)
              _CampoPassword(
                controller: password,
                etichetta: 'Password iniziale',
                aggiorna: aggiorna,
                aiuto:
                    'Almeno 10 caratteri, con lettere e numeri o simboli. '
                    'L\'utente la cambierà al primo accesso.',
              ),
            const SizedBox(height: 12),
            const Text('Ruoli'),
            for (final r in _etichetteRuoli.keys)
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(etichettaRuolo(r)),
                value: ruoli.contains(r),
                onChanged: (v) => aggiorna(() => v == true ? ruoli.add(r) : ruoli.remove(r)),
              ),
          ],
          const SizedBox(height: 8),
          SceltaStruttura(
            strutture: _strutture,
            valore: strutturaId,
            etichetta: 'Struttura organizzativa',
            onChanged: (v) => aggiorna(() => strutturaId = v),
          ),
          if (!nuovo)
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Attivo'),
              subtitle: const Text('Un utente disattivato non accede e le sue sessioni si chiudono'),
              value: attivo,
              onChanged: (v) => aggiorna(() => attivo = v),
            ),
        ],
      ),
    );
    if (ok == true && mounted) _carica();
  }

  Future<void> _reimpostaPassword(Map<String, dynamic> u) async {
    final password = TextEditingController();
    final api = apiDi(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => _FinestraSalvataggio(
        titolo: 'Nuova password per ${u['username']}',
        azione: 'Imposta',
        campi: [password],
        controlla: () => erroreNuovaPassword(password.text),
        salva: () => api.put('/api/v1/ente/utenti/${u['id']}/password', {'password': password.text}),
        contenuto: (aggiorna) => [
          _CampoPassword(
            controller: password,
            etichetta: 'Nuova password',
            aggiorna: aggiorna,
            aiuto:
                'Almeno 10 caratteri, con lettere e numeri o simboli. Le sessioni aperte '
                'dell\'utente si chiudono e al prossimo accesso dovrà sceglierne una propria.',
          ),
        ],
      ),
    );
    if (ok == true && mounted) mostraMessaggio(context, 'Password reimpostata');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'utenti',
        onPressed: () => _modifica(),
        icon: const Icon(Icons.person_add),
        label: const Text('Nuovo utente dell\'app'),
      ),
      body: Caricamento<List<dynamic>>(
        future: _utenti,
        riprova: _carica,
        builder: (context, lista) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 88),
          children: [
            if (lista.isEmpty) const Text('Nessun utente.'),
            for (final u in lista.cast<Map<String, dynamic>>())
              Card(
                child: ListTile(
                  leading: Icon(
                    u['origine'] == 'LOCALE' ? Icons.person : Icons.badge_outlined,
                    color: u['attivo'] == true ? null : Theme.of(context).disabledColor,
                  ),
                  title: Text('${u['nome_completo'] ?? u['username']}${u['attivo'] == true ? '' : ' (disattivato)'}'),
                  subtitle: Text(
                    [
                      u['username'],
                      u['origine'] == 'LOCALE' ? 'utente dell\'app' : 'Active Directory',
                      (u['ruoli'] as List).map((r) => etichettaRuolo(r.toString())).join(', '),
                      ?_struttura(u['struttura_id']),
                      if (u['ultimo_accesso'] != null) 'ultimo accesso ${formatData(u['ultimo_accesso'])}',
                    ].join(' · '),
                  ),
                  trailing: u['origine'] == 'LOCALE'
                      ? IconButton(
                          tooltip: 'Reimposta la password',
                          icon: const Icon(Icons.key),
                          onPressed: () => _reimpostaPassword(u),
                        )
                      : null,
                  onTap: () => _modifica(u),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Errore della nuova password con le stesse regole del server (auth/password.py), così lo
/// si vede subito; il server resta il controllo definitivo.
String? erroreNuovaPassword(String password) {
  if (password.length < 10) return 'La password deve avere almeno 10 caratteri.';
  if (RegExp(r'^\p{L}+$', unicode: true).hasMatch(password) || RegExp(r'^\d+$').hasMatch(password)) {
    return 'La password deve contenere sia lettere sia numeri o simboli.';
  }
  return null;
}

/// Campo password che segnala il problema mentre si scrive (dopo il primo carattere).
class _CampoPassword extends StatelessWidget {
  const _CampoPassword({
    required this.controller,
    required this.etichetta,
    required this.aiuto,
    required this.aggiorna,
  });

  final TextEditingController controller;
  final String etichetta;
  final String aiuto;
  final void Function(VoidCallback) aggiorna;

  @override
  Widget build(BuildContext context) {
    final errore = controller.text.isEmpty ? null : erroreNuovaPassword(controller.text);
    return TextField(
      controller: controller,
      obscureText: true,
      onChanged: (_) => aggiorna(() {}),
      decoration: InputDecoration(
        labelText: etichetta,
        helperText: aiuto,
        helperMaxLines: 3,
        errorText: errore,
        errorMaxLines: 2,
      ),
    );
  }
}

/// Finestra che salva prima di chiudersi: durante l'invio i pulsanti sono disattivati; se il
/// controllo locale o il server danno errore, la finestra resta aperta con i dati e il messaggio
/// (annunciato ai lettori di schermo). Si chiude con `true` solo a salvataggio riuscito.
class _FinestraSalvataggio extends StatefulWidget {
  const _FinestraSalvataggio({
    required this.titolo,
    required this.azione,
    required this.contenuto,
    required this.salva,
    required this.campi,
    this.controlla,
  });

  final String titolo;
  final String azione;
  final List<Widget> Function(void Function(VoidCallback) aggiorna) contenuto;
  final Future<void> Function() salva;
  final String? Function()? controlla;

  /// Controller dei campi, chiusi con la finestra (dopo l'animazione di chiusura).
  final List<TextEditingController> campi;

  @override
  State<_FinestraSalvataggio> createState() => _FinestraSalvataggioState();
}

class _FinestraSalvataggioState extends State<_FinestraSalvataggio> {
  bool _invio = false;
  String? _errore;

  @override
  void dispose() {
    for (final c in widget.campi) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _conferma() async {
    final locale = widget.controlla?.call();
    if (locale != null) {
      setState(() => _errore = locale);
      return;
    }
    setState(() {
      _invio = true;
      _errore = null;
    });
    try {
      await widget.salva();
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _invio = false;
          _errore = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colori = Theme.of(context).colorScheme;
    return AlertDialog(
      title: Text(widget.titolo),
      content: SizedBox(
        width: 440,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ...widget.contenuto(setState),
              if (_errore != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Semantics(
                    liveRegion: true,
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        ExcludeSemantics(child: Icon(Icons.error_outline, color: colori.error)),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(_errore!, style: TextStyle(color: colori.error)),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: _invio ? null : () => Navigator.pop(context, false), child: const Text('Annulla')),
        FilledButton(
          onPressed: _invio ? null : _conferma,
          child: _invio
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, semanticsLabel: 'Salvataggio in corso'),
                )
              : Text(widget.azione),
        ),
      ],
    );
  }
}
