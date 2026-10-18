import type { Mutation } from '@tanstack/react-query'
import { toast } from 'sonner'

import { t } from '@/lib/i18n'

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: { toastErrors?: boolean }
  }
}

// Per gli hook i cui chiamanti non mostrano l'errore (eliminare, revocare,
// ruotare un segreto, uscire da ogni dispositivo): senza, un fallimento si
// vede solo da quello che non è successo, e il motivo (es. "questa API key
// è di sola lettura") si perde. Su richiesta e non per tutte: le altre
// mutation l'errore lo mostrano già, ciascuna a modo suo, e il MutationCache
// non vede le opzioni passate a mutate(): sarebbe un messaggio doppio.
export const TOAST_ERRORS = { toastErrors: true } as const

// onError del MutationCache (main.tsx).
export function reportMutationError(error: Error, mutation: Pick<Mutation<unknown, Error, unknown, unknown>, 'meta'>): void {
  if (mutation.meta?.toastErrors) toast.error(t('common.actionFailed', { message: error.message }))
}
