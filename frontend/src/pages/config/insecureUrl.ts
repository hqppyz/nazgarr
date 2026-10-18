// http:// verso un host pubblico (decisione dell'utente, 2026-10-18): un
// tracker, un client o un Radarr/Sonarr così si salva lo stesso, con un
// avviso. Sulle schede decide il server (insecure_public_url, che risolve il
// nome); mentre si scrive l'indirizzo nel form basta questa stima: la LAN, il
// loopback, Tailscale (100.64.0.0/10), un nome di una parola sola (un
// container, un host di casa) e i domini locali non sono pubblici.
const LOCAL_SUFFIXES = ['.local', '.lan', '.home', '.home.arpa', '.internal', '.localdomain', '.localhost', '.ts.net']

function privateIPv4(host: string): boolean | null {
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host)
  if (!match) return null
  const [a, b] = [Number(match[1]), Number(match[2])]
  return (
    a === 0 || a === 10 || a === 127 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127)
  )
}

export function plainHttpToPublicHost(url: string): boolean {
  let parsed: URL
  try {
    parsed = new URL(url.trim())
  } catch {
    return false
  }
  if (parsed.protocol !== 'http:') return false
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '')
  if (!host) return false
  const v4 = privateIPv4(host)
  if (v4 !== null) return !v4
  if (host.includes(':')) {
    return !(host === '::1' || host.startsWith('fc') || host.startsWith('fd') || host.startsWith('fe80'))
  }
  if (host === 'localhost' || !host.includes('.')) return false
  return !LOCAL_SUFFIXES.some((suffix) => host.endsWith(suffix))
}

// L'avviso di un form: quello del server finché l'indirizzo è quello salvato,
// la stima appena lo si cambia.
export function insecureUrlWarning(typed: string, saved?: { base_url: string; insecure_public_url?: boolean }) {
  if (saved && typed.trim() === saved.base_url) return Boolean(saved.insecure_public_url)
  return plainHttpToPublicHost(typed)
}
