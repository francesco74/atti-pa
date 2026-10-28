import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'result_manager.dart';
import 'tabs/ai_analysis_tab.dart';
import 'tabs/pdf_generator_tab.dart';
import 'tabs/result_tab.dart';

/// Modulo trasparenza (ripreso da PApuntozeroIA): analisi con l'IA delle pubblicazioni di
/// Amministrazione Trasparente, schede generate dagli schemi ANAC, risultati con l'editor,
/// l'archivio dei documenti e il verbale di validazione.
class TrasparenzaPage extends StatefulWidget {
  const TrasparenzaPage({super.key});

  @override
  State<TrasparenzaPage> createState() => _TrasparenzaPageState();
}

class _TrasparenzaPageState extends State<TrasparenzaPage> with SingleTickerProviderStateMixin {
  late final TabController _schede;

  // Ultimo risultato arrivato dalle altre schede
  NuovoRisultato? _risultato;
  bool _elencoVisibile = true;
  int _elencoTrigger = 0; // cambia quando si apre o chiude l'elenco dei documenti
  int _risultatoTrigger = 0; // cambia a ogni nuovo risultato

  @override
  void initState() {
    super.initState();
    _schede = TabController(length: 3, vsync: this);
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
    return Column(children: [
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
          ],
        ),
      ),
    ]);
  }
}
