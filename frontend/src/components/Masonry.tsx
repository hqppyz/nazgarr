import { Children, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'

const GAP_PX = 16

// Senza matchMedia (test in jsdom): una colonna.
const hasMatchMedia = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'

function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (onChange) => {
      if (!hasMatchMedia()) return () => {}
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    () => hasMatchMedia() && window.matchMedia(query).matches,
    () => false,
  )
}

// Masonry vero: ogni scheda va nella colonna più corta, nell'ordine dato.
// Con le colonne CSS l'ordine resta "giù e poi a destra", quindi una scheda
// alta si trascina dietro le successive. Le schede restano sempre figlie
// dello stesso contenitore (posizionate in assoluto), così spostarsi di
// colonna non le smonta e non perdono il loro stato. Sotto lg, una colonna.
export function Masonry({ children, query = '(min-width: 1024px)' }: { children: ReactNode; query?: string }) {
  const items = Children.toArray(children)
  const twoColumns = useMediaQuery(query)
  const refs = useRef<(HTMLDivElement | null)[]>([])
  const [heights, setHeights] = useState<number[]>([])

  useLayoutEffect(() => {
    if (!twoColumns) return
    const measure = () => setHeights(refs.current.map((node) => node?.offsetHeight ?? 0))
    const observer = new ResizeObserver(measure)
    refs.current.forEach((node) => node && observer.observe(node))
    measure()
    return () => observer.disconnect()
  }, [twoColumns, items.length])

  if (!twoColumns) return <div className="grid min-w-0 gap-4 [&>*]:min-w-0">{items}</div>

  const columnHeights = [0, 0]
  const placed = items.map((_, i) => {
    const column = columnHeights[0] <= columnHeights[1] ? 0 : 1
    const top = columnHeights[column]
    columnHeights[column] += (heights[i] ?? 0) + GAP_PX
    return { column, top }
  })
  const height = Math.max(0, ...columnHeights) - GAP_PX

  return (
    <div className="relative min-w-0" style={{ height: Math.max(height, 0) }}>
      {items.map((item, i) => (
        <div
          key={i}
          ref={(node) => {
            refs.current[i] = node
          }}
          className="absolute min-w-0"
          style={{
            top: placed[i].top,
            left: placed[i].column === 0 ? 0 : `calc(50% + ${GAP_PX / 2}px)`,
            width: `calc(50% - ${GAP_PX / 2}px)`,
          }}
        >
          {item}
        </div>
      ))}
    </div>
  )
}
