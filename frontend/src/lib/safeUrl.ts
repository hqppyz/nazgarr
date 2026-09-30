// Un link costruito con dati che arrivano da fuori (URL di un tracker o di
// Radarr/Sonarr salvati nelle impostazioni, link restituiti da un tracker o
// da un host di immagini): solo http(s). Un "javascript:..." eseguirebbe
// codice al clic, con il token di login a portata di mano.
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : undefined
  } catch {
    return undefined
  }
}
