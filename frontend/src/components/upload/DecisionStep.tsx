import { useState } from 'react'
import { toast } from 'sonner'

import { useApproveUpload, type UploadJob } from '@/api/hooks/uploads'
import { AnalysisSummary } from '@/components/upload/AnalysisSummary'
import { OverridesPanel } from '@/components/upload/OverridesPanel'
import { TargetDecisionForm } from '@/components/upload/TargetDecisionForm'
import { ActionBadge, TrackerCheckCard } from '@/components/upload/TrackerCheckCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { t } from '@/lib/i18n'
import { draftProblem, effectiveDraft, type TargetDraft } from '@/lib/upload'

// Secondo punto di approvazione (docs/SPEC.md §9): cosa ha trovato
// l'analisi, i valori rilevati da correggere e, per ogni tracker, dupe
// check e decisione. Approvare è la conferma finale: da lì il worker fa
// tutto da solo, quindi il dialogo riassume cosa succederà.
export function DecisionStep({ job }: { job: UploadJob }) {
  const [edits, setEdits] = useState<Record<number, TargetDraft>>({})
  const [confirmOpen, setConfirmOpen] = useState(false)
  const approve = useApproveUpload(job.id)

  const drafts = job.targets.map((target) => ({ target, draft: effectiveDraft(edits[target.id], target) }))
  const problems = drafts
    .map(({ target, draft }) => ({ target, problem: draftProblem(draft) }))
    .filter((p) => p.problem !== null)
  const busy = job.targets.some((target) => target.status !== 'awaiting_decision')

  function submit() {
    approve.mutate(
      drafts.map(({ target, draft }) => ({
        target_id: target.id,
        action: draft.action,
        name: draft.action === 'upload' ? draft.name : null,
        flags: draft.action === 'upload' ? draft.flags : null,
        category_id: draft.action === 'upload' ? draft.category_id : null,
        type_id: draft.action === 'upload' ? draft.type_id : null,
        resolution_id: draft.action === 'upload' ? draft.resolution_id : null,
        reseed_torrent_id: draft.action === 'reseed' ? draft.reseed_torrent_id : null,
      })),
      {
        onSuccess: () => setConfirmOpen(false),
        onError: (error) => toast.error(t('upload.decision.approveFailed', { message: error.message })),
      },
    )
  }

  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      <AnalysisSummary job={job} />
      <OverridesPanel key={JSON.stringify(job.overrides)} job={job} />
      {drafts.map(({ target, draft }) => (
        <TrackerCheckCard key={target.id} job={job} target={target}>
          <TargetDecisionForm
            target={target}
            draft={draft}
            disabled={target.status !== 'awaiting_decision'}
            onChange={(next) => setEdits((prev) => ({ ...prev, [target.id]: next }))}
          />
        </TrackerCheckCard>
      ))}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div className="grid gap-0.5 text-sm">
            {problems.length === 0 ? (
              <span>{t('upload.decision.ready')}</span>
            ) : (
              problems.map(({ target, problem }) => (
                <span key={target.id} className="text-amber-600 dark:text-amber-400">
                  {target.tracker_label}: {t(problem!)}
                </span>
              ))
            )}
            {busy && <span className="text-muted-foreground">{t('upload.decision.busy')}</span>}
          </div>
          <Button disabled={problems.length > 0 || busy} onClick={() => setConfirmOpen(true)}>
            {t('upload.decision.approve')}
          </Button>
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('upload.decision.confirmTitle')}</DialogTitle>
            <DialogDescription>{t('upload.decision.confirmDescription')}</DialogDescription>
          </DialogHeader>
          <ul className="grid gap-2 text-sm">
            {drafts.map(({ target, draft }) => (
              <li key={target.id} className="grid gap-0.5">
                <span className="flex items-center gap-2 font-medium">
                  {target.tracker_label}
                  <ActionBadge action={draft.action} />
                </span>
                {draft.action === 'upload' && <span className="font-mono text-xs break-all">{draft.name}</span>}
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button disabled={approve.isPending} onClick={submit}>
              {t('upload.decision.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
