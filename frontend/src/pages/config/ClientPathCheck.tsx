import { ArrowRightIcon, CheckCircle2Icon, FolderSearchIcon, RefreshCwIcon, TriangleAlertIcon, XCircleIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import type { Schemas } from '@/api/client'
import { useAssociateDisk, useClientPathCheck } from '@/api/hooks/torrentClients'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

type Result = Schemas['PathCheckResponse']
type Suggestion = Schemas['PathCheckSuggestion']

const VERDICT = {
  ok: { icon: CheckCircle2Icon, style: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' },
  partial: { icon: TriangleAlertIcon, style: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300' },
  none: { icon: XCircleIcon, style: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300' },
  empty: { icon: TriangleAlertIcon, style: 'border-border bg-muted/40 text-muted-foreground' },
} as const

const PROBLEMS = ['unmapped', 'missing', 'outside_seeding'] as const

function SuggestionRow({ clientId, suggestion, onApplied }: {
  clientId: number
  suggestion: Suggestion
  onApplied: () => void
}) {
  const associate = useAssociateDisk()
  const same = suggestion.client_root_path === null
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-sm">
      <span className="font-medium">{suggestion.disk_label}</span>
      {same ? (
        <span className="text-muted-foreground">{t('torrentClients.pathCheck.samePaths')}</span>
      ) : (
        // Da telefono i percorsi troncati non si leggono (e il title non c'è):
        // vanno a capo; da sm la riga di sempre.
        <span className="flex min-w-0 flex-wrap items-center gap-1.5 font-mono text-xs sm:flex-nowrap">
          <span className="min-w-0 break-all sm:truncate">{suggestion.local_rel_path ?? t('torrentClients.mappingDiskRoot')}</span>
          <span className="text-muted-foreground">=</span>
          <span className="min-w-0 break-all sm:truncate">{suggestion.client_root_path}</span>
        </span>
      )}
      <span className="text-xs text-muted-foreground">
        {t('torrentClients.pathCheck.wouldFind', { count: suggestion.matches })}
      </span>
      <span className="flex-1" />
      <Button
        size="sm"
        disabled={associate.isPending}
        onClick={() =>
          associate.mutate(
            {
              torrentClientId: clientId,
              diskId: suggestion.disk_id,
              torrentClientRootPath: suggestion.client_root_path,
              localRelPath: suggestion.local_rel_path,
            },
            {
              onSuccess: () => {
                toast.success(t('torrentClients.mappingSaved'))
                onApplied()
              },
              onError: (error) => toast.error(error.message),
            },
          )
        }
      >
        {t('torrentClients.pathCheck.apply')}
      </Button>
    </div>
  )
}

function ResultView({ clientId, result, onRecheck }: { clientId: number; result: Result; onRecheck: () => void }) {
  if (result.status === 'error') {
    return <p className="text-sm text-red-700 dark:text-red-300">{result.error ?? t('torrentClients.connectionFailed')}</p>
  }
  const verdict = (result.verdict ?? 'empty') as keyof typeof VERDICT
  const { icon: Icon, style } = VERDICT[verdict]
  return (
    <div className="grid gap-4">
      <div className={cn('flex items-start gap-2 rounded-md border p-3 text-sm', style)}>
        <Icon className="mt-0.5 size-4 shrink-0" />
        <span>{t(`torrentClients.pathCheck.verdict.${verdict}`, { ok: result.ok, count: result.checked })}</span>
      </div>
      {PROBLEMS.some((p) => result[p] > 0) && (
        <ul className="grid gap-1 text-sm">
          {PROBLEMS.filter((p) => result[p] > 0).map((p) => (
            <li key={p}>
              <span className="font-medium tabular-nums">{result[p]}</span>{' '}
              <span className="text-muted-foreground">{t(`torrentClients.pathCheck.problem.${p}`)}</span>
            </li>
          ))}
        </ul>
      )}
      {result.examples.length > 0 && (
        <div className="grid gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">{t('torrentClients.pathCheck.examples')}</p>
          {result.examples.map((example) => (
            <div key={`${example.status}:${example.client_path}`} className="grid gap-0.5 rounded-md bg-muted/40 px-2 py-1.5 font-mono text-xs">
              <span className="break-all">{example.client_path}</span>
              <span className="flex items-start gap-1 break-all text-muted-foreground">
                <ArrowRightIcon className="mt-0.5 size-3 shrink-0" />
                {example.local_path ?? t('torrentClients.pathCheck.noDisk')}
              </span>
            </div>
          ))}
        </div>
      )}
      {result.suggestions.length > 0 && (
        <div className="grid gap-1.5">
          <p className="text-sm font-medium">{t('torrentClients.pathCheck.suggestionTitle')}</p>
          <p className="text-xs text-muted-foreground">{t('torrentClients.pathCheck.suggestionHelp')}</p>
          {result.suggestions.map((suggestion) => (
            <SuggestionRow key={suggestion.disk_id} clientId={clientId} suggestion={suggestion} onApplied={onRecheck} />
          ))}
        </div>
      )}
      {result.suggestions.length === 0 && result.unmapped + result.missing > 0 && (
        <p className="text-xs text-muted-foreground">{t('torrentClients.pathCheck.noSuggestion')}</p>
      )}
    </div>
  )
}

// "Verifica percorsi" sulla card del client: i file che ha in seed si
// trovano sui dischi? Se no, perché, e la corrispondenza da applicare.
export function PathCheckButton({ clientId, clientLabel }: { clientId: number; clientLabel: string }) {
  const check = useClientPathCheck()
  const [open, setOpen] = useState(false)
  const run = (live = false) => check.mutate({ id: clientId, live })
  const result = check.data
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        data-tour="clients.path-check"
        // Per il tour: dopo una verifica riuscita si va avanti (prima il passo ricompariva).
        data-tour-filled={result?.status === 'ok' ? 'true' : undefined}
        disabled={check.isPending}
        onClick={() => {
          setOpen(true)
          run()
        }}
      >
        <FolderSearchIcon className="size-4" />
        {t('torrentClients.pathCheck.button')}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-tour="clients.path-check-dialog" className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('torrentClients.pathCheck.title', { client: clientLabel })}</DialogTitle>
            <DialogDescription>{t('torrentClients.pathCheck.description')}</DialogDescription>
          </DialogHeader>
          {check.isPending && <p className="text-sm text-muted-foreground">{t('torrentClients.pathCheck.running')}</p>}
          {!check.isPending && check.error && <p className="text-sm text-red-700 dark:text-red-300">{check.error.message}</p>}
          {!check.isPending && result && <ResultView clientId={clientId} result={result} onRecheck={() => run()} />}
          {!check.isPending && result?.status === 'ok' && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
              <span>{t(`torrentClients.pathCheck.source.${result.source}`)}</span>
              <Button variant="ghost" size="sm" onClick={() => run(true)}>
                <RefreshCwIcon className="size-4" />
                {t('torrentClients.pathCheck.live')}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
