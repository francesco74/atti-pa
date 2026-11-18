import 'package:flutter/material.dart';

import '../../anticorruzione/mappatura.dart' show PubblicazioneMappatura;
import '../../anticorruzione/procedimenti.dart';
import '../../comuni.dart';

const apiProcedimenti = '/api/v1/trasparenza/procedimenti';

/// Procedimenti dell'ente (art. 35 d.lgs. 33/2013): catalogo condiviso con l'anticorruzione.
/// Con il solo modulo trasparenza l'operatore li crea, modifica, importa ed elimina qui,
/// direttamente; con l'anticorruzione attiva li gestisce il RPCT nel catalogo
/// dell'anticorruzione (i referenti propongono) e qui si consultano. In entrambi i casi c'è
/// l'interruttore della pagina pubblica dei procedimenti.
class ProcedimentiTab extends StatefulWidget {
  const ProcedimentiTab({super.key});

  @override
  State<ProcedimentiTab> createState() => _ProcedimentiTabState();
}

class _ProcedimentiTabState extends State<ProcedimentiTab> with AutomaticKeepAliveClientMixin {
  late Future<bool> _conIter;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _carica();
  }

  void _carica() => setState(() {
        _conIter = apiDi(context).get('$apiProcedimenti/pubblicazione').then((r) => (r as Map)['con_iter'] == true);
      });

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Caricamento<bool>(
      future: _conIter,
      riprova: _carica,
      builder: (context, conIter) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            conIter
                ? 'I procedimenti sono un catalogo dell\'anticorruzione: li gestisce il RPCT, con le proposte dei '
                    'referenti. Qui si consultano e si importano nella scheda art. 35.'
                : 'Tipologie di procedimento dell\'ente con i dati dell\'art. 35 d.lgs. 33/2013: si importano nella scheda '
                    'art. 35 e si possono pubblicare in una pagina consultabile dai cittadini.',
          ),
          const SizedBox(height: 12),
          ElencoProcedimenti(
            api: apiProcedimenti,
            gestione: conIter ? GestioneProcedimenti.lettura : GestioneProcedimenti.diretta,
            azioni: const [PubblicazioneMappatura(api: '$apiProcedimenti/pubblicazione', soloProcedimenti: true)],
          ),
        ],
      ),
    );
  }
}
