import 'package:intl/intl.dart';

class DataFormatter {
  // Formattatore statico interno per coerenza di performance
  static final NumberFormat _itCurrency = NumberFormat.currency(
    locale: 'it_IT',
    symbol: '',
    decimalDigits: 2,
  );

  /// Converte una stringa GG/MM/AAAA in un oggetto DateTime per permettere il confronto.
  /// Ritorna null se la data non è valida o mal formattata.
  static DateTime? parseItalianDate(String? dateStr) {
    if (dateStr == null || dateStr.length != 10) return null;
    try {
      final parts = dateStr.split('/');
      if (parts.length == 3) {
        // DateTime accetta: Anno, Mese, Giorno
        return DateTime(int.parse(parts[2]), int.parse(parts[1]), int.parse(parts[0]));
      }
    } catch (_) {
      return null;
    }
    return null;
  }

  /// Forza una stringa nel formato "1.500,00" richiesto da ANAC [cite: 25, 27]
  static String formatCurrency(String value) {
    if (value.isEmpty) return '0,00';

    try {
      // 1. Pulizia: rimuoviamo i punti (migliaia) e convertiamo la virgola in punto per il parsing
      String numericString = value
          .replaceAll('.', '')
          .replaceAll(',', '.')
          .trim();
      double? val = double.tryParse(numericString);

      if (val == null) return '0,00';

      // 2. Formattazione: NumberFormat re-inserisce i punti e la virgola corretta
      return _itCurrency.format(val).trim();
    } catch (e) {
      return '0,00';
    }
  }

  static String? validateCurrencyInput(String? value) {
    if (value == null || value.isEmpty) return 'Campo obbligatorio';
    
    // Rimuove i punti e cambia la virgola in punto per testare se è un double valido
    String numericString = value.replaceAll('.', '').replaceAll(',', '.').trim();
    if (double.tryParse(numericString) == null) {
      return 'Inserisci un importo valido (es. 1500 o 1500,50)';
    }
    return null;
  }

  static String? validateUrl(String? value, {int maxLength = 256, bool isRequired = true}) {
    if (value == null || value.trim().isEmpty) {
      return isRequired ? 'Campo obbligatorio' : null;
    }
    if (value.length > maxLength) return 'Massimo $maxLength caratteri (Attuali: ${value.length})';

    // Lo schema ANAC tipizza il campo come "URL": pretendiamo lo schema esplicito.
    final urlRegex = RegExp(r'^https?:\/\/([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$');
    if (!urlRegex.hasMatch(value.trim())) {
      return 'Inserisci un URL completo di http:// o https://';
    }
    return null;
  }

  static String? validateTextLength(String? value, {required int maxLength, bool isRequired = true}) {
    if (value == null || value.trim().isEmpty) {
      return isRequired ? 'Campo obbligatorio' : null;
    }
    if (value.length > maxLength) {
      return 'Massimo $maxLength caratteri (Attuali: ${value.length})';
    }
    return null;
  }
  
  /// Formatta le percentuali con 2 decimali 
  static String formatPercentage(String value) {
    if (value.isEmpty) return '0,00';
    String normalized = value.replaceAll('.', ',');
    if (!normalized.contains(',')) return '$normalized,00';
    List<String> parts = normalized.split(',');
    if (parts[1].isEmpty) return '${parts[0]},00';
    if (parts[1].length == 1) return '${parts[0]},${parts[1]}0';
    return normalized;
  }

  /// Valida un valore percentuale (0-100, virgola per i decimali).
  /// Da usare al posto di validateCurrencyInput per campi che sono
  /// percentuali e non importi (es. quota di contribuzione pubblica).
  static String? validatePercentageInput(String? value) {
    if (value == null || value.trim().isEmpty) return 'Campo obbligatorio';

    final normalized = value.replaceAll('.', ',').trim();
    final regex = RegExp(r'^\d{1,3}(,\d{1,2})?$');
    if (!regex.hasMatch(normalized)) {
      return 'Inserisci una percentuale valida (es. 45,50)';
    }

    final numeric = double.tryParse(normalized.replaceAll(',', '.'));
    if (numeric == null || numeric < 0 || numeric > 100) {
      return 'Inserisci un valore tra 0 e 100';
    }
    return null;
  }

  static String? validateYear(String? value) {
    if (value == null || value.isEmpty) return 'Obbligatorio';
    if (value.length != 4 || int.tryParse(value) == null) {
      return 'Inserisci 4 cifre';
    }
    int anno = int.parse(value);
    if (anno < 1900 || anno > 2100) return 'Anno non valido';
    return null;
  }

  /// Validatore standard per campi data
  static String? validateDateWithSlash(String? value, {bool isRequired = true}) {
    if (value == null || value.isEmpty) {
      return isRequired ? 'Obbligatorio' : null;
    }
    if (!dateRegexWithSlash.hasMatch(value)) return 'Formato GG/MM/AAAA';
    return null;
  }

  static String? validateDateWithDot(String? value, {bool isRequired = true}) {
    if (value == null || value.isEmpty) {
      return isRequired ? 'Obbligatorio' : null;
    }
    if (!dateRegexWithDot.hasMatch(value)) return 'Formato GG.MM.AAAA';
    return null;
  }

  static String? validateEmailAnac(String? value, {bool isRequired = true}) {
    if (value == null || value.trim().isEmpty) {
      return isRequired ? 'Campo obbligatorio' : null;
    }
    if (value.length > 256) {
      return 'Massimo 256 caratteri (Attuali: ${value.length})';
    }
    // Pattern esatto richiesto da ANAC
    final emailRegex = RegExp(r'^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+$');
    if (!emailRegex.hasMatch(value)) {
      return 'Inserisci un indirizzo email valido';
    }
    return null;
  }

  /// Alcuni campi dello schema ANAC (es. PEO/PEC ufficio in art. 26/27) ammettono
  /// esplicitamente, in alternativa al dato diretto, un link alla sottosezione del
  /// sito dove il dato è già pubblicato (es. quelli relativi agli artt. 13 e 35).
  static String? validateEmailOrUrl(
    String? value, {
    int maxLength = 256,
    bool isRequired = true,
  }) {
    if (value == null || value.trim().isEmpty) {
      return isRequired ? 'Campo obbligatorio' : null;
    }
    if (value.length > maxLength) {
      return 'Massimo $maxLength caratteri (Attuali: ${value.length})';
    }
    final trimmed = value.trim();
    final emailRegex = RegExp(r'^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+$');
    final urlRegex = RegExp(
      r'^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$',
    );
    if (emailRegex.hasMatch(trimmed) || urlRegex.hasMatch(trimmed)) {
      return null;
    }
    return 'Inserisci un indirizzo email valido oppure un link (es. https://...)';
  }

  /// Valida un recapito telefonico diretto (senza l'alternativa "o link"
  /// prevista in altri schemi, es. art. 26/27). Da usare dove lo schema ANAC
  /// richiede sempre e solo il dato diretto (es. art. 35).
  static String? validatePhone(String? value, {bool isRequired = true}) {
    if (value == null || value.trim().isEmpty) {
      return isRequired ? 'Campo obbligatorio' : null;
    }
    final phoneRegex = RegExp(r'^[+\d][\d\s./-]{4,}$');
    if (!phoneRegex.hasMatch(value.trim())) {
      return 'Inserisci un recapito telefonico valido';
    }
    if (value.trim().length > 64) return 'Massimo 64 caratteri';
    return null;
  }

  /// Come sopra, ma per recapiti telefonici che possono essere sostituiti da un
  /// link alla sottosezione del sito dove il numero è già pubblicato.
  static String? validatePhoneOrUrl(
    String? value, {
    int maxLength = 256,
    bool isRequired = true,
  }) {
    if (value == null || value.trim().isEmpty) {
      return isRequired ? 'Campo obbligatorio' : null;
    }
    if (value.length > maxLength) {
      return 'Massimo $maxLength caratteri (Attuali: ${value.length})';
    }
    final trimmed = value.trim();
    final phoneRegex = RegExp(r'^[+\d][\d\s./-]{4,}$');
    final urlRegex = RegExp(
      r'^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$',
    );
    if (phoneRegex.hasMatch(trimmed) || urlRegex.hasMatch(trimmed)) {
      return null;
    }
    return 'Inserisci un recapito telefonico valido oppure un link (es. https://...)';
  }

  static RegExp get dateRegexWithSlash =>
      RegExp(r'^(0[1-9]|[12][0-9]|3[01])\/(0[1-9]|1[012])\/(19|20)\d\d$');
  static RegExp get dateRegexWithDot =>
      RegExp(r'^(0[1-9]|[12][0-9]|3[01])\.(0[1-9]|1[012])\.(19|20)\d\d$');
  static RegExp get percentageRegex => RegExp(r'^\d+(,\d{1,2})?$');
  static RegExp get currencyRegex =>
      RegExp(r'^(0|[1-9]\d{0,2}(\.\d{3})*),\d{2}$');
}