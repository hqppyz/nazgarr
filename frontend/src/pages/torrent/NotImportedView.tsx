import { ArrowRightIcon, CircleCheckIcon, EyeOffIcon, Loader2Icon, RefreshCwIcon, SearchIcon, UploadIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { Schemas } from '@/api/client'
import { useNotImported, useRefreshNotImported } from '@/api/hooks/library'
import { LibrarySummaryCards } from '@/components/LibrarySummaryCards'
import { RowContextMenu, type RowMenuItem } from '@/components/RowContextMenu'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Toggle } from '@/components/ui/toggle'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { t } from '@/lib/i18n'
import { formatBytes, type StateSummary, type StatusOption } from '@/lib/library-filters'
import { NOT_IMPORTED_STYLES } from '@/lib/status-styles'
import { parseApiDate, relativeFromNow } from '@/lib/time'
import { newUploadLink } from '@/lib/upload'
import { cn } from '@/lib/utils'
import { ItemDetailSheet, type OpenItem } from '@/pages/library/ItemDetailSheet'

type Torrent = Schemas['NotImportedItem']

const CATEGORIES = ['superseded', 'copy', 'removed', 'never_imported', 'extras_only'] as const

const OPTIONS: StatusOption[] = [
  { value: 'all', label: t('library.stateAll') },
  ...CATEGORIES.map((c) => ({ value: c, label: t(`notImported.category.${c}`) })),
]

function formatSeedTime(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const days = Math.floor(seconds / 86_400)
  if (days >= 1) return t('notImported.days', { count: days })
  return t('notImported.hours', { count: Math.max(1, Math.floor(seconds / 3600)) })
}

// Se il torrent ha già dato quello che il suo tracker chiede (seedtime e/o
// ratio, impostati sul tracker: nazgarr/seed_requirements.py) e si può togliere.
// Una risposta in cache di prima di questo campo non lo ha: come "tracker sconosciuto".
const NO_REQUIREMENT: Torrent['seed_requirement'] = { status: 'unknown_tracker', remaining: {} }

function SeedRequirementCell({ requirement = NO_REQUIREMENT }: { requirement?: Torrent['seed_requirement'] }) {
  const { status, remaining = {}, tracker_label: tracker } = requirement
  const rule = [
    requirement.min_seed_time_seconds != null && formatSeedTime(requirement.min_seed_time_seconds),
    requirement.min_ratio != null && t('notImported.removable.ratio', { ratio: requirement.min_ratio }),
  ].filter(Boolean).join(requirement.rule === 'all' ? ` ${t('notImported.removable.and')} ` : ` ${t('notImported.removable.or')} `)
  if (status === 'met') {
    return (
      <Badge
        variant="outline"
        title={t('notImported.removable.metHelp', { tracker: tracker ?? '', rule })}
        className="h-auto gap-1 border-emerald-500/40 bg-emerald-500/10 py-0 text-[length:var(--text-xxs)] leading-4 text-emerald-700 dark:text-emerald-300"
      >
        <CircleCheckIcon className="size-3" />
        {t('notImported.removable.met')}
      </Badge>
    )
  }
  if (status === 'pending') {
    const left = [
      remaining.seed_time_seconds != null && formatSeedTime(remaining.seed_time_seconds),
      remaining.ratio != null && t('notImported.removable.ratioLeft', { ratio: remaining.ratio.toFixed(2) }),
    ].filter(Boolean).join(' · ')
    return (
      <span
        className="font-mono text-xs text-amber-600 tabular-nums dark:text-amber-400"
        title={t('notImported.removable.pendingHelp', { tracker: tracker ?? '', rule })}
      >
        {t('notImported.removable.left', { left })}
      </span>
    )
  }
  const help =
    status === 'unknown'
      ? t('notImported.removable.unknownHelp', { tracker: tracker ?? '' })
      : status === 'no_rules'
        ? t('notImported.removable.noRulesHelp', { tracker: tracker ?? '' })
        : t('notImported.removable.unknownTrackerHelp')
  return <span className="text-xs text-muted-foreground" title={help}>{status === 'unknown' ? '?' : '—'}</span>
}

function contentLabel(torrent: Torrent): string | null {
  if (!torrent.title) return null
  const base = torrent.year ? `${torrent.title} (${torrent.year})` : torrent.title
  if (torrent.season_number == null) return base
  const episode = torrent.episode_number != null ? `E${String(torrent.episode_number).padStart(2, '0')}` : ''
  return `${base} · S${String(torrent.season_number).padStart(2, '0')}${episode}`
}

function fileName(path: string) {
  return path.slice(path.lastIndexOf('/') + 1)
}

function CategoryBadge({ category }: { category: string }) {
  const style = NOT_IMPORTED_STYLES[category] ?? NOT_IMPORTED_STYLES.extras_only
  return (
    <Badge variant="outline" className={cn('h-auto gap-1.5 py-0 font-mono text-[length:var(--text-xxs)] leading-4', style.badge)}>
      <span className={cn('size-1.5 rounded-full', style.dot)} />
      {t(`notImported.category.${category}`)}
    </Badge>
  )
}

// Torrent in seed senza hardlink in libreria, per torrent, con il perché
// (nazgarr/not_imported.py). Sola lettura: niente viene rimosso da qui — le
// azioni, se arriveranno, passeranno dalla coda di approvazione.
export function NotImportedView() {
  const navigate = useNavigate()
  const { data, isPending } = useNotImported()
  const refresh = useRefreshNotImported()
  const [category, setCategory] = useState('all')
  const [showExcluded, setShowExcluded] = useState(false)
  const [onlyRemovable, setOnlyRemovable] = useState(false)
  const [search, setSearch] = useState('')
  const [openItem, setOpenItem] = useState<OpenItem | null>(null)

  const summary = useMemo(() => {
    const result: Record<string, StateSummary> = { all: { count: 0, size: 0 } }
    for (const [key, value] of Object.entries(data?.summary ?? {})) {
      result[key] = { count: value.count, size: value.total_bytes }
      result.all.count += value.count
      result.all.size += value.total_bytes
    }
    return result
  }, [data])

  const shown = useMemo(() => {
    const query = search.trim().toLowerCase()
    return (data?.torrents ?? []).filter(
      (tor) =>
        (showExcluded || !tor.excluded) &&
        (category === 'all' || tor.category === category) &&
        (!onlyRemovable || tor.seed_requirement?.status === 'met') &&
        (!query || tor.name.toLowerCase().includes(query) || (contentLabel(tor) ?? '').toLowerCase().includes(query)),
    )
  }, [data, category, search, showExcluded, onlyRemovable])
  const removableCount = (data?.torrents ?? []).filter(
    (tor) => (showExcluded || !tor.excluded) && tor.seed_requirement?.status === 'met',
  ).length

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="text-lg font-semibold">{t('notImported.title')}</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">{t('notImported.description')}</p>
          <p className="text-xs text-muted-foreground">{t('notImported.rightClickHint')}</p>
          <p className="text-xs text-muted-foreground" title={data?.computed_at ? parseApiDate(data.computed_at).toLocaleString() : undefined}>
            {data?.computed_at
              ? t(data.with_arr ? 'notImported.computedWithArr' : 'notImported.computedWithoutArr', {
                  when: relativeFromNow(data.computed_at),
                })
              : t('notImported.neverComputed')}
          </p>
          {data?.skipped_reason && (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              {t('notImported.skipped', { reason: data.skipped_reason, when: relativeFromNow(data.skipped_at) })}
            </p>
          )}
        </div>
        <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          {refresh.isPending ? <Loader2Icon className="size-4 animate-spin" /> : <RefreshCwIcon className="size-4" />}
          {t('notImported.recompute')}
        </Button>
      </div>
      <LibrarySummaryCards statusOptions={OPTIONS} summary={summary} activeStatus={category} onSelect={setCategory} />
      {category !== 'all' && (
        <p className="text-sm text-muted-foreground">{t(`notImported.help.${category}`)}</p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 max-w-md flex-1">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('notImported.searchPlaceholder')}
            className="pl-8"
          />
        </div>
        {/* Come nelle viste a cartella: gli esclusi fuori dai conteggi, visibili a toggle premuto. */}
        <Toggle variant="outline" size="sm" pressed={showExcluded} onPressedChange={setShowExcluded}>
          <EyeOffIcon />
          {t('library.showExcluded')} {data?.excluded_count ? `(${data.excluded_count})` : ''}
        </Toggle>
        <Toggle
          variant="outline"
          size="sm"
          pressed={onlyRemovable}
          onPressedChange={setOnlyRemovable}
          title={t('notImported.removable.filterHelp')}
        >
          <CircleCheckIcon />
          {t('notImported.removable.filter')} ({removableCount})
        </Toggle>
      </div>
      <Card className="py-0">
        <CardContent className="p-0">
          {!data?.classified ? (
            <p className="p-4 text-sm text-muted-foreground">{t('notImported.notYet')}</p>
          ) : shown.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">{t('notImported.nothing')}</p>
          ) : (
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead>{t('notImported.torrent')}</TableHead>
                  <TableHead className="w-40">{t('notImported.why')}</TableHead>
                  <TableHead className="w-[28%]">{t('notImported.inLibrary')}</TableHead>
                  <TableHead className="w-24 text-right">{t('notImported.size')}</TableHead>
                  <TableHead className="w-16 text-right">{t('notImported.ratio')}</TableHead>
                  <TableHead className="w-24 text-right">{t('notImported.seeding')}</TableHead>
                  <TableHead className="w-28 text-right" title={t('notImported.removable.columnHelp')}>
                    {t('notImported.removable.column')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((tor) => {
                  const openable = tor.content_type != null && tor.tmdb_id != null && tor.title != null
                  // Dal menu contestuale: ripubblicare il torrent (es. arrivato da un
                  // tracker pubblico) con un nuovo upload sui suoi file.
                  const source = tor.source
                  const items: RowMenuItem[] = source
                    ? [{
                        label: t('itemDetail.uploadOrReseed'),
                        icon: <UploadIcon />,
                        onSelect: () =>
                          navigate(newUploadLink(
                            { diskId: source.disk_id, path: source.relative_path, isDir: source.is_dir },
                            tor.content_type && tor.tmdb_id ? `${tor.content_type}/${tor.tmdb_id}` : undefined,
                          )),
                      }]
                    : []
                  return (
                    <RowContextMenu key={tor.client_torrent_id} title={tor.name} items={items}>
                    <TableRow
                      className={cn(openable && 'cursor-pointer', tor.excluded && 'opacity-60')}
                      onClick={openable ? () => setOpenItem({ contentType: tor.content_type!, tmdbId: tor.tmdb_id! }) : undefined}
                    >
                      <TableCell title={tor.name}>
                        <span className="block truncate font-mono text-xs">{tor.name}</span>
                        <span className="block truncate text-[length:var(--text-xxs)] text-muted-foreground">
                          {[contentLabel(tor), tor.quality, tor.tracker, tor.client, t('notImported.files', { count: tor.file_count })]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </TableCell>
                      <TableCell title={tor.detail ?? undefined}>
                        <div className="flex flex-wrap gap-1">
                          <CategoryBadge category={tor.category} />
                          {tor.excluded && (
                            <Badge variant="outline" className="h-auto py-0 font-mono text-[length:var(--text-xxs)] leading-4">
                              {t('library.excluded')}
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell title={tor.replaced_by?.relative_path}>
                        {tor.replaced_by ? (
                          <span className="flex min-w-0 items-center gap-1.5">
                            <ArrowRightIcon className="size-3 shrink-0 text-muted-foreground" />
                            <span className="min-w-0">
                              <span className="block truncate font-mono text-xs">{fileName(tor.replaced_by.relative_path)}</span>
                              <span className="block truncate text-[length:var(--text-xxs)] text-muted-foreground">
                                {[tor.replaced_by.quality, formatBytes(tor.replaced_by.size_bytes)].filter(Boolean).join(' · ')}
                              </span>
                            </span>
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">{tor.detail}</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">{formatBytes(tor.total_bytes)}</TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {tor.ratio != null ? tor.ratio.toFixed(2) : '—'}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {formatSeedTime(tor.seeding_time_seconds)}
                      </TableCell>
                      <TableCell className="text-right">
                        <SeedRequirementCell requirement={tor.seed_requirement} />
                      </TableCell>
                    </TableRow>
                    </RowContextMenu>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <ItemDetailSheet item={openItem} onClose={() => setOpenItem(null)} />
    </div>
  )
}
