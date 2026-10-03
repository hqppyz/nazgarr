import { ChevronRightIcon, Loader2Icon, RotateCcwIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  useApproveReview,
  useCandidateAudit,
  useRecentSeedJobs,
  useRejectReview,
  useRetryFailed,
  useReviews,
} from '@/api/hooks/reviews'
import { ErrorsPopover } from '@/components/ErrorsPopover'
import { FullCheckButton } from '@/components/FullCheckButton'
import { StateBadge } from '@/components/StateBadge'
import { VerifyStatus } from '@/components/VerifyStatus'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { parseApiDate, relativeFromNow } from '@/lib/time'
import { cn } from '@/lib/utils'

type Review = NonNullable<ReturnType<typeof useReviews>['data']>[number]
type Layout = NonNullable<Review['layout']>

// Riepilogo di un torrent multi-file (film con extra, season pack), dai
// dati di candidate_file: cosa verrà ricreato da file locali e cosa
// scaricherà il client dopo il recheck.
function layoutSummary(layout: Layout): string {
  const parts = [
    t(layout.video_count > 1 ? 'reseeding.seasonPack' : 'reseeding.withExtras'),
    t('reseeding.videosVerified', {
      verified: layout.videos_piece_verified,
      matched: layout.videos_matched,
      total: layout.video_count,
    }),
  ]
  if (layout.extras_missing > 0) {
    parts.push(
      t('reseeding.extrasToDownload', {
        count: layout.extras_missing,
        size: formatBytes(layout.extras_missing_bytes),
      }),
    )
  }
  return parts.join(' · ')
}

function LayoutFiles({ layout }: { layout: Layout }) {
  return (
    <div className="border-t bg-muted/30 p-3">
      <p className="mb-1.5 text-xs font-medium text-muted-foreground">{t('reseeding.torrentFiles')}</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('reseeding.fileInTorrent')}</TableHead>
            <TableHead>{t('reseeding.localFile')}</TableHead>
            <TableHead className="w-24 text-right">{t('library.columnSize')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {layout.files.map((f) => (
            <TableRow key={f.torrent_path}>
              <TableCell className="max-w-0 truncate font-mono text-xs" title={f.torrent_path}>
                {f.torrent_path}
              </TableCell>
              <TableCell className="max-w-0 truncate text-xs" title={f.local_path ?? undefined}>
                {f.local_path ? (
                  <span className={cn(f.piece_verified === false && 'text-destructive')}>
                    {f.local_path}
                    {f.piece_verified && <Badge variant="secondary" className="ml-1.5">{t('reseeding.verified')}</Badge>}
                  </span>
                ) : (
                  <span className="text-muted-foreground">
                    {f.is_video ? t('reseeding.missingVideo') : t('reseeding.clientDownloads')}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-right text-xs tabular-nums">
                {f.size_bytes != null ? formatBytes(f.size_bytes) : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function CandidateAudit({ mediaItemId }: { mediaItemId: number }) {
  const { data, isPending } = useCandidateAudit(mediaItemId)

  if (isPending) return <p className="p-3 text-xs text-muted-foreground">{t('reseeding.loadingCandidates')}</p>

  return (
    <div className="grid gap-1.5 border-t bg-muted/30 p-3">
      <p className="text-xs font-medium text-muted-foreground">
        {t('reseeding.allCandidatesEvaluated')}
      </p>
      {data?.map((c) => (
        <div key={c.id} className="flex items-center justify-between gap-2 text-xs">
          <span className="truncate font-mono">{c.name}</span>
          <div className="flex shrink-0 items-center gap-2">
            {c.ambiguity_reason && <span className="text-muted-foreground">{c.ambiguity_reason}</span>}
            <span>{(c.confidence * 100).toFixed(0)}%</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function ReviewRow({ review }: { review: Review }) {
  const [open, setOpen] = useState(false)
  const approve = useApproveReview()
  const reject = useRejectReview()
  const verifying = review.verify_status === 'verifying'

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-b last:border-b-0">
      <div className="flex items-center gap-2 px-3 py-2">
        <CollapsibleTrigger>
          <ChevronRightIcon className={cn('size-4 text-muted-foreground transition-transform', open && 'rotate-90')} />
        </CollapsibleTrigger>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{review.candidate_name}</p>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary">{review.direction}</Badge>
            <span>{(review.confidence * 100).toFixed(0)}%</span>
            {review.ambiguity_reason && <span>{review.ambiguity_reason}</span>}
            {review.status === 'auto_approved' && <Badge>{t('reseeding.autoApproved')}</Badge>}
            {/* Il file seeda già altrove: è un cross-seed, non un file da salvare. */}
            {(review.seeding_on?.length ?? 0) > 0 && (
              <Badge variant="outline" title={t('reseeding.crossSeedHelp', { trackers: review.seeding_on ?? [] })}>
                {t('reseeding.crossSeed', { trackers: review.seeding_on ?? [] })}
              </Badge>
            )}
          </div>
          {review.layout && <p className="text-xs text-muted-foreground">{layoutSummary(review.layout)}</p>}
          <VerifyStatus review={review} />
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={verifying || approve.isPending}
          title={verifying ? t('reseeding.verifyingHint') : undefined}
          onClick={() => approve.mutate(review.id)}
        >
          {verifying && <Loader2Icon className="size-4 animate-spin" />}
          {verifying ? t('reseeding.verifying') : t('reseeding.approve')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            reject.mutate(review.id)
          }
        >
          {t('reseeding.reject')}
        </Button>
      </div>
      <CollapsibleContent>
        {review.layout && <LayoutFiles layout={review.layout} />}
        <CandidateAudit mediaItemId={review.media_item_id} />
      </CollapsibleContent>
    </Collapsible>
  )
}

function ReviewCard() {
  const { data: reviews, isPending } = useReviews()

  return (
    <Card data-tour="views.review">
      <CardHeader>
        <CardTitle>{t('misc.review')}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isPending && <p className="p-3 text-sm text-muted-foreground">{t('common.loading')}</p>}
        {reviews?.map((r) => (
          <ReviewRow key={r.id} review={r} />
        ))}
        {reviews?.length === 0 && <p className="p-3 text-sm text-muted-foreground">{t('reseeding.noPendingReviews')}</p>}
      </CardContent>
    </Card>
  )
}

type SeedJob = NonNullable<ReturnType<typeof useRecentSeedJobs>['data']>[number]
type ExecutionFilter = 'all' | 'seeding' | 'in_progress' | 'failed'

const FILTERS: ExecutionFilter[] = ['all', 'seeding', 'in_progress', 'failed']

function ExecutionRow({ job }: { job: SeedJob }) {
  const retry = useRetryFailed()
  const when = job.torrent_added_at ?? job.hardlink_created_at
  return (
    <TableRow>
      <TableCell className="max-w-0 w-full">
        <p className="truncate font-mono text-xs" title={job.candidate_name ?? undefined}>
          {job.candidate_name ?? t('reseeding.candidateHash', { id: job.candidate_id })}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {[job.tracker, job.torrent_client, job.direction && t(`reseeding.direction.${job.direction}`)]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </TableCell>
      <TableCell className="whitespace-nowrap text-xs text-muted-foreground" title={when ? parseApiDate(when).toLocaleString() : undefined}>
        {when ? relativeFromNow(when) : '—'}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-1.5">
          <StateBadge state={job.display_status ?? job.final_status} compact />
          {job.recheck_skipped && (
            <span className="text-[length:var(--text-xxs)] text-muted-foreground" title={t('reseeding.recheckSkippedHint')}>
              {t('reseeding.recheckSkipped')}
            </span>
          )}
          {job.error_message && (
            <ErrorsPopover count={1} messages={[job.error_message]} title={t('reseeding.executionError')} />
          )}
        </div>
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-1.5">
          {(job.display_status ?? job.final_status) !== 'seeding' && (
            <FullCheckButton
              target={{ candidateId: job.candidate_id, seedJobId: job.id }}
              label={job.candidate_name ?? t('reseeding.candidateHash', { id: job.candidate_id })}
            />
          )}
          {job.final_status === 'failed' && (
            <Button
              size="xs"
              variant="outline"
              disabled={retry.isPending}
              onClick={() =>
                retry.mutate(job.id, {
                  onSuccess: () => toast.success(t('reseeding.retryCompleted')),
                  onError: (error) => toast.error(t('reseeding.retryFailed', { message: error.message })),
                })
              }
            >
              <RotateCcwIcon className="size-3" />
              {t('reseeding.retry')}
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

// Tutte le esecuzioni (hardlink + torrent aggiunto al client), non solo
// quelle fallite: si vede anche cosa è tornato in seed e cosa aspetta il recheck.
function ExecutionsCard() {
  const { data: jobs, isPending } = useRecentSeedJobs()
  const [filter, setFilter] = useState<ExecutionFilter>('all')
  // "removed" (era in seed, torrent tolto dal client) conta solo in All.
  const statusOf = (j: SeedJob) => j.display_status ?? j.final_status
  const count = (f: ExecutionFilter) => (f === 'all' ? jobs?.length ?? 0 : jobs?.filter((j) => statusOf(j) === f).length ?? 0)
  const shown = jobs?.filter((j) => filter === 'all' || statusOf(j) === filter)

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('reseeding.executions')}</CardTitle>
        <CardDescription>{t('reseeding.executionsHint')}</CardDescription>
        <CardAction>
          <ToggleGroupSingle value={filter} onValueChange={(v) => setFilter(v as ExecutionFilter)} variant="outline" size="sm">
            {FILTERS.map((f) => (
              <ToggleGroupItem key={f} value={f}>
                {t(`reseeding.filter.${f}`)}
                <span className="ml-1 font-mono text-xs text-muted-foreground tabular-nums">{count(f)}</span>
              </ToggleGroupItem>
            ))}
          </ToggleGroupSingle>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('reseeding.torrent')}</TableHead>
              <TableHead>{t('reseeding.added')}</TableHead>
              <TableHead>{t('reseeding.status')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {shown?.map((job) => <ExecutionRow key={job.id} job={job} />)}
            {shown?.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-sm text-muted-foreground">
                  {t('reseeding.noExecutions')}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

export function ReseedingPage() {
  return (
    <div className="grid gap-6">
      <ReviewCard />
      <ExecutionsCard />
    </div>
  )
}
