import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../comuni.dart';
import 'coda_analisi.dart';
import 'result_manager.dart';
import 'servizio.dart';
import 'tabs/ai_analysis_tab.dart';
import 'tabs/analisi_avviate_tab.dart';
import 'tabs/pdf_generator_tab.dart';
import 'tabs/result_tab.dart';

/// Modulo trasparenza (ripreso da PApuntozeroIA): analisi con l'IA delle pubblicazioni di
/// Amministrazione Trasparente, schede generate dagli schemi ANAC, risultati con l'editor,
/// l'archivio dei documenti e il verbale di validazione. Le analisi avviate girano in
/// background e si seguono nella loro scheda.
class TrasparenzaPage extends StatefulWidget {
  const TrasparenzaPage({super.key});

  @override
  State<TrasparenzaPage> createState() => _TrasparenzaPageState();
}

class _TrasparenzaPageState extends State<TrasparenzaPage> with SingleTickerProviderStateMixin {
  late final TabController _schede;
  late final CodaAnalisi _coda;

  // Ultimo risultato arrivato dalle altre schede
  NuovoRisultato? _risultato;
  bool _elencoVisibile = true;
  int _elencoTrigger = 0; // cambia quando si apre o chiude l'elenco dei documenti
  int _risultatoTrigger = 0; // cambia a ogni nuovo risultato

  @override
  void initState() {
    super.initState();
    _schede = TabController(length: 4, vsync: this);
    _coda = CodaAnalisi(ServizioTrasparenza(apiDi(context)))
      ..suConclusa = _analisiConclusa
      ..aggiorna();
    ResultManager.apriScheda = (scheda) {
      if (mounted) _schede.animateTo(scheda);
    };
    ResultManager.navigateToResults = (risultato) {
      if (!mounted) return;
      setState(() {
        _risultato = risultato;
        // arrivando da un'altra scheda l'elenco dei documenti si chiude
        _elencoVisibile = false;
        _elencoTrigger++;
        _risultatoTrigger++;
      });
      _schede.animateTo(2);
    };
  }

  @override
  void dispose() {
    ResultManager.navigateToResults = null;
    ResultManager.apriScheda = null;
    _coda.dispose();
    _schede.dispose();
    super.dispose();
  }

  void _vaiA(int scheda) {
    if (scheda == 2) {
      // aprendo i risultati dal menu si mostra l'elenco dei documenti salvati
      setState(() {
        _elencoVisibile = true;
        _elencoTrigger++;
      });
    }
    _schede.animateTo(scheda);
  }

  /// Avviso alla fine di un'analisi, con l'apertura del report (PointerInterceptor: può
  /// comparire sopra l'editor dei risultati, un iframe).
  void _analisiConclusa(Map<String, dynamic> lavoro) {
    if (!mounted) return;
    final completata = lavoro['stato'] == 'COMPLETATA';
    final messaggero = ScaffoldMessenger.of(context);
    messaggero.showSnackBar(SnackBar(
      duration: const Duration(seconds: 8),
      content: PointerInterceptor(
        child: Row(children: [
          Expanded(
            child: Text(completata
                ? 'Analisi completata: ${lavoro['titolo']}'
                : 'Analisi non riuscita: ${lavoro['titolo']}'),
          ),
          TextButton(
            onPressed: () async {
              messaggero.hideCurrentSnackBar();
              if (!completata) return _vaiA(3);
              try {
                final html = await _coda.report(lavoro['id'] as String);
                ResultManager.showResultInNewTab(html, nomeProposto: 'Analisi ${lavoro['titolo']}');
              } catch (e) {
                if (mounted) mostraErrore(context, e);
              }
            },
            child: Text(completata ? 'Apri' : 'Dettagli'),
          ),
        ]),
      ),
    ));
  }

  /// Icona delle analisi avviate con il numero di quelle in coda o in corso.
  Widget _iconaAvviate() => ListenableBuilder(
        listenable: _coda,
        builder: (context, _) => Badge(
          isLabelVisible: _coda.inCorso > 0,
          label: Text('${_coda.inCorso}'),
          child: const Icon(Icons.pending_actions),
        ),
      );

  /// Icona dei risultati con un punto quando c'è un documento da salvare.
  Widget _iconaRisultati() => ValueListenableBuilder<bool>(
        valueListenable: ResultManager.daSalvare,
        builder: (context, daSalvare, _) => Badge(
          isLabelVisible: daSalvare,
          smallSize: 9,
          backgroundColor: Colors.orange.shade700,
          child: const Icon(Icons.edit_note),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<CodaAnalisi>.value(
      value: _coda,
      child: Column(children: [
      Row(children: [
        Expanded(
          child: TabBar(
            controller: _schede,
            isScrollable: true,
            onTap: _vaiA,
            tabs: [
              const Tab(icon: Icon(Icons.manage_search), text: 'Analisi'),
              const Tab(icon: Icon(Icons.article_outlined), text: 'Schede'),
              Tab(icon: _iconaRisultati(), text: 'Risultati'),
              Tab(icon: _iconaAvviate(), text: 'Analisi avviate'),
            ],
          ),
        ),
        IconButton(
          tooltip: 'Normativa di riferimento (si apre in una nuova scheda)',
          icon: const Icon(Icons.balance_outlined),
          onPressed: () => launchUrl(
            Uri.base.resolve('assets/assets/trasparenza/normativa.html'),
            webOnlyWindowName: '_blank',
          ),
        ),
      ]),
      Expanded(
        child: TabBarView(
          controller: _schede,
          physics: const NeverScrollableScrollPhysics(),
          children: [
            const AiAnalysisTab(),
            const PdfGeneratorTab(),
            ResultTab(
              risultato: _risultato,
              showSidebar: _elencoVisibile,
              sidebarTrigger: _elencoTrigger,
              risultatoTrigger: _risultatoTrigger,
              onApriScheda: _vaiA,
            ),
            const AnalisiAvviateTab(),
          ],
        ),
      ),
    ]),
    );
  }
}
