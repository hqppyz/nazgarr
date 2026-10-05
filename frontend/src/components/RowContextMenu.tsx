import { EllipsisIcon } from 'lucide-react'
import type { ReactElement, ReactNode } from 'react'

import { Button } from '@/components/ui/button'

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { t } from '@/lib/i18n'

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
      {/* Su touch la pressione lunga non deve selezionare testo né aprire il menu del sistema. */}
      <ContextMenuTrigger render={children} className="pointer-coarse:select-none [-webkit-touch-callout:none]" />
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

// Il pulsante "⋯" di una riga: le stesse voci del tasto destro, per chi non
// ha il tasto destro (touch) o non lo conosce. Non apre la riga.
export function RowMenuButton({ items, title, className }: { items: RowMenuItem[]; title?: string; className?: string }) {
  if (items.length === 0) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon-xs" className={className} aria-label={t('common.moreActions')}
                  title={t('common.moreActions')} onClick={(event) => event.stopPropagation()} />
        }
      >
        <EllipsisIcon className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent onClick={(event) => event.stopPropagation()}>
        <DropdownMenuGroup>
          {title && <DropdownMenuLabel>{title}</DropdownMenuLabel>}
          {items.map((item) => (
            <DropdownMenuItem key={item.label} onClick={item.onSelect} disabled={item.disabled}>
              {item.icon}
              <span className="grid">
                {item.label}
                {item.hint && <span className="text-xs text-muted-foreground">{item.hint}</span>}
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
