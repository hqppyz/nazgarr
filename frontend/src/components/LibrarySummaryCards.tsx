import { Card, CardContent } from '@/components/ui/card'
import { formatBytes, type StateSummary, type StatusOption } from '@/lib/library-filters'
import { summaryStyle } from '@/lib/status-styles'
import { cn } from '@/lib/utils'

export function LibrarySummaryCards({
  statusOptions,
  summary,
  activeStatus,
  onSelect,
}: {
  statusOptions: StatusOption[]
  summary: Record<string, StateSummary>
  activeStatus: string
  onSelect: (status: string) => void
}) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-3" data-tour="views.summary">
      {statusOptions.map((option) => {
        const s = summary[option.value] ?? { count: 0, size: 0 }
        const style = summaryStyle(option.value)
        return (
          <Card
            key={option.value}
            size="sm"
            className={cn(
              'cursor-pointer bg-gradient-to-t to-card font-mono shadow-xs transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-card',
              style.gradient,
              activeStatus === option.value && 'ring-2 ring-primary/40',
            )}
            // Sotto sm sono l'unico filtro di stato: raggiungibili anche da tastiera.
            role="button"
            tabIndex={0}
            aria-pressed={activeStatus === option.value}
            onClick={() => onSelect(option.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ' ') return
              event.preventDefault()
              onSelect(option.value)
            }}
          >
            <CardContent className="grid gap-1">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className={cn('size-2 rounded-full', style.dot)} />
                {option.label}
              </div>
              <div className="text-2xl font-semibold tabular-nums">{s.count}</div>
              <div className="text-xs text-muted-foreground tabular-nums">{formatBytes(s.size)}</div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
