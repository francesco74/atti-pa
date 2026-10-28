import 'package:flutter/widgets.dart';

import '../../comuni.dart';
import '../browser.dart';
import '../servizio.dart';

/// Conversione lato server (converter) dell'HTML dell'editor e download del file.
/// In caso di problemi lancia un'eccezione con un messaggio per l'utente.

Future<void> scaricaComePdf(BuildContext context, String html, String nomeFile) =>
    _converti(context, html, nomeFile, 'pdf');

Future<void> scaricaComeDocx(BuildContext context, String html, String nomeFile) =>
    _converti(context, html, nomeFile, 'docx');

Future<void> _converti(BuildContext context, String html, String nomeFile, String formato) async {
  final nome = nomeFile.toLowerCase().endsWith('.$formato') ? nomeFile : '$nomeFile.$formato';
  final bytes = await ServizioTrasparenza(apiDi(context)).esporta(html, nome.substring(0, nome.length - formato.length - 1), formato);
  scaricaBytes(bytes, nome);
}
