// Dopo un aggiornamento del container i chunk della build vecchia non ci sono
// più (/assets risponde 404): una scheda rimasta aperta, al primo import
// dinamico che non aveva ancora scaricato, non può più caricarlo. L'unico
// rimedio è ricaricare la pagina, che prende la build nuova. Lo fa la vista
// che ne aveva bisogno (CrashPanel, il fallback delle pagine e dell'app), non
// un ascoltatore globale di `vite:preloadError`: un chunk decorativo (l'anello
// del logo) o un precaricamento di fondo che fallisce non deve ricaricare la
// pagina sotto le mani di chi scrive (audit 2026-10-18).

const CHUNK_ERROR =
  /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS/i

export function isChunkLoadError(error: unknown): boolean {
  return error instanceof Error && CHUNK_ERROR.test(error.message)
}

const FLAG = 'nazgarr-chunk-reload'
// Una ricarica appena fatta che non è bastata (il chunk manca anche nella
// build nuova): niente giro infinito, decide l'utente dal messaggio.
const LOOP_WINDOW_MS = 60_000

// Il chunk non si scarica: ricarica la pagina, una volta sola per finestra.
// Vero se la ricarica è partita; falso lascia l'errore all'ErrorBoundary.
export function reloadOnce(
  storage: Pick<Storage, 'getItem' | 'setItem'> = window.sessionStorage,
  reload: () => void = () => window.location.reload(),
  now: number = Date.now(),
): boolean {
  try {
    const last = Number(storage.getItem(FLAG))
    if (Number.isFinite(last) && last > 0 && now - last < LOOP_WINDOW_MS) return false
    storage.setItem(FLAG, String(now))
  } catch {
    return false // senza storage non si può evitare il giro: meglio il messaggio
  }
  reload()
  return true
}
