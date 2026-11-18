"""Catalogo dei procedimenti (art. 35 d.lgs. 33/2013): dato condiviso tra il modulo
anticorruzione e il modulo trasparenza, contrattualizzabili separatamente.

I procedimenti stanno nella tabella ac_procedimenti (codici P.n), con i loro dati dell'art. 35;
non sono processi: nella mappatura dell'anticorruzione un'attività di un processo può essere un
procedimento del catalogo (AcAttivita.procedimento_id), e lo stesso procedimento può comparire
in più processi. Chi li modifica dipende dai moduli attivi dell'ente:

- con il modulo anticorruzione (da solo o con la trasparenza) il RPCT li gestisce nel catalogo
  dell'anticorruzione e i referenti propongono (iter di approvazione); la trasparenza li legge e
  li importa nella scheda art. 35;
- con il solo modulo trasparenza l'operatore della trasparenza li crea, modifica ed elimina
  direttamente.

Se l'ente aggiunge o toglie l'anticorruzione i procedimenti restano gli stessi; cambia solo chi
li modifica. Un procedimento che è un'attività della mappatura non si elimina. La pagina
pubblica dei procedimenti c'è con almeno uno dei due moduli.
"""

from common.models import Ente, Modulo


def disponibili(ente: Ente) -> bool:
    """L'ente ha il catalogo dei procedimenti (almeno uno dei due moduli)."""
    return ente.modulo_attivo(Modulo.ANTICORRUZIONE) or ente.modulo_attivo(Modulo.TRASPARENZA)


def con_iter(ente: Ente) -> bool:
    """I procedimenti si modificano con l'iter della mappatura dell'anticorruzione; altrimenti
    direttamente dalla trasparenza."""
    return ente.modulo_attivo(Modulo.ANTICORRUZIONE)
