export interface RingHandle {
  // Lampo di luce (es. alla chiusura della sidebar).
  flash: () => void
  collapse: (collapsed: boolean) => void
  glow: (on: boolean, instant?: boolean) => void // accende/spegne il bagliore come l'hover
  // Indicatore di caricamento (mode "loader"): pronto = si raddrizza in una
  // O luminosa (la promessa si risolve a fine movimento); errore = un'ultima
  // caduta, poi resta piatto e spento.
  settle: () => Promise<void>
  fall: () => void
}
