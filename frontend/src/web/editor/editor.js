'use strict';

// Editor dei documenti della trasparenza (Summernote), dentro un iframe dell'app.
// Parla con l'app solo con postMessage, e solo con la finestra che lo contiene:
//   app -> editor: imposta {html, barra}, barra {visibile}, leggi {id}
//   editor -> app: pronto, caricato {html}, modifica {html}, testo {id, html}
(function () {
  var origine = window.location.origin;
  var $editor = $('#editor');
  var avviato = false;

  function invia(messaggio) {
    window.parent.postMessage(messaggio, origine);
  }

  // Contenuto attuale, anche mentre si modifica il codice HTML: in quel caso passa dal
  // filtro di Summernote come quando si torna all'editor visuale.
  function contenuto() {
    var html = $editor.summernote('code');
    return $editor.summernote('codeview.isActivated') ? $editor.summernote('codeview.purify', html) : html;
  }

  function barra(visibile) {
    $('.note-editor').toggleClass('barra-nascosta', !visibile);
  }

  // Il documento entra nell'elemento prima di creare l'editor, così la cronologia delle
  // modifiche parte da lì (annullare non lo svuota). innerHTML non esegue script e quelli
  // presenti si tolgono comunque: l'HTML arriva già pulito dall'API.
  function avvia(html, barraVisibile) {
    var elemento = $editor[0];
    elemento.innerHTML = html || '';
    elemento.querySelectorAll('script').forEach(function (s) { s.remove(); });
    $editor.summernote({
      lang: 'it-IT',
      placeholder: 'Il contenuto del documento compare qui...',
      dialogsInBody: true,
      disableDragAndDrop: true,
      // Il filtro del codice HTML è quello di Summernote ma lascia i blocchi <style>,
      // che l'API ammette nei documenti
      codeviewFilter: true,
      codeviewFilterRegex: /<\/*(?:applet|b(?:ase|gsound|link)|embed|frame(?:set)?|ilayer|l(?:ayer|ink)|meta|object|script|t(?:itle|extarea)|xml)[^>]*?>/gi,
      codeviewIframeFilter: true,
      codeviewIframeWhitelistSrcBase: [],
      toolbar: [
        ['stile', ['style']],
        ['carattere', ['bold', 'italic', 'underline', 'strikethrough', 'superscript', 'subscript', 'clear']],
        ['colore', ['color']],
        ['paragrafo', ['ul', 'ol', 'paragraph']],
        ['inserisci', ['link', 'picture', 'table', 'hr']],
        ['altro', ['undo', 'redo', 'codeview']],
      ],
      callbacks: {
        onChange: function () {
          invia({ tipo: 'modifica', html: contenuto() });
        },
        onChangeCodeview: function () {
          invia({ tipo: 'modifica', html: contenuto() });
        },
      },
    });
    barra(barraVisibile !== false);
    avviato = true;
    invia({ tipo: 'caricato', html: contenuto() });
  }

  window.addEventListener('message', function (evento) {
    if (evento.origin !== origine || evento.source !== window.parent) return;
    var m = evento.data || {};
    switch (m.tipo) {
      case 'imposta':
        if (!avviato) avvia(m.html, m.barra);
        break;
      case 'barra':
        barra(m.visibile);
        break;
      case 'leggi':
        invia({ tipo: 'testo', id: m.id, html: avviato ? contenuto() : null });
        break;
    }
  });

  invia({ tipo: 'pronto' });
})();
