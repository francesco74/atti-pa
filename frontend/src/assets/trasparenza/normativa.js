// Testo per l'assistenza agli utenti configurato dall'ente (Amministrazione > Profilo
// dell'ente), in fondo alla pagina della normativa. Indirizzo dell'API da config.json (vuoto:
// stessa origine); l'ente si riconosce dal dominio. Il testo si inserisce come testo, mai come
// HTML: indirizzi email e link diventano collegamenti.
(async function () {
  const paragrafo = document.getElementById('assistenza');
  if (!paragrafo) return;
  try {
    let api = '';
    try {
      const config = await (await fetch('/config.json', { cache: 'no-store' })).json();
      api = (config.API_URL || '').replace(/\/+$/, '');
    } catch (_) {
      // senza config.json: stessa origine
    }
    const risposta = await fetch(`${api}/api/v1/auth/ente`, { credentials: 'omit' });
    if (!risposta.ok) return;
    const testo = ((await risposta.json()).ente || {}).assistenza;
    if (!testo || !testo.trim()) return;
    const collegamento = /(https?:\/\/[^\s<>"]+[^\s<>".,;:!?)]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)/g;
    let inizio = 0;
    for (const m of testo.trim().matchAll(collegamento)) {
      paragrafo.append(document.createTextNode(testo.trim().slice(inizio, m.index)));
      const a = document.createElement('a');
      a.textContent = m[0];
      a.href = m[0].includes('@') && !m[0].startsWith('http') ? `mailto:${m[0]}` : m[0];
      a.target = '_blank';
      a.rel = 'noopener';
      paragrafo.append(a);
      inizio = m.index + m[0].length;
    }
    paragrafo.append(document.createTextNode(testo.trim().slice(inizio)));
    paragrafo.hidden = false;
  } catch (_) {
    // API non raggiungibile: la pagina resta senza il paragrafo
  }
})();
