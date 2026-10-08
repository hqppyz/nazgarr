// La coda di revisione raggruppata: gli episodi singoli della stessa stagione,
// dello stesso tracker, stanno in una riga sola (decisione dell'utente,
// 2026-10-08). Un pack, un film, un episodio da solo restano una riga ciascuno.

export interface GroupableReview {
  direction: string
  format: string
  tracker_id: number
  tmdb_id?: number | null
  season_number?: number | null
  episode_number?: number | null
}

function seasonKey(review: GroupableReview): string | null {
  if (review.format !== 'single' || review.tmdb_id == null || review.season_number == null || review.episode_number == null) {
    return null
  }
  return `${review.direction}:${review.tracker_id}:${review.tmdb_id}:${review.season_number}`
}

// Nell'ordine della coda (la posizione del primo di ogni gruppo), gli episodi
// in ordine di numero.
export function groupBySeason<T extends GroupableReview>(reviews: T[]): T[][] {
  const groups = new Map<string, T[]>()
  const result: T[][] = []
  for (const review of reviews) {
    const key = seasonKey(review)
    const group = key !== null ? groups.get(key) : undefined
    if (group) {
      group.push(review)
    } else {
      const fresh = [review]
      if (key !== null) groups.set(key, fresh)
      result.push(fresh)
    }
  }
  return result.map((group) => [...group].sort((a, b) => (a.episode_number ?? 0) - (b.episode_number ?? 0)))
}

const pad = (n: number) => String(n).padStart(2, '0')

// "E01–E04, E07": quali episodi ci sono, a intervalli.
export function episodeRanges(numbers: number[]): string {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b)
  const parts: string[] = []
  for (let i = 0; i < sorted.length; i++) {
    const start = sorted[i]
    while (i + 1 < sorted.length && sorted[i + 1] === sorted[i] + 1) i++
    parts.push(sorted[i] === start ? `E${pad(start)}` : `E${pad(start)}–E${pad(sorted[i])}`)
  }
  return parts.join(', ')
}

export function seasonLabel(season: number): string {
  return `S${pad(season)}`
}
