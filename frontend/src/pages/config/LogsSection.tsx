import { useState } from 'react'

import { useLogs } from '@/api/hooks/system'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { shortLogger } from '@/lib/logs'
import { cn } from '@/lib/utils'

// DEBUG si chiama "Verbose": il dettaglio per capire un problema, non per
// leggerlo ogni giorno (nazgarr/logging_config.py ci mette le librerie chiacchierone).
const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const
const LEVEL_LABEL: Record<string, string> = { DEBUG: 'Verbose', INFO: 'Info', WARNING: 'Warning', ERROR: 'Error' }
const LEVEL_TAG: Record<string, string> = { DEBUG: 'VRB', INFO: 'INF', WARNING: 'WRN', ERROR: 'ERR', CRITICAL: 'CRT' }


const LEVEL_COLOR: Record<string, string> = {
  DEBUG: 'text-muted-foreground',
  INFO: 'text-foreground',
  WARNING: 'text-amber-600 dark:text-amber-400',
  ERROR: 'text-destructive',
  CRITICAL: 'text-destructive',
}

export function LogsSection() {
  const [minLevel, setMinLevel] = useState<string>('INFO')
  const { data } = useLogs(minLevel)

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>{t('logs.title')}</CardTitle>
          <CardDescription>{t('logs.description')}</CardDescription>
        </div>
        <Select value={minLevel} onValueChange={(v) => v && setMinLevel(v)}>
          <SelectTrigger className="w-40">
            <SelectValue>{(v: string | null) => LEVEL_LABEL[v ?? 'INFO'] ?? v}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {LEVELS.map((level) => (
              <SelectItem key={level} value={level}>
                {LEVEL_LABEL[level]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </CardHeader>
      <CardContent>
        {data && !data.available && <p className="text-sm text-muted-foreground">{t('logs.notAvailable')}</p>}
        {data?.available && data.entries.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('logs.noEntries')}</p>
        )}
        {data && data.entries.length > 0 && (
          <div className="grid max-h-[32rem] gap-0.5 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs">
            {data.entries.map((entry, index) => {
              // Solo l'ora sulla riga; il giorno una volta, quando cambia.
              const [day, time] = entry.timestamp.split(' ')
              const previousDay = index > 0 ? data.entries[index - 1].timestamp.split(' ')[0] : null
              return (
                <div key={index} className="contents">
                  {day !== previousDay && (
                    <div className={cn('text-[length:var(--text-xxs)] font-semibold text-muted-foreground uppercase', index > 0 && 'mt-2')}>
                      {day}
                    </div>
                  )}
                  <div className="grid grid-cols-[4.5rem_2rem_8rem_minmax(0,1fr)] gap-2 whitespace-pre-wrap">
                    <span className="text-muted-foreground tabular-nums">{time ?? entry.timestamp}</span>
                    <span className={cn('font-semibold', LEVEL_COLOR[entry.level])} title={entry.level}>
                      {LEVEL_TAG[entry.level] ?? entry.level}
                    </span>
                    <span className="truncate text-muted-foreground" title={entry.logger}>{shortLogger(entry.logger)}</span>
                    <span className="break-words">{entry.message}</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
