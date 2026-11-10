"""Catalogo dei procedimenti (art. 35 d.lgs. 33/2013): dato condiviso tra il modulo
anticorruzione e il modulo trasparenza, contrattualizzabili separatamente.

I procedimenti sono i processi della mappatura con tipo PROCEDIMENTO (tabella ac_processi) e i
loro dati dell'art. 35. Chi li modifica dipende dai moduli attivi dell'ente:

- con il modulo anticorruzione (da solo o con la trasparenza) fanno parte della mappatura e
  seguono il suo iter: il referente propone, il RPCT approva (o modifica direttamente); la
  trasparenza li legge e li importa nella scheda art. 35;
- con il solo modulo trasparenza l'operatore della trasparenza li crea, modifica ed elimina
  direttamente, senza aree di rischio, attività, rischi e misure.

Se l'ente aggiunge l'anticorruzione, i procedimenti inseriti diventano la base della mappatura
(codice P.n, senza area finché il RPCT non la assegna); se la toglie, i dati restano e i
procedimenti tornano modificabili dalla trasparenza (processi, rischi e misure restano, non
visibili). La pagina pubblica dei procedimenti c'è con almeno uno dei due moduli.
"""

from common.models import Ente, Modulo


def disponibili(ente: Ente) -> bool:
    """L'ente ha il catalogo dei procedimenti (almeno uno dei due moduli)."""
    return ente.modulo_attivo(Modulo.ANTICORRUZIONE) or ente.modulo_attivo(Modulo.TRASPARENZA)


def con_iter(ente: Ente) -> bool:
    """I procedimenti si modificano con l'iter della mappatura dell'anticorruzione; altrimenti
    direttamente dalla trasparenza."""
    return ente.modulo_attivo(Modulo.ANTICORRUZIONE)
