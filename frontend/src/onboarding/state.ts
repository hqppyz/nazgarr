import { useQuery, type QueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { useSetSetting, useSetting } from '@/api/hooks/settings'

// Lo stato del tour del primo accesso, in un'impostazione (app_settings):
// riprende da dove si era rimasti anche da un altro dispositivo.
export const ONBOARDING_SETTING = 'onboarding_state'

export interface OnboardingState {
  status: 'active' | 'dismissed' | 'done'
  // Le risposte del benvenuto: adattano il percorso (salta i passi che non servono).
  answers: { upload: boolean; arr: boolean }
  // I passi facoltativi già mostrati (esclusioni, soglie): contano come fatti.
  seen: string[]
}

export const DEFAULT_STATE: OnboardingState = { status: 'active', answers: { upload: true, arr: false }, seen: [] }

export function parseState(raw: string | null | undefined): OnboardingState | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<OnboardingState>
    if (!value || !['active', 'dismissed', 'done'].includes(value.status as string)) return null
    return { ...DEFAULT_STATE, ...value, answers: { ...DEFAULT_STATE.answers, ...value.answers }, seen: value.seen ?? [] }
  } catch {
    return null
  }
}

export function useOnboarding() {
  const { data, isPending } = useSetting(ONBOARDING_SETTING)
  const save = useSetSetting(ONBOARDING_SETTING)
  const state = parseState(data?.value)
  return {
    isPending,
    // null = mai visto: il benvenuto si apre da solo su un'istanza da configurare.
    state,
    save: (next: OnboardingState) => save.mutate(JSON.stringify(next)),
    saving: save.isPending,
  }
}

// Il benvenuto (mai visto) e la checklist (tour attivo) hanno bisogno dello
// stato della configurazione; a tour finito o chiuso nessuno lo guarda più
// di continuo.
export function isTouring(state: OnboardingState | null): boolean {
  return state === null || state.status === 'active'
}

// Lo stesso, dalla cache: per il MutationCache (main.tsx), che rilegge
// setup-status dopo ogni salvataggio solo finché serve a qualcuno.
export function touringNow(queryClient: QueryClient): boolean {
  return isTouring(parseState(queryClient.getQueryData<{ value?: string | null }>(['settings', ONBOARDING_SETTING])?.value))
}

export function useSetupStatus() {
  const { state } = useOnboarding()
  const touring = isTouring(state)
  return useQuery({
    queryKey: ['setup-status'],
    queryFn: () => unwrap(api.GET('/api/system/setup-status')),
    // Ogni passo si chiude quando la configurazione cambia: un salvataggio
    // in un'altra schermata invalida le sue query, non questa. Si rilegge
    // a ogni ritorno sulla finestra e ogni tanto mentre il tour è aperto.
    refetchInterval: touring ? 15_000 : false,
  })
}
