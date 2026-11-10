import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../stato/auth_state.dart';
import '../comuni.dart';
import '../relazioni/relazioni.dart';
import 'comune.dart';
import 'elenco.dart';
import 'mappatura.dart';
import 'monitoraggio.dart';
import 'proposte.dart';
import 'riepilogo.dart';

/// Modulo anticorruzione (ripreso da Si.Ge.Ri.Co.): mappatura dei processi e procedimenti
/// con la valutazione del rischio, elenco piatto con ricerca e filtri, proposte dei referenti,
/// monitoraggio delle misure, riepilogo con gli allegati al PTPCT.
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
    final rpct = context.read<AuthState>().utente?.isAnticorruzioneRpct ?? false;
    return Caricamento<DatiAnticorruzione>(
      future: _dati,
      riprova: _carica,
      builder: (context, dati) => Provider<DatiAnticorruzione>.value(
        value: dati,
        child: DefaultTabController(
          length: rpct ? 6 : 5,
          child: Column(children: [
            TabBar(isScrollable: true, tabs: [
              const Scheda(Icon(Icons.account_tree_outlined), 'Mappatura'),
              const Scheda(Icon(Icons.table_rows_outlined), 'Elenco'),
              const Scheda(Icon(Icons.rate_review_outlined), 'Proposte'),
              const Scheda(Icon(Icons.fact_check_outlined), 'Monitoraggio'),
              const Scheda(Icon(Icons.insights), 'Riepilogo'),
              if (rpct) const Scheda(Icon(Icons.summarize_outlined), 'Relazioni'),
            ]),
            Expanded(
              child: TabBarView(key: ValueKey(_versione), children: [
                MappaturaTab(onDatiCambiati: _carica),
                const ElencoTab(),
                const ProposteTab(),
                const MonitoraggioTab(),
                RiepilogoTab(onDatiCambiati: _carica),
                if (rpct) const RelazioniTab(tipi: ['RPCT', 'PIAO']),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
