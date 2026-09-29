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

// Bozza della decisione per un tracker, al secondo punto di approvazione.
// touched: i campi che l'utente ha cambiato a mano; gli altri seguono i
// valori proposti dal backend, che cambiano quando si salvano gli override.
export interface TargetDraft {
  action: 'upload' | 'reseed' | 'skip'
  name: string
  category_id: number | null
  type_id: number | null
  resolution_id: number | null
  flags: Record<string, boolean>
  reseed_torrent_id: string | null
  touched: (keyof Omit<TargetDraft, 'touched'>)[]
}

interface DraftSource {
  suggested_action: string | null
  proposed_name: string | null
  category_id: number | null
  type_id: number | null
  resolution_id: number | null
  flags: Record<string, unknown>
  reseed_torrent_id: string | null
  dupes: unknown[]
}

export function initialDraft(target: DraftSource): TargetDraft {
  const identical = (target.dupes as { torrent_id_remote: string; verdict: string }[]).filter(
    (d) => d.verdict === 'identical',
  )
  const suggested = target.suggested_action
  return {
    action: suggested === 'reseed' || suggested === 'skip' ? suggested : 'upload',
    name: target.proposed_name ?? '',
    category_id: target.category_id,
    type_id: target.type_id,
    resolution_id: target.resolution_id,
    flags: Object.fromEntries(Object.entries(target.flags).map(([k, v]) => [k, v === true])),
    reseed_torrent_id: target.reseed_torrent_id ?? identical[0]?.torrent_id_remote ?? null,
    touched: [],
  }
}

/** La bozza da mostrare: i campi toccati dall'utente, il resto proposto. */
export function effectiveDraft(edits: Partial<TargetDraft> | undefined, target: DraftSource): TargetDraft {
  const fresh = initialDraft(target)
  if (!edits) return fresh
  const out: TargetDraft = { ...fresh, touched: edits.touched ?? [] }
  for (const key of out.touched) (out as unknown as Record<string, unknown>)[key] = edits[key]
  return out
}

export function editDraft(draft: TargetDraft, patch: Partial<Omit<TargetDraft, 'touched'>>): TargetDraft {
  const touched = new Set(draft.touched)
  for (const key of Object.keys(patch)) touched.add(key as keyof Omit<TargetDraft, 'touched'>)
  return { ...draft, ...patch, touched: [...touched] }
}

export function draftProblem(draft: TargetDraft): string | null {
  if (draft.action === 'upload') {
    if (!draft.name.trim()) return 'upload.decision.problem.name'
    if (draft.category_id == null || draft.type_id == null || draft.resolution_id == null) {
      return 'upload.decision.problem.ids'
    }
  }
  if (draft.action === 'reseed' && !draft.reseed_torrent_id) return 'upload.decision.problem.reseed'
  return null
}
