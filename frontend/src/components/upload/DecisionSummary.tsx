import { CircleAlertIcon, CircleCheckIcon } from 'lucide-react'

import type { UploadTarget } from '@/api/hooks/uploads'
import { ActionBadge } from '@/components/upload/TrackerCheckCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { t } from '@/lib/i18n'
import { draftProblem, type TargetDraft } from '@/lib/upload'

// Riepilogo prima dell'approvazione: per ogni tracker cosa succederà (azione,
// nome o torrent da rimettere in seed, client, flag) e cosa manca ancora.
export function DecisionSummary({
  drafts,
  busy,
  onApprove,
}: {
  drafts: { target: UploadTarget; draft: TargetDraft }[]
  busy: boolean
  onApprove: () => void
}) {
  const problems = drafts.filter(({ draft }) => draftProblem(draft) !== null)
  const reseedName = (target: UploadTarget, torrentId: string | null) =>
    (target.dupes as unknown as { torrent_id_remote: string; name: string }[]).find(
      (d) => d.torrent_id_remote === torrentId,
    )?.name ?? torrentId
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="text-base">{t('upload.decision.summaryTitle')}</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('upload.decision.summaryTracker')}</TableHead>
              <TableHead>{t('upload.decision.action')}</TableHead>
              <TableHead className="w-full">{t('upload.decision.summaryWhat')}</TableHead>
              <TableHead>{t('upload.decision.summaryClient')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {drafts.map(({ target, draft }) => {
              const problem = draftProblem(draft)
              const flags = Object.entries(draft.flags).filter(([, on]) => on).map(([flag]) => flag)
              return (
                <TableRow key={target.id}>
                  <TableCell className="font-medium">{target.tracker_label}</TableCell>
                  <TableCell>
                    <ActionBadge action={draft.action} />
                  </TableCell>
                  <TableCell className="max-w-0">
                    {draft.action === 'upload' && (
                      <div className="grid min-w-0 gap-1">
                        <span className="truncate font-mono text-xs" title={draft.name}>
                          {draft.name || '—'}
                        </span>
                        {flags.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {flags.map((flag) => (
                              <Badge key={flag} variant="secondary" className="h-4 px-1 text-[10px]">
                                {t(`upload.decision.flag.${flag}`)}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                    {draft.action === 'reseed' && (
                      <span className="block truncate font-mono text-xs" title={reseedName(target, draft.reseed_torrent_id) ?? ''}>
                        {reseedName(target, draft.reseed_torrent_id)}
                      </span>
                    )}
                    {draft.action === 'skip' && (
                      <span className="text-xs text-muted-foreground">{t('upload.decision.summarySkip')}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                    {draft.action === 'skip' ? '—' : (target.torrent_client_label ?? t('upload.noClient'))}
                  </TableCell>
                  <TableCell>
                    {problem ? (
                      <span className="flex items-center gap-1 text-xs whitespace-nowrap text-amber-600 dark:text-amber-400">
                        <CircleAlertIcon className="size-3.5" />
                        {t(problem)}
                      </span>
                    ) : (
                      <CircleCheckIcon className="size-4 text-emerald-500" />
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {busy
              ? t('upload.decision.busy')
              : problems.length > 0
                ? t('upload.decision.summaryMissing', { count: problems.length })
                : t('upload.decision.ready')}
          </p>
          <Button disabled={problems.length > 0 || busy} onClick={onApprove}>
            {t('upload.decision.approve')}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
