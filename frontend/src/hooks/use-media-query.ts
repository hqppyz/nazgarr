import { useSyncExternalStore } from 'react'

// Senza matchMedia (test in jsdom): mai vera.
const hasMatchMedia = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'

// Una media query, letta subito al primo render (useSyncExternalStore) e
// aggiornata quando cambia: niente primo render col valore sbagliato e un
// setState in un effetto per correggerlo.
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (!hasMatchMedia()) return () => {}
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    () => hasMatchMedia() && window.matchMedia(query).matches,
    () => false,
  )
}
