import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

export function useTorrentClients() {
  return useQuery({
    queryKey: ['torrent-clients'],
    queryFn: () => unwrap(api.GET('/api/torrent-clients')),
  })
}

export function useCreateTorrentClient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['TorrentClientCreateRequest']) => unwrap(api.POST('/api/torrent-clients', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['torrent-clients'] }),
  })
}

export function useUpdateTorrentClient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas['TorrentClientUpdateRequest'] }) =>
      unwrap(api.PATCH('/api/torrent-clients/{torrent_client_id}', { params: { path: { torrent_client_id: id } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['torrent-clients'] }),
  })
}

export function useDeleteTorrentClient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/torrent-clients/{torrent_client_id}', { params: { path: { torrent_client_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['torrent-clients'] }),
  })
}

export function useTestTorrentClient() {
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST('/api/torrent-clients/{torrent_client_id}/test', { params: { path: { torrent_client_id: id } } })),
  })
}

export function useAssociateDisk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      torrentClientId,
      diskId,
      torrentClientRootPath,
      localRelPath,
    }: {
      torrentClientId: number
      diskId: number
      torrentClientRootPath?: string | null
      localRelPath?: string | null
    }) =>
      unwrap(
        api.POST('/api/torrent-clients/{torrent_client_id}/disks/{disk_id}', {
          params: { path: { torrent_client_id: torrentClientId, disk_id: diskId } },
          body: {
            torrent_client_root_path: torrentClientRootPath || undefined,
            local_rel_path: localRelPath || undefined,
          },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['torrent-clients'] }),
  })
}

export function useDissociateDisk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ torrentClientId, diskId }: { torrentClientId: number; diskId: number }) =>
      unwrap(
        api.DELETE('/api/torrent-clients/{torrent_client_id}/disks/{disk_id}', {
          params: { path: { torrent_client_id: torrentClientId, disk_id: diskId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['torrent-clients'] }),
  })
}

// Le categorie del client, lette dal vivo: si sceglie solo fra queste.
export function useTorrentClientCategories(id: number | null) {
  return useQuery({
    queryKey: ['torrent-clients', id, 'categories'],
    queryFn: () =>
      unwrap(api.GET('/api/torrent-clients/{torrent_client_id}/categories', { params: { path: { torrent_client_id: id! } } })),
    enabled: id !== null,
    staleTime: 60_000,
  })
}
