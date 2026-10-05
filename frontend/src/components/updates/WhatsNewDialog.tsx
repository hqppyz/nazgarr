import { useMarkReleaseNotesSeen, useReleaseNotes } from '@/api/hooks/system'
import { ReleaseNotesList } from '@/components/updates/ReleaseNotesList'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { t } from '@/lib/i18n'

// Una volta sola dopo un aggiornamento: le note delle versioni arrivate
// dall'ultima vista. Un'installazione nuova non ne ha (nazgarr/core/updates.py).
export function WhatsNewDialog() {
  const { data } = useReleaseNotes()
  const seen = useMarkReleaseNotesSeen()
  const open = (data?.entries.length ?? 0) > 0
  return (
    <Dialog open={open} onOpenChange={(next) => !next && seen.mutate()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('updates.whatsNewTitle', { version: data?.current_version ?? '' })}</DialogTitle>
          <DialogDescription>{t('updates.whatsNewDescription')}</DialogDescription>
        </DialogHeader>
        {data && <ReleaseNotesList notes={data.entries} />}
        <DialogFooter>
          <Button onClick={() => seen.mutate()} disabled={seen.isPending}>{t('updates.gotIt')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
