import { Loader2Icon, ScanSearchIcon } from 'lucide-react'
import { useState } from 'react'

import type { Schemas } from '@/api/client'
import { type FullCheckTarget, useCancelFullCheck, useFullCheck, useStartFullCheck } from '@/api/hooks/fullChecks'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { cn } from '@/lib/utils'

type CheckResult = Schemas['CheckResultResponse']

// L'ultimo controllo avviato per ogni torrent/esecuzione: chiudere la
// finestra (o la scheda) non lo interrompe, riaprirla ne mostra lo stato.
const lastCheck = new Map<string, string>()
const keyOf = (target: FullCheckTarget) => `${target.candidateId}:${target.seedJobId ?? ''}`

function verdict(result: CheckResult, hasExecution: boolean): { tone: 'ok' | 'warn' | 'bad'; text: string } {
  const hashChanged = result.expected_info_hash != null && result.expected_info_hash !== result.info_hash
  if (result.mismatched > 0) {
    return { tone: 'bad', text: t('fullCheck.verdictMismatch', { count: result.mismatched }) }
  }
  if (result.unreadable > 0) {
    return { tone: 'warn', text: t('fullCheck.verdictUnreadable', { count: result.unreadable }) }
  }
  if (hashChanged) return { tone: 'warn', text: t('fullCheck.verdictHashChanged') }
  const outsideSeed = hasExecution && result.files.some((f) => f.location === 'library')
  return { tone: 'ok', text: outsideSeed ? t('fullCheck.verdictOkNotInSeed') : t('fullCheck.verdictOk') }
}

const TONE = {
  ok: 'border-emerald-500/40 bg-emerald-500/10',
  warn: 'border-amber-500/40 bg-amber-500/10',
  bad: 'border-destructive/40 bg-destructive/10',
}

function ResultView({ result, hasExecution }: { result: CheckResult; hasExecution: boolean }) {
  const v = verdict(result, hasExecution)
  return (
    <div className="grid gap-3 text-xs">
      <div className={cn('rounded-md border p-3', TONE[v.tone])}>
        <p className="text-2xl font-semibold tabular-nums">{result.percent.toFixed(result.percent === 100 ? 0 : 2)}%</p>
        <p className="text-muted-foreground tabular-nums">
          {t('fullCheck.piecesSummary', {
            ok: result.ok,
            total: result.pieces,
            size: formatBytes(result.piece_length),
          })}
        </p>
        <p className="mt-2 text-sm">{v.text}</p>
      </div>
      <div className="grid gap-2">
        {result.files.map((f) => {
          const bad = f.mismatched + f.unreadable
          return (
            <div key={f.torrent_path} className="grid gap-0.5 rounded border px-2 py-1.5">
              <div className="flex items-start justify-between gap-2">
                <span className="min-w-0 font-mono break-all">{f.torrent_path}</span>
                <span className={cn('shrink-0 font-mono tabular-nums', bad > 0 ? 'text-destructive' : 'text-emerald-600')}>
                  {f.ok}/{f.pieces}
                </span>
              </div>
              <span className="font-mono break-all text-muted-foreground">
                {f.local_path
                  ? `${f.location === 'seed' ? t('fullCheck.readFromSeed') : t('fullCheck.readFromLibrary')} · ${f.local_path}`
                  : t('fullCheck.noLocalFile')}
              </span>
              {f.local_size_bytes != null && f.local_size_bytes !== f.size_bytes && (
                <span className="text-destructive">
                  {t('fullCheck.sizeDiffers', {
                    local: formatBytes(f.local_size_bytes),
                    expected: formatBytes(f.size_bytes),
                  })}
                </span>
              )}
              {f.mismatched > 0 && (
                <span className="text-destructive">
                  {t('fullCheck.fileMismatch', {
                    count: f.mismatched,
                    offset: formatBytes(f.first_bad_offset ?? 0),
                  })}
                </span>
              )}
              {f.unreadable > 0 && <span className="text-amber-600">{t('fullCheck.fileUnreadable', { count: f.unreadable })}</span>}
            </div>
          )
        })}
      </div>
      <p className="font-mono break-all text-muted-foreground">
        info hash {result.info_hash}
        {result.expected_info_hash && result.expected_info_hash !== result.info_hash && (
          <span className="block text-amber-600">{t('fullCheck.expectedHash', { hash: result.expected_info_hash })}</span>
        )}
      </p>
    </div>
  )
}

// iconOnlyOnPhone: sotto sm solo l'icona, nelle tabelle dove l'etichetta
// toglieva spazio al nome (Esecuzioni del reseeding).
export function FullCheckButton({ target, label, size = 'xs', iconOnlyOnPhone = false }: { target: FullCheckTarget; label: string; size?: 'xs' | 'sm'; iconOnlyOnPhone?: boolean }) {
  const [open, setOpen] = useState(false)
  const [checkId, setCheckId] = useState<string | null>(() => lastCheck.get(keyOf(target)) ?? null)
  const start = useStartFullCheck()
  const cancel = useCancelFullCheck()
  const { data: check } = useFullCheck(checkId)
  const active = check?.status === 'queued' || check?.status === 'running'
  const percent = check?.bytes_total ? (100 * check.bytes_done) / check.bytes_total : 0

  const run = () =>
    start.mutate(target, {
      onSuccess: (state) => {
        lastCheck.set(keyOf(target), state.id)
        setCheckId(state.id)
      },
    })

  return (
    <>
      <Button size={size} variant="outline" title={t('fullCheck.hint')} onClick={() => setOpen(true)}>
        {active ? <Loader2Icon className="size-3 animate-spin" /> : <ScanSearchIcon className="size-3" />}
        <span className={cn(iconOnlyOnPhone && 'max-sm:sr-only')}>{t('fullCheck.button')}</span>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('fullCheck.title')}</DialogTitle>
            <DialogDescription className="font-mono break-all">{label}</DialogDescription>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">{t('fullCheck.explanation')}</p>

          {start.error && <p className="text-xs text-destructive">{start.error.message}</p>}
          {check?.status === 'failed' && <p className="text-xs text-destructive">{check.error}</p>}
          {check?.status === 'cancelled' && <p className="text-xs text-muted-foreground">{t('fullCheck.cancelled')}</p>}

          {active && (
            <div className="grid gap-2">
              <Progress value={percent} />
              <div className="flex items-center justify-between text-xs text-muted-foreground tabular-nums">
                <span>
                  {check.status === 'queued'
                    ? t('fullCheck.queued')
                    : check.bytes_total
                      ? `${formatBytes(check.bytes_done)} / ${formatBytes(check.bytes_total)} · ${percent.toFixed(0)}%`
                      : t('fullCheck.downloadingTorrent')}
                </span>
                <Button size="xs" variant="ghost" disabled={cancel.isPending} onClick={() => cancel.mutate(check.id)}>
                  {t('common.cancel')}
                </Button>
              </div>
            </div>
          )}

          {check?.status === 'done' && check.result && (
            <ResultView result={check.result} hasExecution={target.seedJobId != null} />
          )}

          {!active && (
            <div className="flex justify-end">
              <Button size="sm" disabled={start.isPending} onClick={run}>
                {start.isPending ? <Loader2Icon className="size-4 animate-spin" /> : <ScanSearchIcon className="size-4" />}
                {check ? t('fullCheck.runAgain') : t('fullCheck.start')}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
