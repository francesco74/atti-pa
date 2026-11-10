import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../util/favicon.dart';

/// Ente su cui lavora l'utente, con i moduli abilitati e la presenza del logo.
class EnteUtente {
  EnteUtente.daJson(Map<String, dynamic> j)
      : codice = j['codice'] as String,
        nome = j['nome'] as String,
        moduli = List<String>.from(j['moduli'] as List? ?? const []),
        logo = j['logo'] == true,
        assistenza = (j['assistenza'] as String?)?.trim().isEmpty ?? true ? null : (j['assistenza'] as String).trim();

  final String codice;
  final String nome;
  final List<String> moduli;
  final bool logo;
  final String? assistenza; // testo per l'assistenza agli utenti (null: non configurato)
}

class Utente {
  Utente.daJson(Map<String, dynamic> j)
      : id = j['id'] as String,
        username = j['username'] as String,
        nomeCompleto = (j['nome_completo'] as String?) ?? j['username'] as String,
        ufficio = j['ufficio'] as String?,
        strutturaId = j['struttura_id'] as String?,
        decretoIncarico = j['decreto_incarico'] as String?,
        ruoli = List<String>.from(j['ruoli'] as List),
        origine = (j['origine'] as String?) ?? 'LDAP',
        cambioPassword = j['cambio_password'] == true,
        ente = EnteUtente.daJson(Map<String, dynamic>.from(j['ente'] as Map));

  final String id;
  final String username;
  final String nomeCompleto;
  final String? ufficio;
  final String? strutturaId; // struttura organizzativa (Amministrazione → Strutture)
  final String? decretoIncarico;
  final List<String> ruoli;
  final String origine; // LDAP, LOCALE
  final bool cambioPassword; // password iniziale: va cambiata prima di usare l'app
  final EnteUtente ente;

  bool get locale => origine == 'LOCALE';

  /// Modulo abilitato per l'ente (es. "redazione").
  bool modulo(String nome) => ente.moduli.contains(nome);

  bool get isAdmin => ruoli.contains('ADMIN');
  bool get isRedattore => isAdmin || ruoli.contains('REDATTORE');
  bool get isControllore => isAdmin || ruoli.contains('CONTROLLORE');
  bool get isGestoreModelli => isAdmin || ruoli.contains('GESTORE_MODELLI');
  bool get isTrasparenza => isAdmin || ruoli.contains('TRASPARENZA');
  bool get isAnticorruzioneRpct => isAdmin || ruoli.contains('ANTICORRUZIONE_RPCT');
  bool get isAnticorruzione => isAnticorruzioneRpct || ruoli.contains('ANTICORRUZIONE_REFERENTE');
  bool get isPerformanceAmministratore => isAdmin || ruoli.contains('PERFORMANCE_AMMINISTRATORE');
  bool get isPerformance =>
      isPerformanceAmministratore || ruoli.contains('PERFORMANCE_RESPONSABILE') || ruoli.contains('PERFORMANCE_APPROVATORE');
  bool get isAnalisiRicerche => isAdmin || ruoli.contains('ANALISI_RICERCHE');
}

enum StatoAuth { verifica, anonimo, autenticato }

class AuthState extends ChangeNotifier {
  AuthState(this.api) {
    api.suNonAutenticato = _sessioneScaduta;
  }

  final ApiClient api;
  StatoAuth stato = StatoAuth.verifica;
  Utente? utente;

  /// Logo dell'ente (icona dell'app, favicon e sfondo); null se non caricato.
  Uint8List? logo;

  /// All'avvio verifica se esiste già una sessione valida (cookie di sessione).
  Future<void> avvia() async {
    try {
      utente = Utente.daJson(await api.utenteCorrente());
      stato = StatoAuth.autenticato;
    } catch (_) {
      stato = StatoAuth.anonimo;
    }
    notifyListeners();
    if (utente != null) await _caricaLogo();
  }

  Future<void> login(String username, String password, {String? modo}) async {
    utente = Utente.daJson(await api.login(username, password, modo: modo));
    stato = StatoAuth.autenticato;
    notifyListeners();
    await _caricaLogo();
  }

  Future<void> _caricaLogo() async {
    Uint8List? immagine;
    if (utente?.ente.logo ?? false) {
      try {
        immagine = await api.getBytes('/api/v1/ente/logo');
      } catch (_) {
        // senza logo l'app usa il martelletto
      }
    }
    impostaLogo(immagine);
  }

  /// Logo caricato o tolto dall'amministratore: l'app si aggiorna subito.
  void impostaLogo(Uint8List? immagine) {
    logo = immagine;
    impostaFavicon(immagine);
    notifyListeners();
  }

  /// Profilo modificato dall'utente (settore usato per precompilare gli atti).
  /// Profilo dell'utente; la struttura si sceglie solo se non è ancora assegnata.
  Future<void> aggiornaProfilo({String? ufficio, String? decretoIncarico, String? strutturaId}) async {
    final r = await api.put('/api/v1/auth/profilo', {
      'ufficio': ufficio,
      'decreto_incarico': decretoIncarico,
      'struttura_id': ?strutturaId,
    }) as Map<String, dynamic>;
    utente = Utente.daJson(r);
    notifyListeners();
  }

  /// Cambio della propria password (utenti locali): le altre sessioni si chiudono.
  Future<void> cambiaPassword(String attuale, String nuova) async {
    final r = await api.put('/api/v1/auth/password', {'attuale': attuale, 'nuova': nuova})
        as Map<String, dynamic>;
    utente = Utente.daJson(r['utente'] as Map<String, dynamic>);
    notifyListeners();
  }

  Future<void> logout() async {
    await api.logout();
    utente = null;
    logo = null;
    impostaFavicon(null);
    stato = StatoAuth.anonimo;
    notifyListeners();
  }

  void _sessioneScaduta() {
    if (stato == StatoAuth.autenticato) {
      utente = null;
      logo = null;
      impostaFavicon(null);
      stato = StatoAuth.anonimo;
      notifyListeners();
    }
  }
}
