import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../comuni.dart';
import 'comune.dart';
import 'mappatura.dart';
import 'monitoraggio.dart';
import 'obiettivi.dart';
import 'proposte.dart';
import 'riepilogo.dart';

/// Modulo anticorruzione (ripreso da Si.Ge.Ri.Co.): mappatura dei processi con la
/// valutazione del rischio, proposte dei referenti, monitoraggio delle misure, PIAO e
/// obiettivi di performance, riepilogo con gli allegati al PTPCT.
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
          length: 5,
          child: Column(children: [
            const TabBar(isScrollable: true, tabs: [
              Tab(icon: Icon(Icons.account_tree_outlined), text: 'Mappatura'),
              Tab(icon: Icon(Icons.rate_review_outlined), text: 'Proposte'),
              Tab(icon: Icon(Icons.fact_check_outlined), text: 'Monitoraggio'),
              Tab(icon: Icon(Icons.flag_outlined), text: 'PIAO'),
              Tab(icon: Icon(Icons.insights), text: 'Riepilogo'),
            ]),
            Expanded(
              child: TabBarView(key: ValueKey(_versione), children: [
                MappaturaTab(onDatiCambiati: _carica),
                const ProposteTab(),
                const MonitoraggioTab(),
                const ObiettiviTab(),
                RiepilogoTab(onDatiCambiati: _carica),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
