import { useState } from 'react'
import { toast } from 'sonner'

import { useApproveUpload, type UploadJob } from '@/api/hooks/uploads'
import { Masonry } from '@/components/Masonry'
import { AnalysisSummary } from '@/components/upload/AnalysisSummary'
import { DecisionSummary } from '@/components/upload/DecisionSummary'
import { MatchSummaryCard } from '@/components/upload/MatchSummaryCard'
import { MediaInfoPreview } from '@/components/upload/MediaInfoPreview'
import { OverridesPanel } from '@/components/upload/OverridesPanel'
import { TargetDecisionForm } from '@/components/upload/TargetDecisionForm'
import { ActionBadge, TrackerCheckCard } from '@/components/upload/TrackerCheckCard'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { t } from '@/lib/i18n'
import type { MediaInfoSummary } from '@/lib/mediainfo'
import { effectiveDraft, type TargetDraft } from '@/lib/upload'

// Secondo punto di approvazione (docs/SPEC.md §9): cosa ha trovato
// l'analisi, i valori rilevati da correggere e, per ogni tracker, dupe
// check e decisione. Approvare è la conferma finale: da lì il worker fa
// tutto da solo, quindi il dialogo riassume cosa succederà.
export function DecisionStep({ job }: { job: UploadJob }) {
  const [edits, setEdits] = useState<Record<number, TargetDraft>>({})
  const [confirmOpen, setConfirmOpen] = useState(false)
  const approve = useApproveUpload(job.id)

  const drafts = job.targets.map((target) => ({ target, draft: effectiveDraft(edits[target.id], target) }))
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
      {/* Masonry: ogni scheda nella colonna più corta, così un MediaInfo
          lungo non spinge l'esito dell'analisi sotto di sé. */}
      <Masonry>
        <MatchSummaryCard job={job} />
        <MediaInfoPreview
          summary={((job.analysis as Record<string, unknown> | null)?.mediainfo ?? null) as MediaInfoSummary | null}
          fullText={job.mediainfo_text}
        />
        <OverridesPanel key={JSON.stringify(job.overrides)} job={job} />
        <AnalysisSummary job={job} />
      </Masonry>
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
      <DecisionSummary drafts={drafts} busy={busy} onApprove={() => setConfirmOpen(true)} />

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
