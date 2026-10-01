import { FileVideoIcon, FolderIcon } from 'lucide-react'

import { useUpdateOverrides, type UploadJob } from '@/api/hooks/uploads'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'

interface FileNames {
  available: string[]
  default: string | null
  previews: Record<string, { name: string; files: string[]; count: number }>
}

// I nomi dei file dentro il torrent di un upload (app/upload_file_names.py):
// quelli del torrent in hardlink su un client, generati dal pattern di
// Settings > Upload, o quelli della sorgente. Uno per job: il torrent è lo
// stesso per tutti i tracker.
export function FileNamesCard({ job }: { job: UploadJob }) {
  const save = useUpdateOverrides(job.id)
  const names = (job.analysis as { file_names?: FileNames } | null)?.file_names
  if (!names || names.available.length === 0) return null
  const chosen = (job.overrides as Record<string, unknown>).file_naming as string | undefined
  const mode = chosen && names.available.includes(chosen) ? chosen : (names.default ?? names.available[0])
  const preview = names.previews[mode]
  const isFolder = preview?.files.some((f) => f.includes('/'))

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="text-base">{t('upload.fileNames.title')}</CardTitle>
        <CardDescription>{t('upload.fileNames.description')}</CardDescription>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3">
        <ToggleGroupSingle
          value={mode}
          variant="outline"
          size="sm"
          disabled={save.isPending || job.status !== 'awaiting_decision'}
          onValueChange={(value) => value && save.mutate({ ...job.overrides, file_naming: value })}
        >
          {names.available.map((m) => (
            <ToggleGroupItem key={m} value={m}>
              {t(`upload.fileNames.mode.${m}`)}
              {m === names.default && <span className="ml-1 text-muted-foreground">·{t('upload.fileNames.default')}</span>}
            </ToggleGroupItem>
          ))}
        </ToggleGroupSingle>
        {preview && (
          <div className="grid min-w-0 gap-1 rounded-md border bg-muted/30 p-2.5 font-mono text-xs">
            <span className="flex min-w-0 items-center gap-1.5 font-medium">
              {isFolder ? <FolderIcon className="size-3.5 shrink-0" /> : <FileVideoIcon className="size-3.5 shrink-0" />}
              <span className="break-all">{preview.name}</span>
            </span>
            {isFolder &&
              preview.files.map((file) => (
                <span key={file} className="pl-5 break-all text-muted-foreground">
                  {file.slice(file.indexOf('/') + 1)}
                </span>
              ))}
            {preview.count > preview.files.length && (
              <span className="pl-5 text-muted-foreground">
                {t('upload.fileNames.more', { count: preview.count - preview.files.length })}
              </span>
            )}
          </div>
        )}
        <p className="text-xs text-muted-foreground">{t(`upload.fileNames.help.${mode}`)}</p>
      </CardContent>
    </Card>
  )
}
