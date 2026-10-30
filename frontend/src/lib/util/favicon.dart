// Favicon della scheda del browser: il logo dell'ente, o il martelletto se non c'è; nei test,
// che girano fuori dal browser, non fa nulla.
export 'favicon_vm.dart' if (dart.library.js_interop) 'favicon_web.dart';
