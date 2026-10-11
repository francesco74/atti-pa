import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';

/// Web: apre l'indirizzo del file; il browser invia il cookie di sessione (stessa origine)
/// e gestisce il download in base all'intestazione Content-Disposition.
Future<void> salvaFile(
  ApiClient api,
  String percorso,
  String nomeFile, {
  Map<String, String>? query,
}) async {
  await launchUrl(api.uri(percorso, query), webOnlyWindowName: '_blank');
}
