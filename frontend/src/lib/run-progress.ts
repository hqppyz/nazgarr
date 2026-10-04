import type { Schemas } from '@/api/client'
import { parseApiDate } from '@/lib/time'
import { uiLocale } from '@/lib/i18n'

export type RunResponse = Schemas['RunResponse']
export type PhaseProgress = Schemas['PhaseProgressResponse']

// Stesso ordine della pipeline (nazgarr/reseed/pipeline.py, nazgarr/core/run_progress.py PHASES).
export const PHASE_ORDER = ['scanning', 'resolving', 'indexing', 'matching', 'executing', 'reconciling'] as const
export type PhaseName = (typeof PHASE_ORDER)[number]

export type StepState = 'done' | 'running' | 'pending' | 'skipped'

export interface Step {
  phase: PhaseName
  state: StepState
  progress: PhaseProgress | undefined
}

// Una fase assente da run.phases non è ancora partita; a run finita (per
// un errore che ha interrotto la pipeline) resta "skipped", mai "pending"
// per sempre.
export function runSteps(run: RunResponse): Step[] {
  const finished = run.finished_at != null
  return PHASE_ORDER.map((phase) => {
    const progress = run.phases?.[phase]
    let state: StepState
    if (progress?.status === 'done') state = 'done'
    else if (progress?.status === 'running' && !finished) state = 'running'
    else if (progress) state = 'done'
    else state = finished ? 'skipped' : 'pending'
    return { phase, state, progress }
  })
}

export function percent(done: number | null | undefined, total: number | null | undefined): number | null {
  if (total == null || total <= 0 || done == null) return null
  return Math.min(100, Math.round((done / total) * 100))
}

// Stima del tempo rimanente della fase in corso dal ritmo osservato finora.
// Nessuna stima nei primi secondi o con pochi elementi: sarebbe solo rumore.
export function etaSeconds(progress: PhaseProgress | undefined, now: number = Date.now()): number | null {
  if (!progress?.started_at || progress.total == null || progress.done <= 0) return null
  const elapsed = (now - parseApiDate(progress.started_at).getTime()) / 1000
  if (elapsed < 5 || progress.done < 3) return null
  const remaining = progress.total - progress.done
  if (remaining <= 0) return 0
  return Math.round((elapsed / progress.done) * remaining)
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

export function formatCount(n: number): string {
  return n.toLocaleString(uiLocale())
}
