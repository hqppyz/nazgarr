export interface RingHandle {
  // Lampo di luce (es. alla chiusura della sidebar).
  flash: () => void
  collapse: (collapsed: boolean) => void
  glow: (on: boolean, instant?: boolean) => void // accende/spegne il bagliore come l'hover
}
