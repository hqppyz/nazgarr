import { Loader2Icon, Trash2Icon, TriangleAlertIcon } from 'lucide-react'
import { toast } from 'sonner'

import type { Schemas } from '@/api/client'
import { useRemoveNotImported } from '@/api/hooks/library'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'

type Torrent = Schemas['NotImportedItem']

// Quali avvisi impediscono la rimozione lo dice il server (blocking,
// nazgarr/api/torrents.py BLOCKING_WARNINGS): gli altri, come "ultimo
// seeder", si mostrano nella conferma ma non la bloccano.
export function canRemove(torrent: Torrent): boolean {
  return (
    torrent.seed_requirement?.status === 'met' &&
    !(torrent.removal_warnings ?? []).some((warning) => warning.blocking)
  )
}

// La conferma: cosa succede (via dal client, file cancellati dal disco) e
// gli avvisi che restano, prima del pulsante rosso.
export function RemoveTorrentDialog({ torrent, onClose }: { torrent: Torrent | null; onClose: () => void }) {
  const remove = useRemoveNotImported()
  if (!torrent) return null
  const warnings = torrent.removal_warnings ?? []
  return (
    <Dialog open onOpenChange={(open) => !open && !remove.isPending && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('notImported.remove.title')}</DialogTitle>
          <DialogDescription>
            {t('notImported.remove.explain', { client: torrent.client ?? '?', size: formatBytes(torrent.total_bytes) })}
          </DialogDescription>
        </DialogHeader>
        <p className="font-mono text-xs break-all">{torrent.name}</p>
        {warnings.length > 0 && (
          <ul className="grid gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
            {warnings.map((warning) => (
              <li key={warning.code} className="flex items-start gap-1.5">
                <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                {t(`notImported.removable.warning.${warning.code}`, warning.params as Record<string, string | number>)}
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">{t('notImported.remove.irreversible')}</p>
        <DialogFooter>
          <Button variant="outline" disabled={remove.isPending} onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(torrent.client_torrent_id, {
                onSuccess: () => {
                  toast.success(t('notImported.remove.done', { name: torrent.name }))
                  onClose()
                },
                onError: (error) => toast.error(error.message),
              })
            }
          >
            {remove.isPending ? <Loader2Icon className="size-4 animate-spin" /> : <Trash2Icon className="size-4" />}
            {t('notImported.remove.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
