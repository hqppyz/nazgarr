import { useMutation, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'

export interface FullCheckTarget {
  candidateId: number
  seedJobId?: number | null
}

export function useStartFullCheck() {
  return useMutation({
    mutationFn: (target: FullCheckTarget) =>
      unwrap(
        api.POST('/api/full-checks', {
          body: { candidate_id: target.candidateId, seed_job_id: target.seedJobId ?? null },
        }),
      ),
  })
}

// Stato del controllo in background: si interroga ogni secondo finché è in
// coda o in corso, poi si ferma. Se la richiesta fallisce (per esempio un
// controllo che dopo un riavvio non esiste più) si riprova più di rado e,
// dopo qualche errore, si smette: niente polling infinito a un secondo.
export const FULL_CHECK_MAX_ERRORS = 5

export function fullCheckRefetchInterval(status: string | undefined, failed: boolean, errors: number): number | false {
  if (failed) return errors < FULL_CHECK_MAX_ERRORS ? 5000 : false
  return status === 'queued' || status === 'running' || status === undefined ? 1000 : false
}

export function useFullCheck(id: string | null) {
  return useQuery({
    queryKey: ['full-checks', id],
    queryFn: () => unwrap(api.GET('/api/full-checks/{check_id}', { params: { path: { check_id: id! } } })),
    enabled: id !== null,
    refetchInterval: (query) =>
      fullCheckRefetchInterval(query.state.data?.status, query.state.status === 'error', query.state.errorUpdateCount),
  })
}

export function useCancelFullCheck() {
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST('/api/full-checks/{check_id}/cancel', { params: { path: { check_id: id } } })),
  })
}
