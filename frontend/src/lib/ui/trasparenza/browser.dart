// Funzioni del browser usate dalla trasparenza (anteprima e download di file, avviso
// all'uscita dalla pagina con modifiche non salvate); nei test, fuori dal browser, non fanno
// nulla.
export 'browser_vm.dart' if (dart.library.js_interop) 'browser_web.dart';
