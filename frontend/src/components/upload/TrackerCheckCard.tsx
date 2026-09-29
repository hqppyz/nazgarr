import { LoaderCircleIcon, ShieldCheckIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'

import { useVerifyTarget, type UploadJob, type UploadTarget } from '@/api/hooks/uploads'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { cn } from '@/lib/utils'

interface Dupe {
  torrent_id_remote: string
  name: string
  size_bytes: number
  verdict: 'identical' | 'same_slot' | 'different'
  reasons: string[]
  verification: {
    status: 'passed' | 'failed' | 'error'
    reason: string | null
    ok?: number
    pieces?: number
  } | null
}

const VERDICT_STYLE: Record<Dupe['verdict'], string> = {
  identical: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  same_slot: 'border-red-500/40 bg-red-500/15 text-red-700 dark:text-red-300',
  different: 'border-zinc-400/40 bg-zinc-400/15 text-zinc-600 dark:text-zinc-300',
}

const ACTION_STYLE: Record<string, string> = {
  upload: 'border-sky-500/40 bg-sky-500/15 text-sky-700 dark:text-sky-300',
  reseed: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  skip: 'border-zinc-400/40 bg-zinc-400/15 text-zinc-600 dark:text-zinc-300',
}

export function ActionBadge({ action }: { action: string }) {
  return (
    <Badge variant="outline" className={ACTION_STYLE[action]}>
      {t(`upload.action.${action}`)}
    </Badge>
  )
}

function Verification({ dupe }: { dupe: Dupe }) {
  const v = dupe.verification
  if (!v) return null
  if (v.status === 'passed') {
    return <span className="text-emerald-600 dark:text-emerald-400">{t('upload.dupes.verifyPassed', { pieces: v.pieces })}</span>
  }
  if (v.status === 'failed') {
    return <span className="text-red-600 dark:text-red-400">{t('upload.dupes.verifyFailed', { reason: v.reason })}</span>
  }
  return <span className="text-red-600 dark:text-red-400">{t('upload.dupes.verifyError', { reason: v.reason })}</span>
}

// Un tracker del job: il dupe check con il verdetto di ogni risultato, il
// full hash check sulle release "identical" e (children) la decisione.
export function TrackerCheckCard({
  job,
  target,
  children,
}: {
  job: UploadJob
  target: UploadTarget
  children?: ReactNode
}) {
  const verify = useVerifyTarget(job.id)
  const dupes = target.dupes as unknown as Dupe[]
  const verifying = target.status === 'verifying'
  const canVerify = job.status === 'awaiting_decision' && target.status === 'awaiting_decision'

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2 text-base">
          {target.tracker_label}
          <UploadStatusBadge status={target.status} />
        </CardTitle>
        {target.suggested_action && (
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            {t('upload.dupes.suggested')}
            <ActionBadge action={target.suggested_action} />
          </span>
        )}
      </CardHeader>
      <CardContent className="grid gap-4">
        {target.error_message === 'dupe_check_failed' && (
          <p className="text-sm text-amber-600 dark:text-amber-400">{t('upload.dupes.checkFailed')}</p>
        )}
        {target.error_message !== 'dupe_check_failed' && dupes.length === 0 && target.status !== 'checking' && (
          <p className="text-sm text-muted-foreground">{t('upload.dupes.none')}</p>
        )}
        {dupes.length > 0 && (
          <ul className="grid gap-1.5">
            {dupes.map((dupe) => (
              <li
                key={dupe.torrent_id_remote}
                className={cn(
                  'grid gap-1 rounded-md border px-3 py-2 text-xs',
                  dupe.verdict === 'different' && 'opacity-70',
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={VERDICT_STYLE[dupe.verdict]}>
                    {t(`upload.dupes.verdict.${dupe.verdict}`)}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate font-mono" title={dupe.name}>
                    {dupe.name}
                  </span>
                  <span className="text-muted-foreground tabular-nums">{formatBytes(dupe.size_bytes)}</span>
                </div>
                {(dupe.reasons.length > 0 || dupe.verdict === 'identical') && (
                  <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
                    {dupe.reasons.map((reason) => t(`upload.dupes.reason.${reason}`)).join(' · ')}
                    <Verification dupe={dupe} />
                    {dupe.verdict === 'identical' && !dupe.verification && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7"
                        disabled={!canVerify || verify.isPending}
                        onClick={() =>
                          verify.mutate(
                            { targetId: target.id, torrentIdRemote: dupe.torrent_id_remote },
                            { onError: (error) => toast.error(error.message) },
                          )
                        }
                      >
                        {verifying ? (
                          <LoaderCircleIcon className="size-3.5 animate-spin" />
                        ) : (
                          <ShieldCheckIcon className="size-3.5" />
                        )}
                        {verifying ? t('upload.dupes.verifying') : t('upload.dupes.verify')}
                      </Button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {children}
      </CardContent>
    </Card>
  )
}
