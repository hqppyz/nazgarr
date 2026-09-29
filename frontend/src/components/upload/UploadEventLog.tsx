import { CircleAlertIcon, CircleCheckIcon, InfoIcon } from 'lucide-react'

import type { UploadJob } from '@/api/hooks/uploads'
import { parseApiDate } from '@/lib/time'
import { eventMessage } from '@/lib/upload'
import { cn } from '@/lib/utils'

type UploadEvent = UploadJob['events'][number]

const ICON = {
  info: <InfoIcon className="size-3.5 text-muted-foreground" />,
  warning: <CircleAlertIcon className="size-3.5 text-amber-500" />,
  error: <CircleAlertIcon className="size-3.5 text-red-500" />,
}

export function UploadEventLog({ events, targets }: { events: UploadEvent[]; targets: UploadJob['targets'] }) {
  const trackerOf = new Map(targets.map((target) => [target.id, target.tracker_label]))
  return (
    <ol className="grid gap-1.5">
      {events.map((event) => (
        <li key={event.id} className="flex items-start gap-2 text-xs">
          <span className="mt-0.5">{event.code.endsWith('_done') ? <CircleCheckIcon className="size-3.5 text-emerald-500" /> : ICON[event.level as keyof typeof ICON] ?? ICON.info}</span>
          <span className="w-16 shrink-0 text-muted-foreground tabular-nums">
            {parseApiDate(event.created_at).toLocaleTimeString()}
          </span>
          <span className={cn('min-w-0', event.level === 'error' && 'text-red-600 dark:text-red-400')}>
            {event.target_id != null && (
              <span className="mr-1 font-medium">[{trackerOf.get(event.target_id) ?? event.target_id}]</span>
            )}
            {eventMessage(event)}
          </span>
        </li>
      ))}
    </ol>
  )
}
