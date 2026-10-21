import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'
import { uiLocale } from '@/lib/i18n'

// Candidato TMDB di un upload (nazgarr/upload/identify.py, con la sua
// confidence: nazgarr/upload/match_score.py) o un risultato della ricerca a
// mano (nazgarr/library/tmdb_client.py normalize_result): dall'OpenAPI, non
// più scritti a mano (audit 2026-10-18). Un risultato della ricerca è un
// candidato senza confidence.
export type MetadataCandidate = Schemas['UploadCandidateResponse']
export type MetadataSearchResult = Schemas['MetadataCandidateResponse']
export type MetadataSeason = Schemas['MetadataSeasonResponse']
export type MetadataDetails = Schemas['MetadataDetailsResponse']

export function posterUrl(candidate: Pick<MetadataCandidate, 'content_type' | 'tmdb_id' | 'poster_path'>) {
  const base = `/api/metadata/posters/${candidate.content_type}/${candidate.tmdb_id}.jpg`
  return candidate.poster_path ? `${base}?path=${encodeURIComponent(candidate.poster_path)}` : base
}

export function useMetadataDetails(contentType: string | null, tmdbId: number | null) {
  return useQuery({
    // Nella lingua dell'interfaccia; quello che TMDB lì non ha, in inglese.
    queryKey: ['metadata', contentType, tmdbId, uiLocale()],
    queryFn: () =>
      unwrap(
        api.GET('/api/metadata/{content_type}/{tmdb_id}', {
          params: { path: { content_type: contentType!, tmdb_id: tmdbId! }, query: { language: uiLocale() } },
        }),
      ),
    enabled: contentType !== null && tmdbId !== null,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
}

export function useMetadataSearch(contentType: 'movie' | 'tv', query: string, year: number | null) {
  return useQuery({
    queryKey: ['metadata', 'search', contentType, query, year, uiLocale()],
    queryFn: () =>
      unwrap(
        api.GET('/api/metadata/search', {
          params: { query: { content_type: contentType, query, year: year ?? undefined, language: uiLocale() } },
        }),
      ),
    enabled: query.trim().length > 0,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
}
