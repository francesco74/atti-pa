import 'dart:io';

import 'package:file_picker/file_picker.dart';

import '../api/api_client.dart';

/// Desktop: scarica i byte con il token e chiede all'utente dove salvarli.
Future<void> salvaFile(
  ApiClient api,
  String percorso,
  String nomeFile, {
  Map<String, String>? query,
}) async {
  final bytes = await api.getBytes(percorso, query: query);
  final destinazione = await FilePicker.platform.saveFile(
    dialogTitle: 'Salva documento',
    fileName: nomeFile,
  );
  if (destinazione == null) return;
  await File(destinazione).writeAsBytes(bytes);
}
