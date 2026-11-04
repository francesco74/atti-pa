"""Posta in uscita: messaggio SMTP (mittente, risposta, STARTTLS/SSL, login con la password
decifrata), coda di invio con i nuovi tentativi ad attese crescenti, errore dopo l'ultimo
tentativo o subito per gli errori definitivi (indirizzo rifiutato, ente senza posta).
    python -m unittest common.tests.test_posta
"""

from __future__ import annotations

import asyncio
import smtplib
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common import posta
from common.cifratura import cifra
from common.models import Base, Ente, NotificaEmail

SEGRETO = "segreto-di-prova"


class Invio(unittest.TestCase):
    def _config(self, **altro):
        return posta.ConfigSmtp(host="smtp.example.it", porta=587, utente="atti", mittente="Ente <atti@example.it>",
                                password_cifrata=cifra("pw", SEGRETO), rispondi_a="rpct@example.it", **altro)  # fmt: skip

    def test_starttls_e_login(self):
        with mock.patch("smtplib.SMTP") as smtp:
            server = smtp.return_value
            posta.invia(self._config(), SEGRETO, "a@example.it", "Oggetto", "Testo àè")
        smtp.assert_called_once_with("smtp.example.it", 587, timeout=20.0)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("atti", "pw")
        messaggio = server.send_message.call_args.args[0]
        self.assertEqual((messaggio["From"], messaggio["To"], messaggio["Reply-To"]),
                         ("Ente <atti@example.it>", "a@example.it", "rpct@example.it"))  # fmt: skip
        self.assertIn("Testo àè", messaggio.get_content())

    def test_ssl_e_senza_autenticazione(self):
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            server = smtp.return_value
            posta.invia(self._config(sicurezza="SSL").model_copy(update={"utente": None}), SEGRETO, "a@example.it", "O", "T")
        server.starttls.assert_not_called()
        server.login.assert_not_called()

    def test_errori(self):
        with mock.patch("smtplib.SMTP") as smtp:
            server = smtp.return_value
            server.send_message.side_effect = smtplib.SMTPRecipientsRefused({"a@example.it": (550, b"no")})
            with self.assertRaises(posta.ErrorePosta) as e:
                posta.invia(self._config(), SEGRETO, "a@example.it", "O", "T")
            self.assertTrue(e.exception.definitivo)
            smtp.side_effect = OSError("Connection refused")
            with self.assertRaises(posta.ErrorePosta) as e:
                posta.invia(self._config(), SEGRETO, "a@example.it", "O", "T")
            self.assertFalse(e.exception.definitivo)
        with self.assertRaises(posta.ErrorePosta) as e:  # CHIAVE_CIFRATURA cambiata
            posta.invia(self._config(), "altro-segreto", "a@example.it", "O", "T")
        self.assertTrue(e.exception.definitivo)

    def test_indirizzi(self):
        self.assertTrue(posta.indirizzo_valido("Ente <atti@example.it>"))
        for sbagliato in (None, "", "atti", "atti@", "atti@example"):
            self.assertFalse(posta.indirizzo_valido(sbagliato), sbagliato)


class Coda(unittest.TestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.motore = create_async_engine(f"sqlite+aiosqlite:///{self.cartella.name}/prova.db")
        self.sessioni = async_sessionmaker(self.motore, expire_on_commit=False)

        async def prepara():
            async with self.motore.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            async with self.sessioni() as db:
                self.ente = Ente(codice="e", nome="Ente", dati_json={}, moduli_json=[],
                                 smtp_json={"host": "smtp.example.it", "mittente": "atti@example.it"})  # fmt: skip
                self.senza = Ente(codice="s", nome="Senza", dati_json={}, moduli_json=[])
                db.add_all([self.ente, self.senza])
                await db.flush()
                self.assertEqual(posta.accoda(db, self.ente, ["a@example.it", "A@example.it", None, "x"], "O", "T"), 1)
                self.assertEqual(posta.accoda(db, self.senza, ["b@example.it"], "O", "T"), 0)
                await db.commit()

        asyncio.run(prepara())

    def tearDown(self):
        asyncio.run(self.motore.dispose())
        self.cartella.cleanup()

    def _stato(self):
        async def leggi():
            async with self.sessioni() as db:
                return [(n.destinatario, n.stato, n.tentativi, n.prossimo_tentativo) for n in await db.scalars(select(NotificaEmail))]

        return asyncio.run(leggi())

    def _giro(self, invio, **altro):
        return asyncio.run(posta.invia_in_sospeso(self.sessioni, SEGRETO, invio=invio, tentativi=3, **altro))

    def _anticipa(self):
        async def anticipa():
            async with self.sessioni() as db:
                await db.execute(update(NotificaEmail).values(prossimo_tentativo=datetime.now() - timedelta(seconds=1)))
                await db.commit()

        asyncio.run(anticipa())

    def test_nuovi_tentativi_poi_errore(self):
        def guasto(*_):
            raise posta.ErrorePosta("server giù")

        self.assertEqual(self._giro(guasto), (0, 1))
        [(_, stato, tentativi, prossimo)] = self._stato()
        self.assertEqual((stato, tentativi), ("DA_INVIARE", 1))
        self.assertGreater(prossimo, datetime.now())
        self.assertEqual(self._giro(guasto), (0, 0))  # non è ancora il momento
        self._anticipa()
        self._giro(guasto)
        [(_, _, tentativi, prossimo2)] = self._stato()
        self.assertEqual(tentativi, 2)
        self.assertGreater(prossimo2 - datetime.now(), timedelta(seconds=90))  # attesa raddoppiata
        self._anticipa()
        self._giro(guasto)
        self.assertEqual(self._stato()[0][1:3], ("ERRORE", 3))

    def test_invio_riuscito_e_errore_definitivo(self):
        inviate = []
        self.assertEqual(self._giro(lambda c, s, a, o, t, tm: inviate.append((c.host, a))), (1, 0))
        self.assertEqual(inviate, [("smtp.example.it", "a@example.it")])
        self.assertEqual(self._stato()[0][1], "INVIATA")
        self.assertEqual(self._giro(lambda *_: inviate.append("di nuovo")), (0, 0))

    def test_ente_senza_posta(self):
        async def togli():
            async with self.sessioni() as db:
                e = await db.get(Ente, self.ente.id)
                e.smtp_json = None
                await db.commit()

        asyncio.run(togli())
        self.assertEqual(self._giro(lambda *_: None), (0, 1))
        self.assertEqual(self._stato()[0][1], "ERRORE")


if __name__ == "__main__":
    unittest.main()
