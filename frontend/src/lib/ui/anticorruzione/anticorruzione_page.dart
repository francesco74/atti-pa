import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../comuni.dart';
import 'comune.dart';
import 'mappatura.dart';
import 'monitoraggio.dart';
import 'proposte.dart';
import 'riepilogo.dart';

/// Modulo anticorruzione (ripreso da Si.Ge.Ri.Co.): mappatura dei processi e procedimenti
/// con la valutazione del rischio, proposte dei referenti, monitoraggio delle misure,
/// riepilogo con gli allegati al PTPCT.
class AnticorruzionePage extends StatefulWidget {
  const AnticorruzionePage({super.key});

  @override
  State<AnticorruzionePage> createState() => _AnticorruzionePageState();
}

class _AnticorruzionePageState extends State<AnticorruzionePage> {
  late Future<DatiAnticorruzione> _dati;
  int _versione = 0; // cambia quando si ricaricano i dati comuni: le schede si ricreano

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _dati = DatiAnticorruzione.carica(apiDi(context));
        _versione++;
      });

  @override
  Widget build(BuildContext context) {
    return Caricamento<DatiAnticorruzione>(
      future: _dati,
      riprova: _carica,
      builder: (context, dati) => Provider<DatiAnticorruzione>.value(
        value: dati,
        child: DefaultTabController(
          length: 4,
          child: Column(children: [
            const TabBar(isScrollable: true, tabs: [
              Scheda(Icon(Icons.account_tree_outlined), 'Mappatura'),
              Scheda(Icon(Icons.rate_review_outlined), 'Proposte'),
              Scheda(Icon(Icons.fact_check_outlined), 'Monitoraggio'),
              Scheda(Icon(Icons.insights), 'Riepilogo'),
            ]),
            Expanded(
              child: TabBarView(key: ValueKey(_versione), children: [
                MappaturaTab(onDatiCambiati: _carica),
                const ProposteTab(),
                const MonitoraggioTab(),
                RiepilogoTab(onDatiCambiati: _carica),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
