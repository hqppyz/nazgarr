import { useMediaQuery } from "@/hooks/use-media-query"

// Sotto 1024 px (telefoni e tablet) il menu laterale è a scomparsa: aperto a
// 16rem su un tablet a 768 px lasciava al contenuto meno di 500 px.
// Le classi lg: di components/ui/sidebar.tsx seguono questo valore.
export const MOBILE_BREAKPOINT = 1024

export function useIsMobile() {
  return useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
}
