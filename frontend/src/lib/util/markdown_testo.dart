import 'package:markdown/markdown.dart' as md;

// Il markdown delle risposte dell'assistente, per copiarle fuori dall'app: in HTML (grassetto,
// elenchi e tabelle restano tali in un'email o in un documento) e in testo semplice, senza i
// simboli del markdown (per chi incolla solo testo).

/// HTML del [markdown] (come GitHub: tabelle, elenchi, barrato); le tabelle con i bordi, che
/// nelle email altrimenti non si vedono.
String markdownInHtml(String markdown) => md
    .markdownToHtml(markdown, extensionSet: md.ExtensionSet.gitHubFlavored)
    .replaceAll('<table>', '<table style="border-collapse: collapse">')
    .replaceAllMapped(RegExp(r'<(t[hd])(?=[ >])'), (m) => '<${m[1]} style="border: 1px solid #999; padding: 4px 8px"');

/// Testo semplice del [markdown]: paragrafi separati da una riga vuota, elenchi con "-" o con
/// il numero, celle delle tabelle separate da tabulazioni.
String markdownInTesto(String markdown) {
  final nodi = md.Document(extensionSet: md.ExtensionSet.gitHubFlavored, encodeHtml: false)
      .parseLines(markdown.replaceAll('\r\n', '\n').split('\n'));
  return _blocchi(nodi, '').trimRight().replaceAll(RegExp(r'\n{3,}'), '\n\n');
}

const _blocco = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'pre', 'blockquote', 'hr', 'table'};

String _blocchi(List<md.Node> nodi, String rientro) {
  final b = StringBuffer();
  for (final n in nodi) {
    if (n is! md.Element) {
      b.write('$rientro${n.textContent.trim()}\n\n');
      continue;
    }
    switch (n.tag) {
      case 'ul' || 'ol':
        var numero = int.tryParse(n.attributes['start'] ?? '') ?? 1;
        for (final li in (n.children ?? const <md.Node>[]).whereType<md.Element>()) {
          final segno = n.tag == 'ol' ? '${numero++}. ' : '- ';
          b.write('$rientro$segno${_voce(li, '$rientro${' ' * segno.length}')}\n');
        }
        b.write('\n');
      case 'pre':
        b.write('${n.textContent.trimRight()}\n\n');
      case 'hr':
        b.write('$rientro———\n\n');
      case 'blockquote':
        b.write(_blocchi(n.children ?? const [], rientro));
      case 'table':
        for (final riga in _righe(n)) {
          b.write('$rientro${riga.join('\t')}\n');
        }
        b.write('\n');
      default: // paragrafi e titoli
        b.write('$rientro${_inline(n)}\n\n');
    }
  }
  return b.toString();
}

/// Una voce di elenco: il testo e, sotto, gli elenchi annidati rientrati.
String _voce(md.Element li, String rientro) {
  final figli = li.children ?? const <md.Node>[];
  final testo = StringBuffer(), sotto = <md.Node>[];
  for (final n in figli) {
    if (n is md.Element && _blocco.contains(n.tag)) {
      if (n.tag == 'p' && sotto.isEmpty && testo.isEmpty) {
        testo.write(_inline(n));
      } else {
        sotto.add(n);
      }
    } else {
      testo.write(n is md.Element ? _inline(n) : n.textContent);
    }
  }
  final resto = _blocchi(sotto, rientro).trimRight();
  return resto.isEmpty ? testo.toString().trim() : '${testo.toString().trim()}\n$resto';
}

String _inline(md.Node n) {
  if (n is! md.Element) return n.textContent;
  if (n.tag == 'br') return '\n';
  if (n.tag == 'img') return n.attributes['alt'] ?? '';
  final testo = (n.children ?? const <md.Node>[]).map(_inline).join();
  // il collegamento con un testo diverso dall'indirizzo: anche l'indirizzo
  final href = n.attributes['href'];
  return n.tag == 'a' && href != null && href != testo ? '$testo ($href)' : testo;
}

List<List<String>> _righe(md.Element tabella) => [
      for (final sezione in (tabella.children ?? const <md.Node>[]).whereType<md.Element>())
        for (final tr in (sezione.children ?? const <md.Node>[]).whereType<md.Element>())
          [for (final cella in (tr.children ?? const <md.Node>[]).whereType<md.Element>()) _inline(cella).trim()],
    ];
