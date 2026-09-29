// Pezzi condivisi dalle pagine del flusso di upload v2 (docs/SPEC.md §9).

import { t } from '@/lib/i18n'

export const EMPTY_IDS = { tmdb: '', imdb: '', tvdb: '', mal: '' }
export type ForcedIdsDraft = typeof EMPTY_IDS
export type IdKey = keyof ForcedIdsDraft

export const ID_FIELDS: { key: IdKey; label: string; placeholder: string }[] = [
  { key: 'tmdb', label: 'TMDB', placeholder: 'movie/603, tv/1399, URL' },
  { key: 'imdb', label: 'IMDB', placeholder: 'tt0133093' },
  { key: 'tvdb', label: 'TVDB', placeholder: '121361' },
  { key: 'mal', label: 'MAL', placeholder: '5114' },
]

export function toForcedIds(ids: ForcedIdsDraft) {
  const number = (value: string) => (/^\d+$/.test(value.trim()) ? Number(value.trim()) : undefined)
  return {
    tmdb: ids.tmdb.trim() || undefined,
    imdb: ids.imdb.trim() || undefined,
    tvdb: number(ids.tvdb),
    mal: number(ids.mal),
  }
}

export function fromForcedIds(forced: Record<string, unknown> | undefined): ForcedIdsDraft {
  const text = (value: unknown) => (value == null ? '' : String(value))
  return { tmdb: text(forced?.tmdb), imdb: text(forced?.imdb), tvdb: text(forced?.tvdb), mal: text(forced?.mal) }
}

export type UploadKind = 'movie' | 'episode' | 'season_pack' | 'complete_pack'
export const TV_KINDS: UploadKind[] = ['episode', 'season_pack', 'complete_pack']

// Episodi attesi e mancanti di una stagione, dal confronto fra i file
// trovati nella sorgente e il numero di episodi che TMDB conosce.
export function missingEpisodes(found: number[], expected: number): number[] {
  const have = new Set(found)
  const missing: number[] = []
  for (let episode = 1; episode <= expected; episode++) if (!have.has(episode)) missing.push(episode)
  return missing
}

// Il backend scrive code + params (app/upload_jobs.py log_event): la frase
// è qui, tradotta. Un codice d'errore senza una frase dedicata passa da
// errors.<code>, lo stesso dizionario degli errori delle API.
export function eventMessage(event: { code: string; params: Record<string, unknown> }) {
  const key = `upload.event.${event.code}`
  const message = t(key, event.params)
  return message === key ? t(`errors.${event.code}`, event.params) : message
}
