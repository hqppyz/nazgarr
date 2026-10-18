import { Menu } from '@base-ui/react/menu'
import { Popover } from '@base-ui/react/popover'
import { useState, type ReactNode } from 'react'

// Un menu o un popover di Base UI per tutte le righe di una lista lunga,
// invece di uno per riga: ogni root montato costa, e l'albero della libreria
// o il triage ne avevano due o tre per riga (audit 2026-10-18). Le righe
// portano trigger staccati (handle + payload); il componente condiviso
// (SharedRowMenu, InfoPopoverHost) disegna il contenuto della riga attiva.

// Il menu "⋯": il payload è l'id della riga.
export type RowMenuHandle = Menu.Handle<string>

export function useRowMenuHandle(): RowMenuHandle {
  const [handle] = useState(() => Menu.createHandle<string>())
  return handle
}

// Quello che un trigger passa al popover condiviso della sua lista.
export interface InfoPopoverPayload {
  content: ReactNode
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}

export type InfoPopoverHandle = Popover.Handle<InfoPopoverPayload>

export function useInfoPopoverHandle(): InfoPopoverHandle {
  const [handle] = useState(() => Popover.createHandle<InfoPopoverPayload>())
  return handle
}
