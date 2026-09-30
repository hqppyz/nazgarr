import { createContext, useContext } from 'react'

// Il contenitore in basso a destra del layout (components/layout/AppLayout.tsx),
// nella stessa pila delle notifiche e della run: una pagina ci mette i suoi
// pannelli flottanti con createPortal, senza sovrapporsi agli altri.
export const FloatingSlotContext = createContext<HTMLElement | null>(null)

export function useFloatingSlot() {
  return useContext(FloatingSlotContext)
}
