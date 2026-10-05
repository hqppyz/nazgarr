import { useEffect, useRef, useState } from 'react'

// Quanti elementi di una lista lunga rendere: i primi `pageSize`, poi altri
// `pageSize` ogni volta che la sentinella (l'ultimo elemento reso) si
// avvicina alla vista. Quando `resetKey` cambia (un altro filtro, un'altra
// ricerca) si riparte dal primo blocco. Rende un albero di decine di
// migliaia di file senza decine di migliaia di righe nel DOM.
export function useIncrementalCount<T extends Element>(total: number, pageSize: number, resetKey: unknown) {
  const [count, setCount] = useState(pageSize)
  const [key, setKey] = useState(resetKey)
  if (key !== resetKey) {
    // Reset durante il render (il modo consigliato da React per derivare
    // stato da una prop), non in un effetto: niente render con il blocco vecchio.
    setKey(resetKey)
    setCount(pageSize)
  }
  const sentinelRef = useRef<T | null>(null)
  useEffect(() => {
    const node = sentinelRef.current
    if (!node || count >= total) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setCount((n) => n + pageSize)
      },
      { rootMargin: '800px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [count, total, pageSize])
  return { visible: Math.min(count, total), hasMore: count < total, sentinelRef }
}
