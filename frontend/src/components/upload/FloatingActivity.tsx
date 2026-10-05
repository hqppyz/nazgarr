import { ChevronDownIcon, ChevronUpIcon, ListIcon } from 'lucide-react'
import { useState } from 'react'
import { createPortal } from 'react-dom'

import type { UploadJob } from '@/api/hooks/uploads'
import { UploadEventLog } from '@/components/upload/UploadEventLog'
import { useFloatingSlot } from '@/lib/floatingSlot'
import { t } from '@/lib/i18n'
import { eventMessage } from '@/lib/upload'
import { cn } from '@/lib/utils'

// Il registro del job come pannello flottante: chiuso mostra solo l'ultimo
// passo, aperto tutto il registro.
export function FloatingActivity({ job }: { job: UploadJob }) {
  const [open, setOpen] = useState(false)
  const slot = useFloatingSlot()
  const last = job.events[job.events.length - 1]
  const panel = (
    <div className="w-96 max-w-[calc(100vw-2rem)] rounded-lg border bg-card text-sm shadow-lg max-sm:w-full">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full min-w-0 items-center gap-2 px-4 py-2.5 text-left"
      >
        <ListIcon className="size-4 shrink-0 text-muted-foreground" />
        <span className="font-medium">{t('upload.activity')}</span>
        <span className="text-xs text-muted-foreground tabular-nums">{job.events.length}</span>
        {!open && last && (
          <span className={cn('min-w-0 flex-1 truncate text-xs text-muted-foreground', last.level === 'error' && 'text-red-600 dark:text-red-400')}>
            {eventMessage(last)}
          </span>
        )}
        <span className="ml-auto shrink-0">
          {open ? <ChevronDownIcon className="size-4" /> : <ChevronUpIcon className="size-4" />}
        </span>
      </button>
      {open && (
        <div className="max-h-[40svh] overflow-y-auto border-t px-4 py-3 sm:max-h-[50vh]">
          <UploadEventLog events={job.events} targets={job.targets} />
        </div>
      )}
    </div>
  )
  return slot ? createPortal(panel, slot) : panel
}
