import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

export function useTrackers() {
  return useQuery({
    queryKey: ['trackers'],
    queryFn: () => unwrap(api.GET('/api/trackers')),
  })
}

export function useCreateTracker() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['TrackerCreateRequest']) => unwrap(api.POST('/api/trackers', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trackers'] }),
  })
}

export function useUpdateTracker() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas['TrackerUpdateRequest'] }) =>
      unwrap(api.PATCH('/api/trackers/{tracker_id}', { params: { path: { tracker_id: id } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trackers'] }),
  })
}

export function useDeleteTracker() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE('/api/trackers/{tracker_id}', { params: { path: { tracker_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trackers'] }),
  })
}

export function useBundledUploadProfiles() {
  return useQuery({
    queryKey: ['trackers', 'upload-profiles', 'bundled'],
    queryFn: () => unwrap(api.GET('/api/trackers/upload-profiles/bundled')),
  })
}

export function useUploadProfile(trackerId: number) {
  return useQuery({
    queryKey: ['trackers', trackerId, 'upload-profile'],
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/trackers/{tracker_id}/upload-profile', {
        params: { path: { tracker_id: trackerId } },
      })
      if (response.status === 404) return null
      if (error) throw new Error(JSON.stringify(error))
      return data ?? null
    },
  })
}

export function useCreateUploadProfile(trackerId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['UploadProfileCreateRequest']) =>
      unwrap(api.POST('/api/trackers/{tracker_id}/upload-profile', { params: { path: { tracker_id: trackerId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trackers', trackerId, 'upload-profile'] }),
  })
}

export function useUpdateUploadProfile(trackerId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['UploadProfileUpdateRequest']) =>
      unwrap(api.PATCH('/api/trackers/{tracker_id}/upload-profile', { params: { path: { tracker_id: trackerId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trackers', trackerId, 'upload-profile'] }),
  })
}

export function useDeleteUploadProfile(trackerId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(api.DELETE('/api/trackers/{tracker_id}/upload-profile', { params: { path: { tracker_id: trackerId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trackers', trackerId, 'upload-profile'] }),
  })
}

export function useUpdateNamingFromBundled(trackerId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/trackers/{tracker_id}/upload-profile/naming/update', { params: { path: { tracker_id: trackerId } } }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['trackers', trackerId, 'upload-profile'] }),
  })
}
