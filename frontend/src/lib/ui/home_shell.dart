import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../stato/auth_state.dart';
import 'admin/admin_page.dart';
import 'comuni.dart';
import 'bozze/bozze_page.dart';
import 'controllo/controlli_page.dart';
import 'libreria/libreria_page.dart';

class _Voce {
  const _Voce(this.etichetta, this.icona, this.pagina);

  final String etichetta;
  final IconData icona;
  final Widget pagina;
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.utente});

  final Utente utente;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _indice = 0;

  /// Cambia a ogni selezione del menu: la pagina viene ricreata e ricarica i dati.
  int _generazione = 0;

  void _seleziona(int i) => setState(() {
        _indice = i;
        _generazione++;
      });

  List<_Voce> get _voci => [
        if (widget.utente.isRedattore)
          const _Voce('Le mie bozze', Icons.edit_document, BozzePage()),
        const _Voce('Libreria normativa', Icons.menu_book, LibreriaPage()),
        if (widget.utente.isControllore)
          const _Voce('Controllo atti', Icons.fact_check, ControlliPage()),
        if (widget.utente.isAdmin)
          const _Voce('Amministrazione', Icons.admin_panel_settings, AdminPage()),
      ];

  String _iniziale(String nome) => nome.isEmpty ? '?' : nome.substring(0, 1).toUpperCase();

  /// Settore e decreto di incarico dell'utente: precompilano gli atti.
  Future<void> _profilo() async {
    final ufficio = TextEditingController(text: widget.utente.ufficio ?? '');
    final decreto = TextEditingController(text: widget.utente.decretoIncarico ?? '');
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Il mio profilo'),
        content: SizedBox(
          width: 420,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(widget.utente.nomeCompleto),
              subtitle: Text(widget.utente.username),
            ),
            TextField(
              controller: ufficio,
              decoration: const InputDecoration(
                labelText: 'Settore',
                helperText: 'Usato per precompilare gli atti. Se in Active Directory è indicato il '
                    'reparto, all\'accesso viene aggiornato da lì.',
                helperMaxLines: 3,
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: decreto,
              decoration: const InputDecoration(
                labelText: 'Decreto di conferimento dell\'incarico',
                hintText: 'del Sindaco n. 12 del 3 gennaio 2026',
                helperText: 'Richiamato negli atti per la competenza ad adottarli (art. 107 TUEL).',
                helperMaxLines: 2,
              ),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Salva')),
        ],
      ),
    );
    if (ok == true && mounted) {
      try {
        await context
            .read<AuthState>()
            .aggiornaProfilo(ufficio: ufficio.text.trim(), decretoIncarico: decreto.text.trim());
        if (mounted) mostraMessaggio(context, 'Profilo aggiornato');
      } catch (e) {
        if (mounted) mostraErrore(context, e);
      }
    }
    ufficio.dispose();
    decreto.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final voci = _voci;
    final indice = _indice.clamp(0, voci.length - 1);
    final largo = MediaQuery.sizeOf(context).width >= 900;

    final menuUtente = PopupMenuButton<String>(
      tooltip: widget.utente.nomeCompleto,
      icon: CircleAvatar(child: Text(_iniziale(widget.utente.nomeCompleto))),
      itemBuilder: (_) => [
        PopupMenuItem(
          enabled: false,
          child: Text('${widget.utente.nomeCompleto}\n${widget.utente.ruoli.join(', ')}'
              '${widget.utente.ufficio != null ? '\n${widget.utente.ufficio}' : ''}'),
        ),
        const PopupMenuItem(value: 'profilo', child: Text('Il mio profilo')),
        const PopupMenuItem(value: 'esci', child: Text('Esci')),
      ],
      onSelected: (v) {
        if (v == 'esci') context.read<AuthState>().logout();
        if (v == 'profilo') _profilo();
      },
    );

    // Solo la pagina selezionata, con una chiave nuova a ogni selezione: niente dati vecchi
    final contenuto = KeyedSubtree(key: ValueKey(_generazione), child: voci[indice].pagina);

    if (largo) {
      return Scaffold(
        body: Row(children: [
          NavigationRail(
            selectedIndex: indice,
            onDestinationSelected: _seleziona,
            labelType: NavigationRailLabelType.all,
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Icon(Icons.gavel, color: Theme.of(context).colorScheme.primary, size: 32),
            ),
            trailing: Expanded(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(padding: const EdgeInsets.only(bottom: 16), child: menuUtente),
              ),
            ),
            destinations: [
              for (final v in voci)
                NavigationRailDestination(icon: Icon(v.icona), label: Text(v.etichetta)),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: contenuto),
        ]),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(voci[indice].etichetta), actions: [menuUtente]),
      body: contenuto,
      bottomNavigationBar: voci.length < 2
          ? null
          : NavigationBar(
              selectedIndex: indice,
              onDestinationSelected: _seleziona,
              destinations: [
                for (final v in voci) NavigationDestination(icon: Icon(v.icona), label: v.etichetta),
              ],
            ),
    );
  }
}
