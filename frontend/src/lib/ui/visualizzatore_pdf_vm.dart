import 'package:flutter/material.dart';

class VisualizzatorePdf extends StatelessWidget {
  const VisualizzatorePdf({super.key, required this.url});

  final Uri url;

  @override
  Widget build(BuildContext context) => Center(child: Text('Anteprima: $url'));
}
