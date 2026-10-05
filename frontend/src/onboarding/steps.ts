import type { Schemas } from '@/api/client'
import type { OnboardingState } from '@/onboarding/state'

type SetupStatus = Schemas['SetupStatusResponse']

export interface ChecklistStep {
  key: string
  // Dove si configura: un tab delle impostazioni o una pagina.
  to: string
  optional: boolean
  // Fatto dalla configurazione reale (setup-status) o, per i passi con dei
  // default già sensati, quando il tour li ha mostrati.
  from: 'status' | 'seen'
  // Mostrato solo se la risposta del benvenuto lo chiede.
  when?: keyof OnboardingState['answers']
}

// Nell'ordine in cui conviene farli: ogni passo usa i precedenti.
export const CHECKLIST: ChecklistStep[] = [
  { key: 'storage', to: '/config?tab=storage', optional: false, from: 'status' },
  { key: 'clients', to: '/config?tab=clients', optional: false, from: 'status' },
  { key: 'metadata', to: '/config?tab=integrations', optional: false, from: 'status' },
  { key: 'arr', to: '/config?tab=integrations', optional: true, from: 'status', when: 'arr' },
  { key: 'trackers', to: '/config?tab=trackers', optional: false, from: 'status' },
  { key: 'exclusions', to: '/config?tab=exclusions', optional: true, from: 'seen' },
  { key: 'reseeding', to: '/config?tab=matching', optional: true, from: 'seen' },
  { key: 'upload', to: '/config?tab=images', optional: true, from: 'status', when: 'upload' },
  { key: 'first_scan', to: '/dashboard', optional: false, from: 'status' },
  // Solo per far conoscere il resto: upload, notifiche, istanze, API key, plugin.
  { key: 'extras', to: '/upload', optional: true, from: 'seen' },
]

export function visibleSteps(state: OnboardingState): ChecklistStep[] {
  return CHECKLIST.filter((step) => !step.when || state.answers[step.when])
}

export function isDone(step: ChecklistStep, status: SetupStatus | undefined, state: OnboardingState): boolean {
  if (step.from === 'seen') return state.seen.includes(step.key)
  return status?.steps[step.key]?.done ?? false
}
