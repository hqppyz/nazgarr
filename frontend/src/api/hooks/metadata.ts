import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { uiLocale } from '@/lib/i18n'

// Candidato TMDB di un upload (nazgarr/tmdb_client.py normalize_result), più la
// fonte da cui è arrivato (nazgarr/upload_identify.py).
export interface MetadataCandidate {
  tmdb_id: number
  content_type: 'movie' | 'tv'
  title: string | null
  original_title?: string | null
  year: number | null
  poster_path: string | null
  overview?: string | null
  source?: string
  // Solo nei candidati di un upload (nazgarr/upload_match_score.py).
  confidence?: number
  ambiguous?: boolean
  confidence_parts?: { basis: 'forced' | 'arr' | 'name'; title?: number; year?: number; type?: number }
}

export interface MetadataSeason {
  season_number: number
  name: string | null
  episode_count: number
  air_date: string | null
}

export interface MetadataDetails extends MetadataCandidate {
  genres: string[]
  runtime: number | null
  imdb_id: string | null
  tvdb_id: number | null
  cast: string[]
  original_language: string | null
  seasons: MetadataSeason[]
}

export function posterUrl(candidate: Pick<MetadataCandidate, 'content_type' | 'tmdb_id' | 'poster_path'>) {
  const base = `/api/metadata/posters/${candidate.content_type}/${candidate.tmdb_id}.jpg`
  return candidate.poster_path ? `${base}?path=${encodeURIComponent(candidate.poster_path)}` : base
}

export function useMetadataDetails(contentType: string | null, tmdbId: number | null) {
  return useQuery({
    // Nella lingua dell'interfaccia; quello che TMDB lì non ha, in inglese.
    queryKey: ['metadata', contentType, tmdbId, uiLocale()],
    queryFn: async () =>
      (await unwrap(
        api.GET('/api/metadata/{content_type}/{tmdb_id}', {
          params: { path: { content_type: contentType!, tmdb_id: tmdbId! }, query: { language: uiLocale() } },
        }),
      )) as unknown as MetadataDetails,
    enabled: contentType !== null && tmdbId !== null,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
}

export function useMetadataSearch(contentType: 'movie' | 'tv', query: string, year: number | null) {
  return useQuery({
    queryKey: ['metadata', 'search', contentType, query, year, uiLocale()],
    queryFn: async () =>
      (await unwrap(
        api.GET('/api/metadata/search', {
          params: { query: { content_type: contentType, query, year: year ?? undefined, language: uiLocale() } },
        }),
      )) as unknown as MetadataCandidate[],
    enabled: query.trim().length > 0,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
}
