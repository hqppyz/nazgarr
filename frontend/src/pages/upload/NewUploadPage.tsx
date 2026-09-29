import { CheckIcon, FileVideoIcon, FolderIcon, FolderSearchIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useCreateUpload, useUploadTrackers } from '@/api/hooks/uploads'
import { ForcedIdFields } from '@/components/upload/ForcedIdFields'
import { SourcePickerSheet, type UploadSource } from '@/components/upload/SourcePickerSheet'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { t } from '@/lib/i18n'
import { EMPTY_IDS, toForcedIds } from '@/lib/upload'
import { cn } from '@/lib/utils'

export function NewUploadPage() {
  const navigate = useNavigate()
  const { data: trackers, isPending: trackersPending } = useUploadTrackers()
  const create = useCreateUpload()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [source, setSource] = useState<UploadSource | null>(null)
  const [ids, setIds] = useState(EMPTY_IDS)
  // null = scelta non ancora toccata: tutti i tracker con un profilo di upload.
  const [trackerChoice, setTrackerChoice] = useState<Set<number> | null>(null)
  const selectedTrackers = trackerChoice ?? (trackers ? new Set(trackers.map((tr) => tr.id)) : null)

  const toggleTracker = (id: number) =>
    setTrackerChoice(() => {
      const next = new Set(selectedTrackers ?? [])
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const canSubmit = source !== null && (selectedTrackers?.size ?? 0) > 0 && !create.isPending

  function submit() {
    if (!source || !selectedTrackers) return
    create.mutate(
      {
        disk_id: source.diskId,
        relative_path: source.relativePath,
        tracker_ids: [...selectedTrackers],
        forced_ids: toForcedIds(ids),
      },
      {
        onSuccess: (job) => navigate(`/upload/${job.id}`),
        onError: (error) => toast.error(t('upload.createFailed', { message: error.message })),
      },
    )
  }

  return (
    <div className="grid min-w-0 gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('upload.newUpload')}</CardTitle>
          <CardDescription>{t('upload.newUploadDescription')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6">
          <div className="grid gap-1.5">
            <Label>{t('upload.source')}</Label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPickerOpen(true)}
                className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border bg-transparent px-3 text-left font-mono text-xs shadow-xs hover:bg-muted"
              >
                {source ? (
                  source.isDir ? (
                    <FolderIcon className="size-4 shrink-0 text-primary" />
                  ) : (
                    <FileVideoIcon className="size-4 shrink-0 text-muted-foreground" />
                  )
                ) : null}
                <span className={cn('truncate', !source && 'text-muted-foreground')}>
                  {source ? source.relativePath : t('upload.sourcePlaceholder')}
                </span>
              </button>
              <Button variant="outline" onClick={() => setPickerOpen(true)}>
                <FolderSearchIcon className="size-4" />
                {t('upload.browse')}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{t('upload.sourceHelp')}</p>
          </div>

          <div className="grid gap-2">
            <div>
              <Label>{t('upload.forcedIds')}</Label>
              <p className="text-xs text-muted-foreground">{t('upload.forcedIdsHelp')}</p>
            </div>
            <ForcedIdFields ids={ids} onChange={setIds} />
          </div>

          <div className="grid gap-2">
            <div>
              <Label>{t('upload.trackers')}</Label>
              <p className="text-xs text-muted-foreground">{t('upload.trackersHelp')}</p>
            </div>
            {trackersPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
            {trackers?.length === 0 && <p className="text-sm text-muted-foreground">{t('upload.noUploadTrackers')}</p>}
            <div className="flex flex-wrap gap-2">
              {trackers?.map((tracker) => {
                const active = selectedTrackers?.has(tracker.id) ?? false
                return (
                  <button
                    key={tracker.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => toggleTracker(tracker.id)}
                    className={cn(
                      'flex items-center gap-2 rounded-md border px-3 py-2 text-left text-sm transition',
                      active ? 'border-primary bg-primary/10' : 'text-muted-foreground hover:bg-muted',
                    )}
                  >
                    <span
                      className={cn(
                        'flex size-4 items-center justify-center rounded-sm border',
                        active && 'border-primary bg-primary text-primary-foreground',
                      )}
                    >
                      {active && <CheckIcon className="size-3" />}
                    </span>
                    <span className="grid">
                      <span className="font-medium text-foreground">{tracker.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {tracker.torrent_client_label
                          ? t('upload.seedsOn', { client: tracker.torrent_client_label })
                          : t('upload.noClient')}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => navigate('/upload')}>
              {t('common.cancel')}
            </Button>
            <Button disabled={!canSubmit} onClick={submit}>
              {create.isPending ? t('upload.starting') : t('upload.start')}
            </Button>
          </div>
        </CardContent>
      </Card>
      <SourcePickerSheet open={pickerOpen} onOpenChange={setPickerOpen} initial={source} onSelect={setSource} />
    </div>
  )
}
