import { ArrowRightIcon, SearchIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { Schemas } from '@/api/client'
import { useNotImported } from '@/api/hooks/library'
import { LibrarySummaryCards } from '@/components/LibrarySummaryCards'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { t } from '@/lib/i18n'
import { formatBytes, type StateSummary, type StatusOption } from '@/lib/library-filters'
import { NOT_IMPORTED_STYLES } from '@/lib/status-styles'
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
// (app/not_imported.py). Sola lettura: niente viene rimosso da qui — le
// azioni, se arriveranno, passeranno dalla coda di approvazione.
export function NotImportedView() {
  const { data, isPending } = useNotImported()
  const [category, setCategory] = useState('all')
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
        (category === 'all' || tor.category === category) &&
        (!query || tor.name.toLowerCase().includes(query) || (contentLabel(tor) ?? '').toLowerCase().includes(query)),
    )
  }, [data, category, search])

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>

  return (
    <div className="grid gap-4">
      <div className="grid gap-1">
        <h1 className="text-lg font-semibold">{t('notImported.title')}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{t('notImported.description')}</p>
      </div>
      <LibrarySummaryCards statusOptions={OPTIONS} summary={summary} activeStatus={category} onSelect={setCategory} />
      {category !== 'all' && (
        <p className="text-sm text-muted-foreground">{t(`notImported.help.${category}`)}</p>
      )}
      <div className="relative max-w-md">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('notImported.searchPlaceholder')}
          className="pl-8"
        />
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
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((tor) => {
                  const openable = tor.content_type != null && tor.tmdb_id != null && tor.title != null
                  return (
                    <TableRow
                      key={tor.client_torrent_id}
                      className={cn(openable && 'cursor-pointer')}
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
                        <CategoryBadge category={tor.category} />
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
                    </TableRow>
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
