import { LoaderCircleIcon } from 'lucide-react'

import type { UploadJob } from '@/api/hooks/uploads'
import { ExecutionSteps } from '@/components/upload/ExecutionSteps'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { t } from '@/lib/i18n'
import { executionSteps } from '@/lib/upload'

// Lo stage del worker (nazgarr/upload_execute.py): "hashing", "screenshots",
// "tracker:<label>".
function stageLabel(stage: string | null) {
  if (!stage) return null
  if (stage.startsWith('tracker:')) return t('upload.progress.tracker', { tracker: stage.slice('tracker:'.length) })
  return t(`upload.progress.${stage}`)
}

export function ProgressStep({ job }: { job: UploadJob }) {
  const total = job.progress_total
  const pct = total ? Math.round((100 * (job.progress_done ?? 0)) / total) : null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <LoaderCircleIcon className="size-4 animate-spin text-primary" />
          {job.status === 'queued'
            ? t('upload.working.queued')
            : (stageLabel(job.stage) ?? t(`upload.working.${job.status}`))}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <ExecutionSteps steps={executionSteps(job)} />
        {pct !== null && (
          <div className="grid gap-1">
            <Progress value={pct} />
            <span className="text-xs text-muted-foreground tabular-nums">
              {job.progress_done}/{total} ({pct}%)
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
