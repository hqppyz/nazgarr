import { TrashIcon, TriangleAlertIcon } from 'lucide-react'
import { useState } from 'react'

import { useDeleteDisk, useDiskDeletePreview } from '@/api/hooks/disks'
import { useDeleteTracker, useTrackerDeletePreview } from '@/api/hooks/trackers'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { t, uiLocale } from '@/lib/i18n'

// Eliminare un tracker o un disco già usati porta via la sua storia nel DB
// (decisione dell'utente, 2026-10-18: ON DELETE CASCADE). La conferma dice
// quanta, letta all'apertura (GET .../delete-preview), e che sul disco, sul
// tracker e nei client non cambia niente. Con un lavoro suo in corso il
// server rifiuterebbe (409): lo si dice subito, e Elimina resta spento.
type Row = { label: string; count: number }

function DeleteDialog({
  title,
  description,
  intro,
  nothing,
  untouched,
  rows,
  kept,
  busy,
  loading,
  error,
  pending,
  open,
  onOpenChange,
  onConfirm,
}: {
  title: string
  description: string
  intro: string
  nothing: string
  untouched: string
  rows: Row[] | undefined
  kept?: string | null
  busy?: string | null
  loading: boolean
  error: Error | null
  pending: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}) {
  const shown = rows?.filter((row) => row.count > 0) ?? []
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        render={
          <Button variant="ghost" size="icon-sm" title={t('common.delete')}>
            <TrashIcon className="size-4" />
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="pr-6 break-words">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 text-sm">
          {loading && <p className="text-muted-foreground">{t('common.loading')}</p>}
          {error && <p className="text-destructive">{t('config.deletePreviewFailed', { message: error.message })}</p>}
          {rows && (shown.length > 0 ? (
            <div className="grid gap-1.5">
              <p>{intro}</p>
              <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 rounded-md border px-3 py-2 text-xs">
                {shown.map((row) => (
                  <div key={row.label} className="contents">
                    <dt className="text-muted-foreground">{row.label}</dt>
                    <dd className="text-right tabular-nums">{row.count.toLocaleString(uiLocale())}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : (
            <p>{nothing}</p>
          ))}
          {kept && <p className="text-muted-foreground">{kept}</p>}
          {rows && <p className="font-medium">{untouched}</p>}
          {busy && (
            <p role="alert" className="flex items-start gap-1.5 text-amber-700 dark:text-amber-300">
              <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>{busy}</span>
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
          <Button
            className="bg-destructive text-white hover:bg-destructive/90"
            disabled={pending || loading || Boolean(busy)}
            onClick={() => {
              onConfirm()
              onOpenChange(false)
            }}
          >
            {t('common.delete')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function TrackerDeleteButton({ tracker }: { tracker: { id: number; label: string } }) {
  const [open, setOpen] = useState(false)
  const preview = useTrackerDeletePreview(tracker.id, open)
  const deleteTracker = useDeleteTracker()
  const p = preview.data
  const rows = p && [
    { label: t('trackers.deletePreview.candidates'), count: p.candidates },
    { label: t('trackers.deletePreview.reviews'), count: p.reviews },
    { label: t('trackers.deletePreview.executions'), count: p.executions },
    { label: t('trackers.deletePreview.executionsSeeding'), count: p.executions_seeding },
    { label: t('trackers.deletePreview.matchAttempts'), count: p.match_attempts },
    { label: t('trackers.deletePreview.uploadTargets'), count: p.upload_targets },
    { label: t('trackers.deletePreview.uploadProfile'), count: p.upload_profile ? 1 : 0 },
  ]
  return (
    <DeleteDialog
      title={t('trackers.deleteTitle', { label: tracker.label })}
      description={t('trackers.deleteDescription')}
      intro={t('trackers.deletePreview.intro')}
      nothing={t('trackers.deletePreview.nothing')}
      untouched={t('trackers.deletePreview.untouched')}
      rows={rows}
      busy={p?.busy ? t('trackers.deletePreview.busy') : null}
      loading={preview.isFetching && !p}
      error={preview.error}
      pending={deleteTracker.isPending}
      open={open}
      onOpenChange={setOpen}
      onConfirm={() => deleteTracker.mutate(tracker.id)}
    />
  )
}

export function DiskDeleteButton({ disk }: { disk: { id: number; label: string } }) {
  const [open, setOpen] = useState(false)
  const preview = useDiskDeletePreview(disk.id, open)
  const deleteDisk = useDeleteDisk()
  const p = preview.data
  const rows = p && [
    { label: t('disks.deletePreview.folders'), count: p.folders },
    { label: t('disks.deletePreview.mediaFiles'), count: p.media_files },
    { label: t('disks.deletePreview.seedFiles'), count: p.seed_files },
    { label: t('disks.deletePreview.reviews'), count: p.reviews },
    { label: t('disks.deletePreview.executions'), count: p.executions },
    { label: t('disks.deletePreview.matchAttempts'), count: p.match_attempts },
    { label: t('disks.deletePreview.watchEntries'), count: p.watch_entries },
    { label: t('disks.deletePreview.clientLinks'), count: p.client_links },
  ]
  return (
    <DeleteDialog
      title={t('disks.deleteTitle', { label: disk.label })}
      description={t('disks.deleteDescription')}
      intro={t('disks.deletePreview.intro')}
      nothing={t('disks.deletePreview.nothing')}
      untouched={t('disks.deletePreview.untouched')}
      rows={rows}
      kept={p?.upload_jobs ? t('disks.deletePreview.uploadsKept', { count: p.upload_jobs }) : null}
      busy={p?.busy ? t(p.busy === 'upload' ? 'disks.deletePreview.busyUpload' : 'disks.deletePreview.busyReseed') : null}
      loading={preview.isFetching && !p}
      error={preview.error}
      pending={deleteDisk.isPending}
      open={open}
      onOpenChange={setOpen}
      onConfirm={() => deleteDisk.mutate(disk.id)}
    />
  )
}
