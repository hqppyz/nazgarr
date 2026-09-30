import { useLayoutEffect, useRef, useSyncExternalStore, type ReactNode } from 'react'

import { cn } from '@/lib/utils'

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

const FULL = 'full'

// Masonry vero: ogni scheda va nella colonna più corta, nell'ordine dato.
// Con le colonne CSS l'ordine resta "giù e poi a destra" e column-span: all
// si impagina male (schede che si sovrappongono). Lavora sui nodi DOM figli,
// così funziona anche con le sezioni che restituiscono le loro schede in un
// fragment, e le schede non si smontano mai quando cambiano colonna.
// Una scheda con data-masonry="full" occupa tutta la larghezza, sotto le
// colonne fin lì. Sotto lg, una colonna normale.
export function Masonry({
  children,
  gap = 16,
  className,
  query = '(min-width: 1024px)',
}: {
  children: ReactNode
  gap?: number
  className?: string
  query?: string
}) {
  const container = useRef<HTMLDivElement | null>(null)
  const twoColumns = useMediaQuery(query)

  useLayoutEffect(() => {
    const root = container.current
    if (!root) return
    const items = () => Array.from(root.children) as HTMLElement[]

    const reset = () => {
      root.style.height = ''
      for (const item of items()) {
        item.style.position = item.style.top = item.style.left = item.style.width = item.style.height = ''
      }
    }
    if (!twoColumns) {
      reset()
      return
    }

    const layout = () => {
      const heights = [0, 0]
      for (const item of items()) {
        item.style.position = 'absolute'
        // Mai l'altezza del contenitore (che imposta questo stesso layout):
        // una card con h-full si allungherebbe fino in fondo.
        item.style.height = 'auto'
        if (item.dataset.masonry === FULL) {
          const top = Math.max(...heights)
          Object.assign(item.style, { top: `${top}px`, left: '0px', width: '100%' })
          heights[0] = heights[1] = top + item.offsetHeight + gap
          continue
        }
        const column = heights[0] <= heights[1] ? 0 : 1
        Object.assign(item.style, {
          top: `${heights[column]}px`,
          left: column === 0 ? '0px' : `calc(50% + ${gap / 2}px)`,
          width: `calc(50% - ${gap / 2}px)`,
        })
        heights[column] += item.offsetHeight + gap
      }
      root.style.height = `${Math.max(0, Math.max(...heights) - gap)}px`
    }

    const resize = new ResizeObserver(layout)
    const watch = () => {
      resize.disconnect()
      items().forEach((item) => resize.observe(item))
      layout()
    }
    // Schede aggiunte o tolte (dati che arrivano, sezioni condizionali).
    const mutations = new MutationObserver(watch)
    mutations.observe(root, { childList: true })
    watch()
    return () => {
      resize.disconnect()
      mutations.disconnect()
      reset()
    }
  }, [twoColumns, gap])

  return (
    <div
      ref={container}
      className={cn('min-w-0', twoColumns ? 'relative' : 'grid [&>*]:min-w-0', className)}
      style={twoColumns ? undefined : { gap }}
    >
      {children}
    </div>
  )
}
