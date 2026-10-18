import type { MessageKey } from '@/locales/en'

/**
 * Dizionario leggero, niente libreria i18n pesante (react-i18next e simili):
 * un'app di amministrazione self-hosted con un solo utente reale non
 * giustifica il peso extra. Due lingue, inglese e italiano (src/locales/<lang>):
 * la scelta sta nel browser (Settings › Interface), di default la lingua del
 * browser. Cambiarla ricarica la pagina: molte etichette si calcolano una
 * volta sola, al caricamento dei moduli.
 *
 * I placeholder nel template sono {nome}, sostituiti con params[nome] —
 * un array viene unito con ", ", tutto il resto passa per String(). Una
 * chiave assente ritorna la chiave stessa invece di lanciare, così una UI
 * mai perfettamente in sync col backend resta comunque leggibile invece di
 * rompersi. L'italiano ha per tipo ogni chiave dell'inglese
 * (locales/it/index.ts): un'inglese di riserva non servirebbe mai.
 */
export const LOCALES = ['en', 'it'] as const
export type Locale = (typeof LOCALES)[number]
export const LOCALE_NAMES: Record<Locale, string> = { en: 'English', it: 'Italiano' }
const STORAGE_KEY = 'nazgarr-locale'

function detect(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && (LOCALES as readonly string[]).includes(saved)) return saved as Locale
  } catch {
    // localStorage non disponibile (es. navigazione privata): la lingua del browser
  }
  const browser = typeof navigator !== 'undefined' ? navigator.language.toLowerCase() : 'en'
  return browser.startsWith('it') ? 'it' : 'en'
}

let current: Locale = detect()

// Solo il dizionario della lingua scelta: l'altro (circa 150 KB, 45 KB gzip)
// non si scarica né si analizza più a ogni caricamento (audit 2026-10-18).
// Top-level await: ogni modulo che importa t() aspetta il dizionario prima
// di eseguirsi, anche le etichette calcolate al caricamento (lib/nav.ts).
const DICTIONARY: Record<string, string> =
  current === 'it' ? (await import('@/locales/it')).it : (await import('@/locales/en')).en

export function currentLocale(): Locale {
  return current
}

// Per Intl (date, numeri, nomi delle lingue): "it-IT", "en-US".
export function uiLocale(): string {
  return current === 'it' ? 'it-IT' : 'en-US'
}

export function setLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // niente da salvare: vale fino alla chiusura della pagina
  }
  current = locale
  if (typeof document !== 'undefined') document.documentElement.lang = locale
}

if (typeof document !== 'undefined') document.documentElement.lang = current

export function t(key: MessageKey | (string & {}), params?: Record<string, unknown>): string {
  const template = DICTIONARY[key] ?? key
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    if (!(name in params)) return match
    const value = params[name]
    return Array.isArray(value) ? value.join(', ') : String(value)
  })
}
