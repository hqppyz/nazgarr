import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

// Ripolla finché almeno una run è ancora in corso (finished_at nullo) —
// così la pagina si aggiorna da sola durante un bulk import, senza un
// websocket dedicato per uno scenario così poco frequente. Esportata a
// parte per poterla testare senza dover montare l'intero hook TanStack Query.
export function nextRunsRefetchInterval(runs: Schemas['RunResponse'][] | undefined): number | false {
  const anyInProgress = runs?.some((r) => r.finished_at === null)
  return anyInProgress ? 3_000 : false
}

// Le ultime: la run in corso è sempre la prima, e la cronologia ne mostra
// tante. Tutte, dopo mesi di run ogni ora, erano MB a ogni poll (audit 2026-10-18).
export const RUNS_SHOWN = 10

export function useRuns() {
  return useQuery({
    queryKey: ['runs'],
    queryFn: () => unwrap(api.GET('/api/runs', { params: { query: { limit: RUNS_SHOWN } } })),
    refetchInterval: (query) => nextRunsRefetchInterval(query.state.data),
  })
}

export function useTriggerRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/runs')),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export function useCancelRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (runId: number) =>
      unwrap(api.POST('/api/runs/{run_id}/cancel', { params: { path: { run_id: runId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runs'] }),
  })
}
