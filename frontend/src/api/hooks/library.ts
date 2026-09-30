import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { pushActivity, updateActivity } from '@/lib/activity'
import { t } from '@/lib/i18n'
import { useTrackerFilter } from '@/lib/trackerFilter'

export function useLibraryItems(diskId?: number) {
  const tracker = useTrackerFilter()
  return useQuery({
    queryKey: ['library', 'items', diskId, tracker],
    queryFn: () => unwrap(api.GET('/api/library/items', { params: { query: { disk_id: diskId, tracker } } })),
  })
}

export function useMediaFiles(diskId?: number) {
  const tracker = useTrackerFilter()
  return useQuery({
    queryKey: ['library', 'media-files', diskId, tracker],
    queryFn: () => unwrap(api.GET('/api/media-files', { params: { query: { disk_id: diskId, tracker } } })),
  })
}

export function useSeedFiles(diskId?: number) {
  const tracker = useTrackerFilter()
  return useQuery({
    queryKey: ['library', 'seed-files', diskId, tracker],
    queryFn: () => unwrap(api.GET('/api/seed-files', { params: { query: { disk_id: diskId, tracker } } })),
  })
}

export function useUnmatched(diskId?: number) {
  return useQuery({
    queryKey: ['library', 'unmatched', diskId],
    queryFn: () => unwrap(api.GET('/api/library/unmatched', { params: { query: { disk_id: diskId } } })),
  })
}

export function useLibraryDuplicates(diskId?: number) {
  return useQuery({
    queryKey: ['library', 'duplicates', diskId],
    queryFn: () => unwrap(api.GET('/api/library/duplicates', { params: { query: { disk_id: diskId } } })),
  })
}

export function useItemDetail(contentType: string | null, tmdbId: number | null) {
  return useQuery({
    queryKey: ['library', 'detail', contentType, tmdbId],
    enabled: contentType != null && tmdbId != null,
    queryFn: () =>
      unwrap(
        api.GET('/api/library/items/{content_type}/{tmdb_id}', {
          params: { path: { content_type: contentType as string, tmdb_id: tmdbId as number } },
        }),
      ),
  })
}

export function useSearchNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ contentType, tmdbId }: { contentType: string; tmdbId: number; label?: string }) =>
      unwrap(
        api.POST('/api/library/items/{content_type}/{tmdb_id}/search', {
          params: { path: { content_type: contentType, tmdb_id: tmdbId } },
        }),
      ),
    onMutate: ({ label }) => ({
      activityId: pushActivity({ status: 'running', title: t('activity.searching'), detail: label }),
    }),
    onError: (error, _v, context) => {
      if (context) updateActivity(context.activityId, { status: 'error', title: t('activity.searchFailed'), detail: error.message })
    },
    onSuccess: (result, { label }, context) => {
      if (context) {
        updateActivity(context.activityId, {
          status: result.rate_limited ? 'error' : result.candidates > 0 ? 'success' : 'info',
          title: t(result.rate_limited ? 'itemDetail.searchRateLimited' : 'itemDetail.searchDone', {
            files: result.files_searched,
            candidates: result.candidates,
          }),
          detail: label,
        })
      }
      queryClient.invalidateQueries({ queryKey: ['library'] })
      queryClient.invalidateQueries({ queryKey: ['reviews'] })
    },
  })
}

export function useExcludeFile() {
  const queryClient = useQueryClient()
  return useMutation({
    // Una stringa = un file; { isDir: true } = tutto quello che c'è nella cartella.
    mutationFn: (target: string | { relativePath: string; isDir?: boolean }) => {
      const { relativePath, isDir = false } = typeof target === 'string' ? { relativePath: target } : target
      return unwrap(api.POST('/api/library/exclude', { body: { relative_path: relativePath, is_dir: isDir } }))
    },
    onError: (error) => {
      pushActivity({ status: 'error', title: t('activity.excludeFailed'), detail: error.message })
    },
    onSuccess: (_result, target) => {
      const relativePath = typeof target === 'string' ? target : target.relativePath
      pushActivity({ status: 'success', title: t('itemDetail.excluded'), detail: relativePath })
      queryClient.invalidateQueries({ queryKey: ['library'] })
      queryClient.invalidateQueries({ queryKey: ['settings', 'exclusion_patterns'] })
    },
  })
}

export function useNotImported() {
  return useQuery({
    queryKey: ['library', 'not-imported'],
    queryFn: () => unwrap(api.GET('/api/torrents/not-imported')),
  })
}

export function useRefreshNotImported() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/torrents/not-imported/refresh')),
    onMutate: () => ({ activityId: pushActivity({ status: 'running', title: t('notImported.recomputing') }) }),
    onError: (error, _v, context) => {
      if (context) updateActivity(context.activityId, { status: 'error', title: t('notImported.recomputeFailed'), detail: error.message })
    },
    onSuccess: (data, _v, context) => {
      queryClient.setQueryData(['library', 'not-imported'], data)
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      if (context) updateActivity(context.activityId, { status: 'success', title: t('notImported.recomputed') })
    },
  })
}
