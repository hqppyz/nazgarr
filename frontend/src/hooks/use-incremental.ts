import { useEffect, useState } from 'react'

import { scrollRoot } from '@/lib/scrollRoot'

// Quanti elementi di una lista lunga rendere: i primi `pageSize`, poi altri
// `pageSize` ogni volta che la sentinella (l'ultimo elemento reso) si
// avvicina alla vista. Quando `resetKey` cambia (un altro filtro, un'altra
// ricerca) si riparte dal primo blocco. Per le griglie e le liste che
// crescono soltanto (i poster, i torrent non importati); l'albero della
// libreria monta solo le righe vicine alla vista (use-virtual-rows.ts).
export function useIncrementalCount<T extends Element>(total: number, pageSize: number, resetKey: unknown) {
  const [count, setCount] = useState(pageSize)
  const [key, setKey] = useState(resetKey)
  if (key !== resetKey) {
    // Reset durante il render (il modo consigliato da React per derivare
    // stato da una prop), non in un effetto: niente render con il blocco vecchio.
    setKey(resetKey)
    setCount(pageSize)
  }
  // La sentinella come stato (un ref a callback), non un useRef: l'effetto
  // riparte quando monta. Con useRef una lista resa la prima volta dietro
  // il loader (NotImportedView: i dati arrivano durante la sua dissolvenza,
  // la tabella monta dopo) non agganciava mai l'observer e restava ai primi
  // 100 (audit 2026-10-18).
  const [node, sentinelRef] = useState<T | null>(null)
  useEffect(() => {
    if (!node || count >= total) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setCount((n) => n + pageSize)
      },
      // Contro l'area che scorre: con la finestra gli 800 px valevano 0.
      { root: scrollRoot(node), rootMargin: '800px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [node, count, total, pageSize])
  return { visible: Math.min(count, total), hasMore: count < total, sentinelRef }
}
