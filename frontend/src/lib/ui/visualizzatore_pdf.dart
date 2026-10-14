// Visualizzatore del PDF di un atto: nel browser un riquadro (iframe) con il visualizzatore
// PDF integrato; nei test, che girano fuori dal browser, un semplice segnaposto.
export 'visualizzatore_pdf_vm.dart' if (dart.library.js_interop) 'visualizzatore_pdf_web.dart';
