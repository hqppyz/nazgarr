import { useCallback, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { flushSync } from 'react-dom'

import { scrollRoot } from '@/lib/scrollRoot'
import {
  anchorAt,
  anchorShift,
  mergeHeights,
  nextRange,
  nextRowWith,
  rowOffsets,
  windowSlots,
  type RowAnchor,
  type RowMeasures,
  type RowRange,
  type RowSlot,
  type ViewSpan,
} from '@/lib/virtualRows'

// Una lista lunga con solo le righe vicine alla vista nel DOM (i numeri in
// lib/virtualRows.ts). Le righe portano il loro id in questo attributo: da
// lì si misurano e si ritrovano.
export const ROW_KEY_ATTR = 'data-row-key'

// Altezza di una riga finché non se ne misura nessuna: poi la media di
// quelle misurate.
const DEFAULT_ROW_HEIGHT = 33
// Margini attorno alla parte visibile: sotto i NEAR px si ricalcola la
// finestra, che poi copre FAR px sopra e sotto.
const NEAR_PX = 400
const FAR_PX = 1000
// Prima di sapere dov'è la vista (il primo render, prima degli effetti).
const INITIAL_ROWS = 40

const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]'

// I controlli di una riga raggiungibili col Tab, nell'ordine del DOM. Senza
// quelli nascosti: i badge sono resi due volte (sotto il nome sul telefono,
// nella colonna Stato altrimenti) e una delle due copie non si vede.
export function rowControls(row: Element): HTMLElement[] {
  return Array.from(row.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) =>
      el.tabIndex >= 0 &&
      !el.hasAttribute('disabled') &&
      el.getAttribute('aria-hidden') !== 'true' &&
      (typeof el.checkVisibility === 'function' ? el.checkVisibility() : true),
  )
}

function rowElement(el: Element | null): Element | null {
  return el?.closest(`[${ROW_KEY_ATTR}]`) ?? null
}

function mountedRows(body: Element): Element[] {
  return Array.from(body.querySelectorAll(`[${ROW_KEY_ATTR}]`))
}

function findRow(body: Element, key: string): Element | null {
  return mountedRows(body).find((row) => row.getAttribute(ROW_KEY_ATTR) === key) ?? null
}

// Le righe montate da non smontare anche se escono dalla finestra: quella
// col fuoco (smontata, il fuoco finirebbe sul body e il Tab ripartirebbe
// dall'inizio della pagina) e quella da cui è aperto un menu "⋯" o un
// popover (Base UI segna il trigger con data-popup-open): il popup è
// ancorato lì, e alla chiusura il fuoco torna lì.
export function keptRowKeys(body: Element): string[] {
  const keys = new Set<string>()
  const add = (el: Element | null) => {
    const row = rowElement(el)
    const key = row && body.contains(row) ? row.getAttribute(ROW_KEY_ATTR) : null
    if (key !== null) keys.add(key)
  }
  const active = document.activeElement
  if (active && body.contains(active)) add(active)
  body.querySelectorAll('[data-popup-open]').forEach(add)
  return [...keys]
}

// La parte visibile, in coordinate della lista: l'area che scorre della
// pagina (AppLayout, lib/scrollRoot) o, fuori da lei, la finestra.
function viewSpan(body: Element): ViewSpan {
  const bodyTop = body.getBoundingClientRect().top
  const root = scrollRoot(body)
  if (!root) return { top: -bodyTop, bottom: window.innerHeight - bodyTop }
  const top = root.getBoundingClientRect().top + root.clientTop - bodyTop
  return { top, bottom: top + root.clientHeight }
}

function scrollByPx(body: Element, dy: number) {
  const root = scrollRoot(body)
  if (root) root.scrollTop += dy
  else window.scrollBy(0, dy)
}

interface WindowState {
  range: RowRange
  kept: readonly string[]
}

const sameKeys = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((k, i) => k === b[i])

const INITIAL_MEASURES: RowMeasures = { heights: new Map(), estimate: DEFAULT_ROW_HEIGHT }

export interface VirtualRowsOptions {
  // Gli id delle righe nell'ordine mostrato (per l'albero il path).
  keys: readonly string[]
  // Quando cambia è un'altra lista (un filtro, una ricerca): nessuna riga da
  // tenere ferma. Un aggiornamento dei dati con lo stesso resetKey lascia la
  // riga in cima alla vista dov'era.
  resetKey: unknown
  // Un'altra riga da tenere montata: per l'albero quella del menu
  // contestuale, aperto sul <tbody> e non su un trigger della riga.
  pinned?: string | null
  // Se la riga ha qualcosa da mettere a fuoco, anche smontata: il Tab e le
  // frecce la raggiungono montandola.
  hasControls: (index: number) => boolean
}

// Le righe da rendere e come agganciarle: `bodyRef` sul contenitore delle
// righe (il <tbody>), `slots` le righe (per indice) e gli spazi al posto
// delle altre, `onKeyDownCapture` sul contenitore per Tab, Maiusc+Tab e
// frecce su/giù anche verso righe smontate.
export function useVirtualRows({ keys, resetKey, pinned = null, hasControls }: VirtualRowsOptions) {
  const [body, setBody] = useState<HTMLElement | null>(null)
  const [measures, setMeasures] = useState(INITIAL_MEASURES)
  const offsets = useMemo(() => rowOffsets(keys, measures.heights, measures.estimate), [keys, measures])
  const indexOf = useMemo(() => new Map(keys.map((key, i) => [key, i])), [keys])
  const [win, setWin] = useState<WindowState>(() => ({ range: { start: 0, end: INITIAL_ROWS }, kept: [] }))
  // Una riga da montare subito perché il Tab o una freccia ci va.
  const [forced, setForced] = useState<string | null>(null)
  const anchor = useRef<RowAnchor | null>(null)

  // I valori del render più recente, per chi gira fuori dal render (lo
  // scroll, i tasti).
  const latest = useRef({ keys, offsets, indexOf, hasControls })
  useLayoutEffect(() => {
    latest.current = { keys, offsets, indexOf, hasControls }
  })

  // Rilegge la vista: la finestra, le righe da tenere montate, l'ancora.
  const update = useCallback(() => {
    if (!body) return
    const { keys: currentKeys, offsets: currentOffsets } = latest.current
    const view = viewSpan(body)
    anchor.current = anchorAt(currentOffsets, currentKeys, view.top)
    const kept = keptRowKeys(body)
    setWin((prev) => {
      const range = nextRange(prev.range, currentOffsets, view, NEAR_PX, FAR_PX)
      return range === prev.range && sameKeys(kept, prev.kept) ? prev : { range, kept }
    })
  }, [body])

  // Le altezze vere delle righe montate: variano (il nome che va a capo su
  // touch, i badge sotto il nome sul telefono).
  const measure = useCallback(() => {
    if (!body) return
    const found = mountedRows(body).map((row) => [row.getAttribute(ROW_KEY_ATTR) ?? '', row.getBoundingClientRect().height] as const)
    setMeasures((prev) => mergeHeights(prev, found))
  }, [body])

  // Un'altra lista: niente da tenere fermo (prima dell'effetto dell'ancora).
  useLayoutEffect(() => {
    anchor.current = null
  }, [resetKey])

  const slots: RowSlot[] = useMemo(() => {
    const kept = [...win.kept, pinned, forced].flatMap((key) => {
      const index = key === null ? undefined : indexOf.get(key)
      return index === undefined ? [] : [index]
    })
    return windowSlots(win.range, kept, offsets)
  }, [win, pinned, forced, indexOf, offsets])

  // Dopo ogni cambio delle righe nel DOM, prima che si vedano: si misurano
  // quelle montate; con altezze o dati nuovi la riga in cima alla vista
  // resta dov'era; poi si ricalcola la finestra. Misurare il layout prima
  // del paint e ridisegnare con quelle misure è il caso di useLayoutEffect
  // (la regola qui sotto lo scambia per stato derivabile nel render).
  useLayoutEffect(() => {
    if (!body) return
    // oxlint-disable-next-line react/set-state-in-effect -- misure del DOM, non derivabili nel render
    measure()
    const current = anchor.current
    if (current) {
      const shift = anchorShift(current, offsets, indexOf, viewSpan(body).top)
      if (Math.abs(shift) >= 1) scrollByPx(body, shift)
    }
    update()
  }, [body, slots, offsets, indexOf, measure, update])

  // Lo scroll e le dimensioni: dell'area che scorre (o, fuori da lei, di
  // qualunque contenitore, in cattura) e della lista stessa. Una larghezza
  // nuova (il telefono girato, la barra laterale) cambia gli a capo: le
  // altezze misurate non valgono più.
  useLayoutEffect(() => {
    if (!body) return
    const root = scrollRoot(body)
    const target: EventTarget = root ?? document
    const options = { passive: true, capture: root === null }
    target.addEventListener('scroll', update, options)
    window.addEventListener('resize', update)
    let observer: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      let width = body.getBoundingClientRect().width
      observer = new ResizeObserver(() => {
        const next = body.getBoundingClientRect().width
        if (Math.abs(next - width) >= 1) {
          width = next
          // Si rimisura quello che è montato; il resto torna alla stima.
          setMeasures((prev) => ({ heights: new Map(), estimate: prev.estimate }))
        } else {
          measure()
          update()
        }
      })
      observer.observe(body)
      if (root) observer.observe(root)
    }
    return () => {
      target.removeEventListener('scroll', update, options)
      window.removeEventListener('resize', update)
      observer?.disconnect()
    }
  }, [body, measure, update])

  // Tab, Maiusc+Tab e frecce verso la riga dopo (o prima) con un controllo,
  // anche smontata: la si monta, se ne mette a fuoco il primo (o l'ultimo)
  // controllo e il browser la porta in vista; la finestra la segue. In
  // cattura, prima dei controlli della riga: sul pulsante "⋯" le frecce
  // aprirebbero il menu (lo aprono Invio e Spazio), qui passano di riga.
  const onKeyDownCapture = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || !body) return
      const target = event.target as HTMLElement
      const row = rowElement(target)
      const key = row?.getAttribute(ROW_KEY_ATTR)
      const { keys: currentKeys, indexOf: currentIndex, hasControls: has } = latest.current
      const index = key != null ? currentIndex.get(key) : undefined
      if (!row || index === undefined) return
      let step: 1 | -1
      let last = false
      if (event.key === 'Tab') {
        // Dentro la riga il Tab resta del browser; dall'ultimo controllo (o
        // dal primo, all'indietro) va alla riga dopo invece di saltare lo
        // spazio delle righe smontate.
        const controls = rowControls(row)
        const position = controls.indexOf(target)
        if (position < 0) return
        step = event.shiftKey ? -1 : 1
        if (step === 1 ? position < controls.length - 1 : position > 0) return
        last = step === -1
      } else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !event.shiftKey) {
        step = event.key === 'ArrowDown' ? 1 : -1
      } else {
        return
      }
      const next = nextRowWith(index, step, currentKeys.length, has)
      if (next === null) return  // fine della lista: il Tab esce dall'albero, come sempre
      const nextKey = currentKeys[next]
      let nextRow = findRow(body, nextKey)
      if (!nextRow) {
        flushSync(() => setForced(nextKey))
        nextRow = findRow(body, nextKey)
      }
      const controls = nextRow ? rowControls(nextRow) : []
      const control = last ? controls.at(-1) : controls[0]
      if (control) {
        event.preventDefault()
        if (event.key !== 'Tab') event.stopPropagation()
        control.focus()
      }
      // Subito, non al prossimo scroll: col fuoco la riga resta montata
      // anche se il browser non ha dovuto scorrere.
      update()
      setForced(null)
    },
    [body, update],
  )

  return { bodyRef: setBody, slots, onKeyDownCapture }
}
