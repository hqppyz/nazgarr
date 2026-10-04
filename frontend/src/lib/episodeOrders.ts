import type { EpisodeOrder } from '@/api/hooks/uploads'

// La stessa traduzione di nazgarr/episode_orders.py, per l'anteprima al match:
// un episodio di un ordinamento -> gli episodi di un altro con gli stessi
// riferimenti (le stagioni di default di TMDB).

export interface MappedEpisode {
  season: number
  episode: number
  titles: string[]
}

const refKey = (ref: number[]) => `${ref[0]}x${ref[1]}`

export function translateEpisode(source: EpisodeOrder, target: EpisodeOrder, season: number, episode: number): MappedEpisode[] {
  const from = source.seasons.find((s) => s.season_number === season)?.episodes.find((e) => e.number === episode)
  if (!from) return []
  if (source.key === target.key) return [{ season, episode, titles: from.titles }]
  const wanted = new Set(from.refs.map(refKey))
  if (wanted.size === 0) return []
  const out: MappedEpisode[] = []
  for (const s of target.seasons) {
    for (const e of s.episodes) {
      if (e.refs.some((ref) => wanted.has(refKey(ref)))) out.push({ season: s.season_number, episode: e.number, titles: e.titles })
    }
  }
  return out.sort((a, b) => a.season - b.season || a.episode - b.episode)
}

export function episodeLabel(season: number, episodes: number[]): string {
  return `S${String(season).padStart(2, '0')}${episodes.map((e) => `E${String(e).padStart(2, '0')}`).join('')}`
}

// "S1 13 · S2 39 · S3 13": gli episodi per stagione, speciali in fondo.
export function seasonCounts(order: EpisodeOrder): string {
  return [...order.seasons]
    .sort((a, b) => Number(a.season_number === 0) - Number(b.season_number === 0) || a.season_number - b.season_number)
    .map((s) => `S${s.season_number} ${s.episodes.length}`)
    .join(' · ')
}

// Le fonti che non hanno dato niente, e perché: "TVDB: chiave non configurata".
export function sourceProblems(sources: Record<string, string> | undefined, t: (key: string, params?: Record<string, unknown>) => string): string[] {
  return Object.entries(sources ?? {})
    .filter(([, status]) => status !== 'ok' && status !== 'not_needed')
    .map(([source, status]) => {
      const [code, ...rest] = status.split(': ')
      return t('metadata.orderSource', {
        source: t(`metadata.orderSourceName.${source}`),
        status: code === 'error' ? t('metadata.orderStatus.error', { detail: rest.join(': ') }) : t(`metadata.orderStatus.${code}`),
      })
    })
}

