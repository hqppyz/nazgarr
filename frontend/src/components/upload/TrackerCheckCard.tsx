import { LoaderCircleIcon, ScanSearchIcon, TriangleAlertIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'

import { useVerifyTarget, type UploadJob, type UploadTarget } from '@/api/hooks/uploads'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t, uiLocale } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { dupeUrl } from '@/lib/upload'
import { cn } from '@/lib/utils'
import { safeHref } from '@/lib/safeUrl'

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

// Il nome di un dupe: sul telefono va a capo (fino a tre righe), da sm si tronca.
const DUPE_NAME = 'font-mono max-sm:line-clamp-3 max-sm:break-all sm:truncate'

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

function verificationText(dupe: Dupe): string | null {
  const v = dupe.verification
  if (!v) return null
  if (v.status === 'passed') return t('upload.dupes.verifyPassed', { pieces: v.pieces })
  if (v.status === 'failed') return t('upload.dupes.verifyFailed', { reason: v.reason })
  return t('upload.dupes.verifyError', { reason: v.reason })
}

function Verification({ dupe }: { dupe: Dupe }) {
  const text = verificationText(dupe)
  if (!text) return null
  const ok = dupe.verification?.status === 'passed'
  return <span className={ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>{text}</span>
}

// Motivi e verifica in una riga: per il title quando su desktop si tronca.
function dupeDetails(dupe: Dupe): string {
  return [...dupe.reasons.map((reason) => t(`upload.dupes.reason.${reason}`)), verificationText(dupe)].filter(Boolean).join(' · ')
}

function languageName(code: string) {
  try {
    return new Intl.DisplayNames([uiLocale()], { type: 'language' }).of(code) ?? code
  } catch {
    return code
  }
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{children}</p>
}

// Un tracker del job: il dupe check con il verdetto di ogni risultato (una
// riga ciascuno: verdetto, nome e motivi, dimensione, link e azione), il
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
  const seeding = ((job.analysis as Record<string, unknown> | null)?.seeding_here as
    | Record<string, { name: string; client: string }>
    | undefined)?.[String(target.id)]
  // La lingua del tracker nell'audio del file (nazgarr/upload/naming.py audio_language_check).
  const language = ((job.analysis as Record<string, unknown> | null)?.languages as
    | Record<string, { language: string; status: 'present' | 'missing' | 'unknown' }>
    | undefined)?.[String(target.tracker_id)]

  return (
    <Card className="min-w-0">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <div className="grid min-w-0 gap-0.5">
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            {target.tracker_label}
            <UploadStatusBadge status={target.status} />
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            {target.torrent_client_label
              ? t('upload.seedsOn', { client: target.torrent_client_label })
              : t('upload.noClient')}
          </span>
        </div>
        {target.suggested_action && (
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            {t('upload.dupes.suggested')}
            <ActionBadge action={target.suggested_action} />
          </span>
        )}
      </CardHeader>
      <CardContent className="grid min-w-0 gap-5">
        {language && language.status !== 'present' && (
          <p className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
            <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
            {t(`upload.language.${language.status}`, { language: languageName(language.language) })}
          </p>
        )}
        <div className="grid min-w-0 gap-2">
          <SectionLabel>{t('upload.dupes.onTracker')}</SectionLabel>
          {seeding && (
            <p className="text-sm text-amber-600 dark:text-amber-400">
              {t('upload.dupes.seedingHere', { client: seeding.client, torrent: seeding.name })}
            </p>
          )}
          {target.error_message === 'dupe_check_failed' && (
            <p className="text-sm text-amber-600 dark:text-amber-400">{t('upload.dupes.checkFailed')}</p>
          )}
          {target.error_message !== 'dupe_check_failed' && dupes.length === 0 && target.status !== 'checking' && (
            <p className="text-sm text-muted-foreground">{t('upload.dupes.none')}</p>
          )}
          {dupes.length > 0 && (
            <ul className="grid min-w-0 divide-y rounded-md border">
              {dupes.map((dupe) => {
                const url = dupeUrl(target, dupe.torrent_id_remote)
                return (
                  <li
                    key={dupe.torrent_id_remote}
                    className={cn(
                      // Sul telefono le azioni vanno su una riga loro: accanto lasciavano
                      // al nome pochi pixel. Da sm tre colonne, come prima.
                      'grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 px-3 py-2 text-xs sm:grid-cols-[auto_minmax(0,1fr)_auto]',
                      dupe.verdict === 'different' && 'opacity-70',
                    )}
                  >
                    <Badge variant="outline" className={cn('justify-self-start', VERDICT_STYLE[dupe.verdict])}>
                      {t(`upload.dupes.verdict.${dupe.verdict}`)}
                    </Badge>
                    <div className="grid min-w-0">
                      {url ? (
                        <a href={safeHref(url)} target="_blank" rel="noreferrer" className={cn(DUPE_NAME, 'hover:underline')} title={dupe.name}>
                          {dupe.name}
                        </a>
                      ) : (
                        <span className={DUPE_NAME} title={dupe.name}>{dupe.name}</span>
                      )}
                      {(dupe.reasons.length > 0 || dupe.verification) && (
                        <span className="text-muted-foreground max-sm:break-words sm:truncate" title={dupeDetails(dupe)}>
                          {dupe.reasons.map((reason) => t(`upload.dupes.reason.${reason}`)).join(' · ')}
                          {dupe.reasons.length > 0 && dupe.verification && ' · '}
                          <Verification dupe={dupe} />
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 max-sm:col-span-full max-sm:justify-self-end">
                      {dupe.verdict === 'identical' && !dupe.verification && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 pointer-coarse:h-9"
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
                            <ScanSearchIcon className="size-3.5" />
                          )}
                          {verifying ? t('upload.dupes.verifying') : t('upload.dupes.verify')}
                        </Button>
                      )}
                      <span className="text-muted-foreground tabular-nums">{formatBytes(dupe.size_bytes)}</span>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
        {children && (
          <div className="grid min-w-0 gap-2">
            <SectionLabel>{t('upload.decision.yourDecision')}</SectionLabel>
            {children}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
