import 'package:flutter/material.dart';
import 'dart:async';

// The showErrorDialog function remains unchanged.
Future<void> showErrorDialog(
  BuildContext context, {
  required String content,
}) async {
  return showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (BuildContext dialogContext) {
      return AlertDialog(
        title: const Text('Errore'),
        content: SingleChildScrollView(child: Text(content)),
        actions: <Widget>[
          TextButton(
            child: const Text('Chiudi'),
            onPressed: () {
              Navigator.of(dialogContext).pop();
            },
          ),
        ],
      );
    },
  );
}
