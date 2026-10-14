"""Event loop persistente per eseguire il codice asincrono dalle viste Flask.

La libreria comune (database, Normattiva, LLM, verifiche) è asincrona ed è condivisa con
il worker. Flask gira invece su thread WSGI: ogni processo ha un solo event loop, in un
thread dedicato, su cui girano tutte le coroutine delle richieste. Così il pool di
connessioni al database e i client HTTP restano legati sempre allo stesso loop.

Le coroutine ricevono una copia del contesto del thread chiamante: `flask.request` e
`flask.g` funzionano anche dentro il loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class CicloAsync:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        pronto = threading.Event()
        self.loop.call_soon(pronto.set)
        self._thread = threading.Thread(
            target=self.loop.run_forever, name="atti-pa-asyncio", daemon=True
        )
        self._thread.start()
        pronto.wait()

    def esegui(self, coro: Coroutine[Any, Any, T]) -> T:
        """Esegue la coroutine sul loop e ne attende il risultato dal thread chiamante."""
        if not self.loop.is_running():
            coro.close()
            raise RuntimeError("Event loop dell'applicazione già fermato")
        contesto = contextvars.copy_context()
        futuro: concurrent.futures.Future[T] = concurrent.futures.Future()

        def avvia() -> None:
            task = self.loop.create_task(coro, context=contesto)

            def completa(t: asyncio.Task) -> None:
                if t.cancelled():
                    futuro.cancel()
                elif (errore := t.exception()) is not None:
                    futuro.set_exception(errore)
                else:
                    futuro.set_result(t.result())

            task.add_done_callback(completa)

        self.loop.call_soon_threadsafe(avvia)
        return futuro.result()

    def chiudi(self) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=5)
