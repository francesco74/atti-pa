// Client HTTP: nel browser invia i cookie anche verso un'altra origine (sviluppo);
// nei test, che girano sulla VM Dart, si usa il client standard.
export 'http_client_vm.dart' if (dart.library.js_interop) 'http_client_web.dart';
