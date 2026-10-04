import { ChevronDownIcon, GlobeIcon, UploadIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { Schemas } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'
import { commonFolder, newUploadLink } from '@/lib/upload'
import { cn } from '@/lib/utils'
import { TrackerLogo } from '@/pages/config/ServiceIcons'

type Detail = Schemas['ItemDetailResponse']
type Group = Detail['trackers'][number]

function episodeCode(entry: Group['entries'][number]) {
  if (entry.season_number == null || entry.episode_number == null) return null
  return `S${String(entry.season_number).padStart(2, '0')}E${String(entry.episode_number).padStart(2, '0')}`
}

function coverage(group: Group) {
  if (group.total === 0) return 'muted'
  if (group.seeding === group.total) return 'full'
  return group.seeding > 0 ? 'partial' : 'none'
}

const TONE = {
  full: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  partial: 'border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-300',
  none: 'border-zinc-400/40 bg-zinc-400/15 text-zinc-600 dark:text-zinc-300',
  muted: 'border-zinc-400/40 bg-zinc-400/15 text-zinc-600 dark:text-zinc-300',
}

// Dove carica il contenuto: l'intero film o serie (i video non esclusi) o,
// per una serie, la cartella che li contiene tutti.
function uploadSource(detail: Detail) {
  const videos = detail.files.filter((f) => f.is_video && !f.excluded)
  if (detail.content_type === 'movie' && videos.length === 1) {
    return { diskId: videos[0].disk_id, path: videos[0].relative_path, isDir: false }
  }
  const folder = commonFolder(videos)
  return folder ? { ...folder, isDir: true } : null
}

function TrackerRow({ detail, group }: { detail: Detail; group: Group }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const tone = coverage(group)
  const disabled = group.entries.length > 0 && group.entries.every((e) => !e.client_enabled)
  const source = uploadSource(detail)
  const canUpload = group.configured && group.has_upload_profile && group.seeding < group.total && source !== null
  return (
    <div className="rounded-md border">
      <div className="flex min-w-0 items-center gap-2.5 px-3 py-2">
        <button
          type="button"
          aria-expanded={open}
          disabled={group.entries.length === 0}
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2.5 text-left disabled:cursor-default"
        >
          {/* Il logo grande quanto l'icona generica dei tracker non configurati. */}
          {group.tracker_id != null ? (
            <TrackerLogo trackerId={group.tracker_id} className="size-5 shrink-0" />
          ) : (
            <GlobeIcon className="size-5 shrink-0 text-muted-foreground" />
          )}
          <span className="min-w-0 truncate text-sm font-medium">{group.label}</span>
          {!group.configured && <span className="shrink-0 text-xs text-muted-foreground">{t('itemDetail.trackerNotConfigured')}</span>}
          {disabled && <span className="shrink-0 text-xs text-amber-600 dark:text-amber-400">{t('itemDetail.clientDisabled')}</span>}
          <Badge variant="outline" className={cn('ml-auto shrink-0 tabular-nums', TONE[tone])}>
            {t('itemDetail.trackerSeeding', { seeding: group.seeding, total: group.total })}
          </Badge>
          {group.entries.length > 0 && (
            <ChevronDownIcon className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
          )}
        </button>
        {canUpload && (
          <Button
            size="xs"
            variant="outline"
            title={t('itemDetail.uploadToTrackerHelp')}
            onClick={() =>
              navigate(newUploadLink(source, `${detail.content_type}/${detail.tmdb_id}`, [group.tracker_id!]))
            }
          >
            <UploadIcon className="size-3.5" />
            {t('itemDetail.uploadToTracker', { tracker: group.label })}
          </Button>
        )}
      </div>
      {open && (
        <ul className="grid max-h-64 gap-1 overflow-y-auto border-t px-3 py-2 text-xs">
          {group.entries.map((entry, i) => (
            <li key={`${entry.seed_path}-${i}`} className="grid min-w-0 gap-0.5">
              <span className="flex min-w-0 gap-1.5 font-mono">
                {episodeCode(entry) && <span className="shrink-0 font-sans font-medium">{episodeCode(entry)}</span>}
                <span className="break-all">{entry.seed_path}</span>
              </span>
              <span className="text-muted-foreground">
                {entry.client}
                {!entry.client_enabled && ` (${t('itemDetail.disabled')})`} · {entry.state}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Panoramica compatta per tracker: in seed su ciascun tracker configurato
// (anche a zero) e sugli altri trovati nei torrent, con i percorsi a
// richiesta e, dove manca, l'upload o reseed verso quel tracker.
export function TrackerOverview({ detail }: { detail: Detail }) {
  // Un dettaglio salvato in cache da una versione precedente non ha trackers.
  const trackers = detail.trackers ?? []
  if (trackers.length === 0) return null
  return (
    <div className="grid gap-1.5">
      {trackers.map((group) => (
        <TrackerRow key={group.tracker_id ?? `h-${group.label}`} detail={detail} group={group} />
      ))}
    </div>
  )
}
