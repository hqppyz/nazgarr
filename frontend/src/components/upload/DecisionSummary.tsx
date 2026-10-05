import { CircleAlertIcon, CircleCheckIcon } from 'lucide-react'

import type { UploadTarget } from '@/api/hooks/uploads'
import { ActionBadge } from '@/components/upload/TrackerCheckCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { t } from '@/lib/i18n'
import { draftProblem, type TargetDraft } from '@/lib/upload'

// Freeleech e flag accesi di un upload, come badge.
function FlagBadges({ draft }: { draft: TargetDraft }) {
  const flags = Object.entries(draft.flags).filter(([, on]) => on).map(([flag]) => flag)
  if (flags.length === 0 && draft.freeleech <= 0) return null
  return (
    <div className="flex flex-wrap gap-1">
      {draft.freeleech > 0 && (
        <Badge variant="secondary" className="h-4 px-1 text-[10px]">
          FL {draft.freeleech}%
        </Badge>
      )}
      {flags.map((flag) => (
        <Badge key={flag} variant="secondary" className="h-4 px-1 text-[10px]">
          {t(`upload.decision.flag.${flag}`)}
        </Badge>
      ))}
    </div>
  )
}

// Riepilogo prima dell'approvazione: per ogni tracker cosa succederà (azione,
// nome o torrent da rimettere in seed, client, flag) e cosa manca ancora.
export function DecisionSummary({
  drafts,
  busy,
  blocked = null,
  onApprove,
}: {
  drafts: { target: UploadTarget; draft: TargetDraft }[]
  busy: boolean
  // Un motivo che ferma tutto il job (es. un pack misto non confermato).
  blocked?: string | null
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
        {/* Sul telefono cinque colonne non ci stanno: un blocco per tracker,
            con il nome intero (va a capo). La tabella resta da sm in su. */}
        <ul className="grid gap-2 sm:hidden">
          {drafts.map(({ target, draft }) => {
            const problem = draftProblem(draft)
            return (
              <li key={target.id} className="grid min-w-0 gap-1.5 rounded-md border p-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{target.tracker_label}</span>
                  <ActionBadge action={draft.action} />
                  <span className="ml-auto">
                    {problem ? (
                      <CircleAlertIcon className="size-4 text-amber-600 dark:text-amber-400" />
                    ) : (
                      <CircleCheckIcon className="size-4 text-emerald-500" />
                    )}
                  </span>
                </div>
                {problem && <p className="text-xs text-amber-600 dark:text-amber-400">{t(problem)}</p>}
                {draft.action === 'upload' && <p className="font-mono text-xs break-all">{draft.name || '—'}</p>}
                {draft.action === 'reseed' && (
                  <p className="font-mono text-xs break-all">{reseedName(target, draft.reseed_torrent_id)}</p>
                )}
                {draft.action === 'skip' ? (
                  <p className="text-xs text-muted-foreground">{t('upload.decision.summarySkip')}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {[target.torrent_client_label ?? t('upload.noClient'), draft.client_category, draft.client_tags.trim()]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                )}
                {draft.action === 'upload' && <FlagBadges draft={draft} />}
              </li>
            )
          })}
        </ul>
        <div className="hidden sm:block">
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
                          <FlagBadges draft={draft} />
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
                      {draft.action === 'skip' ? (
                        '—'
                      ) : (
                        <span className="grid gap-0.5">
                          <span>{target.torrent_client_label ?? t('upload.noClient')}</span>
                          {(draft.client_category || draft.client_tags.trim()) && (
                            <span className="text-[11px]">
                              {[draft.client_category, draft.client_tags.trim()].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </span>
                      )}
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
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {busy
              ? t('upload.decision.busy')
              : blocked
                ? blocked
                : problems.length > 0
                ? t('upload.decision.summaryMissing', { count: problems.length })
                : t('upload.decision.ready')}
          </p>
          <Button disabled={problems.length > 0 || busy || !!blocked} onClick={onApprove}>
            {t('upload.decision.approve')}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
