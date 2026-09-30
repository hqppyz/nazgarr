import { LoaderCircleIcon } from 'lucide-react'

import type { UploadJob } from '@/api/hooks/uploads'
import { Masonry } from '@/components/Masonry'
import { MatchSummaryCard } from '@/components/upload/MatchSummaryCard'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/lib/i18n'

function SkeletonCard({ title, lines }: { title: string; lines: string[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {title}
          <LoaderCircleIcon className="size-3.5 animate-spin text-muted-foreground" />
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2">
        {lines.map((width, i) => (
          <Skeleton key={i} className="h-3.5" style={{ width }} />
        ))}
      </CardContent>
    </Card>
  )
}

// Mentre l'analisi gira: la stessa disposizione della schermata di decisione
// (components/upload/DecisionStep.tsx), con la scheda del contenuto già al
// suo posto e le altre come scheletri, così all'arrivo della decisione
// niente cambia dimensione o si sposta.
export function DecisionSkeleton({ job }: { job: UploadJob }) {
  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      <Masonry>
        <MatchSummaryCard job={job} />
        <SkeletonCard title="MediaInfo" lines={['60%', '90%', '75%', '85%', '40%', '70%']} />
        <SkeletonCard title={t('upload.overrides.title')} lines={['80%', '55%']} />
        <SkeletonCard title={t('upload.analysis.title')} lines={['70%', '50%']} />
      </Masonry>
      {job.targets.map((target) => (
        <Card key={target.id} className="min-w-0">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {target.tracker_label}
              <UploadStatusBadge status={target.status} />
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-3.5 w-1/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
