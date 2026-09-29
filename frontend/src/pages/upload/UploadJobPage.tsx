import { ArrowLeftIcon, FileVideoIcon, FolderIcon, LoaderCircleIcon } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { useCancelUpload, useDeleteUpload, useUpload, WORKER_STATES, type UploadJob } from '@/api/hooks/uploads'
import { DecisionStep } from '@/components/upload/DecisionStep'
import { MatchStep } from '@/components/upload/MatchStep'
import { UploadEventLog } from '@/components/upload/UploadEventLog'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { eventMessage } from '@/lib/upload'

const FINAL_STATES = ['done', 'partial', 'failed', 'cancelled']

function JobHeader({ job }: { job: UploadJob }) {
  const navigate = useNavigate()
  const cancel = useCancelUpload()
  const remove = useDeleteUpload()
  const final = FINAL_STATES.includes(job.status)
  const working = WORKER_STATES.includes(job.status)
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="grid min-w-0 gap-1">
        <button
          type="button"
          onClick={() => navigate('/upload')}
          className="flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeftIcon className="size-3" />
          {t('upload.backToList')}
        </button>
        <h1 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
          {job.title ? `${job.title}${job.year ? ` (${job.year})` : ''}` : t('upload.untitled')}
          {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
          <UploadStatusBadge status={job.status} />
        </h1>
        <p className="flex items-center gap-1.5 truncate font-mono text-xs text-muted-foreground" title={job.source_path}>
          {job.is_dir ? <FolderIcon className="size-3.5 shrink-0" /> : <FileVideoIcon className="size-3.5 shrink-0" />}
          {job.relative_path}
        </p>
      </div>
      <div className="flex gap-2">
        {!final && (
          <Button
            variant="outline"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate(job.id, { onError: (error) => toast.error(error.message) })}
          >
            {t('upload.cancelJob')}
          </Button>
        )}
        {!working && (
          <Button
            variant="ghost"
            className="text-destructive"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(job.id, {
                onSuccess: () => navigate('/upload'),
                onError: (error) => toast.error(error.message),
              })
            }
          >
            {t('upload.deleteJob')}
          </Button>
        )}
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
  if (WORKER_STATES.includes(job.status)) return <WorkingStep job={job} />
  if (job.status === 'failed') return <FailedStep job={job} />
  return null
}

export function UploadJobPage() {
  const { uploadId } = useParams()
  const id = Number(uploadId)
  const { data: job, isPending, isError, error } = useUpload(Number.isFinite(id) ? id : null)

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  if (isError || !job) return <p className="text-sm text-destructive">{error?.message}</p>

  return (
    <div className="grid gap-4">
      <JobHeader job={job} />
      <JobBody job={job} />
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('upload.activity')}</CardTitle>
        </CardHeader>
        <CardContent>
          <UploadEventLog events={job.events} targets={job.targets} />
        </CardContent>
      </Card>
    </div>
  )
}
