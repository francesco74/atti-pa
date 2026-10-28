import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../utils/data_formatter.dart';

/// Helper condivisi dai form: una riga ripetibile con i propri controller,
/// i campi di base e il selettore dell'ambito soggettivo.

/// Riga di un elenco "da replicare": i controller sono creati alla prima
/// richiesta della chiave, le scelte vincolate sono tenute in [scelte].
class RigaDati {
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, String?> scelte = {};
  // Elenchi annidati (sotto-elementi da replicare), indicizzati per campo.
  final Map<String, List<RigaDati>> _elenchi = {};
  // Negli elenchi ripetibili una riga può essere compressa al solo riassunto.
  bool espansa = true;

  TextEditingController operator [](String key) =>
      _controllers.putIfAbsent(key, () => TextEditingController());

  String testo(String key) => _controllers[key]?.text.trim() ?? '';

  List<RigaDati> elenco(String key) =>
      _elenchi.putIfAbsent(key, () => [RigaDati()]);

  /// Sostituisce gli elementi di un elenco annidato (es. dati ricaricati).
  void impostaElenco(String key, List<RigaDati> righe) {
    final precedenti = _elenchi[key];
    if (precedenti != null) disponiRighe(precedenti);
    _elenchi[key] = righe;
  }

  /// Una riga è vuota se nessun campo è stato compilato: i validator la
  /// ignorano e non finisce nel documento generato.
  bool get isEmpty =>
      _controllers.values.every((c) => c.text.trim().isEmpty) &&
      scelte.values.every((v) => v == null) &&
      _elenchi.values.every((righe) => righe.every((r) => r.isEmpty));

  /// Copia indipendente della riga, compresi gli elenchi annidati.
  RigaDati copia() {
    final nuova = RigaDati();
    _controllers.forEach((k, c) => nuova[k].text = c.text);
    nuova.scelte.addAll(scelte);
    _elenchi.forEach(
      (k, righe) => nuova._elenchi[k] = [for (final r in righe) r.copia()],
    );
    return nuova;
  }

  /// Riapre la riga e tutte quelle annidate (es. per mostrare gli errori).
  void espandiTutto() {
    espansa = true;
    for (final righe in _elenchi.values) {
      for (final r in righe) {
        r.espandiTutto();
      }
    }
  }

  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    for (final righe in _elenchi.values) {
      for (final r in righe) {
        r.dispose();
      }
    }
  }
}

void disponiRighe(List<RigaDati> righe) {
  for (final r in righe) {
    r.dispose();
  }
  righe.clear();
}

/// Validator che non blocca le righe lasciate completamente vuote.
String? Function(String?) seCompilata(
  RigaDati riga,
  String? Function(String?) validator,
) {
  return (value) => riga.isEmpty ? null : validator(value);
}

String? obbligatorio(String? value) =>
    (value == null || value.trim().isEmpty) ? 'Campo obbligatorio' : null;

Widget campoTesto(
  TextEditingController controller,
  String label, {
  String? Function(String?)? validator,
  String? hint,
  int maxLines = 1,
  TextInputType? keyboardType,
}) {
  return Padding(
    padding: const EdgeInsets.only(bottom: 12.0),
    child: TextFormField(
      controller: controller,
      maxLines: maxLines,
      keyboardType: keyboardType,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        border: const OutlineInputBorder(),
        isDense: true,
      ),
      validator: validator,
    ),
  );
}

/// Campo data GG/MM/AAAA: si può scrivere a mano oppure scegliere dal
/// calendario con l'icona a destra.
Widget campoData(
  BuildContext context,
  TextEditingController controller,
  String label, {
  String? Function(String?)? validator,
  String separatore = '/',
}) {
  final formato = 'GG${separatore}MM${separatore}AAAA';
  Future<void> apriCalendario() async {
    final iniziale =
        DataFormatter.parseItalianDate(
          controller.text.trim().replaceAll(separatore, '/'),
        ) ??
        DateTime.now();
    final scelta = await showDatePicker(
      context: context,
      initialDate: iniziale,
      firstDate: DateTime(1990),
      lastDate: DateTime(2100),
      helpText: 'Seleziona la data',
      cancelText: 'Annulla',
      confirmText: 'OK',
      fieldLabelText: 'Data ($formato)',
      fieldHintText: 'GG/MM/AAAA',
      errorFormatText: 'Formato non valido',
      errorInvalidText: 'Data fuori intervallo',
    );
    if (scelta != null) {
      controller.text = DateFormat(
        'dd${separatore}MM${separatore}yyyy',
      ).format(scelta);
    }
  }

  return Padding(
    padding: const EdgeInsets.only(bottom: 12.0),
    child: TextFormField(
      controller: controller,
      keyboardType: TextInputType.datetime,
      decoration: InputDecoration(
        labelText: label,
        hintText: formato,
        border: const OutlineInputBorder(),
        isDense: true,
        suffixIcon: IconButton(
          icon: const Icon(Icons.calendar_month),
          tooltip: 'Scegli dal calendario',
          onPressed: apriCalendario,
        ),
      ),
      validator: validator,
    ),
  );
}

Widget campoScelta({
  required String? value,
  required String label,
  required List<String> opzioni,
  required ValueChanged<String?> onChanged,
  String? Function(String?)? validator,
}) {
  return Padding(
    padding: const EdgeInsets.only(bottom: 12.0),
    child: DropdownButtonFormField<String>(
      initialValue: value,
      isExpanded: true,
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
        isDense: true,
      ),
      items: opzioni
          .map((o) => DropdownMenuItem<String>(value: o, child: Text(o)))
          .toList(),
      onChanged: onChanged,
      validator: validator,
    ),
  );
}

/// Selettore dell'ambito soggettivo. Gli schemi della delibera 495/2024
/// aggiornati al 10.06.2026 prevedono solo la precisazione di non
/// applicabilità; quelli della delibera 497/2025 (es. art. 41) chiedono
/// ancora di dichiararsi tenuto / tenuto parzialmente / non tenuto.
Widget selettoreAmbito({
  required String value,
  required ValueChanged<String> onChanged,
  bool conAutodichiarazione = false,
  String articolo = '',
}) {
  final items = conAutodichiarazione
      ? [
          DropdownMenuItem(
            value: 'TENUTO',
            child: Text("Soggetto tenuto all'obbligo di pubblicazione ex $articolo"),
          ),
          DropdownMenuItem(
            value: 'PARZIALE',
            child: Text(
              "Soggetto tenuto parzialmente all'obbligo di pubblicazione ex $articolo",
            ),
          ),
          DropdownMenuItem(
            value: 'NON_TENUTO',
            child: Text(
              "Soggetto non tenuto all'obbligo di pubblicazione ex $articolo",
            ),
          ),
        ]
      : const [
          DropdownMenuItem(
            value: 'TENUTO',
            child: Text("Obbligo di pubblicazione applicabile all'amministrazione"),
          ),
          DropdownMenuItem(
            value: 'NON_TENUTO',
            child: Text(
              "L'obbligo di pubblicazione non è applicabile all'amministrazione",
            ),
          ),
        ];
  return DropdownButtonFormField<String>(
    initialValue: value,
    isExpanded: true,
    decoration: const InputDecoration(
      labelText: 'Ambito soggettivo di applicazione *',
      border: OutlineInputBorder(),
      prefixIcon: Icon(Icons.gavel),
    ),
    items: items,
    onChanged: (v) => onChanged(v ?? 'TENUTO'),
  );
}

/// Elenco di righe ripetibili. Ogni riga ha un'intestazione con il
/// riassunto del contenuto e i pulsanti per comprimerla, duplicarla e
/// rimuoverla. Le righe compresse restano nel form (e quindi vengono
/// validate) ma non sono visibili.
Widget elencoRipetibile({
  required String titoloRiga,
  required List<RigaDati> righe,
  required Widget Function(RigaDati riga) costruisciRiga,
  required VoidCallback onAggiungi,
  required void Function(int index) onRimuovi,
  required void Function(int index) onDuplica,
  required void Function(int index) onEspandi,
  String Function(RigaDati riga)? riassunto,
  String etichettaAggiungi = 'Aggiungi',
}) {
  return Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      for (var index = 0; index < righe.length; index++)
        Builder(
          builder: (context) {
            final riga = righe[index];
            final sintesi = riassunto?.call(riga) ?? '';
            return Container(
              margin: const EdgeInsets.only(bottom: 12.0),
              decoration: BoxDecoration(
                color: Colors.grey.shade50,
                border: Border.all(color: Colors.grey.shade300),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  InkWell(
                    onTap: () => onEspandi(index),
                    borderRadius: BorderRadius.circular(8),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 4.0,
                        vertical: 2.0,
                      ),
                      child: Row(
                        children: [
                          Icon(
                            riga.espansa
                                ? Icons.expand_less
                                : Icons.expand_more,
                            color: Colors.blueGrey,
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: Text.rich(
                              TextSpan(
                                children: [
                                  TextSpan(
                                    text: '$titoloRiga ${index + 1}',
                                    style: const TextStyle(
                                      fontWeight: FontWeight.bold,
                                      color: Colors.blueGrey,
                                    ),
                                  ),
                                  if (sintesi.isNotEmpty)
                                    TextSpan(
                                      text: '  ·  $sintesi',
                                      style: TextStyle(
                                        color: Colors.grey.shade800,
                                      ),
                                    ),
                                ],
                              ),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          IconButton(
                            icon: const Icon(Icons.copy_outlined, size: 20),
                            tooltip: 'Duplica',
                            onPressed: () => onDuplica(index),
                          ),
                          if (righe.length > 1)
                            IconButton(
                              icon: Icon(
                                Icons.delete_outline,
                                color: Colors.red.shade700,
                              ),
                              tooltip: 'Rimuovi',
                              onPressed: () => onRimuovi(index),
                            ),
                        ],
                      ),
                    ),
                  ),
                  Visibility(
                    visible: riga.espansa,
                    maintainState: true,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const Divider(height: 1),
                          const SizedBox(height: 12),
                          costruisciRiga(riga),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            );
          },
        ),
      Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton.icon(
          onPressed: onAggiungi,
          icon: const Icon(Icons.add),
          label: Text(etichettaAggiungi),
        ),
      ),
    ],
  );
}

/// Sotto-titolo di un gruppo di campi (chiave 'gruppo' dello schema).
Widget titoloGruppo(BuildContext context, String testo) {
  return Padding(
    padding: const EdgeInsets.only(top: 8.0, bottom: 12.0),
    child: Row(
      children: [
        Text(
          testo,
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.bold,
            color: Theme.of(context).colorScheme.primary,
          ),
        ),
        const SizedBox(width: 12),
        const Expanded(child: Divider()),
      ],
    ),
  );
}

Widget titoloSezione(String testo) {
  return Padding(
    padding: const EdgeInsets.only(top: 8.0, bottom: 12.0),
    child: Text(
      testo,
      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
    ),
  );
}

Widget notaInformativa(String testo) {
  return Padding(
    padding: const EdgeInsets.only(bottom: 12.0),
    child: Text(
      testo,
      style: const TextStyle(fontSize: 12, color: Colors.blueGrey),
    ),
  );
}
