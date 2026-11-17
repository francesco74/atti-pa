import 'package:flutter/services.dart';

/// Fuori dal browser solo il testo semplice.
Future<void> copiaFormattato({required String html, required String testo}) => Clipboard.setData(ClipboardData(text: testo));
