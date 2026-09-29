// localStorage invece che in-memory: un JWT valido 30 giorni (app/auth.py)
// deve sopravvivere a un refresh della pagina, non solo alla sessione tab.
const STORAGE_KEY = 'nazgarr_token'
// Prima del rename del progetto (Gauntletarr -> Nazgarr): letta una volta e
// spostata sulla chiave nuova, così nessuno viene disconnesso dal rename.
const LEGACY_STORAGE_KEY = 'gauntletarr_token'

export function getToken(): string | null {
  try {
    const token = localStorage.getItem(STORAGE_KEY)
    if (token != null) return token
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (legacy != null) {
      localStorage.setItem(STORAGE_KEY, legacy)
      localStorage.removeItem(LEGACY_STORAGE_KEY)
    }
    return legacy
  } catch {
    return null
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token)
  } catch {
    // storage non disponibile (privata/bloccato): l'utente dovrà rifare
    // login a ogni refresh, mai un errore bloccante per questo.
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // vedi sopra
  }
}
