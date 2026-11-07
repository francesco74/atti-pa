import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import 'package:provider/provider.dart';

import '../stato/auth_state.dart';
import 'admin/admin_page.dart';
import 'anticorruzione/anticorruzione_page.dart';
import 'performance/performance_page.dart';
import 'ricerche/ricerche_page.dart';
import 'assistente/assistente_page.dart';
import 'comuni.dart';
import 'configurazione/configurazione_page.dart';
import 'bozze/bozze_page.dart';
import 'controllo/controlli_page.dart';
import 'libreria/libreria_page.dart';
import 'logo_ente.dart';
import 'trasparenza/result_manager.dart';
import 'trasparenza/trasparenza_page.dart';

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

  /// Le pagine aperte dalla voce del menu (dettagli, editor): stanno nell'area dei contenuti,
  /// con il menu sempre visibile.
  _PagineAperte _pagine = _PagineAperte();

  /// La chat dell'assistente sta qui: resta cambiando voce del menu e si perde all'uscita.
  final _conversazione = ConversazioneAssistente();

  @override
  void dispose() {
    _conversazione.dispose();
    super.dispose();
  }

  Future<void> _seleziona(int i) async {
    if (!await _puoiLasciare()) return;
    setState(() {
      _indice = i;
      _generazione++;
      _pagine = _PagineAperte();
    });
  }

  /// La pagina della trasparenza può avere un documento non salvato nell'editor: quelli già
  /// salvati si aggiornano da soli, per gli altri si chiede conferma.
  Future<bool> _puoiLasciare() async {
    // una pagina aperta con modifiche da confermare (es. un editor) chiede lei cosa fare; se
    // si esce, si resta sulla voce e il menu si può cliccare di nuovo
    if (_pagine.rotte.any((r) => r.popDisposition == RoutePopDisposition.doNotPop)) {
      await _pagine.navigator?.maybePop();
      return false;
    }
    await ResultManager.salvaModifiche?.call();
    if (!(ResultManager.modificheNonSalvate?.call() ?? false) || !mounted) return true;
    return conferma(
      context,
      'Modifiche non salvate',
      'Il documento aperto nei risultati della trasparenza non è salvato: lasciando la pagina andrà perso.',
    );
  }

  List<_Voce> get _voci {
    final u = widget.utente;
    final redazione = u.modulo('redazione'); // redazione e controllo degli atti
    final trasparenza = u.modulo('trasparenza'); // verifica di Amministrazione Trasparente
    final anticorruzione = u.modulo('anticorruzione'); // mappatura dei processi e rischi corruttivi
    final performance = u.modulo('performance'); // obiettivi del PIAO per struttura
    final assistente = u.modulo('assistente'); // chat con l'LLM, per tutti gli utenti dell'ente
    // ricerche registrate e feedback: oggi ci sono solo quelle della mappatura e dei procedimenti
    final ricerche = anticorruzione && u.isAnalisiRicerche;
    return [
      if (redazione && u.isRedattore) const _Voce('Le mie bozze', Icons.edit_document, BozzePage()),
      if (redazione && (u.isRedattore || u.isControllore || u.isGestoreModelli))
        const _Voce('Libreria normativa', Icons.menu_book, LibreriaPage()),
      if (redazione && u.isControllore) const _Voce('Controllo atti', Icons.fact_check, ControlliPage()),
      if (redazione && u.isGestoreModelli)
        const _Voce('Modelli e checklist', Icons.architecture, ConfigurazionePage()),
      if (trasparenza && u.isTrasparenza) const _Voce('Trasparenza', Icons.visibility_outlined, TrasparenzaPage()),
      if (anticorruzione && u.isAnticorruzione)
        const _Voce('Anticorruzione', Icons.shield_outlined, AnticorruzionePage()),
      if (performance && u.isPerformance) const _Voce('Performance', Icons.flag_outlined, PerformancePage()),
      if (assistente)
        _Voce('Assistente', Icons.chat_outlined, AssistentePage(conversazione: _conversazione)),
      if (ricerche) const _Voce('Ricerche e feedback', Icons.manage_search, RicerchePage()),
      if (u.isAdmin) const _Voce('Amministrazione', Icons.admin_panel_settings, AdminPage()),
      if (!redazione && !trasparenza && !anticorruzione && !performance && !assistente && !ricerche && !u.isAdmin)
        const _Voce('Benvenuto', Icons.home, _NessunModulo()),
    ];
  }

  /// Testo per l'assistenza configurato dall'ente.
  void _assistenza() => showDialog<void>(
        context: context,
        builder: (c) => PointerInterceptor(
          child: AlertDialog(
            title: const Text('Assistenza'),
            content: SizedBox(width: 480, child: TestoAssistenza(widget.utente.ente.assistenza!)),
            actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Chiudi'))],
          ),
        ),
      );

  /// Cambio della password (solo utenti dell'app: quelle di dominio si cambiano in AD).
  Future<void> _cambiaPassword() async {
    final attuale = TextEditingController();
    final nuova = TextEditingController();
    final ripeti = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Cambia la password'),
        content: SizedBox(
          width: 380,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: attuale, obscureText: true, decoration: const InputDecoration(labelText: 'Password attuale')),
            TextField(
              controller: nuova,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'Nuova password',
                helperText: 'Almeno 10 caratteri, con lettere e numeri o simboli',
              ),
            ),
            TextField(controller: ripeti, obscureText: true, decoration: const InputDecoration(labelText: 'Ripeti la nuova password')),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Cambia')),
        ],
      ),
    );
    final valori = (attuale.text, nuova.text, ripeti.text);
    attuale.dispose();
    nuova.dispose();
    ripeti.dispose();
    if (ok != true || !mounted) return;
    if (valori.$2 != valori.$3) {
      mostraErrore(context, 'Le due password nuove non coincidono');
      return;
    }
    try {
      await context.read<AuthState>().cambiaPassword(valori.$1, valori.$2);
      if (mounted) mostraMessaggio(context, 'Password cambiata: le altre sessioni sono state chiuse');
    } catch (e) {
      if (mounted) mostraErrore(context, e);
    }
  }

  String _iniziale(String nome) => nome.isEmpty ? '?' : nome.substring(0, 1).toUpperCase();

  /// Settore e decreto di incarico dell'utente (precompilano gli atti) e struttura
  /// organizzativa: questa si sceglie una sola volta, poi la cambia l'amministratore.
  Future<void> _profilo() async {
    final utente = context.read<AuthState>().utente ?? widget.utente;
    final ufficio = TextEditingController(text: utente.ufficio ?? '');
    final decreto = TextEditingController(text: utente.decretoIncarico ?? '');
    var strutture = const <Map<String, dynamic>>[];
    try {
      strutture = ((await apiDi(context).get('/api/v1/ente/strutture')) as List).cast<Map<String, dynamic>>();
    } catch (_) {
      // senza l'elenco la struttura non si sceglie; il resto del profilo si modifica
    }
    if (!mounted) return;
    String nome(Map<String, dynamic> s) => '${s['codice']} - ${s['descrizione']}';
    final assegnata = strutture.where((s) => s['id'] == utente.strutturaId).firstOrNull;
    String? scelta;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => StatefulBuilder(builder: (c, aggiorna) => AlertDialog(
        title: const Text('Il mio profilo'),
        content: SizedBox(
          width: 420,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(utente.nomeCompleto),
              subtitle: Text(utente.username),
            ),
            if (utente.strutturaId != null)
              InputDecorator(
                decoration: const InputDecoration(
                  labelText: 'Struttura organizzativa',
                  helperText: 'Per cambiarla rivolgiti all\'amministratore.',
                ),
                child: Text(assegnata == null ? 'Assegnata' : nome(assegnata)),
              )
            else if (strutture.isNotEmpty)
              DropdownButtonFormField<String?>(
                initialValue: scelta,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: 'Struttura organizzativa',
                  helperText: 'Si sceglie una sola volta: per cambiarla poi serve l\'amministratore.',
                  helperMaxLines: 2,
                ),
                items: [
                  const DropdownMenuItem(value: null, child: Text('Non indicata')),
                  for (final s in strutture.where((s) => s['attiva'] == true))
                    DropdownMenuItem(value: s['id'] as String, child: Text(nome(s), overflow: TextOverflow.ellipsis)),
                ],
                onChanged: (v) => aggiorna(() => scelta = v),
              ),
            const SizedBox(height: 12),
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
      )),
    );
    if (ok == true && mounted) {
      try {
        await context
            .read<AuthState>()
            .aggiornaProfilo(ufficio: ufficio.text.trim(), decretoIncarico: decreto.text.trim(), strutturaId: scelta);
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
    final piccolo = schermoPiccolo(context);
    final logo = context.select<AuthState, Uint8List?>((a) => a.logo);

    final menuUtente = PopupMenuButton<String>(
      tooltip: widget.utente.nomeCompleto,
      icon: CircleAvatar(child: Text(_iniziale(widget.utente.nomeCompleto))),
      // PointerInterceptor: il menu può aprirsi sopra l'editor della trasparenza (un
      // iframe), che altrimenti riceverebbe i clic
      itemBuilder: (_) => [
        PopupMenuItem(
          enabled: false,
          child: PointerInterceptor(
            child: Text('${widget.utente.nomeCompleto}\n${widget.utente.ruoli.join(', ')}'
                '\n${widget.utente.ente.nome}'
                '${widget.utente.ufficio != null ? '\n${widget.utente.ufficio}' : ''}'),
          ),
        ),
        for (final (valore, testo) in [
          ('profilo', 'Il mio profilo'),
          if (widget.utente.ente.assistenza != null) ('assistenza', 'Assistenza'),
          if (widget.utente.locale) ('password', 'Cambia la password'),
          ('esci', 'Esci'),
        ])
          PopupMenuItem(
            value: valore,
            padding: EdgeInsets.zero,
            child: PointerInterceptor(
              child: Container(
                height: 48,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                alignment: Alignment.centerLeft,
                child: Text(testo),
              ),
            ),
          ),
      ],
      onSelected: (v) async {
        if (v == 'esci' && await _puoiLasciare() && context.mounted) context.read<AuthState>().logout();
        if (v == 'profilo') _profilo();
        if (v == 'assistenza') _assistenza();
        if (v == 'password') _cambiaPassword();
      },
    );

    // Solo la pagina selezionata, con una chiave nuova a ogni selezione: niente dati vecchi
    final contenuto = Navigator(
      key: ValueKey(_generazione),
      observers: [_pagine],
      onGenerateRoute: (impostazioni) => MaterialPageRoute(settings: impostazioni, builder: (_) => voci[indice].pagina),
    );

    if (largo) {
      return Scaffold(
        body: Row(children: [
          NavigationRail(
            selectedIndex: indice,
            onDestinationSelected: _seleziona,
            labelType: piccolo ? NavigationRailLabelType.none : NavigationRailLabelType.all,
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Tooltip(message: widget.utente.ente.nome, child: IconaEnte(logo: logo)),
            ),
            trailing: Expanded(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(padding: const EdgeInsets.only(bottom: 16), child: menuUtente),
              ),
            ),
            destinations: [
              for (final v in voci)
                NavigationRailDestination(icon: Tooltip(message: v.etichetta, child: Icon(v.icona)), label: Text(v.etichetta)),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: contenuto),
        ]),
      );
    }
    return Scaffold(
      appBar: AppBar(
        leading: Padding(padding: const EdgeInsets.all(10), child: IconaEnte(logo: logo)),
        title: Text(voci[indice].etichetta),
        actions: [menuUtente],
      ),
      body: contenuto,
      bottomNavigationBar: voci.length < 2
          ? null
          : NavigationBar(
              labelBehavior: piccolo ? NavigationDestinationLabelBehavior.alwaysHide : null,
              selectedIndex: indice,
              onDestinationSelected: _seleziona,
              destinations: [
                for (final v in voci) NavigationDestination(icon: Icon(v.icona), label: v.etichetta),
              ],
            ),
    );
  }
}

/// Tiene l'elenco delle pagine aperte nell'area dei contenuti.
class _PagineAperte extends NavigatorObserver {
  final rotte = <Route<dynamic>>[];

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) => rotte.add(route);
  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) => rotte.remove(route);
  @override
  void didRemove(Route<dynamic> route, Route<dynamic>? previousRoute) => rotte.remove(route);
  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    rotte.remove(oldRoute);
    if (newRoute != null) rotte.add(newRoute);
  }
}

class _NessunModulo extends StatelessWidget {
  const _NessunModulo();

  @override
  Widget build(BuildContext context) => const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Nessun modulo abilitato per il tuo ente o per i tuoi ruoli: rivolgiti all\'amministratore.',
            textAlign: TextAlign.center,
          ),
        ),
      );
}
