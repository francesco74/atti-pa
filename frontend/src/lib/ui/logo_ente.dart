import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../stato/auth_state.dart';

/// Icona dell'app: il logo dell'ente se caricato, altrimenti il martelletto.
class IconaEnte extends StatelessWidget {
  const IconaEnte({super.key, required this.logo, this.dimensione = 40});

  final Uint8List? logo;
  final double dimensione;

  @override
  Widget build(BuildContext context) {
    final immagine = logo;
    if (immagine == null) {
      return Icon(Icons.gavel, color: Theme.of(context).colorScheme.primary, size: dimensione * 0.8);
    }
    return SizedBox.square(
      dimension: dimensione,
      child: Image.memory(immagine, fit: BoxFit.contain, gaplessPlayback: true),
    );
  }
}

/// Fondo di ogni pagina dell'app: il colore del tema con il logo dell'ente (o il martelletto,
/// prima dell'accesso o senza logo). Lo applica [TransizioneConSfondo] a tutte le pagine,
/// anche quelle aperte sopra il menu; gli Scaffold sono trasparenti (tema in main.dart).
class SfondoEnte extends StatelessWidget {
  const SfondoEnte({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final logo = context.select<AuthState, Uint8List?>((a) => a.logo);
    return ColoredBox(
      color: Theme.of(context).colorScheme.surface,
      child: SfondoLogo(logo: logo, child: child),
    );
  }
}

/// Transizione tra le pagine (quella predefinita) con il fondo [SfondoEnte]: la pagina resta
/// opaca anche durante l'animazione.
class TransizioneConSfondo extends PageTransitionsBuilder {
  const TransizioneConSfondo();

  static const _predefinita = ZoomPageTransitionsBuilder();

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) =>
      _predefinita.buildTransitions(route, context, animation, secondaryAnimation, SfondoEnte(child: child));
}

/// Logo dell'ente (o il martelletto) ripetuto a mattoncino con una leggera trasparenza,
/// dietro [child]; card e campi restano opachi e il testo si legge come prima.
class SfondoLogo extends StatefulWidget {
  const SfondoLogo({super.key, required this.logo, required this.child});

  final Uint8List? logo;
  final Widget child;

  @override
  State<SfondoLogo> createState() => _SfondoLogoState();
}

class _SfondoLogoState extends State<SfondoLogo> {
  ui.Image? _immagine;

  @override
  void initState() {
    super.initState();
    _decodifica();
  }

  @override
  void didUpdateWidget(SfondoLogo vecchio) {
    super.didUpdateWidget(vecchio);
    if (!identical(vecchio.logo, widget.logo)) _decodifica();
  }

  @override
  void dispose() {
    _immagine?.dispose();
    super.dispose();
  }

  Future<void> _decodifica() async {
    final logo = widget.logo;
    ui.Image? immagine;
    if (logo != null) {
      try {
        immagine = (await (await ui.instantiateImageCodec(logo)).getNextFrame()).image;
      } catch (_) {
        // immagine non leggibile: resta il martelletto
      }
    }
    if (!mounted || !identical(logo, widget.logo)) {
      immagine?.dispose();
      return;
    }
    setState(() {
      _immagine?.dispose();
      _immagine = immagine;
    });
  }

  @override
  Widget build(BuildContext context) {
    final colori = Theme.of(context).colorScheme;
    return CustomPaint(
      painter: _Mattonelle(_immagine, colori.primary),
      child: widget.child,
    );
  }
}

class _Mattonelle extends CustomPainter {
  _Mattonelle(this.immagine, this.colore);

  final ui.Image? immagine;
  final Color colore;

  static const _passo = 140.0; // distanza tra i loghi
  static const _lato = 64.0; // riquadro in cui sta ogni logo
  static const _opacitaLogo = 0.06;
  static const _opacitaMartelletto = 0.05;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    final disegna = immagine == null ? _martelletto() : _logo(immagine!);
    for (var riga = 0; riga * _passo < size.height + _passo; riga++) {
      final sfasamento = riga.isOdd ? _passo / 2 : 0.0;
      for (var x = -sfasamento; x < size.width + _passo; x += _passo) {
        disegna(canvas, Offset(x + (_passo - _lato) / 2, riga * _passo + (_passo - _lato) / 2));
      }
    }
    canvas.restore();
  }

  void Function(Canvas, Offset) _logo(ui.Image img) {
    final origine = Rect.fromLTWH(0, 0, img.width.toDouble(), img.height.toDouble());
    final scala = _lato / (img.width > img.height ? img.width : img.height);
    final w = img.width * scala, h = img.height * scala;
    final pennello = Paint()
      ..color = const Color.fromRGBO(0, 0, 0, _opacitaLogo)
      ..filterQuality = FilterQuality.medium;
    return (canvas, o) => canvas.drawImageRect(
        img, origine, Rect.fromLTWH(o.dx + (_lato - w) / 2, o.dy + (_lato - h) / 2, w, h), pennello);
  }

  void Function(Canvas, Offset) _martelletto() {
    final testo = TextPainter(
      text: TextSpan(
        text: String.fromCharCode(Icons.gavel.codePoint),
        style: TextStyle(
          fontFamily: Icons.gavel.fontFamily,
          package: Icons.gavel.fontPackage,
          fontSize: _lato,
          color: colore.withValues(alpha: _opacitaMartelletto),
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    return (canvas, o) => testo.paint(canvas, o);
  }

  @override
  bool shouldRepaint(_Mattonelle vecchio) => vecchio.immagine != immagine || vecchio.colore != colore;
}
