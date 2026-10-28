import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

/// File scelto dal computer, con il contenuto già letto.
class FileScelto {
  const FileScelto(this.name, this.bytes);

  final String name;
  final Uint8List bytes;
}

Future<FileScelto?> scegliFile(List<String> estensioni) async {
  final file = await FilePicker.pickFile(type: FileType.custom, allowedExtensions: estensioni);
  return file == null ? null : FileScelto(file.name, await file.readAsBytes());
}

Future<List<FileScelto>> scegliFiles(List<String> estensioni) async {
  final scelti = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: estensioni);
  return [for (final f in scelti) FileScelto(f.name, await f.readAsBytes())];
}
