// La finestra di una lista lunga con righe di altezza diversa (l'albero della
// libreria): solo le righe dentro la parte visibile, e un margine attorno,
// sono nel DOM; al posto delle altre uno spazio della loro altezza. Qui la
// parte pura, coi numeri: il hook (hooks/use-virtual-rows.ts) legge il DOM e
// la chiama (audit 2026-10-18, decisione dell'utente 2026-10-21).
//
// Le coordinate sono "della lista": 0 è l'inizio della prima riga.

// Righe [start, end).
export interface RowRange {
  start: number
  end: number
}

// La parte visibile, in coordinate della lista: con la lista più in basso
// dello schermo top è negativo.
export interface ViewSpan {
  top: number
  bottom: number
}

// Dove comincia ogni riga: offsets[i] è l'inizio della riga i, offsets[n]
// l'altezza di tutta la lista. Una riga mai misurata vale `estimate`.
export function rowOffsets(keys: readonly string[], heights: ReadonlyMap<string, number>, estimate: number): Float64Array {
  const offsets = new Float64Array(keys.length + 1)
  for (let i = 0; i < keys.length; i++) offsets[i + 1] = offsets[i] + (heights.get(keys[i]) ?? estimate)
  return offsets
}

// La riga che contiene y; sopra la lista la prima, sotto l'ultima.
export function rowAt(offsets: Float64Array, y: number): number {
  const count = offsets.length - 1
  if (count <= 0) return 0
  let lo = 0
  let hi = count - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (offsets[mid] <= y) lo = mid
    else hi = mid - 1
  }
  return lo
}

// Le righe che toccano [top, bottom): sempre almeno una, se la lista ne ha.
export function rowsBetween(offsets: Float64Array, top: number, bottom: number): RowRange {
  const count = offsets.length - 1
  if (count <= 0) return { start: 0, end: 0 }
  const start = rowAt(offsets, top)
  return { start, end: Math.max(start + 1, Math.min(count, rowAt(offsets, bottom) + 1)) }
}

// La finestra da montare. Con isteresi: resta quella montata finché copre la
// parte visibile più `near` px sopra e sotto; quando non basta più si
// ricalcola con `far` px attorno. Scorrendo, React ridisegna l'albero ogni
// (far - near) px circa, non a ogni riga.
export function nextRange(current: RowRange | null, offsets: Float64Array, view: ViewSpan, near: number, far: number): RowRange {
  const count = offsets.length - 1
  if (count <= 0) return { start: 0, end: 0 }
  const needed = rowsBetween(offsets, view.top - near, view.bottom + near)
  if (current && current.end <= count && current.start <= needed.start && current.end >= needed.end) return current
  return rowsBetween(offsets, view.top - far, view.bottom + far)
}

// Cosa rendere, in ordine: le righe della finestra, quelle tenute montate
// fuori da lei (con il fuoco, o un menu aperto) e lo spazio fra l'una e
// l'altra, così ogni riga resta al suo posto.
export type RowSlot = { kind: 'row'; index: number } | { kind: 'gap'; key: string; height: number }

// La chiave React di uno spazio, accanto alle righe che hanno per chiave il
// loro id (per l'albero il path): col NUL davanti, che nessun nome di file
// può contenere. Con "gap-0" un file "gap-0" in cima all'albero aveva la
// stessa chiave dello spazio che comincia dalla riga 0.
export const gapKey = (start: number) => `\0gap-${start}`

export function windowSlots(range: RowRange, kept: readonly number[], offsets: Float64Array): RowSlot[] {
  const count = offsets.length - 1
  const start = Math.max(0, Math.min(range.start, count))
  const end = Math.max(start, Math.min(range.end, count))
  const extra = kept.filter((i) => i >= 0 && i < count && (i < start || i >= end))
  const indices = [...new Set(extra)].sort((a, b) => a - b)
  // Le tenute prima della finestra, la finestra, le tenute dopo: già in ordine.
  const ordered = [
    ...indices.filter((i) => i < start),
    ...Array.from({ length: end - start }, (_, k) => start + k),
    ...indices.filter((i) => i >= end),
  ]
  const slots: RowSlot[] = []
  let cursor = 0
  for (const index of ordered) {
    if (index > cursor) slots.push({ kind: 'gap', key: gapKey(cursor), height: offsets[index] - offsets[cursor] })
    slots.push({ kind: 'row', index })
    cursor = index + 1
  }
  if (cursor < count) slots.push({ kind: 'gap', key: gapKey(cursor), height: offsets[count] - offsets[cursor] })
  return slots
}

// La riga che tiene ferma la vista: la prima visibile, e di quanto il suo
// inizio sta sopra (negativo) o sotto il bordo alto. Quando cambiano le
// altezze sopra di lei (righe misurate per la prima volta) o i dati (un seed
// finito, un'esclusione), si scorre di quanto serve perché resti lì. Nessuna
// ancora con l'inizio della lista in vista: lì resta l'inizio.
export interface RowAnchor {
  key: string
  offset: number
}

export function anchorAt(offsets: Float64Array, keys: readonly string[], viewTop: number): RowAnchor | null {
  if (keys.length === 0 || viewTop <= 0) return null
  const index = rowAt(offsets, viewTop)
  return { key: keys[index], offset: offsets[index] - viewTop }
}

// Di quanto scorrere (positivo = in giù) perché l'ancora torni dov'era; 0
// se la sua riga non c'è più.
export function anchorShift(anchor: RowAnchor, offsets: Float64Array, indexOf: ReadonlyMap<string, number>, viewTop: number): number {
  const index = indexOf.get(anchor.key)
  if (index === undefined) return 0
  return offsets[index] - anchor.offset - viewTop
}

// La prossima riga (step +1 in giù, -1 in su) che ha qualcosa da mettere a
// fuoco, montata o no; null alla fine della lista.
export function nextRowWith(from: number, step: 1 | -1, count: number, has: (index: number) => boolean): number | null {
  for (let i = from + step; i >= 0 && i < count; i += step) if (has(i)) return i
  return null
}

// Le altezze misurate per id, e la stima per le righe mai montate (la media
// delle prime misurate, vedi mergeHeights).
export interface RowMeasures {
  heights: ReadonlyMap<string, number>
  estimate: number
}

// Le altezze appena lette dal DOM sopra quelle note: lo stesso oggetto se
// nessuna è cambiata di almeno mezzo pixel, così React non ridisegna.
//
// La stima è la media delle prime righe misurate (dopo il montaggio, o dopo
// un cambio di larghezza, che svuota le misure) e poi resta quella: così
// una misura nuova sposta solo le righe misurate, e la vista (che l'ancora
// tiene sulla riga in cima) si muove di quanto sono cambiate loro. Con la
// media ricalcolata a ogni misura cambiava l'inizio di ogni riga mai
// montata: dopo un salto a metà di un albero di 10.000 righe la vista si
// spostava di decine di migliaia di px, e trascinando la barra di
// scorrimento contenuto e cursore si rincorrevano.
export function mergeHeights(prev: RowMeasures, found: readonly (readonly [string, number])[]): RowMeasures {
  let next: Map<string, number> | null = null
  for (const [key, height] of found) {
    if (height <= 0) continue  // jsdom, o una riga nascosta: resta la stima
    const known = prev.heights.get(key)
    if (known !== undefined && Math.abs(known - height) < 0.5) continue
    next ??= new Map(prev.heights)
    next.set(key, height)
  }
  if (!next) return prev
  if (prev.heights.size > 0) return { heights: next, estimate: prev.estimate }
  let total = 0
  for (const height of next.values()) total += height
  return { heights: next, estimate: total / next.size }
}
