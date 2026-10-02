import { LoaderCircleIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

const TONE = {
  working: 'border-sky-500/40 bg-sky-500/15 text-sky-700 dark:text-sky-300',
  gate: 'border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-300',
  ok: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  partial: 'border-orange-500/40 bg-orange-500/15 text-orange-700 dark:text-orange-300',
  failed: 'border-red-500/40 bg-red-500/15 text-red-700 dark:text-red-300',
  muted: 'border-zinc-400/40 bg-zinc-400/15 text-zinc-600 dark:text-zinc-300',
}

// Stati di upload_job e upload_target (nazgarr/models.py) -> tono del badge.
const STATUS_TONE: Record<string, keyof typeof TONE> = {
  identifying: 'working',
  analyzing: 'working',
  queued: 'muted',
  running: 'working',
  awaiting_match: 'gate',
  awaiting_decision: 'gate',
  done: 'ok',
  partial: 'partial',
  failed: 'failed',
  cancelled: 'muted',
  pending: 'muted',
  checking: 'working',
  approved: 'muted',
  verifying: 'working',
  preparing: 'working',
  uploading: 'working',
  seeding: 'working',
  skipped: 'muted',
}

export function UploadStatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = STATUS_TONE[status] ?? 'muted'
  return (
    <Badge variant="outline" className={cn(TONE[tone], className)}>
      {tone === 'working' && <LoaderCircleIcon className="size-3 animate-spin" />}
      {t(`upload.status.${status}`)}
    </Badge>
  )
}
