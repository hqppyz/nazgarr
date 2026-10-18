import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { EllipsisIcon } from 'lucide-react'
import { useState, type ReactElement, type ReactNode, type SyntheticEvent } from 'react'

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
import type { RowMenuHandle } from '@/lib/popupHandles'

export interface RowMenuItem {
  label: string
  icon?: ReactNode
  onSelect: () => void
  // Voce visibile ma non utilizzabile, con il perché sotto l'etichetta.
  disabled?: boolean
  hint?: string
}

// Le voci di una riga e il titolo sopra (di solito il percorso).
export interface RowMenu {
  title?: string
  items: RowMenuItem[]
}

const stop = (event: SyntheticEvent) => event.stopPropagation()

function ItemLabel({ item }: { item: RowMenuItem }) {
  return (
    <>
      {item.icon}
      <span className="grid">
        {item.label}
        {item.hint && <span className="text-xs text-muted-foreground">{item.hint}</span>}
      </span>
    </>
  )
}

function ContextItems({ menu }: { menu: RowMenu }) {
  return (
    <ContextMenuGroup>
      {menu.title && <ContextMenuLabel>{menu.title}</ContextMenuLabel>}
      {menu.items.map((item) => (
        <ContextMenuItem key={item.label} onClick={item.onSelect} disabled={item.disabled}>
          <ItemLabel item={item} />
        </ContextMenuItem>
      ))}
    </ContextMenuGroup>
  )
}

function DropdownItems({ menu }: { menu: RowMenu }) {
  return (
    <DropdownMenuGroup>
      {menu.title && <DropdownMenuLabel>{menu.title}</DropdownMenuLabel>}
      {menu.items.map((item) => (
        <DropdownMenuItem key={item.label} onClick={item.onSelect} disabled={item.disabled}>
          <ItemLabel item={item} />
        </DropdownMenuItem>
      ))}
    </DropdownMenuGroup>
  )
}

// Su touch la pressione lunga non deve selezionare testo né aprire il menu del sistema.
const TOUCH_TRIGGER = 'pointer-coarse:select-none [-webkit-touch-callout:none]'

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
      <ContextMenuTrigger render={children} className={TOUCH_TRIGGER} />
      <ContextMenuContent>
        <ContextItems menu={{ title, items }} />
      </ContextMenuContent>
    </ContextMenu>
  )
}

const MENU_BUTTON_PROPS = { variant: 'ghost', size: 'icon-xs' } as const

// Il pulsante "⋯" di una riga: le stesse voci del tasto destro, per chi non
// ha il tasto destro (touch) o non lo conosce. Non apre la riga.
export function RowMenuButton({ items, title, className }: { items: RowMenuItem[]; title?: string; className?: string }) {
  if (items.length === 0) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button {...MENU_BUTTON_PROPS} className={className} aria-label={t('common.moreActions')}
                  title={t('common.moreActions')} onClick={stop} />
        }
      >
        <EllipsisIcon className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent onClick={stop}>
        <DropdownItems menu={{ title, items }} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// --- Un menu solo per tutte le righe di una lista lunga -------------------
//
// RowContextMenu e RowMenuButton montano due menu di Base UI per riga: con
// migliaia di righe (l'albero della libreria, il triage) erano la parte più
// cara di ogni render. Qui un menu contestuale e un menu "⋯" per tutta la
// lista: la riga porta solo il suo id (data-row-menu, o il payload del
// pulsante, lib/popupHandles.ts) e le voci si calcolano quando il menu si
// apre (audit 2026-10-18).

// Il menu contestuale di tutte le righe dentro `render` (di solito il
// <tbody>): la riga sotto il cursore (o il dito) è quella col data-row-menu
// più vicino. Senza voci per quella riga resta il menu del browser, come
// prima.
export function SharedRowContextMenu({
  menuFor,
  render,
  children,
}: {
  menuFor: (id: string) => RowMenu | null
  render: ReactElement
  children: ReactNode
}) {
  const [target, setTarget] = useState<string | null>(null)
  // In cattura: prima che il trigger di Base UI apra il menu, così il menu si
  // apre già con le voci della riga giusta.
  const aim = (event: SyntheticEvent) => {
    const row = event.target instanceof Element ? event.target.closest('[data-row-menu]') : null
    const id = row?.getAttribute('data-row-menu') ?? null
    if (id === null || !menuFor(id)?.items.length) {
      event.stopPropagation()
      return
    }
    setTarget(id)
  }
  const menu = target !== null ? menuFor(target) : null
  return (
    <ContextMenu>
      <ContextMenuTrigger render={render} className={TOUCH_TRIGGER} onContextMenuCapture={aim} onTouchStartCapture={aim}>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent>{menu && <ContextItems menu={menu} />}</ContextMenuContent>
    </ContextMenu>
  )
}

// Il menu "⋯" di tutte le righe: si apre accanto al RowMenuTrigger premuto.
export function SharedRowMenu({ handle, menuFor }: { handle: RowMenuHandle; menuFor: (id: string) => RowMenu | null }) {
  return (
    <MenuPrimitive.Root handle={handle}>
      {({ payload }) => {
        const menu = payload != null ? menuFor(payload) : null
        return (
          menu && (
            <DropdownMenuContent onClick={stop}>
              <DropdownItems menu={menu} />
            </DropdownMenuContent>
          )
        )
      }}
    </MenuPrimitive.Root>
  )
}

// Il pulsante "⋯" di una riga, per il SharedRowMenu della sua lista.
export function RowMenuTrigger({ handle, id, className }: { handle: RowMenuHandle; id: string; className?: string }) {
  return (
    <MenuPrimitive.Trigger
      handle={handle}
      payload={id}
      render={
        <Button {...MENU_BUTTON_PROPS} className={className} aria-label={t('common.moreActions')}
                title={t('common.moreActions')} onClick={stop} />
      }
    >
      <EllipsisIcon className="size-4" />
    </MenuPrimitive.Trigger>
  )
}
