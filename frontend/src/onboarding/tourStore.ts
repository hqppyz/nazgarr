import { useSyncExternalStore } from 'react'

// Quale tour è aperto e a che passo: fuori da React, così la checklist, il
// benvenuto e il runner lo condividono senza un provider.
export interface ActiveTour {
  key: string
  index: number
}

let active: ActiveTour | null = null
const listeners = new Set<() => void>()

function emit(next: ActiveTour | null) {
  active = next
  listeners.forEach((listener) => listener())
}

export const tourStore = {
  get: () => active,
  start: (key: string) => emit({ key, index: 0 }),
  goTo: (index: number) => active && emit({ ...active, index }),
  stop: () => emit(null),
  subscribe: (listener: () => void) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}

export function useActiveTour(): ActiveTour | null {
  return useSyncExternalStore(tourStore.subscribe, tourStore.get, tourStore.get)
}
