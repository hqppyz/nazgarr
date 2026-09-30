import { ArrowDownIcon, ArrowUpIcon, PlusIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { posterUrl } from '@/api/hooks/metadata'
import { useReorderQueue, useUploads, type UploadJobSummary } from '@/api/hooks/uploads'
import { AuthedPoster } from '@/components/AuthedPoster'
import { ActionBadge } from '@/components/upload/TrackerCheckCard'
import { UploadDetailSheet } from '@/components/upload/UploadDetailSheet'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { t } from '@/lib/i18n'
import { parseApiDate } from '@/lib/time'
import { cn } from '@/lib/utils'

const FINAL_STATES = ['done', 'partial', 'failed', 'cancelled']
// In corso: prima quello che gira, poi la coda in ordine, poi quelli che
// aspettano l'utente, poi quelli che il worker sta identificando/analizzando.
const ACTIVE_ORDER = ['running', 'queued', 'awaiting_decision', 'awaiting_match', 'analyzing', 'identifying']

function title(job: UploadJobSummary) {
  return job.title ? `${job.title}${job.year ? ` (${job.year})` : ''}` : t('upload.untitled')
}

function Poster({ job }: { job: UploadJobSummary }) {
  if (!job.tmdb_id || !job.content_type) return <div className="aspect-[2/3] w-10 shrink-0 rounded bg-muted" />
  return (
    <AuthedPoster
      contentType={job.content_type}
      tmdbId={job.tmdb_id}
      hasPoster
      url={posterUrl({ content_type: job.content_type as 'movie' | 'tv', tmdb_id: job.tmdb_id, poster_path: job.poster_path })}
      className="aspect-[2/3] w-10 shrink-0 overflow-hidden rounded"
    />
  )
}

function TargetOutcomes({ job }: { job: UploadJobSummary }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {job.targets.map((target) => (
        <span key={target.id} className="inline-flex items-center gap-1 text-xs">
          <span className="text-muted-foreground">{target.tracker_label}</span>
          {target.action && FINAL_STATES.includes(job.status) ? (
            target.status === 'failed' ? (
              <Badge variant="outline" className="border-red-500/40 bg-red-500/15 text-red-700 dark:text-red-300">
                {t('upload.status.failed')}
              </Badge>
            ) : (
              <ActionBadge action={target.action} />
            )
          ) : (
            <UploadStatusBadge status={target.status} className="h-5 text-[10px]" />
          )}
        </span>
      ))}
    </div>
  )
}

function ActiveList({ jobs }: { jobs: UploadJobSummary[] }) {
  const navigate = useNavigate()
  const reorder = useReorderQueue()
  const queued = jobs.filter((job) => job.status === 'queued')

  function move(job: UploadJobSummary, delta: number) {
    const ids = queued.map((j) => j.id)
    const from = ids.indexOf(job.id)
    const to = from + delta
    if (to < 0 || to >= ids.length) return
    ;[ids[from], ids[to]] = [ids[to], ids[from]]
    reorder.mutate(ids, { onError: (error) => toast.error(error.message) })
  }

  if (jobs.length === 0) return <p className="py-6 text-center text-sm text-muted-foreground">{t('upload.history.noActive')}</p>
  return (
    <ul className="grid gap-2">
      {jobs.map((job) => {
        const pct = job.progress_total ? Math.round((100 * (job.progress_done ?? 0)) / job.progress_total) : null
        const index = queued.indexOf(job)
        return (
          <li
            key={job.id}
            className="flex cursor-pointer items-center gap-3 rounded-md border p-2 hover:bg-muted/50"
            onClick={() => navigate(`/upload/${job.id}`)}
          >
            <Poster job={job} />
            <div className="grid min-w-0 flex-1 gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate text-sm font-medium">{title(job)}</span>
                {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
                {job.status === 'queued' && (
                  <span className="text-xs text-muted-foreground">#{index + 1}</span>
                )}
              </div>
              <p className="truncate font-mono text-xs text-muted-foreground">{job.relative_path}</p>
              {job.status === 'running' && pct !== null && <Progress value={pct} className="max-w-sm" />}
              <TargetOutcomes job={job} />
            </div>
            {job.status === 'queued' && queued.length > 1 && (
              <div className="flex flex-col" onClick={(e) => e.stopPropagation()}>
                <Button variant="ghost" size="icon-sm" disabled={index === 0} title={t('upload.history.moveUp')} onClick={() => move(job, -1)}>
                  <ArrowUpIcon className="size-4" />
                </Button>
                <Button variant="ghost" size="icon-sm" disabled={index === queued.length - 1} title={t('upload.history.moveDown')} onClick={() => move(job, 1)}>
                  <ArrowDownIcon className="size-4" />
                </Button>
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function HistoryList({ jobs, onOpen }: { jobs: UploadJobSummary[]; onOpen: (id: number) => void }) {
  if (jobs.length === 0) return <p className="py-6 text-center text-sm text-muted-foreground">{t('upload.noUploadsYet')}</p>
  return (
    <ul className="grid gap-2">
      {jobs.map((job) => (
        <li
          key={job.id}
          className={cn('flex cursor-pointer items-center gap-3 rounded-md border p-2 hover:bg-muted/50', job.status === 'cancelled' && 'opacity-60')}
          onClick={() => onOpen(job.id)}
        >
          <Poster job={job} />
          <div className="grid min-w-0 flex-1 gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-sm font-medium">{title(job)}</span>
              {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
              <UploadStatusBadge status={job.status} />
            </div>
            <TargetOutcomes job={job} />
          </div>
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {job.finished_at && parseApiDate(job.finished_at).toLocaleString()}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function UploadQueuePage() {
  const { data, isPending } = useUploads()
  const navigate = useNavigate()
  const [openId, setOpenId] = useState<number | null>(null)
  const [params] = useSearchParams()

  const jobs = data ?? []
  const active = jobs
    .filter((job) => !FINAL_STATES.includes(job.status))
    .sort(
      (a, b) =>
        ACTIVE_ORDER.indexOf(a.status) - ACTIVE_ORDER.indexOf(b.status) ||
        (a.queue_position ?? 0) - (b.queue_position ?? 0) ||
        a.id - b.id,
    )
  const history = jobs.filter((job) => FINAL_STATES.includes(job.status))

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Upload</CardTitle>
        <Button onClick={() => navigate('/upload/new')}>
          <PlusIcon className="size-4" />
          {t('upload.newUpload')}
        </Button>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : (
          <Tabs defaultValue={params.get('tab') ?? (active.length > 0 || history.length === 0 ? 'active' : 'history')}>
            <TabsList>
              <TabsTrigger value="active">{t('upload.history.activeTab', { count: active.length })}</TabsTrigger>
              <TabsTrigger value="history">{t('upload.history.historyTab', { count: history.length })}</TabsTrigger>
            </TabsList>
            <TabsContent value="active" className="pt-3">
              <ActiveList jobs={active} />
            </TabsContent>
            <TabsContent value="history" className="pt-3">
              <HistoryList jobs={history} onOpen={setOpenId} />
            </TabsContent>
          </Tabs>
        )}
      </CardContent>
      <UploadDetailSheet uploadId={openId} onClose={() => setOpenId(null)} />
    </Card>
  )
}
