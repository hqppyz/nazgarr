import {
  CopyIcon,
  FileSearchIcon,
  Link2Icon,
  Trash2Icon,
  TrendingDownIcon,
  TrendingUpIcon,
  type LucideIcon,
} from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'

import type { Schemas } from '@/api/client'
import { useDashboard, useDashboardHistory } from '@/api/hooks/dashboard'
import { useTrackerFilter } from '@/lib/trackerFilter'
import { ChangesCard } from '@/components/ChangesCard'
import { GettingStartedCard } from '@/onboarding/GettingStartedCard'
import { isRemote } from '@/lib/instance'
import { HealthGauge } from '@/components/HealthGauge'
import { ScanHistoryCard } from '@/components/ScanHistoryCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { useRingLoader } from '@/components/RingLoader'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { healthLabel } from '@/lib/health'
import { STATUS_STYLES } from '@/lib/status-styles'
import { parseApiDate } from '@/lib/time'
import { cn } from '@/lib/utils'

type Dashboard = Schemas['DashboardResponse']
type HistoryPoint = Schemas['HistoryPoint']

// Finestra della parte superiore (anello, grafico): giorni, non numero di
// scansioni — con gli scan manuali il numero non dice quanto tempo è passato.
const WINDOWS = [
  { value: '7', days: 7 },
  { value: '30', days: 30 },
  { value: '90', days: 90 },
  { value: 'all', days: null },
] as const

function daysAgo(value: string | null | undefined): number | null {
  if (!value) return null
  return Math.max(0, Math.round((Date.now() - parseApiDate(value).getTime()) / 86_400_000))
}

function HealthCard({ data, history }: { data: Dashboard; history: HistoryPoint[] | undefined }) {
  const { label, dot, color } = healthLabel(data.health_pct)
  // history è dalla più recente: il confronto è con la prima della finestra.
  const withHealth = (history ?? []).filter((point) => point.health_snapshot != null)
  const oldest = withHealth.length > 1 ? withHealth[withHealth.length - 1] : null
  const delta = oldest?.health_snapshot != null ? data.health_pct - oldest.health_snapshot : null
  // Senza una cartella media (solo torrent e upload) la salute non ha senso.
  if (!data.total_media_size) {
    return (
      <Card data-tour="views.health">
        <CardHeader>
          <CardTitle>{t('dashboard.libraryHealth')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-center">
          <p className="text-3xl font-semibold text-muted-foreground">—</p>
          <p className="text-xs text-muted-foreground">{t('dashboard.noLibrary')}</p>
        </CardContent>
      </Card>
    )
  }
  const ago = daysAgo(oldest?.finished_at)
  return (
    <Card data-tour="views.health">
      <CardHeader>
        <CardTitle>{t('dashboard.libraryHealth')}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <HealthGauge value={data.health_pct} color={color}>
          <span className="text-4xl font-semibold tabular-nums sm:text-5xl">{Math.round(data.health_pct)}</span>
          <span className="font-mono text-xs text-muted-foreground">/ 100</span>
          <span className="mt-1 flex items-center gap-1.5 text-sm font-medium">
            <span className={cn('size-2 rounded-full', dot)} />
            {label}
          </span>
        </HealthGauge>
        <p className="text-center text-xs text-muted-foreground">
          {delta == null ? (
            t('dashboard.healthNoHistory')
          ) : (
            <span className={cn(delta > 0 && 'text-emerald-600 dark:text-emerald-400', delta < 0 && 'text-destructive')}>
              {delta >= 0 ? '↑' : '↓'} {t('dashboard.ptsVsAgo', { delta: Math.abs(delta).toFixed(1), days: ago ?? 0 })}
            </span>
          )}
        </p>
      </CardContent>
    </Card>
  )
}

// Il grafico (recharts, il pezzo più pesante della pagina) in un chunk a
// parte: le card compaiono senza aspettarlo.
const HistoryChart = lazy(() => import('@/components/HistoryChart').then((m) => ({ default: m.HistoryChart })))

type Trend = 'improving' | 'worsening' | 'stable' | null

// lowerIsBetter: per spazio orfano, non importato e duplicato meno è meglio.
function trendOf(current: number, previous: number | null | undefined, lowerIsBetter: boolean): Trend {
  if (previous == null) return null
  if (current === previous) return 'stable'
  return current < previous === lowerIsBetter ? 'improving' : 'worsening'
}

function TrendLine({ trend }: { trend: Trend }) {
  if (trend == null) return <p className="text-xs text-muted-foreground">{t('dashboard.noPreviousScan')}</p>
  if (trend === 'stable') return <p className="text-xs text-muted-foreground">{t('dashboard.trendStable')}</p>
  const Icon = trend === 'improving' ? TrendingUpIcon : TrendingDownIcon
  return (
    <p
      className={cn(
        'flex items-center gap-1 text-xs font-medium',
        trend === 'improving' ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive',
      )}
    >
      <Icon className="size-3.5" />
      {trend === 'improving' ? t('dashboard.trendImproving') : t('dashboard.trendWorsening')}
    </p>
  )
}

function BigValue({ value }: { value: string }) {
  // "38.2 GiB" -> numero grande, unità piccola.
  const [number, unit] = value.split(' ')
  return (
    <p className="text-3xl font-semibold tabular-nums">
      {number}
      {unit && <span className="ml-1 text-base font-normal text-muted-foreground">{unit}</span>}
    </p>
  )
}

function MetricCard({
  title,
  dot,
  value,
  subline,
  trend,
  description,
  action,
}: {
  title: string
  dot: string
  value: React.ReactNode
  subline: string
  trend: Trend
  description: string
  action: { label: string; to: string; icon: LucideIcon }
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <span className={cn('size-2 rounded-full', dot)} />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-2">
        {value}
        <p className="text-xs text-muted-foreground">{subline}</p>
        <TrendLine trend={trend} />
        {/* Sul telefono la descrizione allungava la pagina di un'altra schermata. */}
        <p className="hidden flex-1 text-sm text-muted-foreground sm:block">{description}</p>
        <Button variant="outline" className="mt-2 h-auto min-h-8 justify-start text-left whitespace-normal"
                render={<Link to={action.to} />}>
          <action.icon className="size-4" />
          {action.label}
        </Button>
      </CardContent>
    </Card>
  )
}

// Un backend più vecchio del frontend (es. un container non aggiornato) può
// non mandare i campi nuovi: 0 invece di far cadere tutta la dashboard.
const num = (value: number | null | undefined) => value ?? 0

function MetricCards({ data }: { data: Dashboard }) {
  const previous = data.previous
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-tour="views.metrics">
      <MetricCard
        title={t('dashboard.hardlinkedMedia')}
        dot={STATUS_STYLES.seeding.dot}
        value={
          <p className="text-3xl font-semibold tabular-nums">
            {data.total_media_size ? num(data.health_pct).toFixed(1) : '—'}
            {data.total_media_size ? <span className="ml-0.5 text-base font-normal text-muted-foreground">%</span> : null}
          </p>
        }
        subline={t('dashboard.seedingOfTotal', {
          seeding: formatBytes(num(data.seeding_media_size)),
          total: formatBytes(num(data.total_media_size)),
        })}
        trend={data.total_media_size ? trendOf(num(data.health_pct), previous?.health_snapshot, false) : undefined}
        description={t('dashboard.hardlinkedDescription')}
        action={{ label: t('dashboard.viewOrphanedMedia'), to: '/library/folder?status=orphan_media', icon: Link2Icon }}
      />
      <MetricCard
        title={t('dashboard.orphanedTorrents')}
        dot={STATUS_STYLES.orphan.dot}
        value={<BigValue value={formatBytes(num(data.orphan_torrent_bytes))} />}
        subline={t('dashboard.orphanedSubline', {
          count: num(data.orphan_torrent_count).toLocaleString(),
          size: formatBytes(num(data.orphan_not_in_library_bytes)),
        })}
        trend={trendOf(num(data.orphan_torrent_bytes), previous?.orphan_torrent_bytes, true)}
        description={t('dashboard.orphanedDescription')}
        action={{ label: t('dashboard.viewOrphanedTorrents'), to: '/torrent/folder?status=orphan_torrent', icon: Trash2Icon }}
      />
      <MetricCard
        title={t('dashboard.notImported')}
        dot={STATUS_STYLES.ignored.dot}
        // Gli stessi numeri della vista (per torrent, esclusi fuori) quando è
        // calcolata; prima, il conto per file come ripiego.
        value={<BigValue value={formatBytes(data.not_imported_bytes ?? num(data.ignored_bytes))} />}
        subline={
          data.not_imported_torrents != null
            ? t('dashboard.torrentsCount', { count: data.not_imported_torrents.toLocaleString() })
            : t('dashboard.filesCount', { count: num(data.ignored_count).toLocaleString() })
        }
        trend={trendOf(num(data.ignored_bytes), previous?.ignored_bytes, true)}
        description={t('dashboard.notImportedDescription')}
        action={{ label: t('dashboard.viewNotImported'), to: '/torrent/triage', icon: FileSearchIcon }}
      />
      <MetricCard
        title={t('dashboard.duplicates')}
        dot={STATUS_STYLES.duplicate.dot}
        value={<BigValue value={formatBytes(num(data.duplicate_wasted_bytes))} />}
        subline={t('dashboard.duplicatesSubline', {
          count: num(data.duplicate_files).toLocaleString(),
          hardlinks: num(data.duplicate_hardlink_groups).toLocaleString(),
        })}
        trend={trendOf(num(data.duplicate_wasted_bytes), previous?.duplicate_wasted_bytes, true)}
        description={t('dashboard.duplicatesDescription')}
        action={{ label: t('dashboard.viewDuplicates'), to: '/library/folder?status=duplicates', icon: CopyIcon }}
      />
    </div>
  )
}

// Panoramica dello stato del server, ispirata alla dashboard di Auditorr:
// anello della salute (solo hardlink: GB in seed / GB in libreria, docs/SPEC.md
// §10), storico nella finestra scelta, quattro card con valore, andamento
// rispetto alla scansione precedente e un link alla vista filtrata. Sotto,
// i cambiamenti per file e la cronologia delle scansioni.
export function DashboardPage() {
  const query = useDashboard()
  const { data } = query
  const loader = useRingLoader(query)
  const [period, setPeriod] = useState<string>('30')
  const days = WINDOWS.find((w) => w.value === period)?.days ?? null
  const { data: history } = useDashboardHistory(days)
  const tracker = useTrackerFilter()

  if (loader) return loader
  if (!data) return null

  return (
    <div className="grid gap-6">
      {!isRemote() && <GettingStartedCard />}
      <ToggleGroupSingle value={period} onValueChange={setPeriod} variant="outline" className="justify-self-start">
        {WINDOWS.map((w) => (
          <ToggleGroupItem key={w.value} value={w.value} className="font-mono text-xs">
            {w.days == null ? t('dashboard.windowAll') : `${w.days}d`}
          </ToggleGroupItem>
        ))}
      </ToggleGroupSingle>
      {/* Lo storico per tracker si salva dalla prima scansione con il filtro. */}
      {tracker !== 'all' && history?.length === 0 && (
        <p className="-mt-3 text-xs text-muted-foreground">{t('trackerFilter.historyStartsNextScan')}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <HealthCard data={data} history={history} />
        <Suspense fallback={<Card className="lg:col-span-2" />}>
          <HistoryChart history={history} current={data.health_pct} />
        </Suspense>
      </div>

      <MetricCards data={data} />

      <div className="grid gap-6 xl:grid-cols-5" data-tour="views.changes">
        <ChangesCard className="xl:col-span-3" />
        <ScanHistoryCard className="xl:col-span-2" />
      </div>
    </div>
  )
}
