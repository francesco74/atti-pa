import 'package:flutter/material.dart';

import 'editor_documento_comune.dart';

/// Fuori dal browser (test) l'editor mostra il documento senza modificarlo.
class EditorDocumento extends StatefulWidget {
  const EditorDocumento({
    super.key,
    required this.controllo,
    required this.contenuto,
    this.barraVisibile = true,
    required this.onCaricato,
    required this.onModifica,
  });

  final ControlloEditor controllo;
  final String contenuto;
  final bool barraVisibile;
  final ValueChanged<String> onCaricato;
  final ValueChanged<String> onModifica;

  @override
  State<EditorDocumento> createState() => _EditorDocumentoState();
}

class _EditorDocumentoState extends State<EditorDocumento> {
  @override
  void initState() {
    super.initState();
    widget.controllo.lettore = _leggi;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.onCaricato(widget.contenuto);
    });
  }

  @override
  void dispose() {
    if (widget.controllo.lettore == _leggi) widget.controllo.lettore = null;
    super.dispose();
  }

  Future<String> _leggi() async => widget.contenuto;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(child: SelectableText(widget.contenuto));
}
