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
  // Voce visibile ma non utilizzabile, con il perché sotto l'etichetta.
  disabled?: boolean
  hint?: string
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
            <ContextMenuItem key={item.label} onClick={item.onSelect} disabled={item.disabled}>
              {item.icon}
              <span className="grid">
                {item.label}
                {item.hint && <span className="text-xs text-muted-foreground">{item.hint}</span>}
              </span>
            </ContextMenuItem>
          ))}
        </ContextMenuGroup>
      </ContextMenuContent>
    </ContextMenu>
  )
}
