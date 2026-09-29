import type { UploadJob } from '@/api/hooks/uploads'
import { AnalysisSummary } from '@/components/upload/AnalysisSummary'
import { TrackerCheckCard } from '@/components/upload/TrackerCheckCard'

// Secondo punto di approvazione (docs/SPEC.md §9): cosa ha trovato
// l'analisi e, per ogni tracker, il dupe check con l'azione suggerita.
export function DecisionStep({ job }: { job: UploadJob }) {
  return (
    <div className="grid gap-4">
      <AnalysisSummary job={job} />
      {job.targets.map((target) => (
        <TrackerCheckCard key={target.id} job={job} target={target} />
      ))}
    </div>
  )
}
