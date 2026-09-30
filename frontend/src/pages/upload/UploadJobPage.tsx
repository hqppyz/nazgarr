import { FileVideoIcon, FolderIcon, LoaderCircleIcon } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { useUpload, WORKER_STATES, type UploadJob } from '@/api/hooks/uploads'
import { DecisionStep } from '@/components/upload/DecisionStep'
import { MatchStep } from '@/components/upload/MatchStep'
import { ProgressStep } from '@/components/upload/ProgressStep'
import { ResultStep } from '@/components/upload/ResultStep'
import { FloatingActivity } from '@/components/upload/FloatingActivity'
import { JobToolbar } from '@/components/upload/JobToolbar'
import { MatchSummaryCard } from '@/components/upload/MatchSummaryCard'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { eventMessage } from '@/lib/upload'

// Prima del match: il nome della sorgente, niente poster.
function JobHeader({ job }: { job: UploadJob }) {
  return (
    <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
      <div className="grid min-w-0 flex-1 gap-1">
        <h1 className="flex min-w-0 flex-wrap items-center gap-2 text-lg font-semibold break-words">
          {job.title ? `${job.title}${job.year ? ` (${job.year})` : ''}` : t('upload.untitled')}
          {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
          <UploadStatusBadge status={job.status} />
        </h1>
        <p className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground" title={job.source_path}>
          {job.is_dir ? <FolderIcon className="size-3.5 shrink-0" /> : <FileVideoIcon className="size-3.5 shrink-0" />}
          <span className="truncate">{job.relative_path}</span>
        </p>
      </div>
    </div>
  )
}

function WorkingStep({ job }: { job: UploadJob }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-6 text-sm">
        <LoaderCircleIcon className="size-5 animate-spin text-primary" />
        <span>{t(`upload.working.${job.status}`)}</span>
      </CardContent>
    </Card>
  )
}

function FailedStep({ job }: { job: UploadJob }) {
  const lastError = [...job.events].reverse().find((event) => event.level === 'error')
  return (
    <Card className="border-red-500/40">
      <CardHeader>
        <CardTitle className="text-base">{t('upload.failedTitle')}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {lastError ? eventMessage(lastError) : job.error_message}
      </CardContent>
    </Card>
  )
}

function JobBody({ job }: { job: UploadJob }) {
  if (job.status === 'awaiting_match') return <MatchStep key={job.candidates.length} job={job} />
  if (job.status === 'awaiting_decision') return <DecisionStep job={job} />
  if (job.status === 'queued' || job.status === 'running') return <ProgressStep job={job} />
  if (WORKER_STATES.includes(job.status)) return <WorkingStep job={job} />
  // Un job fallito prima di arrivare ai tracker (identificazione, analisi)
  // ha solo l'errore; dopo l'approvazione, l'esito per tracker.
  if (job.status === 'failed' && !job.targets.some((target) => target.action)) return <FailedStep job={job} />
  if (['done', 'partial', 'failed'].includes(job.status)) return <ResultStep job={job} />
  return null
}

export function UploadJobPage() {
  const { uploadId } = useParams()
  const id = Number(uploadId)
  const { data: job, isPending, isError, error } = useUpload(Number.isFinite(id) ? id : null)

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  if (isError || !job) return <p className="text-sm text-destructive">{error?.message}</p>

  // Dopo il match la testata è la scheda del contenuto (con poster); la
  // pagina di decisione la mette nella sua griglia.
  const matched = job.tmdb_id != null && !['identifying', 'awaiting_match'].includes(job.status)
  return (
    <div className="grid min-w-0 gap-4 pb-16 [&>*]:min-w-0">
      <JobToolbar job={job} />
      {!matched && <JobHeader job={job} />}
      {matched && job.status !== 'awaiting_decision' && <MatchSummaryCard job={job} />}
      <JobBody job={job} />
      <FloatingActivity job={job} />
    </div>
  )
}
