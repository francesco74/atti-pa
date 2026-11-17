import 'package:flutter/material.dart';

import '../stato/auth_state.dart';
import 'comuni.dart';

/// A cosa serve ogni voce del menu (per le schede "I tuoi moduli").
const _descrizioni = {
  'Le mie bozze': 'Redazione degli atti guidata dai modelli, con la verifica sulle schede di controllo.',
  'Libreria normativa': 'Le norme citate negli atti, aggiornate da Normattiva.',
  'Controllo atti': 'Controllo successivo di regolarità amministrativa degli atti, con le schede di controllo.',
  'Modelli e checklist': 'Modelli di atto, specificità e schede di controllo dell\'ente.',
  'Trasparenza': 'Verifica dei dati pubblicati in Amministrazione Trasparente.',
  'Anticorruzione': 'Mappatura dei processi, valutazione dei rischi, misure, proposte e monitoraggio.',
  'Performance': 'Obiettivi del PIAO per struttura, con azioni, misure, indicatori e avanzamento.',
  'Assistente': 'Scrive e rivede testi, riassume e risponde sui documenti che carichi.',
  'Ricerche e feedback': 'Cosa cercano gli utenti e i cittadini, e i loro giudizi.',
  'Amministrazione': 'Utenti, strutture, accesso e configurazione dell\'ente.',
};

/// Pagina iniziale dopo l'accesso: saluto, messaggio dell'amministratore dell'ente, le cose da
/// fare per l'utente (con la voce del menu dove si fanno) e i moduli a cui ha accesso.
class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.utente, required this.moduli, required this.onApri});

  final Utente utente;
  final List<(String, IconData)> moduli; // voci del menu (etichetta, icona), senza la Home
  final ValueChanged<String> onApri; // apre la voce del menu con quell'etichetta

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late Future<Map<String, dynamic>> _home;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        // senza moduli non c'è niente da chiedere
        _home = widget.moduli.isEmpty
            ? Future.value(const {'da_fare': <dynamic>[]})
            : apiDi(context).get('/api/v1/home').then((v) => v as Map<String, dynamic>);
      });

  static String _saluto(DateTime ora) => ora.hour < 13 ? 'Buongiorno' : (ora.hour < 18 ? 'Buon pomeriggio' : 'Buonasera');

  IconData _icona(String voce) => widget.moduli.where((m) => m.$1 == voce).firstOrNull?.$2 ?? Icons.arrow_forward;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final u = widget.utente;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('${_saluto(DateTime.now())}, ${u.nomeCompleto}', style: tema.textTheme.headlineSmall),
      Text([u.ente.nome, ?u.ufficio].join(' · '), style: tema.textTheme.bodyMedium?.copyWith(color: tema.colorScheme.onSurfaceVariant)),
      const SizedBox(height: 16),
      if (widget.moduli.isEmpty)
        const Text('Nessun modulo abilitato per il tuo ente o per i tuoi ruoli: rivolgiti all\'amministratore.')
      else
        Caricamento<Map<String, dynamic>>(
          future: _home,
          riprova: _carica,
          builder: (context, home) {
            final daFare = (home['da_fare'] as List).cast<Map<String, dynamic>>();
            final messaggio = home['benvenuto'] as String?;
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (messaggio != null && messaggio.trim().isNotEmpty)
                Card(
                  color: tema.colorScheme.secondaryContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Icon(Icons.campaign_outlined, color: tema.colorScheme.onSecondaryContainer),
                      const SizedBox(width: 12),
                      Expanded(child: TestoAssistenza(messaggio, stile: TextStyle(color: tema.colorScheme.onSecondaryContainer))),
                    ]),
                  ),
                ),
              Sezione(
                titolo: 'Da fare',
                child: daFare.isEmpty
                    ? const Text('Niente in sospeso.')
                    : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        for (final v in daFare)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: Icon(_icona(v['voce'] as String)),
                            title: Text('${v['testo']}'),
                            subtitle: Text([v['voce'], ?v['dove']].join(' › ')),
                            trailing: const Icon(Icons.chevron_right),
                            onTap: () => widget.onApri(v['voce'] as String),
                          ),
                      ]),
              ),
            ]);
          },
        ),
      if (widget.moduli.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text('I tuoi moduli', style: tema.textTheme.titleMedium),
        const SizedBox(height: 8),
        Wrap(spacing: 12, runSpacing: 12, children: [
          for (final (etichetta, icona) in widget.moduli)
            SizedBox(
              width: 300,
              child: Card(
                child: InkWell(
                  onTap: () => widget.onApri(etichetta),
                  borderRadius: BorderRadius.circular(12),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Icon(icona, color: tema.colorScheme.primary),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(etichetta, style: tema.textTheme.titleSmall),
                          if (_descrizioni[etichetta] case final d?) Text(d, style: tema.textTheme.bodySmall),
                        ]),
                      ),
                    ]),
                  ),
                ),
              ),
            ),
        ]),
      ],
    ]);
  }
}
