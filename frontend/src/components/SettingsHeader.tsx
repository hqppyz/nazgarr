import type { ReactNode } from 'react'

// L'intestazione di ogni tab delle impostazioni: titolo in alto (alto quanto
// un pulsante, così non si sposta se l'azione c'è o non c'è), sotto le
// informazioni aggiuntive, a destra l'azione (aggiungi, filtro). Da telefono
// l'azione va sotto, così un'azione lunga non schiaccia titolo e descrizione.
export function SettingsHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex min-h-8 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="grid min-w-0 gap-1">
        <h2 className="text-lg leading-8 font-semibold">{title}</h2>
        {description && <p className="max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>
  )
}
