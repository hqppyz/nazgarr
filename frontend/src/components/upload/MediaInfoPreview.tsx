import { CheckIcon, CopyIcon, InfoIcon, MinusIcon, PlusIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import {
  audioLine,
  flagOf,
  formatBitrate,
  formatDuration,
  formatFrameRate,
  languageName,
  type MediaInfoSummary,
} from '@/lib/mediainfo'

function Rows({ rows }: { rows: [string, string | null][] }) {
  const shown = rows.filter((row): row is [string, string] => !!row[1])
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {shown.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-right text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid content-start gap-2">
      <p className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</p>
      {children}
    </div>
  )
}

// Anteprima MediaInfo come quella dei tracker UNIT3D: generale, video,
// audio, sottotitoli; il report completo solo a richiesta, nel suo riquadro
// con lo scroll orizzontale (le righe di mediainfo sono lunghissime).
export function MediaInfoPreview({ summary, fullText }: { summary: MediaInfoSummary | null; fullText: string | null }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)
  if (!summary && !fullText) return null
  const { general, video } = summary ?? { general: null, video: null }

  return (
    <Card className="min-w-0">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <InfoIcon className="size-4" />
          MediaInfo
        </CardTitle>
        <div className="flex gap-1">
          {fullText && (
            <Button
              variant="ghost"
              size="sm"
              title={expanded ? t('upload.mediainfo.collapse') : t('upload.mediainfo.expand')}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? <MinusIcon className="size-4" /> : <PlusIcon className="size-4" />}
            </Button>
          )}
          {fullText && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                navigator.clipboard?.writeText(fullText).then(() => {
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1500)
                })
              }
            >
              {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
              {t('upload.mediainfo.copy')}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-4">
        {summary?.file_name && <p className="truncate font-mono text-xs" title={summary.file_name}>{summary.file_name}</p>}
        {summary && (
          <div className="grid gap-6 sm:grid-cols-[auto_auto_1fr]">
            {general && (
              <Block title={t('upload.mediainfo.general')}>
                <Rows
                  rows={[
                    [t('upload.mediainfo.format'), general.format],
                    [t('upload.mediainfo.duration'), formatDuration(general.duration_ms)],
                    [t('upload.mediainfo.bitrate'), formatBitrate(general.overall_bit_rate)],
                    [t('upload.mediainfo.size'), general.file_size ? formatBytes(general.file_size) : null],
                  ]}
                />
              </Block>
            )}
            {video && (
              <Block title={t('upload.mediainfo.video')}>
                <Rows
                  rows={[
                    [t('upload.mediainfo.format'), video.format && `${video.format}${video.bit_depth ? ` (${video.bit_depth} bits)` : ''}`],
                    [t('upload.mediainfo.resolution'), video.width && video.height ? `${video.width} × ${video.height}` : null],
                    [t('upload.mediainfo.aspectRatio'), video.display_aspect_ratio],
                    [t('upload.mediainfo.frameRate'), formatFrameRate(video)],
                    [t('upload.mediainfo.bitrate'), formatBitrate(video.bit_rate)],
                    ['HDR', video.hdr_format],
                  ]}
                />
              </Block>
            )}
            {summary.audio.length > 0 && (
              <Block title={t('upload.mediainfo.audio')}>
                <ol className="grid gap-0.5 text-xs">
                  {summary.audio.map((track, i) => (
                    <li key={i} className="flex min-w-0 gap-2">
                      <span className="text-muted-foreground tabular-nums">{i + 1}.</span>
                      <span>{flagOf(track.language) ?? '🏳️'}</span>
                      <span className="min-w-0 break-words">{audioLine(track)}</span>
                    </li>
                  ))}
                </ol>
              </Block>
            )}
          </div>
        )}
        {summary && summary.subtitles.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
              {t('upload.mediainfo.subtitles')}
            </p>
            {summary.subtitles.map((track, i) => (
              <span key={i} title={`${languageName(track.language)}${track.forced ? ' (forced)' : ''}${track.title ? ` · ${track.title}` : ''}`}>
                {flagOf(track.language) ?? '🏳️'}
              </span>
            ))}
          </div>
        )}
        {expanded && fullText && (
          <pre className="max-h-[32rem] overflow-auto rounded bg-muted p-3 font-mono text-[11px] leading-snug">{fullText}</pre>
        )}
      </CardContent>
    </Card>
  )
}
