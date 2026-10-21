// L'attributo dell'area che scorre il contenuto delle pagine (AppLayout): la
// finestra non scorre mai, il contenuto scorre lì dentro.
export const SCROLL_ROOT_ATTR = 'data-scroll-root'

// La radice per un IntersectionObserver che guarda `node`. Un rootMargin
// allarga solo il rettangolo della radice: con la radice implicita (la
// finestra) l'area che scorre taglia senza margine, e un "a 300 px dallo
// schermo" valeva 0 (audit 2026-10-18). Si cerca un antenato marcato invece
// del primo con overflow auto: il contenitore overflow-x-auto delle tabelle
// ha anche overflow-y auto calcolato, ma non scorre in verticale, e con lui
// come radice ogni riga risulterebbe sempre visibile. Un elemento fuori da
// quell'area (un pannello o un dialogo, montati altrove nel DOM) usa la
// finestra, come prima. È anche l'area di cui la finestra dell'albero
// (hooks/use-virtual-rows.ts) ascolta lo scroll e misura la parte visibile.
export function scrollRoot(node: Element): Element | null {
  return node.parentElement?.closest(`[${SCROLL_ROOT_ATTR}]`) ?? null
}
