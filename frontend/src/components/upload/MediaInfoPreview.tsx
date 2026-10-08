import { InfoIcon, PlusIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { CopyButton } from '@/components/CopyButton'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
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
  const [fullOpen, setFullOpen] = useState(false)
  if (!summary && !fullText) return null
  const copyProps = {
    text: fullText,
    label: t('upload.mediainfo.copy'),
    successMessage: t('upload.mediainfo.copied'),
    failMessage: t('upload.mediainfo.copyFailed'),
    size: 'sm' as const,
  }
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
              title={t('upload.mediainfo.expand')}
              aria-label={t('upload.mediainfo.expand')}
              onClick={() => setFullOpen(true)}
            >
              <PlusIcon className="size-4" />
            </Button>
          )}
          {fullText && (
            <CopyButton {...copyProps} variant="ghost">
              {t('upload.mediainfo.copy')}
            </CopyButton>
          )}
        </div>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-4">
        {summary?.file_name && <p className="truncate font-mono text-xs" title={summary.file_name}>{summary.file_name}</p>}
        {summary && (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(14rem,1fr))] gap-6">
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
        {fullText && (
          <Dialog open={fullOpen} onOpenChange={setFullOpen}>
            <DialogContent className="max-h-[90vh] grid-rows-[auto_minmax(0,1fr)] sm:max-w-5xl">
              <DialogHeader className="flex flex-row items-center justify-between gap-2 pr-8">
                <DialogTitle className="min-w-0 truncate">
                  MediaInfo{summary?.file_name ? ` · ${summary.file_name}` : ''}
                </DialogTitle>
                <CopyButton {...copyProps}>{t('upload.mediainfo.copy')}</CopyButton>
              </DialogHeader>
              <pre className="min-h-0 overflow-auto rounded bg-muted p-3 font-mono text-[11px] leading-snug">{fullText}</pre>
            </DialogContent>
          </Dialog>
        )}
      </CardContent>
    </Card>
  )
}
