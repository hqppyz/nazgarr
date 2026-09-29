import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

export type UploadJob = Schemas['UploadJobDetail']
export type UploadJobSummary = Schemas['UploadJobSummary']
export type UploadTarget = Schemas['UploadTargetResponse']

// Stati in cui il worker sta lavorando (app/upload_jobs.py WORKER_STATES):
// solo lì serve il polling, a un punto di approvazione o a job finito no.
export const WORKER_STATES = ['identifying', 'analyzing', 'queued', 'running']
const POLL_MS = 2000

// Anche a un punto di approvazione un target può avere un full hash check in corso.
const TARGET_WORKING_STATES = ['checking', 'verifying', 'preparing', 'uploading', 'seeding']

function isWorking(status: string | undefined) {
  return status !== undefined && WORKER_STATES.includes(status)
}

function isJobWorking(job: UploadJobSummary | undefined) {
  return !!job && (isWorking(job.status) || job.targets.some((target) => TARGET_WORKING_STATES.includes(target.status)))
}

export function useUploads() {
  return useQuery({
    queryKey: ['uploads'],
    queryFn: () => unwrap(api.GET('/api/uploads')),
    refetchInterval: (query) => (query.state.data?.some(isJobWorking) ? POLL_MS : false),
  })
}

export function useUpload(uploadId: number | null) {
  return useQuery({
    queryKey: ['uploads', uploadId],
    queryFn: () => unwrap(api.GET('/api/uploads/{upload_id}', { params: { path: { upload_id: uploadId! } } })),
    enabled: uploadId !== null,
    refetchInterval: (query) => (isJobWorking(query.state.data) ? POLL_MS : false),
  })
}

export function useCreateUpload() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['UploadCreateRequest']) => unwrap(api.POST('/api/uploads', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['uploads'] }),
  })
}

export function useCancelUpload() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uploadId: number) =>
      unwrap(api.POST('/api/uploads/{upload_id}/cancel', { params: { path: { upload_id: uploadId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['uploads'] }),
  })
}

export function useDeleteUpload() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uploadId: number) =>
      unwrap(api.DELETE('/api/uploads/{upload_id}', { params: { path: { upload_id: uploadId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['uploads'] }),
  })
}

export function useUploadTrackers() {
  return useQuery({
    queryKey: ['uploads', 'trackers'],
    queryFn: () => unwrap(api.GET('/api/uploads/trackers')),
  })
}

export function useConfirmMatch(uploadId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['UploadMatchRequest']) =>
      unwrap(api.POST('/api/uploads/{upload_id}/match', { params: { path: { upload_id: uploadId } }, body })),
    onSuccess: (job) => {
      queryClient.setQueryData(['uploads', uploadId], job)
      queryClient.invalidateQueries({ queryKey: ['uploads'] })
    },
  })
}

export function useReidentify(uploadId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (forcedIds: Schemas['ForcedIds']) =>
      unwrap(
        api.POST('/api/uploads/{upload_id}/reidentify', {
          params: { path: { upload_id: uploadId } },
          body: { forced_ids: forcedIds },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(['uploads', uploadId], job)
      queryClient.invalidateQueries({ queryKey: ['uploads'] })
    },
  })
}

export function useVerifyTarget(uploadId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ targetId, torrentIdRemote }: { targetId: number; torrentIdRemote: string }) =>
      unwrap(
        api.POST('/api/uploads/{upload_id}/targets/{target_id}/verify', {
          params: { path: { upload_id: uploadId, target_id: targetId } },
          body: { torrent_id_remote: torrentIdRemote },
        }),
      ),
    onSuccess: (job) => queryClient.setQueryData(['uploads', uploadId], job),
  })
}

export function useUpdateOverrides(uploadId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (overrides: Record<string, unknown>) =>
      unwrap(
        api.PUT('/api/uploads/{upload_id}/overrides', {
          params: { path: { upload_id: uploadId } },
          body: { overrides },
        }),
      ),
    onSuccess: (job) => queryClient.setQueryData(['uploads', uploadId], job),
  })
}

export function useApproveUpload(uploadId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (targets: Schemas['TargetDecision'][]) =>
      unwrap(api.POST('/api/uploads/{upload_id}/approve', { params: { path: { upload_id: uploadId } }, body: { targets } })),
    onSuccess: (job) => {
      queryClient.setQueryData(['uploads', uploadId], job)
      queryClient.invalidateQueries({ queryKey: ['uploads'] })
    },
  })
}
