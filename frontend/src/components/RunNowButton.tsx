import { Loader2Icon, PlayIcon, SquareIcon } from 'lucide-react'
import { toast } from 'sonner'

import { useCancelRun, useRuns, useTriggerRun } from '@/api/hooks/runs'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'

// Stesso trigger di ReseedingPage (POST /api/runs), nel TopHeader della
// Dashboard. Mentre una run è in corso diventa "Stop run" (richiesta
// esplicita: un modo di fermarla se lanciata per sbaglio) — la pipeline si
// ferma al prossimo aggiornamento dell'avanzamento, senza perdere il lavoro
// già salvato (nazgarr/core/run_progress.py RunCancelled).
export function RunNowButton() {
  const { data: runs } = useRuns()
  const triggerRun = useTriggerRun()
  const cancelRun = useCancelRun()
  const activeRun = runs?.find((r) => r.finished_at == null)

  if (activeRun) {
    const stopping = activeRun.cancel_requested || cancelRun.isPending
    return (
      <Button
        size="sm"
        variant="outline"
        data-tour="dashboard.run"
        data-tour-filled="true"
        className="text-destructive hover:text-destructive"
        disabled={stopping}
        onClick={() =>
          cancelRun.mutate(activeRun.id, {
            onError: (error) => toast.error(t('common.stopFailed', { message: error.message })),
          })
        }
      >
        {stopping ? <Loader2Icon className="size-4 animate-spin" /> : <SquareIcon className="size-4" />}
        <span className="max-sm:sr-only">{stopping ? t('common.stopping') : t('common.stopRun')}</span>
      </Button>
    )
  }

  return (
    <Button
      size="sm"
      data-tour="dashboard.run"
      onClick={() =>
        triggerRun.mutate(undefined, {
          onError: (error) => toast.error(t('common.runFailed', { message: error.message })),
        })
      }
      disabled={triggerRun.isPending}
    >
      <PlayIcon className="size-4" />
      {/* Sul telefono solo l'icona: con il testo l'intestazione usciva dallo schermo. */}
      <span className="max-sm:sr-only">{t('common.runNow')}</span>
    </Button>
  )
}
