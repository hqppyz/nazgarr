// Le card della vista a poster (src/pages/library/PosterView.tsx), dai
// titoli della libreria.

import type { Schemas } from '@/api/client'

type MediaItemOverview = Schemas['MediaItemOverview']

// Una card per film, una per SERIE (non per episodio: a parità di
// poster sarebbero migliaia di card identiche).
export interface PosterCard {
  key: string
  content_type: string
  tmdb_id: number
  title: string | null
  year: number | null
  has_poster: boolean
  episodes: number
  sizeBytes: number
  counts: Record<StatusKey, number>
}

// Pallini di stato, contati per file (per una serie: per episodio). I
// file esclusi non contano mai, come nel resto dell'interfaccia.
export type StatusKey = 'seeding' | 'orphan' | 'review' | 'duplicate'

export function toCards(items: MediaItemOverview[]): PosterCard[] {
  const cards = new Map<string, PosterCard>()
  for (const item of items) {
    const key = `${item.content_type}-${item.tmdb_id}`
    const card = cards.get(key) ?? {
      key, content_type: item.content_type, tmdb_id: item.tmdb_id, title: null, year: null,
      has_poster: false, episodes: 0, sizeBytes: 0, counts: { seeding: 0, orphan: 0, review: 0, duplicate: 0 },
    }
    card.title ??= item.title ?? null
    card.year ??= item.year ?? null
    card.has_poster ||= item.has_poster
    card.episodes += 1
    for (const f of item.files) {
      if (f.excluded) continue
      card.sizeBytes += f.size_bytes ?? 0
      if (f.state === 'seeding') card.counts.seeding += 1
      else card.counts.orphan += 1
      if (f.in_review) card.counts.review += 1
      if (f.duplicate) card.counts.duplicate += 1
    }
    cards.set(key, card)
  }
  // Un titolo con soli file esclusi (es. un sample o un extra identificato
  // come film) è fuori da ogni controllo come i suoi file: senza questo
  // contava nel Total senza essere né seeding né orfano.
  return [...cards.values()].filter((c) => c.counts.seeding + c.counts.orphan > 0).sort((a, b) =>
    (a.title ?? '\uffff').localeCompare(b.title ?? '\uffff') || a.tmdb_id - b.tmdb_id,
  )
}
