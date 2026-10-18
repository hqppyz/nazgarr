import { useState } from 'react'

import { RingLoader, type Phase } from '@/components/RingLoader'

// L'anello al posto di una pagina finché la sua query carica, poi il tempo
// della O; se fallisce senza dati, l'anello caduto con l'errore e Riprova.
// null = mostra la pagina. Da chiamare prima di ogni return della pagina.
export function useRingLoader(query: {
  data: unknown
  isPending: boolean
  isError: boolean
  isFetching: boolean
  error: Error | null
  refetch: () => unknown
}) {
  const [shown, setShown] = useState(query.isPending)
  const [retries, setRetries] = useState(0) // un anello nuovo, che ricade, a ogni Riprova
  if (query.isPending && !shown) setShown(true)
  const failed = query.isError && query.data === undefined
  if (!shown && !failed) return null
  const phase: Phase = query.isPending || (failed && query.isFetching) ? 'loading' : failed ? 'error' : 'done'
  return (
    <RingLoader
      key={retries}
      phase={phase}
      error={query.error?.message}
      onRetry={() => {
        setRetries((n) => n + 1)
        void query.refetch()
      }}
      onExited={() => setShown(false)}
    />
  )
}
