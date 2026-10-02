import { CheckIcon, FileVideoIcon, FolderIcon, FolderSearchIcon, PackageIcon, TriangleAlertIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { useCreateUpload, useImageHostStatus, useUploadTrackers } from '@/api/hooks/uploads'
import { ForcedIdFields } from '@/components/upload/ForcedIdFields'
import { SourcePickerSheet, type UploadSource } from '@/components/upload/SourcePickerSheet'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { t } from '@/lib/i18n'
import { EMPTY_IDS, parseNewUploadParams, toForcedIds } from '@/lib/upload'
import { readPackState, type PackState } from '@/lib/pack'
import { cn } from '@/lib/utils'

const IMAGE_HOST_LABELS: Record<string, string> = { imgbox: 'Imgbox', pixhost: 'Pixhost' }

// Prima di iniziare: senza una API key gli screenshot vanno solo sugli host
// anonimi, senza nessun host utilizzabile un upload fallirebbe agli screenshot.
function ImageHostWarning() {
  const { data } = useImageHostStatus()
  if (!data || data.with_api_key.length > 0) return null
  const none = data.usable.length === 0
  return (
    <div
      role="alert"
      className={cn(
        'flex gap-3 rounded-lg border p-4 text-sm',
        none ? 'border-red-500/40 bg-red-500/10' : 'border-amber-500/40 bg-amber-500/10',
      )}
    >
      <TriangleAlertIcon
        className={cn('mt-0.5 size-4 shrink-0', none ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400')}
      />
      <div className="grid gap-1">
        <p className="font-medium">{t(none ? 'upload.imageHostsNoneTitle' : 'upload.imageHostsNoKeyTitle')}</p>
        <p className="text-muted-foreground">
          {none
            ? t('upload.imageHostsNone')
            : t('upload.imageHostsNoKey', { hosts: data.usable.map((key) => IMAGE_HOST_LABELS[key] ?? key).join(', ') })}
        </p>
        <Link to="/config?tab=images" className="w-fit font-medium text-primary underline-offset-4 hover:underline">
          {t('upload.imageHostsSettings')}
        </Link>
      </div>
    </div>
  )
}

export function NewUploadPage() {
  const navigate = useNavigate()
  const { data: trackers, isPending: trackersPending } = useUploadTrackers()
  const create = useCreateUpload()
  const [pickerOpen, setPickerOpen] = useState(false)
  // Arrivando dalla vista poster: sorgente e TMDB già scelti (?disk=&path=&tmdb=).
  const [params] = useSearchParams()
  const [initial] = useState(() => parseNewUploadParams(params))
  const [source, setSource] = useState<UploadSource | null>(initial.source)
  // Episodi scelti a mano per un pack (nazgarr/upload_pack.py), dalla
  // libreria o dalla vista dei torrent.
  const location = useLocation()
  const [pack, setPack] = useState<PackState | null>(() => readPackState(location.state))
  const [ids, setIds] = useState({ ...EMPTY_IDS, tmdb: initial.tmdb })
  // null = scelta non ancora toccata: tutti i tracker con un profilo di upload.
  const [trackerChoice, setTrackerChoice] = useState<Set<number> | null>(
    () => (initial.trackers ? new Set(initial.trackers) : null),
  )
  const selectedTrackers = trackerChoice ?? (trackers ? new Set(trackers.map((tr) => tr.id)) : null)

  // Freeleech scelto per tracker (solo per chi lo concede): undefined = il
  // default del profilo.
  const [freeleech, setFreeleech] = useState<Record<number, number>>({})
  const freeleechOf = (id: number) =>
    freeleech[id] ?? trackers?.find((tr) => tr.id === id)?.default_freeleech ?? 0

  const toggleTracker = (id: number) =>
    setTrackerChoice(() => {
      const next = new Set(selectedTrackers ?? [])
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const canSubmit = (pack !== null || source !== null) && (selectedTrackers?.size ?? 0) > 0 && !create.isPending

  function submit() {
    if ((!source && !pack) || !selectedTrackers) return
    create.mutate(
      {
        ...(pack
          ? { disk_id: pack.diskId, files: pack.files }
          : { disk_id: source!.diskId, relative_path: source!.relativePath }),
        tracker_ids: [...selectedTrackers],
        forced_ids: toForcedIds(ids),
        tracker_choices: Object.fromEntries(
          [...selectedTrackers]
            .filter((id) => freeleechOf(id) > 0)
            .map((id) => [id, { freeleech: freeleechOf(id) }]),
        ),
      },
      {
        onSuccess: (job) => navigate(`/upload/${job.id}`),
        onError: (error) => toast.error(t('upload.createFailed', { message: error.message })),
      },
    )
  }

  return (
    <div className="grid min-w-0 gap-4">
      <ImageHostWarning />
      <Card>
        <CardHeader>
          <CardTitle>{t('upload.newUpload')}</CardTitle>
          <CardDescription>{t('upload.newUploadDescription')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6">
          {pack ? (
            <div className="grid gap-1.5">
              <Label>{t('upload.source')}</Label>
              <div className="grid gap-1 rounded-md border bg-muted/30 p-2.5 font-mono text-xs">
                <span className="flex items-center gap-1.5 font-sans text-sm font-medium">
                  <PackageIcon className="size-4 shrink-0 text-primary" />
                  {t('pack.source', { count: pack.files.length })}
                </span>
                {pack.files.map((file) => (
                  <span key={file} className="flex min-w-0 items-center gap-1.5 pl-5 break-all text-muted-foreground">
                    <FileVideoIcon className="size-3.5 shrink-0" />
                    {file}
                  </span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{t('pack.sourceHelp')}</p>
              <Button variant="link" size="sm" className="h-auto w-fit p-0" onClick={() => setPack(null)}>
                {t('pack.change')}
              </Button>
            </div>
          ) : (
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
          )}

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
                      {active && tracker.freeleech_options.length > 0 && (
                        <span className="mt-1 flex flex-wrap gap-1" onClick={(e) => e.stopPropagation()}>
                          {[0, ...tracker.freeleech_options].map((value) => (
                            <span
                              key={value}
                              role="radio"
                              aria-checked={freeleechOf(tracker.id) === value}
                              tabIndex={0}
                              onClick={() => setFreeleech((prev) => ({ ...prev, [tracker.id]: value }))}
                              onKeyDown={(e) => e.key === 'Enter' && setFreeleech((prev) => ({ ...prev, [tracker.id]: value }))}
                              className={cn(
                                'cursor-pointer rounded border px-1.5 text-[11px] tabular-nums',
                                freeleechOf(tracker.id) === value
                                  ? 'border-primary bg-primary/10 text-primary'
                                  : 'text-muted-foreground hover:bg-muted',
                              )}
                            >
                              {value === 0 ? t('upload.noFreeleech') : `FL ${value}%`}
                            </span>
                          ))}
                        </span>
                      )}
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
