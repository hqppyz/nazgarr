import type { ReactElement, ReactNode } from 'react'

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'

export interface RowMenuItem {
  label: string
  icon?: ReactNode
  onSelect: () => void
}

// Menu contestuale (tasto destro, o pressione lunga su touch) su una riga di
// tabella o lista: la riga resta quella di sempre, il trigger la rende al
// suo posto. Senza voci non aggiunge niente.
export function RowContextMenu({
  items,
  title,
  children,
}: {
  items: RowMenuItem[]
  title?: string
  children: ReactElement
}) {
  if (items.length === 0) return children
  return (
    <ContextMenu>
      <ContextMenuTrigger render={children} />
      <ContextMenuContent>
        <ContextMenuGroup>
          {title && <ContextMenuLabel>{title}</ContextMenuLabel>}
          {items.map((item) => (
            <ContextMenuItem key={item.label} onClick={item.onSelect}>
              {item.icon}
              {item.label}
            </ContextMenuItem>
          ))}
        </ContextMenuGroup>
      </ContextMenuContent>
    </ContextMenu>
  )
}
